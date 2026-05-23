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
    is_valid_seller_name,
    looks_like_rating,
    normalize_country,
    parse_review_date,
    reviewer_name_before_country,
    seller_name_from_gig,
    username_from_gig_url,
)

JSON_SCRIPT_SELECTORS = [
    "#__NEXT_DATA__",
    'script[type="application/json"]',
    'script[id*="perseus" i]',
    'script[type="application/ld+json"]',
]


async def _extract_page_json_blobs(page: Page) -> list[Any]:
    blobs: list[Any] = []
    seen: set[str] = set()

    for selector in JSON_SCRIPT_SELECTORS:
        loc = page.locator(selector)
        try:
            count = min(await loc.count(), 80)
        except Exception:
            continue
        for i in range(count):
            try:
                raw = await loc.nth(i).text_content(timeout=1200)
            except Exception:
                continue
            if not raw or len(raw) < 20:
                continue
            key = raw[:200]
            if key in seen:
                continue
            seen.add(key)
            try:
                blobs.append(json.loads(raw))
            except Exception:
                continue

    return blobs


def _slug_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value).lower())


def _is_seller_name(value: str, seller_slug: str) -> bool:
    return bool(seller_slug and _slug_key(value) == _slug_key(seller_slug))


def _field_text(obj: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str):
            text = clean_text(value).lstrip("@")
            if text:
                return text
        if isinstance(value, (int, float)):
            return clean_text(value)
    return ""


def _pick_buyer(obj: dict[str, Any], seller_slug: str) -> str:
    keys = [
        "buyerUsername",
        "reviewerUsername",
        "authorUsername",
        "username",
        "userName",
        "displayName",
        "name",
    ]
    name = _field_text(obj, keys)
    if (
        name
        and not looks_like_rating(name)
        and not _is_seller_name(name, seller_slug)
        and is_valid_reviewer_name(name)
    ):
        return name

    for nested_key in ("buyer", "reviewer", "author", "user"):
        nested = obj.get(nested_key)
        if not isinstance(nested, dict):
            continue
        name = _field_text(nested, keys)
        if (
            name
            and not looks_like_rating(name)
            and not _is_seller_name(name, seller_slug)
            and is_valid_reviewer_name(name)
        ):
            return name
    return ""


def _pick_text(obj: dict[str, Any]) -> str:
    for key in (
        "comment",
        "commentText",
        "reviewText",
        "description",
        "text",
        "message",
        "content",
        "body",
    ):
        value = obj.get(key)
        if isinstance(value, str):
            text = clean_text(value)
            if len(text) >= 15:
                return text
    return ""


def _pick_rating(obj: dict[str, Any]) -> float:
    for key in ("rating", "value", "stars", "score", "ratingScore", "reviewRating"):
        value = obj.get(key)
        try:
            rating = float(value)
        except (TypeError, ValueError):
            continue
        if 1 <= rating <= 5:
            return rating
    return 5.0


def _pick_country(obj: dict[str, Any]) -> str:
    for key in ("country", "countryCode", "location", "reviewerCountry"):
        country = normalize_country(clean_text(obj.get(key)))
        if country in ("United States", "Canada"):
            return country

    for nested_key in ("buyer", "reviewer", "author", "user"):
        nested = obj.get(nested_key)
        if not isinstance(nested, dict):
            continue
        country = _pick_country(nested)
        if country:
            return country
    return ""


def _pick_image(obj: dict[str, Any]) -> str:
    for key in ("reviewedImage", "attachment", "image", "deliveryImage", "url", "src"):
        value = obj.get(key)
        if isinstance(value, str) and value.startswith(("http", "//", "/")):
            return value
        if isinstance(value, dict):
            nested = _pick_image(value)
            if nested:
                return nested

    attachments = obj.get("attachments") or obj.get("media") or obj.get("images")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, str) and item.startswith(("http", "//", "/")):
                return item
            if isinstance(item, dict):
                nested = _pick_image(item)
                if nested:
                    return nested
    return ""


def _pick_date(obj: dict[str, Any]):
    for key in (
        "reviewDate",
        "createdAt",
        "created_at",
        "updatedAt",
        "date",
        "time",
        "reviewedAt",
    ):
        parsed = parse_review_date(obj.get(key))
        if parsed:
            return parsed
    return None


def _walk_reviews(blobs: list[Any], seller_slug: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def try_review(node: Any) -> None:
        if not isinstance(node, dict):
            return
        text = _pick_text(node)
        if len(text) < 15:
            return
        buyer = _pick_buyer(node, seller_slug)
        if not buyer:
            return
        country = _pick_country(node)
        if country not in ("United States", "Canada"):
            return
        key = f"{_slug_key(buyer)}|{text[:90].lower()}"
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "reviewerName": buyer,
                "reviewerCountry": country,
                "reviewText": text[:2000],
                "reviewRating": _pick_rating(node),
                "reviewDate": _pick_date(node),
                "reviewedImageLink": _pick_image(node),
            }
        )

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 14:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return

        try_review(node)
        for key in ("reviews", "buyerReviews", "gigReviews", "userReviews", "items", "nodes", "data", "list"):
            value = node.get(key)
            if isinstance(value, list):
                for item in value:
                    try_review(item)
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, depth + 1)

    for blob in blobs:
        walk(blob)
    return out


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
                for key in ("displayName", "name", "fullName", "sellerName"):
                    value = node.get(key)
                    if not isinstance(value, str):
                        continue
                    name = clean_text(value).lstrip("@")
                    if (
                        not display
                        and slug
                        and is_valid_seller_name(name, slug, "")
                        and name.lower() != "fiverr"
                    ):
                        display = name
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
    return {
        "sellerUsername": slug,
        "sellerDisplayName": display or slug,
        "sellerName": display or slug,
    }


async def extract_reviews_from_page_json(
    page: Page, seller_username: str
) -> list[dict[str, Any]]:
    try:
        blobs = await _extract_page_json_blobs(page)
        if not blobs:
            return []
        raw = _walk_reviews(blobs, seller_username or "")
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
                "reviewDate": item.get("reviewDate"),
                "reviewedImageLink": img,
            }
        )

    if results:
        print(f"[page_data] JSON: {len(results)} US/CA reviews (buyer names from page data)")
    return results


async def enrich_gig_from_page_json(page: Page, gig: dict) -> dict:
    """Ensure seller fields always match gig URL / embedded JSON — never 'Fiverr'."""
    slug = seller_name_from_gig(gig) or username_from_gig_url(page.url)
    current_display = clean_text(gig.get("sellerDisplayName") or gig.get("sellerName") or "")
    if slug:
        gig["sellerUsername"] = slug
        if current_display and is_valid_seller_name(
            current_display,
            slug,
            gig.get("gigTitle", ""),
        ):
            gig["sellerDisplayName"] = current_display
            gig["sellerName"] = current_display
            return gig
    url = gig.get("gigUrl") or page.url

    try:
        blobs = await _extract_page_json_blobs(page)
        if blobs:
            picked = _pick_seller_from_json(blobs, url)
            if picked.get("sellerUsername"):
                gig.update(picked)
    except Exception:
        pass

    slug = username_from_gig_url(url)
    if slug:
        gig["sellerUsername"] = slug
        display = clean_text(gig.get("sellerDisplayName") or gig.get("sellerName") or "")
        if not display or not is_valid_seller_name(display, slug, gig.get("gigTitle", "")):
            display = slug
        gig["sellerDisplayName"] = display
        gig["sellerName"] = display
    return gig
