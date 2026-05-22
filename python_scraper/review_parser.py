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
    parse_rating_after_country,
    reviewer_name_before_country,
)
from db import append_activity
from dom_extract import extract_reviews_from_dom
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
        scope = page

    for _ in range(max_clicks):
        try:
            clicked = await scope.evaluate(
                """(root) => {
                  if (!root) return false;
                  const bad = /expand-description|expand-button|gig-description/i;
                  const btns = root.querySelectorAll('button, [role="button"]');
                  for (const b of btns) {
                    const t = (b.innerText || '').trim();
                    const cls = (b.className || '') + (b.getAttribute('class') || '');
                    if (bad.test(cls)) continue;
                    if (!/^(show more|see more|load more|show more reviews|see all reviews)$/i.test(t)) continue;
                    if (t.length > 40) continue;
                    b.click();
                    return true;
                  }
                  return false;
                }"""
            )
            if not clicked:
                break
            clicks += 1
            await asyncio.sleep(0.85)
            await page.mouse.wheel(0, 400)
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
    return parse_rating_after_country(text)


async def _reviewer_before_country_dom(card: Locator) -> str:
    """DOM: reviewer label is the sibling/segment before country (rating comes after)."""
    try:
        raw = await card.evaluate(
            """(el) => {
              const isRating = (t) => /^[1-5](?:\\.\\d)?$/.test((t||'').trim()) || /^\\d+(?:\\.\\d+)?$/.test((t||'').trim());
              const ok = (t) => {
                t = (t||'').trim().replace(/^@/, '');
                return t.length >= 2 && t.length <= 60 && /^[a-zA-Z]/.test(t) && !isRating(t);
              };
              const countryPat = /\\b(United States|USA|U\\.S\\.?|Canada)\\b/i;
              const full = (el.innerText||'').replace(/\\s+/g,' ').trim();
              const m = full.match(countryPat);
              if (m && m.index > 0) {
                let before = full.slice(0, m.index).trim();
                before = before.replace(/^[1-5](?:\\.\\d)?\\s*/, '').trim();
                const lines = before.split(/\\n/).map(s => s.trim()).filter(Boolean);
                for (let i = lines.length - 1; i >= 0; i--) {
                  if (ok(lines[i])) return lines[i];
                }
                const words = before.split(/\\s+/);
                for (let n = Math.min(4, words.length); n >= 1; n--) {
                  const cand = words.slice(-n).join(' ');
                  if (ok(cand)) return cand;
                }
              }
              for (const node of el.querySelectorAll('*')) {
                const t = (node.innerText||'').trim();
                if (!countryPat.test(t) || t.length > 40) continue;
                let prev = node.previousElementSibling;
                while (prev) {
                  const pt = (prev.innerText||'').trim().split('\\n')[0].replace(/^@/,'').trim();
                  if (ok(pt)) return pt;
                  prev = prev.previousElementSibling;
                }
              }
              return '';
            }"""
        )
        name = clean_text(str(raw or "")).lstrip("@")
        if name and not looks_like_rating(name) and is_valid_reviewer_name(name):
            return name
    except Exception:
        pass
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
    try:
        raw = await card.evaluate(
            """(el, seller) => {
              const isRating = (t) => /^[1-5](?:\\.\\d)?$/.test(t) || /^\\d+(?:\\.\\d+)?$/.test(t);
              const ok = (t) => {
                t = (t || "").trim().replace(/^@/, "");
                return t.length >= 2 && t.length <= 60 && /^[a-zA-Z]/.test(t) && !isRating(t);
              };
              const sellerL = (seller || "").toLowerCase();
              for (const sel of [
                '[data-testid*="reviewer" i]',
                '[class*="buyer" i] a',
                '[class*="reviewer" i] a',
                '[class*="user-name" i]',
                '[class*="username" i]',
                'a[href*="/users/"]',
              ]) {
                for (const n of el.querySelectorAll(sel)) {
                  const t = (n.innerText || "").trim();
                  if (ok(t) && t.toLowerCase() !== sellerL) return t.replace(/^@/, "");
                  const h = n.getAttribute("href") || "";
                  const um = h.match(/\\/users\\/([^/?#]+)/i);
                  if (um && ok(um[1]) && um[1].toLowerCase() !== sellerL) return um[1];
                }
              }
              for (const a of el.querySelectorAll('a[href^="/"]')) {
                const h = a.getAttribute("href") || "";
                if (/\\/users\\/|inbox|search|categories|login|join/i.test(h)) continue;
                const parts = h.replace(/^\\//, "").split("/").filter(Boolean);
                if (parts.length === 1 && parts[0].toLowerCase() !== sellerL && ok(parts[0]))
                  return parts[0];
              }
              return "";
            }""",
            seller_username or "",
        )
        name = clean_text(str(raw or "")).lstrip("@")
        if name and not looks_like_rating(name) and is_valid_reviewer_name(name):
            return name
    except Exception:
        pass
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
