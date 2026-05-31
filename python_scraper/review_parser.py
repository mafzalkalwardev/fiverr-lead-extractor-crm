import asyncio
import re
from datetime import datetime

from playwright.async_api import Locator, Page

import config
from utils import (
    absolutize_url,
    clean_text,
    infer_reviewer_from_text,
    is_valid_review_image,
    is_valid_reviewer_name,
    looks_like_rating,
    normalize_country,
    parse_review_date,
    parse_rating_after_country,
    reviewer_name_before_country,
)
from db import append_activity, update_job
from page_data import extract_reviews_from_page_json
from verification import assert_page_accessible

# Avoid gig-page carousel / description expanders (causes timeouts & wrong clicks)
REVIEW_SECTION = (
    '[data-testid="reviews-tab-panel"], [data-testid*="reviews-tab" i], '
    '#reviews-tab, section:has([data-testid*="review-card" i]), '
    '[class*="reviews-package" i], [class*="reviews-list" i]'
)
REVIEW_ROOT = '[data-testid="reviews-tab-panel"], [data-testid*="review-card" i]'
REVIEW_CARD_SELECTORS = [
    '[data-testid*="review-card" i]',
    '[class*="review-card" i]',
    '[class*="review-item" i]',
    "article[class*='review' i]",
    "li[class*='review' i]",
]

BAD_REVIEW_IMAGE = re.compile(
    r"trophy|generic_asset|avatar|profile|badge|icon|flag|\.gif|/assets/|seller|agency",
    re.I,
)
REVIEW_IMAGE_HINT = re.compile(
    r"attachments|attachment|delivery|t_delivery|t_smartwm|review",
    re.I,
)
GENERIC_FIVERR_IMAGE_HOST = re.compile(r"cloudinary|fiverr-res|fiverrstatic", re.I)
GIG_IMAGE_HINT = re.compile(
    r"/gigs/|t_main|gig_card|gig-card|gig_cards|gig-cards",
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
        try:
            await tab.click(timeout=5000)
            await asyncio.sleep(1.0)
        except Exception:
            pass

    section = page.locator(REVIEW_SECTION).first
    if await section.count():
        try:
            await section.scroll_into_view_if_needed(timeout=8000)
        except Exception:
            pass
    else:
        for _ in range(6):
            await page.mouse.wheel(0, 1100)
            await asyncio.sleep(0.35)

    await asyncio.sleep(0.6)
    for _ in range(4):
        await page.mouse.wheel(0, 800)
        await asyncio.sleep(0.25)


async def click_load_more(page: Page, max_clicks: int = 50) -> int:
    """Only click load-more inside buyer reviews — not gig description 'See more'."""
    clicks = 0
    scope = page.locator(REVIEW_SECTION).first
    if not await scope.count():
        scope = page.locator("body")

    for _ in range(max_clicks):
        try:
            before_text = clean_text(await scope.inner_text(timeout=1000))
            buttons = scope.locator('button, [role="button"], a')
            count = min(await buttons.count(), 80)
            clicked = False
            for i in range(count):
                btn = buttons.nth(i)
                text = clean_text(await btn.inner_text(timeout=700))
                aria = clean_text(await btn.get_attribute("aria-label") or "")
                label = text or aria
                if not re.match(
                    r"^(show more|see more|load more|show more reviews|load more reviews|see all reviews|more reviews)$",
                    label,
                    re.I,
                ):
                    continue
                if len(label) > 40:
                    continue
                marker_parts = []
                for attr in ("class", "id", "data-testid"):
                    marker_parts.append(clean_text(await btn.get_attribute(attr) or ""))
                marker = " ".join(marker_parts)
                if re.search(r"expand-description|gig-description|package", marker, re.I):
                    continue
                if not await btn.is_visible(timeout=500):
                    continue
                try:
                    if not await btn.is_enabled(timeout=500):
                        continue
                except Exception:
                    pass
                await btn.click(timeout=3000)
                clicked = True
                break
            if not clicked:
                break
            clicks += 1
            await asyncio.sleep(0.85)
            await page.mouse.wheel(0, 400)
            after_text = clean_text(await scope.inner_text(timeout=1000))
            if len(after_text) <= len(before_text) + 5:
                break
        except Exception:
            break
    return clicks


async def _close_open_dialogs(page: Page) -> None:
    """Dismiss any open gallery/portfolio overlay that could interfere with review pagination."""
    try:
        for sel in (
            '[role="dialog"] button[aria-label*="close" i]',
            '[role="dialog"] button[aria-label*="dismiss" i]',
            '[class*="overlay" i] button[aria-label*="close" i]',
        ):
            btn = page.locator(sel).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=2000)
                await asyncio.sleep(0.3)
                return
        if await page.locator('[role="dialog"]:visible').count():
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
    except Exception:
        pass


async def click_next_review_page(page: Page, current_page: int) -> bool:
    """Click the next reviews pagination control inside the review section."""
    scope = page.locator(REVIEW_SECTION).first
    if not await scope.count():
        return False  # No review section found — never fall back to body-level pagination

    candidates = [
        scope.get_by_role("button", name=re.compile(r"^(next|next page|>)$", re.I)),
        scope.get_by_role("link", name=re.compile(r"^(next|next page|>)$", re.I)),
        scope.locator('[aria-label*="next" i]'),
        scope.locator(f'button:has-text("{current_page + 1}")'),
        scope.locator(f'a:has-text("{current_page + 1}")'),
    ]

    for loc in candidates:
        count = min(await loc.count(), 8)
        for i in range(count):
            btn = loc.nth(i)
            try:
                label = clean_text(
                    await btn.inner_text(timeout=600)
                    or await btn.get_attribute("aria-label")
                    or ""
                )
            except Exception:
                label = clean_text(await btn.get_attribute("aria-label") or "")
            marker_parts = []
            for attr in ("class", "aria-disabled", "disabled"):
                marker_parts.append(clean_text(await btn.get_attribute(attr) or ""))
            marker = " ".join(marker_parts)
            if re.search(r"disabled|true", marker, re.I):
                continue
            if label and re.search(r"previous|prev", label, re.I):
                continue
            try:
                if not await btn.is_visible(timeout=500):
                    continue
                if not await btn.is_enabled(timeout=500):
                    continue
            except Exception:
                continue
            try:
                await btn.click(timeout=3000)
                await asyncio.sleep(1.1)
                await page.mouse.wheel(0, 400)
                return True
            except Exception:
                continue
    return False


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
    return parse_rating_after_country(text)


async def _reviewer_before_country_dom(card: Locator) -> str:
    """DOM: reviewer label is the sibling/segment before country (rating comes after)."""
    try:
        raw = await card.inner_text(timeout=2000)
    except Exception:
        raw = ""

    lines = [clean_text(line).lstrip("@") for line in str(raw).splitlines()]
    lines = [line for line in lines if line]
    country_pat = re.compile(r"\b(United States|USA|U\.S\.?|Canada)\b", re.I)

    for idx, line in enumerate(lines):
        match = country_pat.search(line)
        if not match:
            continue

        before = clean_text(line[: match.start()]).lstrip("@")
        if before and not looks_like_rating(before) and is_valid_reviewer_name(before):
            return before

        for prev in reversed(lines[:idx]):
            name = re.sub(r"^[1-5](?:\.\d)?\s*", "", prev).strip().lstrip("@")
            if name and not looks_like_rating(name) and is_valid_reviewer_name(name):
                return name

    name = reviewer_name_before_country(raw)
    if name and not looks_like_rating(name) and is_valid_reviewer_name(name):
        return name
    return ""


def _fix_reviewer_from_json(
    reviewer: str, card_text: str, json_reviews: list[dict]
) -> str:
    if reviewer and not looks_like_rating(reviewer) and is_valid_reviewer_name(reviewer):
        return reviewer
    key = card_text[:120].lower()
    for jr in json_reviews:
        jt = (jr.get("reviewText") or "")[:120].lower()
        if not jt:
            continue
        if key[:60] in jt or jt[:60] in key:
            name = clean_text(jr.get("reviewerName", ""))
            if name and is_valid_reviewer_name(name):
                return name
    return reviewer


def _reviewer_from_href(href: str) -> str:
    m = re.search(r"/users/([^/?#]+)", href or "", re.I)
    if not m:
        return ""
    return clean_text(m.group(1)).lstrip("@")


async def _reviewer_from_card_js(card: Locator, seller_username: str) -> str:
    seller_l = (seller_username or "").lower()
    selectors = [
        '[data-testid*="reviewer" i]',
        '[class*="buyer" i] a',
        '[class*="reviewer" i] a',
        '[class*="user-name" i]',
        '[class*="username" i]',
        'a[href*="/users/"]',
        'a[href^="/"]',
    ]
    for sel in selectors:
        loc = card.locator(sel)
        try:
            count = min(await loc.count(), 12)
        except Exception:
            continue
        for i in range(count):
            node = loc.nth(i)
            href = await node.get_attribute("href") or ""
            slug = _reviewer_from_href(href)
            if slug and slug.lower() != seller_l and is_valid_reviewer_name(slug):
                return slug
            text = clean_text(await node.inner_text(timeout=700)).lstrip("@")
            if (
                text
                and text.lower() != seller_l
                and not looks_like_rating(text)
                and is_valid_reviewer_name(text)
            ):
                return text
    return ""


async def _reviewer_name(card: Locator, card_text: str, seller_username: str = "") -> str:
    js_name = await _reviewer_from_card_js(card, seller_username)
    if js_name:
        return js_name

    user_links = card.locator('a[href*="/users/"]')
    for i in range(min(await user_links.count(), 8)):
        link = user_links.nth(i)
        href = await link.get_attribute("href") or ""
        slug = _reviewer_from_href(href)
        if slug and is_valid_reviewer_name(slug):
            return slug
        t = clean_text(await link.inner_text(timeout=800)).lstrip("@")
        if t and not looks_like_rating(t) and is_valid_reviewer_name(t):
            return t

    for sel in (
        '[data-testid*="reviewer" i] a',
        '[data-testid*="reviewer" i]',
        '[class*="reviewer" i] a',
        '[class*="buyer" i] a',
        '[class*="username" i]',
        '[class*="user-name" i]',
    ):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 8)):
            href = await loc.nth(i).get_attribute("href") or ""
            slug = _reviewer_from_href(href)
            if slug and is_valid_reviewer_name(slug):
                return slug
            t = clean_text(await loc.nth(i).inner_text(timeout=800)).lstrip("@")
            if t and not looks_like_rating(t) and is_valid_reviewer_name(t):
                return t

    inferred = infer_reviewer_from_text(card_text, seller_username)
    if inferred:
        return inferred

    m = re.search(r"(?:reviewed by|by)\s+([a-zA-Z][a-zA-Z0-9_'. -]{1,50})", card_text, re.I)
    if m and is_valid_reviewer_name(m.group(1).strip()):
        return m.group(1).strip()

    return ""


def _review_text_from_card_text(card_text: str, country: str) -> str:
    raw = clean_text(card_text)
    country_match = re.search(rf"\b({re.escape(country)}|USA|U\.S\.?|Canada)\b", raw, re.I)
    if not country_match:
        return ""
    body = raw[country_match.end() :].strip()
    body = re.sub(r"^[1-5](?:\.\d)?\s*", "", body).strip()
    body = re.sub(
        r"^(?:just now|today|yesterday|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago)\s+",
        "",
        body,
        flags=re.I,
    ).strip()
    body = re.split(
        r"\b(?:Up to|PKR[\d,.-]*|US\$|\$|Price|Duration|S\s*Seller'?s Response|Seller'?s Response)\b",
        body,
        flags=re.I,
    )[0]
    body = re.sub(
        r"\s+(?:just now|today|yesterday|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago)$",
        "",
        body,
        flags=re.I,
    )
    body = clean_text(body.replace("See more", " ").replace("See less", " "))
    return body[:2000] if len(body) >= 15 else ""


async def _review_text(card: Locator, card_text: str, reviewer: str, country: str) -> str:
    from_card = _review_text_from_card_text(card_text, country)
    if from_card:
        return from_card

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
                t = re.split(r"\bS?\s*Seller'?s Response\b", t, flags=re.I)[0]
                t = clean_text(t)
                if len(t) < 15:
                    continue
                if not re.match(r"^\d+(\.\d+)?$", t):
                    candidates.append(t)
    if candidates:
        return max(candidates, key=len)[:2000]

    fallback = card_text
    for token in (reviewer, country, "United States", "Canada", "See less", "See more"):
        fallback = re.sub(re.escape(token), " ", fallback, flags=re.I)
    fallback = re.split(r"\bS?\s*Seller'?s Response\b", fallback, flags=re.I)[0]
    fallback = clean_text(fallback)
    return fallback[:2000] if len(fallback) >= 15 else ""


def _strip_image_url(value: str) -> str:
    return clean_text(value).split("?")[0].rstrip("/")


def _score_review_image(url: str, reject_urls: set[str] | None = None) -> int:
    if not url or not url.startswith("http"):
        return 0
    if reject_urls and _strip_image_url(url) in reject_urls:
        return 0
    if BAD_REVIEW_IMAGE.search(url):
        return 0
    if GIG_IMAGE_HINT.search(url) and not REVIEW_IMAGE_HINT.search(url):
        return 0
    if REVIEW_IMAGE_HINT.search(url):
        return 4
    if (
        GENERIC_FIVERR_IMAGE_HOST.search(url)
        and re.search(r"\.(jpg|jpeg|png|webp)", url, re.I)
        and not GIG_IMAGE_HINT.search(url)
    ):
        return 2
    return 0


async def _review_delivery_image(card: Locator, reject_urls: set[str] | None = None) -> str:
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
            score = _score_review_image(full, reject_urls)
            if score > best_score:
                best_score = score
                best = full
        srcset = await img.get_attribute("srcset") or ""
        full = _image_from_srcset(srcset)
        score = _score_review_image(full, reject_urls)
        if score > best_score:
            best_score = score
            best = full

    for sel in ('a[href*=".jpg"], a[href*=".jpeg"], a[href*=".png"], a[href*="cloudinary"]',):
        links = card.locator(sel)
        for i in range(min(await links.count(), 8)):
            href = await links.nth(i).get_attribute("href") or ""
            full = absolutize_url(href)
            score = _score_review_image(full, reject_urls)
            if score > best_score:
                best_score = score
                best = full

    styled = card.locator('[style*="background"]')
    for i in range(min(await styled.count(), 12)):
        style = await styled.nth(i).get_attribute("style") or ""
        match = re.search(r"url\([\"']?([^\"')]+)", style)
        if not match:
            continue
        full = absolutize_url(match.group(1))
        score = _score_review_image(full, reject_urls)
        if score > best_score:
            best_score = score
            best = full

    return best if best_score > 0 else ""


def _country_mention_count(text: str) -> int:
    return len(re.findall(r"\b(United States|USA|U\.S\.?|Canada)\b", text, re.I))


async def _review_date(card: Locator, card_text: str):
    time_el = card.locator("time").first
    if await time_el.count():
        for attr in ("datetime", "title", "aria-label"):
            parsed = parse_review_date(await time_el.get_attribute(attr) or "")
            if parsed:
                return parsed
        parsed = parse_review_date(await time_el.inner_text(timeout=800))
        if parsed:
            return parsed

    for sel in ('[class*="date" i]', '[data-testid*="date" i]', '[class*="time" i]'):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 8)):
            parsed = parse_review_date(await loc.nth(i).inner_text(timeout=700))
            if parsed:
                return parsed

    m = re.search(
        r"\b(?:just now|today|yesterday|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
        card_text,
        re.I,
    )
    return parse_review_date(m.group(0)) if m else None


async def _collect_review_cards(page: Page) -> list[tuple[Locator, str]]:
    seen: set[str] = set()
    out: list[tuple[Locator, str, str]] = []

    for selector_index, sel in enumerate(REVIEW_CARD_SELECTORS):
        loc = page.locator(sel)
        for i in range(min(await loc.count(), 200)):
            card = loc.nth(i)
            text = await _card_text(card)
            if len(text) < 40 or len(text) > 4500:
                continue
            key = text[:100].lower()
            if key in seen:
                continue
            country = await _find_country(card, text)
            class_name = (await card.get_attribute("class") or "").lower()
            if "review-item-description" in class_name:
                continue
            if not country and "review" not in class_name:
                continue
            if selector_index >= 3 and _country_mention_count(text) > 3 and "review" not in class_name:
                continue
            seen.add(key)
            out.append((card, text, class_name))
        if out and selector_index < 3:
            break
    out.sort(
        key=lambda item: (
            0 if "review-item-component-wrapper" in item[2] else 1,
            0 if item[1].find("Seller's Response") < 0 else 1,
            -len(item[1]),
        )
    )
    return [(card, text) for card, text, _class_name in out]


async def _extract_reviews_legacy_unused(
    page: Page,
    max_reviews: int,
    job_id: str,
    seller_username: str = "",
) -> tuple[list[dict], int]:
    """
    Load all visible reviews on the current gig page, then return US/CA reviews with images.
    max_reviews <= 0 means no cap (extract every qualifying review on the page).
    """
    unlimited = max_reviews <= 0
    if not unlimited and max_reviews < 1:
        max_reviews = 500

    # Primary: embedded page JSON (__NEXT_DATA__ / Perseus) — stable buyer usernames
    json_reviews = await extract_reviews_from_page_json(page, seller_username)
    parsed: list[dict] = list(json_reviews)

    await scroll_to_reviews(page)
    load_clicks = await click_load_more(page, max_clicks=config.REVIEW_LOAD_MORE_MAX)
    if load_clicks:
        append_activity(job_id, f"Expanded reviews ({load_clicks} load-more clicks)")

    await assert_page_accessible(page, job_id)

    candidates = await _collect_review_cards(page)
    checked = len(json_reviews)
    seen_keys = {
        f"{r['reviewerName']}|{r['reviewText'][:80].lower()}" for r in parsed
    }

    for card, card_text in candidates:
        checked += 1

        country = await _find_country(card, card_text)
        norm = normalize_country(country)
        if norm not in ("United States", "Canada"):
            continue

        image = await _review_delivery_image(card)
        if not image or not is_valid_review_image(image):
            continue

        reviewer = await _reviewer_before_country_dom(card)
        if not reviewer:
            reviewer = reviewer_name_before_country(card_text)
        if not reviewer:
            reviewer = await _reviewer_name(card, card_text, seller_username)
        reviewer = _fix_reviewer_from_json(reviewer, card_text, json_reviews)
        if not reviewer or looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
            reviewer = infer_reviewer_from_text(card_text, seller_username)
        if not reviewer or looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
            continue

        rating = parse_rating_after_country(card_text)
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

        key = f"{reviewer}|{text[:80].lower()}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        parsed.append(
            {
                "reviewerName": reviewer,
                "reviewerCountry": norm,
                "reviewText": text,
                "reviewRating": rating,
                "reviewDate": review_date,
                "reviewedImageLink": image,
                "cardText": card_text,
            }
        )

    if len(parsed) < 1:
        dom_list = await extract_reviews_from_dom(page, seller_username)
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


async def extract_reviews(
    page: Page,
    max_reviews: int,
    job_id: str,
    seller_username: str = "",
    progress_base: int = 0,
    review_image_mode: str = "with_image",
    main_gig_image: str = "",
) -> tuple[list[dict], int]:
    """
    Load all review pages on the current gig page, then return US/CA reviews.
    max_reviews <= 0 means no cap.
    """
    unlimited = max_reviews <= 0
    if not unlimited and max_reviews < 1:
        max_reviews = 500

    with_images = review_image_mode != "without_image"
    reject_image_urls = {
        _strip_image_url(absolutize_url(main_gig_image)),
    } - {""}

    json_reviews = await extract_reviews_from_page_json(page, seller_username)
    if with_images:
        parsed: list[dict] = [
            r
            for r in json_reviews
            if is_valid_review_image(absolutize_url(r.get("reviewedImageLink") or ""))
            and _strip_image_url(absolutize_url(r.get("reviewedImageLink") or ""))
            not in reject_image_urls
        ]
    else:
        parsed = [{**r, "reviewedImageLink": ""} for r in json_reviews]
    checked = len(json_reviews)
    seen_keys = {
        f"{clean_text(r['reviewerName']).lower()}|{clean_text(r['reviewText'])[:100].lower()}"
        for r in parsed
    }
    seen_text_keys = {clean_text(r["reviewText"])[:140].lower() for r in parsed}
    if json_reviews:
        mode_note = "with review image links" if with_images else "without review image links"
        append_activity(
            job_id,
            f"JSON reviews parsed: {len(parsed)}/{len(json_reviews)} US/CA reviews ({mode_note})",
        )

    await scroll_to_reviews(page)
    review_page = 1
    total_load_clicks = 0
    seen_page_signatures: set[str] = set()
    consecutive_empty_pages = 0

    await _close_open_dialogs(page)

    while True:
        if review_page > max(1, config.REVIEW_MAX_PAGES):
            append_activity(
                job_id,
                f"Review pagination stopped at safety limit ({config.REVIEW_MAX_PAGES} pages)",
            )
            break

        update_job(
            job_id,
            {
                "currentReviewPage": review_page,
                "totalReviewsParsed": progress_base + checked,
            },
        )

        load_clicks = await click_load_more(page, max_clicks=config.REVIEW_LOAD_MORE_MAX)
        total_load_clicks += load_clicks
        if load_clicks:
            append_activity(
                job_id,
                f"Review page {review_page}: expanded reviews ({load_clicks} load-more clicks)",
            )

        await assert_page_accessible(page, job_id)
        candidates = await _collect_review_cards(page)
        append_activity(
            job_id,
            f"Review page {review_page}: {len(candidates)} review block(s) found",
        )
        signature = "|".join(clean_text(text)[:120].lower() for _card, text in candidates[:10])
        if signature and signature in seen_page_signatures:
            append_activity(
                job_id,
                f"Review page {review_page}: repeated page content detected; stopping pagination",
            )
            break
        if signature:
            seen_page_signatures.add(signature)

        if len(candidates) == 0:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:
                append_activity(
                    job_id,
                    f"Review page {review_page}: no review blocks on {consecutive_empty_pages} "
                    "consecutive pages — stopping pagination",
                )
                break
        else:
            consecutive_empty_pages = 0

        kept_before_page = len(parsed)

        for card, card_text in candidates:
            checked += 1

            country = await _find_country(card, card_text)
            norm = normalize_country(country)
            if norm not in ("United States", "Canada"):
                if country:
                    append_activity(job_id, f"Review skipped: country={country}")
                continue

            reviewer = await _reviewer_before_country_dom(card)
            if not reviewer:
                reviewer = reviewer_name_before_country(card_text)
            if not reviewer:
                reviewer = await _reviewer_name(card, card_text, seller_username)
            reviewer = _fix_reviewer_from_json(reviewer, card_text, json_reviews)
            if not reviewer or looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
                reviewer = infer_reviewer_from_text(card_text, seller_username)
            if not reviewer or looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
                append_activity(job_id, "Review skipped: reviewer missing or looked like rating")
                continue

            rating = parse_rating_after_country(card_text)
            text = await _review_text(card, card_text, reviewer, norm)
            if len(text) < 15:
                append_activity(job_id, f"Review skipped: text too short for reviewer={reviewer}")
                continue

            image = ""
            if with_images:
                image = await _review_delivery_image(card, reject_image_urls)
                if image and not is_valid_review_image(image):
                    image = ""
                if not image:
                    append_activity(job_id, f"Review skipped: no review image for reviewer={reviewer}")
                    continue

            review_date = await _review_date(card, card_text)
            key = f"{reviewer.strip().lower()}|{text[:100].lower()}"
            text_key = clean_text(text)[:140].lower()
            if key in seen_keys or text_key in seen_text_keys:
                append_activity(job_id, f"Duplicate skipped: {reviewer} ({norm})")
                continue
            seen_keys.add(key)
            seen_text_keys.add(text_key)

            append_activity(
                job_id,
                f"Reviewer extracted: {reviewer} | country={norm} | rating={rating} | page={review_page}",
            )
            parsed.append(
                {
                    "reviewerName": reviewer,
                    "reviewerCountry": norm,
                    "reviewText": text,
                    "reviewRating": rating,
                    "reviewDate": review_date,
                    "reviewedImageLink": image if with_images else "",
                    "cardText": card_text,
                    "reviewPage": review_page,
                }
            )

            if not unlimited and len(parsed) >= max_reviews:
                break

        kept_on_page = len(parsed) - kept_before_page
        update_job(
            job_id,
            {
                "currentReviewPage": review_page,
                "totalReviewsParsed": progress_base + checked,
            },
        )
        append_activity(
            job_id,
            f"Review page {review_page}: kept {kept_on_page} US/CA review(s); total kept {len(parsed)}",
        )

        if not unlimited and len(parsed) >= max_reviews:
            break
        await _close_open_dialogs(page)
        if not await click_next_review_page(page, review_page):
            break
        review_page += 1
        await scroll_to_reviews(page)

    if not unlimited:
        parsed = parsed[:max_reviews]

    append_activity(
        job_id,
        f"Reviews on gig: {len(parsed)} US/CA ({checked} reviews scanned, review pages={review_page}, imageMode={review_image_mode})",
    )
    print(
        f"[reviews] {len(parsed)} US/CA leads ({review_image_mode}) "
        f"({checked} cards checked, pages={review_page}, load-more={total_load_clicks})"
    )
    return parsed, checked
