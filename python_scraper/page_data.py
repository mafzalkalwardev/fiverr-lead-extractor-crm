"""
Extract seller + reviews from Fiverr embedded JSON (__NEXT_DATA__, Perseus props, JSON-LD).
More reliable than DOM text when the UI shows ratings instead of buyer names.
"""
from __future__ import annotations

import json
import re
from typing import Any

from playwright.async_api import Page

from utils import (
    absolutize_url,
    clean_text,
    infer_reviewer_from_text,
    is_valid_review_image,
    is_valid_reviewer_name,
    looks_like_rating,
    normalize_country,
    reviewer_name_before_country,
    seller_name_from_gig,
    username_from_gig_url,
)

_EXTRACT_PAGE_JSON_JS = r"""
() => {
  const blobs = [];
  const push = (raw) => {
    if (!raw || raw.length < 20) return;
    try {
      blobs.push(JSON.parse(raw));
    } catch (_) {}
  };

  const nd = document.querySelector("#__NEXT_DATA__");
  if (nd && nd.textContent) push(nd.textContent);

  for (const s of document.querySelectorAll('script[type="application/json"], script[id*="perseus" i]')) {
    const t = s.textContent || "";
    if (t.length > 100) push(t);
  }

  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    const t = s.textContent || "";
    if (t.length > 20) push(t);
  }

  return blobs;
}
"""

_WALK_REVIEW_JS = r"""
(blobs, sellerSlug) => {
  const seen = new Set();
  const out = [];
  const sellerL = (sellerSlug || "").toLowerCase();
  const isRating = (t) => /^[1-5](?:\.\d)?$/.test(t) || /^\d+(?:\.\d+)?$/.test(t);
  const slugKey = (t) => (t || "").toLowerCase().replace(/[^a-z0-9]/g, "");

  const normCountry = (v) => {
    const t = String(v || "");
    if (/united states|usa|u\.s\./i.test(t) || t === "US") return "United States";
    if (/canada/i.test(t) || t === "CA") return "Canada";
    return "";
  };

  const pickBuyer = (o) => {
    const keys = ["username", "userName", "buyerUsername", "reviewerUsername", "authorUsername", "name", "displayName"];
    for (const k of keys) {
      const v = o[k];
      if (typeof v === "string" && v.length >= 2 && !isRating(v)) {
        const sk = slugKey(v);
        if (sellerL && sk === slugKey(sellerL)) continue;
        return v.replace(/^@/, "").trim();
      }
    }
    if (o.user && typeof o.user === "object") {
      for (const k of ["username", "name", "displayName"]) {
        const v = o.user[k];
        if (typeof v === "string" && v.length >= 2 && !isRating(v)) {
          const sk = slugKey(v);
          if (sellerL && sk === slugKey(sellerL)) continue;
          return v.replace(/^@/, "").trim();
        }
      }
    }
    if (o.buyer && typeof o.buyer === "object") {
      for (const k of ["username", "name", "displayName"]) {
        const v = o.buyer[k];
        if (typeof v === "string" && v.length >= 2 && !isRating(v)) return v.replace(/^@/, "").trim();
      }
    }
    return "";
  };

  const pickText = (o) => {
    for (const k of ["comment", "reviewText", "description", "text", "message", "content", "body"]) {
      const v = o[k];
      if (typeof v === "string" && v.length >= 15) return v.trim();
    }
    return "";
  };

  const pickRating = (o) => {
    for (const k of ["rating", "value", "stars", "score", "ratingScore"]) {
      const v = o[k];
      if (typeof v === "number" && v >= 1 && v <= 5) return v;
      if (typeof v === "string" && /^[1-5](?:\.\d)?$/.test(v)) return parseFloat(v);
    }
    return 5;
  };

  const pickCountry = (o) => {
    for (const k of ["country", "countryCode", "location", "reviewerCountry"]) {
      const c = normCountry(o[k]);
      if (c) return c;
    }
    if (o.user && typeof o.user === "object") {
      const c = normCountry(o.user.country || o.user.countryCode);
      if (c) return c;
    }
    return "";
  };

  const pickImage = (o) => {
    for (const k of ["reviewedImage", "attachment", "image", "deliveryImage", "url", "src"]) {
      const v = o[k];
      if (typeof v === "string" && v.startsWith("http")) return v;
      if (v && typeof v === "object" && typeof v.url === "string") return v.url;
    }
    if (Array.isArray(o.attachments)) {
      for (const a of o.attachments) {
        if (a && typeof a.url === "string") return a.url;
        if (typeof a === "string" && a.startsWith("http")) return a;
      }
    }
    return "";
  };

  const tryReview = (o) => {
    if (!o || typeof o !== "object") return;
    const text = pickText(o);
    if (text.length < 15) return;
    const buyer = pickBuyer(o);
    if (!buyer || isRating(buyer)) return;
    const country = pickCountry(o);
    if (!country) return;
    const img = pickImage(o);
    const rating = pickRating(o);
    const key = buyer + "|" + text.slice(0, 60).toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      reviewerName: buyer,
      reviewerCountry: country,
      reviewText: text.slice(0, 2000),
      reviewRating: rating,
      reviewedImageLink: img || "",
    });
  };

  const walk = (node, depth) => {
    if (!node || depth > 14) return;
    if (Array.isArray(node)) {
      for (const item of node) walk(item, depth + 1);
      return;
    }
    if (typeof node !== "object") return;

    tryReview(node);

    for (const k of ["reviews", "buyerReviews", "gigReviews", "userReviews", "items", "nodes", "data", "list"]) {
      const v = node[k];
      if (Array.isArray(v)) {
        for (const item of v) tryReview(item);
      }
    }

    for (const v of Object.values(node)) {
      if (v && typeof v === "object") walk(v, depth + 1);
    }
  };

  for (const blob of blobs || []) {
    walk(blob, 0);
  }
  return out;
}
"""


def _pick_seller_from_json(blobs: list[Any], gig_url: str) -> dict[str, str]:
    slug = username_from_gig_url(gig_url)
    display = ""
    for blob in blobs:
        stack: list[Any] = [blob]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                u = node.get("username") or node.get("sellerName") or node.get("sellerUsername")
                if isinstance(u, str) and u.lower() not in ("fiverr", "seller") and len(u) >= 2:
                    if slug and u.lower() == slug.lower():
                        pass
                    elif not slug:
                        slug = u
                for k in ("seller", "user", "owner", "gig", "gigData", "sellerData"):
                    v = node.get(k)
                    if isinstance(v, dict):
                        stack.append(v)
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    if not slug:
        slug = username_from_gig_url(gig_url)
    return {"sellerUsername": slug, "sellerName": slug}


async def extract_reviews_from_page_json(
    page: Page, seller_username: str
) -> list[dict[str, Any]]:
    try:
        blobs = await page.evaluate(_EXTRACT_PAGE_JSON_JS)
        if not blobs:
            return []
        raw = await page.evaluate(_WALK_REVIEW_JS, blobs, seller_username or "")
    except Exception as err:
        print(f"[page_data] JSON review extract failed: {err}")
        return []

    results: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        reviewer = clean_text(item.get("reviewerName")).lstrip("@")
        country = normalize_country(clean_text(item.get("reviewerCountry")))
        text = clean_text(item.get("reviewText"))
        img = absolutize_url(item.get("reviewedImageLink") or "")

        if looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
            reviewer = reviewer_name_before_country(text) or infer_reviewer_from_text(
                text, seller_username
            )
        if not reviewer or looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
            continue
        if country not in ("United States", "Canada"):
            continue
        if len(text) < 15:
            continue
        if img and not is_valid_review_image(img):
            img = ""

        try:
            rating = float(item.get("reviewRating") or 5)
        except (TypeError, ValueError):
            rating = 5.0
        if rating < 1 or rating > 5:
            rating = 5.0

        results.append(
            {
                "reviewerName": reviewer,
                "reviewerCountry": country,
                "reviewText": text,
                "reviewRating": rating,
                "reviewDate": None,
                "reviewedImageLink": img,
            }
        )

    if results:
        print(f"[page_data] JSON: {len(results)} US/CA reviews (buyer names from page data)")
    return results


async def enrich_gig_from_page_json(page: Page, gig: dict) -> dict:
    """Ensure seller fields always match gig URL / embedded JSON — never 'Fiverr'."""
    slug = seller_name_from_gig(gig) or username_from_gig_url(page.url)
    if slug:
        gig["sellerUsername"] = slug
        gig["sellerName"] = slug
        return gig
    url = gig.get("gigUrl") or page.url

    try:
        blobs = await page.evaluate(_EXTRACT_PAGE_JSON_JS)
        if blobs:
            picked = _pick_seller_from_json(blobs, url)
            if picked.get("sellerUsername"):
                gig.update(picked)
    except Exception:
        pass

    slug = username_from_gig_url(url)
    if slug:
        gig["sellerUsername"] = slug
        gig["sellerName"] = slug
    return gig
