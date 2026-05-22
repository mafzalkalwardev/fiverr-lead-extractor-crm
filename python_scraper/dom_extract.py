"""
Extract reviews via in-page DOM (faster than many locator round-trips).
Used as fallback when Playwright locators find few cards.
"""
from typing import Any

from playwright.async_api import Page

from utils import (
    absolutize_url,
    clean_text,
    infer_reviewer_from_text,
    is_valid_review_image,
    is_valid_reviewer_name,
    looks_like_rating,
    parse_rating_after_country,
    reviewer_name_before_country,
)

_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const isUS = (t) => /\b(United States|USA|U\.S\.)\b/i.test(t);
  const isCA = (t) => /\bCanada\b/i.test(t);
  const badImg = /avatar|profile|badge|trophy|icon|flag|\.gif/i;
  const isRating = (t) => /^[1-5](?:\.\d)?$/.test((t||'').trim()) || /^\d+(\.\d+)?$/.test((t||'').trim());
  const countryPat = /\b(United States|USA|U\.S\.?|Canada)\b/i;

  const pickImage = (root) => {
    for (const im of root.querySelectorAll("img")) {
      for (const a of ["src", "data-src", "data-lazy-src"]) {
        const s = im.getAttribute(a) || "";
        if (s && !badImg.test(s)) return s;
      }
      const ss = im.getAttribute("srcset");
      if (ss) {
        const u = ss.split(",")[0].trim().split(/\s+/)[0];
        if (u && !badImg.test(u)) return u;
      }
    }
    for (const a of root.querySelectorAll('a[href*=".jpg"], a[href*=".png"], a[href*="cloudinary"]')) {
      const h = a.getAttribute("href") || "";
      if (h && !badImg.test(h)) return h;
    }
    return "";
  };

  const okName = (t) => {
    t = (t || "").trim().replace(/^@/, "");
    return t.length >= 2 && t.length <= 60 && /^[a-zA-Z]/.test(t) && !isRating(t);
  };

  /** Reviewer is BEFORE country; rating is AFTER country */
  const pickReviewer = (text) => {
    const m = text.match(countryPat);
    if (!m || m.index <= 0) return "";
    let before = text.slice(0, m.index).trim();
    before = before.replace(/^[1-5](?:\.\d)?\s*/, "").trim();
    const lines = before.split(/\n/).map((s) => s.trim()).filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      if (okName(lines[i])) return lines[i];
    }
    const words = before.split(/\s+/);
    for (let n = Math.min(4, words.length); n >= 1; n--) {
      const cand = words.slice(-n).join(" ");
      if (okName(cand)) return cand;
    }
    return "";
  };

  const pickRating = (text) => {
    const m = text.match(countryPat);
    if (m) {
      const tail = text.slice(m.index + m[0].length, m.index + m[0].length + 30);
      const r = tail.match(/^\s*([1-5](?:\.\d)?)\b/);
      if (r) return parseFloat(r[1]);
    }
    const star = text.match(/\b([1-5](?:\.\d)?)\s*(?:stars?|\/\s*5)/i);
    return star ? parseFloat(star[1]) : 5;
  };

  const selectors = [
    '[data-testid*="review-card" i]',
    '[data-testid*="review" i]',
    '[class*="review-card" i]',
    '[class*="ReviewCard" i]',
    '[class*="review-item" i]',
    "article",
    "li",
  ];

  const nodes = new Set();
  for (const sel of selectors) {
    document.querySelectorAll(sel).forEach((n) => nodes.add(n));
  }

  for (const el of nodes) {
    const text = (el.innerText || "").replace(/\s+/g, " ").trim();
    if (text.length < 45 || text.length > 4500) continue;
    const country = isUS(text) ? "United States" : isCA(text) ? "Canada" : "";
    if (!country) continue;

    const key = text.slice(0, 80).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    const img = pickImage(el);
    const reviewer = pickReviewer(text);
    if (!reviewer || isRating(reviewer)) continue;

    const rating = pickRating(text);
    let reviewText = text;
    const cm = text.match(countryPat);
    if (cm) {
      let body = text.slice(cm.index + cm[0].length).trim();
      body = body.replace(/^[1-5](?:\.\d)?\s*/, "").trim();
      if (body.length >= 15) reviewText = body;
    }
    for (const rm of [reviewer, country, "See less", "See more", "Helpful"]) {
      reviewText = reviewText.replace(new RegExp(rm, "gi"), " ");
    }
    reviewText = reviewText.replace(/\s+/g, " ").trim();
    if (reviewText.length < 15) continue;

    out.push({
      reviewerName: reviewer,
      reviewerCountry: country,
      reviewText: reviewText.slice(0, 2000),
      reviewRating: rating,
      reviewedImageLink: img,
      cardText: text,
    });
  }
  return out;
}
"""


async def extract_reviews_from_dom(
    page: Page, seller_username: str = ""
) -> list[dict[str, Any]]:
    try:
        raw = await page.evaluate(_EXTRACT_JS)
    except Exception as err:
        print(f"[dom] evaluate failed: {err}")
        return []

    results: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        card_text = clean_text(item.get("cardText") or item.get("reviewText"))
        reviewer = reviewer_name_before_country(card_text)
        if not reviewer:
            reviewer = clean_text(item.get("reviewerName"))
        if looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
            reviewer = infer_reviewer_from_text(card_text, seller_username)
        if not reviewer or not is_valid_reviewer_name(reviewer):
            continue
        country = clean_text(item.get("reviewerCountry"))
        text = clean_text(item.get("reviewText"))
        img = absolutize_url(item.get("reviewedImageLink") or "")
        if country not in ("United States", "Canada"):
            continue
        if len(text) < 15:
            continue
        if not img or not is_valid_review_image(img):
            continue
        try:
            rating = float(item.get("reviewRating") or parse_rating_after_country(card_text))
        except (TypeError, ValueError):
            rating = parse_rating_after_country(card_text)
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
                "cardText": card_text,
            }
        )

    print(f"[dom] DOM scan: {len(results)} US/CA reviews with images")
    return results
