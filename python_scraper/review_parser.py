import asyncio
import re
from datetime import datetime

from playwright.async_api import Locator, Page

from utils import absolutize_url, clean_text, is_valid_reviewer_name, normalize_country
from verification import assert_page_accessible

REVIEW_ROOT = '[class*="reviews" i], #reviews, [data-testid*="reviews" i]'
REVIEW_CARD_SELECTORS = [
    '[data-testid*="review-card" i]',
    '[class*="review-card" i]',
    '[class*="review-item" i]',
    "article[class*='review' i]",
    "li[class*='review' i]",
]

DELIVERY_IMAGE = re.compile(
    r"delivery|attachments|t_delivery|t_smartwm|/image/upload/",
    re.I,
)
BAD_REVIEW_IMAGE = re.compile(
    r"trophy|generic_asset|avatar|profile|badge|icon|flag|\.gif|/assets/",
    re.I,
)


def _normalize_target_country(value: str) -> str:
    text = clean_text(value)
    if re.search(r"united states|usa|u\.s\.", text, re.I):
        return "United States"
    if re.search(r"\bcanada\b", text, re.I):
        return "Canada"
    return ""


async def scroll_to_reviews(page: Page) -> None:
    tab = page.get_by_role("tab", name=re.compile(r"reviews", re.I)).first
    if await tab.count() and await tab.is_visible():
        await tab.click()
        await asyncio.sleep(1.5)

    for label in ("Reviews", "See all reviews", "Show all reviews"):
        btn = page.get_by_text(label, exact=False).first
        if await btn.count() and await btn.is_visible():
            await btn.click()
            await asyncio.sleep(1.2)

    section = page.locator(REVIEW_ROOT).first
    if await section.count():
        await section.scroll_into_view_if_needed(timeout=5000)

    await asyncio.sleep(2)
    for _ in range(8):
        await page.mouse.wheel(0, 900)
        await asyncio.sleep(0.45)


async def click_load_more(page: Page, max_clicks: int = 20) -> None:
    pattern = page.locator(
        'button:has-text("Show more"), button:has-text("See more"), '
        'button:has-text("Load more"), button:has-text("Show More")'
    )
    for _ in range(max_clicks):
        btn = pattern.first
        if not await btn.count() or not await btn.is_visible():
            break
        try:
            await btn.click(timeout=3000)
            await asyncio.sleep(1.5)
            await page.mouse.wheel(0, 400)
        except Exception:
            break


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
    return 0.0


async def _reviewer_name(card: Locator, card_text: str) -> str:
    # Profile link in review header is most reliable
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

    # "Review by username" patterns in text
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


async def _review_delivery_image(card: Locator) -> str:
    """Review attachment image (required) — delivery/upload URLs only."""
    imgs = card.locator("img")
    for i in range(min(await imgs.count(), 25)):
        src = (
            await imgs.nth(i).get_attribute("src")
            or await imgs.nth(i).get_attribute("data-src")
            or ""
        )
        full = absolutize_url(src)
        if not full or BAD_REVIEW_IMAGE.search(full):
            continue
        if DELIVERY_IMAGE.search(full) and "fiverr" in full:
            return full
    return ""


async def _collect_review_cards(page: Page) -> list[tuple[Locator, str]]:
    seen: set[str] = set()
    out: list[tuple[Locator, str]] = []

    for sel in REVIEW_CARD_SELECTORS:
        loc = page.locator(sel)
        for i in range(min(await loc.count(), 100)):
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
    if max_reviews <= 0:
        max_reviews = 500

    await scroll_to_reviews(page)
    await click_load_more(page, max_clicks=25)
    await assert_page_accessible(page, job_id)

    candidates = await _collect_review_cards(page)
    reviews: list[dict] = []
    checked = 0

    for card, card_text in candidates:
        if len(reviews) >= max_reviews:
            break
        checked += 1

        country = await _find_country(card, card_text)
        norm = normalize_country(country)
        if norm not in ("United States", "Canada"):
            continue

        image = await _review_delivery_image(card)
        if not image:
            continue

        reviewer = await _reviewer_name(card, card_text)
        if not is_valid_reviewer_name(reviewer):
            continue

        rating = _parse_rating(card_text)
        if rating < 1:
            continue

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

        reviews.append(
            {
                "reviewerName": reviewer,
                "reviewerCountry": norm,
                "reviewText": text,
                "reviewRating": rating,
                "reviewDate": review_date,
                "reviewedImageLink": image,
            }
        )

    print(f"[reviews] {len(reviews)} US/CA leads with review images ({checked} cards checked)")
    return reviews, checked
