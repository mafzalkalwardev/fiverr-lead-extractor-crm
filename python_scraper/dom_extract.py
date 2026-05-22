"""
Extract reviews via in-page DOM (faster than many locator round-trips).
Used as fallback when Playwright locators find few cards.
"""
from typing import Any

from playwright.async_api import Page

from utils import absolutize_url, clean_text, is_valid_review_image, is_valid_reviewer_name

_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const isUS = (t) => /\b(United States|USA|U\.S\.)\b/i.test(t);
  const isCA = (t) => /\bCanada\b/i.test(t);
  const badImg = /avatar|profile|badge|trophy|icon|flag|\.gif/i;

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

  const pickName = (root, text) => {
    for (const a of root.querySelectorAll('a[href^="/"]')) {
      const h = a.getAttribute("href") || "";
      if (h.includes("/users/") || h.includes("/inbox")) continue;
      const t = (a.innerText || "").trim().replace(/^@/, "");
      if (t.length >= 2 && t.length <= 50 && /^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$/.test(t)) return t;
    }
    const m = text.match(/(?:reviewed by|by)\s+([a-zA-Z0-9_]{2,40})/i);
    return m ? m[1] : "";
  };

  const pickRating = (text) => {
    const m = text.match(/\b([1-5](?:\.\d)?)\s*(?:stars?|\/\s*5)/i) || text.match(/\b([1-5])\s*star/i);
    return m ? parseFloat(m[1]) : 5;
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
    const reviewer = pickName(el, text);
    if (!reviewer) continue;

    const rating = pickRating(text);
    let reviewText = text;
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
    });
  }
  return out;
}
"""


async def extract_reviews_from_dom(page: Page) -> list[dict[str, Any]]:
    try:
        raw = await page.evaluate(_EXTRACT_JS)
    except Exception as err:
        print(f"[dom] evaluate failed: {err}")
        return []

    results: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        reviewer = clean_text(item.get("reviewerName"))
        country = clean_text(item.get("reviewerCountry"))
        text = clean_text(item.get("reviewText"))
        img = absolutize_url(item.get("reviewedImageLink") or "")
        if not is_valid_reviewer_name(reviewer):
            continue
        if country not in ("United States", "Canada"):
            continue
        if len(text) < 15:
            continue
        if not img or not is_valid_review_image(img):
            continue
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

    print(f"[dom] DOM scan: {len(results)} US/CA reviews with images")
    return results
