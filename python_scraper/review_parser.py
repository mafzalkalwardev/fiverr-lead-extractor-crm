import asyncio
import re
from datetime import datetime

from playwright.async_api import Locator, Page

import config
from utils import (
    absolutize_url,
    clean_text,
    is_valid_review_image,
    is_valid_reviewer_name,
    normalize_country,
)
from db import append_activity
from dom_extract import extract_reviews_from_dom
from verification import assert_page_accessible

REVIEW_ROOT = '[class*="reviews" i], #reviews, [data-testid*="reviews" i]'
REVIEW_CARD_SELECTORS = [
    '[data-testid*="review-card" i]',
    '[class*="review-card" i]',
    '[class*="review-item" i]',
    "article[class*='review' i]",
    "li[class*='review' i]",
]

BAD_REVIEW_IMAGE = re.compile(
    r"trophy|generic_asset|avatar|profile|badge|icon|flag|\.gif|/assets/|seller",
    re.I,
)
REVIEW_IMAGE_HINT = re.compile(
    r"cloudinary|fiverr-res|fiverrstatic|/image/upload/|attachments|delivery|t_delivery|t_smartwm|review",
    re.I,
)


def _normalize_target_country(value: str) -> str:
    text = clean_text(value)
    if re.search(r"united states|usa|u\.s\.", text, re.I):
        return "United States"
    if re.search(r"\bcanada\b", text, re.I):
        return "Canada"
    return ""


def _image_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    first = srcset.split(",")[0].strip().split()[0]
    return absolutize_url(first)


async def scroll_to_reviews(page: Page) -> None:
    tab = page.get_by_role("tab", name=re.compile(r"reviews", re.I)).first
    if await tab.count() and await tab.is_visible():
        await tab.click()
        await asyncio.sleep(0.8)

    for label in ("Reviews", "See all reviews", "Show all reviews"):
        btn = page.get_by_text(label, exact=False).first
        if await btn.count() and await btn.is_visible():
            await btn.click()
            await asyncio.sleep(0.6)

    section = page.locator(REVIEW_ROOT).first
    if await section.count():
        await section.scroll_into_view_if_needed(timeout=5000)

    await asyncio.sleep(0.8)
    for _ in range(5):
        await page.mouse.wheel(0, 900)
        await asyncio.sleep(0.25)


async def click_load_more(page: Page, max_clicks: int = 50) -> int:
    pattern = page.locator(
        'button:has-text("Show more"), button:has-text("See more"), '
        'button:has-text("Load more"), button:has-text("Show More"), '
        'button:has-text("See all")'
    )
    clicks = 0
    for _ in range(max_clicks):
        btn = pattern.first
        if not await btn.count() or not await btn.is_visible():
            break
        try:
            await btn.scroll_into_view_if_needed(timeout=2000)
            await btn.click(timeout=3000)
            clicks += 1
            await asyncio.sleep(0.9)
            await page.mouse.wheel(0, 500)
        except Exception:
            break
    return clicks


async def _card_text(card: Locator) -> str:
    try:
        return clean_text(await card.inner_text(timeout=2500))
    except Exception:
        return ""


async def _find_country(card: Locator, card_text: str) -> str:
    for sel in ('[class*="country" i]', '[class*="location" i]', '[data-testid*="country" i]'):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 10)):
            t = clean_text(await loc.nth(i).inner_text(timeout=800))
            c = _normalize_target_country(t)
            if c:
                return c
            alt = await loc.nth(i).get_attribute("aria-label") or ""
            c = _normalize_target_country(alt)
            if c:
                return c

    m = re.search(
        r"\b(?:from|located in)\s+(United States|USA|U\.S\.|Canada)\b",
        card_text,
        re.I,
    )
    if m:
        return _normalize_target_country(m.group(1))
    return ""


def _parse_rating(text: str) -> float:
    m = re.search(r"\b([1-5](?:\.\d)?)\b(?=.*\b(?:stars?|rating)\b)", text, re.I)
    if not m:
        m = re.search(r"\b([1-5](?:\.\d)?)\s*/\s*5\b", text, re.I)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 5:
            return v
    m = re.search(r"\b([1-5])\s*star", text, re.I)
    if m:
        return float(m.group(1))
    return 5.0


async def _reviewer_name(card: Locator, card_text: str) -> str:
    for sel in (
        'a[href^="/"]',
        '[data-testid*="reviewer" i]',
        '[class*="reviewer" i] a',
        '[class*="username" i]',
        "h4",
        "strong",
    ):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 8)):
            href = await loc.nth(i).get_attribute("href") or ""
            if "/users/" in href or "/inbox" in href:
                continue
            t = clean_text(await loc.nth(i).inner_text(timeout=800)).lstrip("@")
            if is_valid_reviewer_name(t):
                return t

    m = re.search(r"(?:reviewed by|by)\s+([a-zA-Z0-9_]{2,40})", card_text, re.I)
    if m and is_valid_reviewer_name(m.group(1)):
        return m.group(1)

    return ""


async def _review_text(card: Locator, card_text: str, reviewer: str, country: str) -> str:
    candidates = []
    for sel in (
        '[data-testid*="review-comment" i]',
        '[class*="review-text" i]',
        '[class*="review-description" i]',
        '[class*="comment" i]',
        "p",
    ):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 15)):
            t = clean_text(await loc.nth(i).inner_text(timeout=800))
            if len(t) >= 15 and t != reviewer and t != country:
                if not re.match(r"^\d+(\.\d+)?$", t):
                    candidates.append(t)
    if candidates:
        return max(candidates, key=len)[:2000]

    fallback = card_text
    for token in (reviewer, country, "United States", "Canada", "See less", "See more"):
        fallback = re.sub(re.escape(token), " ", fallback, flags=re.I)
    fallback = clean_text(fallback)
    return fallback[:2000] if len(fallback) >= 15 else ""


def _score_review_image(url: str) -> int:
    if not url or not url.startswith("http"):
        return 0
    if BAD_REVIEW_IMAGE.search(url):
        return 0
    if REVIEW_IMAGE_HINT.search(url):
        return 3
    if "fiverr" in url.lower() and re.search(r"\.(jpg|jpeg|png|webp)", url, re.I):
        return 2
    return 0


async def _review_delivery_image(card: Locator) -> str:
    """Review attachment / delivery image — scroll card into view so lazy images populate."""
    try:
        await card.scroll_into_view_if_needed(timeout=3000)
        await asyncio.sleep(0.35)
    except Exception:
        pass

    best = ""
    best_score = 0

    imgs = card.locator("img")
    for i in range(min(await imgs.count(), 30)):
        img = imgs.nth(i)
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            src = await img.get_attribute(attr) or ""
            full = absolutize_url(src)
            score = _score_review_image(full)
            if score > best_score:
                best_score = score
                best = full
        srcset = await img.get_attribute("srcset") or ""
        full = _image_from_srcset(srcset)
        score = _score_review_image(full)
        if score > best_score:
            best_score = score
            best = full

    for sel in ('a[href*=".jpg"], a[href*=".jpeg"], a[href*=".png"], a[href*="cloudinary"]'):
        links = card.locator(sel)
        for i in range(min(await links.count(), 8)):
            href = await links.nth(i).get_attribute("href") or ""
            full = absolutize_url(href)
            score = _score_review_image(full)
            if score > best_score:
                best_score = score
                best = full

    try:
        urls = await card.evaluate(
            """(el) => {
              const out = [];
              el.querySelectorAll('img').forEach((img) => {
                ['src','data-src','data-lazy-src'].forEach((a) => {
                  const v = img.getAttribute(a);
                  if (v) out.push(v);
                });
                const ss = img.getAttribute('srcset');
                if (ss) out.push(ss.split(',')[0].trim().split(' ')[0]);
              });
              el.querySelectorAll('[style*="background"]').forEach((n) => {
                const m = (n.getAttribute('style')||'').match(/url\\(["']?([^"')]+)/);
                if (m) out.push(m[1]);
              });
              return out;
            }"""
        )
        for raw in urls or []:
            full = absolutize_url(str(raw))
            score = _score_review_image(full)
            if score > best_score:
                best_score = score
                best = full
    except Exception:
        pass

    return best if best_score > 0 else ""


async def _collect_review_cards(page: Page) -> list[tuple[Locator, str]]:
    seen: set[str] = set()
    out: list[tuple[Locator, str]] = []

    for sel in REVIEW_CARD_SELECTORS:
        loc = page.locator(sel)
        for i in range(min(await loc.count(), 200)):
            card = loc.nth(i)
            text = await _card_text(card)
            if len(text) < 40:
                continue
            key = text[:100].lower()
            if key in seen:
                continue
            country = await _find_country(card, text)
            if not country and "review" not in (await card.get_attribute("class") or "").lower():
                continue
            seen.add(key)
            out.append((card, text))
    return out


async def extract_reviews(
    page: Page,
    max_reviews: int,
    job_id: str,
) -> tuple[list[dict], int]:
    """
    Load all visible reviews on the current gig page, then return US/CA reviews with images.
    max_reviews <= 0 means no cap (extract every qualifying review on the page).
    """
    unlimited = max_reviews <= 0
    if not unlimited and max_reviews < 1:
        max_reviews = 500

    await scroll_to_reviews(page)
    load_clicks = await click_load_more(page, max_clicks=config.REVIEW_LOAD_MORE_MAX)
    if load_clicks:
        append_activity(job_id, f"Expanded reviews ({load_clicks} load-more clicks)")

    await assert_page_accessible(page, job_id)

    candidates = await _collect_review_cards(page)
    parsed: list[dict] = []
    checked = 0

    for card, card_text in candidates:
        checked += 1

        country = await _find_country(card, card_text)
        norm = normalize_country(country)
        if norm not in ("United States", "Canada"):
            continue

        image = await _review_delivery_image(card)
        if not image or not is_valid_review_image(image):
            continue

        reviewer = await _reviewer_name(card, card_text)
        if not is_valid_reviewer_name(reviewer):
            continue

        rating = _parse_rating(card_text)
        text = await _review_text(card, card_text, reviewer, norm)
        if len(text) < 15:
            continue

        review_date = None
        time_el = card.locator("time").first
        if await time_el.count():
            raw = await time_el.get_attribute("datetime") or await time_el.inner_text()
            try:
                review_date = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                pass

        parsed.append(
            {
                "reviewerName": reviewer,
                "reviewerCountry": norm,
                "reviewText": text,
                "reviewRating": rating,
                "reviewDate": review_date,
                "reviewedImageLink": image,
            }
        )

    if len(parsed) < 1:
        dom_list = await extract_reviews_from_dom(page)
        seen_keys = {
            f"{r['reviewerName']}|{r['reviewText'][:80].lower()}" for r in parsed
        }
        for r in dom_list:
            key = f"{r['reviewerName']}|{r['reviewText'][:80].lower()}"
            if key not in seen_keys:
                seen_keys.add(key)
                parsed.append(r)
        if dom_list:
            append_activity(
                job_id,
                f"DOM fallback: +{len(dom_list)} review(s) (locators found {checked} cards)",
            )
        checked = max(checked, len(dom_list))

    if not unlimited:
        parsed = parsed[:max_reviews]

    append_activity(
        job_id,
        f"Reviews on gig: {len(parsed)} US/CA with images ({checked} cards scanned)",
    )

    print(
        f"[reviews] {len(parsed)} US/CA leads with review images "
        f"({checked} cards checked, load-more={load_clicks})"
    )
    return parsed, checked
