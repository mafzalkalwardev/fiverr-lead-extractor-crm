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
    '[data-testid*="reviews" i], #reviews-tab, #reviews, '
    'section:has([data-testid*="review-card" i]), '
    '[class*="reviews-package" i], [class*="reviews-list" i], '
    '[class*="reviews-component" i], [class*="gig-reviews" i]'
)
REVIEW_ROOT = '[data-testid="reviews-tab-panel"], [data-testid*="review-card" i]'
REVIEW_CARD_SELECTORS = [
    '[data-testid*="review-card" i]',
    '[class*="review-item-component-wrapper" i]',
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


def _normalize_target_country(value: str, allow_short_code: bool = False) -> str:
    text = clean_text(value)
    text = re.sub(r"\bflag\s+of\b", " ", text, flags=re.I)
    text = re.sub(r"\bflag\b", " ", text, flags=re.I)
    text = re.sub(r"\bcountry\b", " ", text, flags=re.I)
    text = re.sub(r"^from\s+", "", text, flags=re.I)
    text = clean_text(text)
    if not text:
        return ""
    if re.search(r"\b(united states|usa|u\.s\.a\.|u\.s\.)\b", text, re.I):
        return "United States"
    if re.search(r"\bcanada\b", text, re.I):
        return "Canada"
    if allow_short_code and re.match(r"^(us|u\.s\.|usa|u\.s\.a\.)$", text, re.I):
        return "United States"
    if allow_short_code and re.match(r"^ca$", text, re.I):
        return "Canada"
    return ""


def _image_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    first = srcset.split(",")[0].strip().split()[0]
    return absolutize_url(first)


async def open_all_reviews_panel(page: Page) -> bool:
    """
    Modern Fiverr gig pages only show a review preview.
    Full list + pagination live behind 'See all reviews' / '(N reviews)'.
    """
    # Already in a reviews dialog that has multiple review cards?
    try:
        already = await page.evaluate(
            """() => {
              for (const d of document.querySelectorAll('[role="dialog"]')) {
                const r = d.getBoundingClientRect();
                const st = window.getComputedStyle(d);
                if (r.width < 120 || r.height < 120 || st.display === 'none' || st.visibility === 'hidden') continue;
                const cards = d.querySelectorAll(
                  '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                ).length;
                if (cards >= 3) return true;
              }
              return false;
            }"""
        )
        if already:
            return True
    except Exception:
        pass

    # JS click is more reliable than Playwright role matching on Fiverr
    try:
        clicked = await page.evaluate(
            """() => {
              const isVisible = (el) => {
                const r = el.getBoundingClientRect();
                const st = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
              };
              const scored = [];
              for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                if (!isVisible(el)) continue;
                const label = ((el.innerText || el.getAttribute('aria-label') || '') + '')
                  .replace(/\\s+/g, ' ').trim();
                if (!label) continue;
                const cls = (el.className || '').toString();
                if (/expand-description|gig-description|package/i.test(cls)) continue;
                let score = 0;
                if (/^see all reviews$/i.test(label)) score = 100;
                else if (/see all reviews/i.test(label)) score = 80;
                else if (/^\\(?\\d[\\d,]*\\s*reviews?\\)?$/i.test(label)) score = 40;
                if (!score) continue;
                scored.push({ el, score, y: el.getBoundingClientRect().top });
              }
              if (!scored.length) return false;
              scored.sort((a, b) => b.score - a.score || Math.abs(a.y - 300) - Math.abs(b.y - 300));
              scored[0].el.scrollIntoView({ block: 'center', behavior: 'instant' });
              scored[0].el.click();
              return scored[0].score >= 80 ? 'see_all' : 'count';
            }"""
        )
        if clicked:
            await asyncio.sleep(1.8)
            return True
    except Exception:
        pass

    # Playwright fallback
    for loc in (
        page.locator('button:has-text("See all reviews")'),
        page.locator('a:has-text("See all reviews")'),
    ):
        try:
            btn = loc.first
            if await btn.count() and await btn.is_visible(timeout=800):
                await btn.scroll_into_view_if_needed(timeout=3000)
                await btn.click(timeout=4000)
                await asyncio.sleep(1.8)
                return True
        except Exception:
            continue
    return False


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

    # Open the full reviews panel so page controls become available
    await open_all_reviews_panel(page)
    await asyncio.sleep(0.5)


async def click_load_more(page: Page, max_clicks: int = 50) -> int:
    """
    Expand the reviews list via 'Show More Reviews' / similar.
    Large gigs often have NO page numbers — only this button (adds ~5 cards/click).
    """
    clicks = 0
    load_more_re = re.compile(
        r"^(show more reviews|load more reviews|see more reviews|more reviews|"
        r"show more|load more)$",
        re.I,
    )

    for _ in range(max_clicks):
        try:
            before = await page.evaluate(
                """() => document.querySelectorAll(
                  '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                ).length"""
            )
            # Prefer exact "Show More Reviews" body-wide (not scoped — button sits under the list)
            clicked = False
            for loc in (
                page.get_by_role("button", name=re.compile(r"show more reviews", re.I)),
                page.locator('button:has-text("Show More Reviews")'),
                page.locator('button:has-text("Load More Reviews")'),
                page.locator('button:has-text("More Reviews")'),
            ):
                try:
                    btn = loc.first
                    if not await btn.count() or not await btn.is_visible(timeout=600):
                        continue
                    label = clean_text(await btn.inner_text(timeout=700) or "")
                    if not load_more_re.match(label) and "review" not in label.lower():
                        continue
                    marker = " ".join(
                        clean_text(await btn.get_attribute(a) or "")
                        for a in ("class", "id", "data-testid")
                    )
                    if re.search(r"expand-description|gig-description|package", marker, re.I):
                        continue
                    await btn.scroll_into_view_if_needed(timeout=3000)
                    await btn.click(timeout=4000)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                # JS fallback
                clicked = await page.evaluate(
                    """() => {
                      const isVisible = (el) => {
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                      };
                      for (const el of document.querySelectorAll('button, [role="button"]')) {
                        if (!isVisible(el)) continue;
                        const label = ((el.innerText || el.getAttribute('aria-label') || '') + '')
                          .replace(/\\s+/g, ' ').trim();
                        if (!/^(show more reviews|load more reviews|see more reviews|more reviews)$/i.test(label)) continue;
                        if (/expand-description|gig-description/i.test((el.className || '').toString())) continue;
                        el.scrollIntoView({ block: 'center', behavior: 'instant' });
                        el.click();
                        return true;
                      }
                      return false;
                    }"""
                )

            if not clicked:
                break
            clicks += 1
            await asyncio.sleep(0.9)
            after = await page.evaluate(
                """() => document.querySelectorAll(
                  '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                ).length"""
            )
            if after <= before:
                # One retry scroll then stop if still stuck
                await page.mouse.wheel(0, 900)
                await asyncio.sleep(0.5)
                after2 = await page.evaluate(
                    """() => document.querySelectorAll(
                      '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                    ).length"""
                )
                if after2 <= before:
                    break
        except Exception:
            break
    return clicks


async def _close_open_dialogs(page: Page) -> None:
    """
    Dismiss gallery/portfolio overlays — but NEVER the full reviews panel
    (that dialog is where pagination lives on modern Fiverr gig pages).
    """
    try:
        dialogs = page.locator('[role="dialog"]:visible')
        for i in range(min(await dialogs.count(), 6)):
            dlg = dialogs.nth(i)
            try:
                text = clean_text(await dlg.inner_text(timeout=800))[:400].lower()
            except Exception:
                text = ""
            # Keep the reviews modal open
            if "review" in text or await dlg.locator(
                '[data-testid*="review" i], [class*="review-card" i]'
            ).count():
                continue
            close_btn = dlg.locator(
                'button[aria-label*="close" i], button[aria-label*="dismiss" i]'
            ).first
            if await close_btn.count() and await close_btn.is_visible():
                await close_btn.click(timeout=2000)
                await asyncio.sleep(0.3)
                return
    except Exception:
        pass


async def click_next_review_page(page: Page, current_page: int) -> bool:
    """
    Click the next reviews pagination control.

    Fiverr puts page numbers / Next *below* the review list — often a sibling of
    the cards, not inside each review-card root. Search the whole document and
    prefer controls sitting just under the last review card.
    """
    target = current_page + 1

    # Bring pagination into view (it sits under the current review cards)
    try:
        await page.evaluate(
            """() => {
              const root =
                document.querySelector('[role="dialog"]') || document;
              const cards = root.querySelectorAll(
                '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
              );
              if (cards.length) {
                cards[cards.length - 1].scrollIntoView({ block: 'center', behavior: 'instant' });
              }
            }"""
        )
        await asyncio.sleep(0.35)
        await page.mouse.wheel(0, 700)
        await asyncio.sleep(0.25)
    except Exception:
        pass

    try:
        clicked = await page.evaluate(
            """(targetPage) => {
              const isVisible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0
                  && st.visibility !== 'hidden' && st.display !== 'none'
                  && st.opacity !== '0';
              };
              const disabled = (el) =>
                el.hasAttribute('disabled') ||
                el.getAttribute('aria-disabled') === 'true' ||
                /disabled/i.test(el.className || '') ||
                /disabled/i.test(el.parentElement?.className || '');

              // Prefer a reviews dialog that actually contains review cards
              let root = document;
              for (const d of document.querySelectorAll('[role="dialog"]')) {
                const cardsIn = d.querySelectorAll(
                  '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                ).length;
                if (cardsIn >= 2) { root = d; break; }
              }
              const cards = Array.from(root.querySelectorAll(
                '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
              )).filter(isVisible);
              let anchorY = window.innerHeight * 0.55;
              if (cards.length) {
                const last = cards[cards.length - 1].getBoundingClientRect();
                anchorY = last.bottom;
              }

              const nodes = root.querySelectorAll(
                'button, a, [role="button"], [role="link"], li, span, div[class*="page" i]'
              );
              const candidates = [];
              for (const el of nodes) {
                if (!isVisible(el) || disabled(el)) continue;
                // Skip controls nested inside a review card body
                if (el.closest('[data-testid*="review-card" i], [class*="review-item-component-wrapper" i]')) {
                  continue;
                }
                const label = ((el.getAttribute('aria-label') || el.innerText || '') + '')
                  .replace(/\\s+/g, ' ')
                  .trim();
                if (!label || label.length > 28) continue;
                if (/prev|previous|back/i.test(label)) continue;
                const isNext = /^(next|next page|>|›|»|→)$/i.test(label)
                  || /go to next/i.test(label);
                const isNum = new RegExp('^' + targetPage + '$').test(label);
                if (!isNext && !isNum) continue;
                const y = el.getBoundingClientRect().top;
                // Prefer controls near / just below the reviews list
                const dist = Math.abs(y - anchorY);
                candidates.push({ el, y, dist, isNext, isNum });
              }

              if (!candidates.length) return false;
              candidates.sort((a, b) => {
                if (a.isNum !== b.isNum) return a.isNum ? -1 : 1;
                if (a.dist !== b.dist) return a.dist - b.dist;
                return a.y - b.y;
              });
              const pick = candidates[0].el;
              pick.scrollIntoView({ block: 'center', behavior: 'instant' });
              pick.click();
              return true;
            }""",
            target,
        )
        if clicked:
            await asyncio.sleep(1.5)
            await page.mouse.wheel(0, 400)
            await asyncio.sleep(0.35)
            return True
    except Exception:
        pass

    # Fallback: Playwright locators — dialog first, then review section, then body
    scopes = []
    dialog = page.locator('[role="dialog"]').first
    if await dialog.count():
        scopes.append(dialog)
    section = page.locator(REVIEW_SECTION).first
    if await section.count():
        scopes.append(section)
    scopes.append(page.locator("body"))

    for scope in scopes:
        candidates = [
            scope.get_by_role("button", name=re.compile(rf"^{target}$")),
            scope.get_by_role("link", name=re.compile(rf"^{target}$")),
            scope.get_by_role("button", name=re.compile(r"^(next|next page|>)$", re.I)),
            scope.get_by_role("link", name=re.compile(r"^(next|next page|>)$", re.I)),
            scope.locator('[aria-label*="next" i]:not([aria-label*="previous" i])'),
            scope.locator(f'nav button:has-text("{target}")'),
            scope.locator(f'nav a:has-text("{target}")'),
            scope.locator(f'[class*="pagination" i] button:has-text("{target}")'),
            scope.locator(f'[class*="pagination" i] a:has-text("{target}")'),
            scope.locator(f'button:has-text("{target}")'),
            scope.locator(f'a:has-text("{target}")'),
        ]
        for loc in candidates:
            count = min(await loc.count(), 16)
            for i in range(count):
                btn = loc.nth(i)
                try:
                    if not await btn.is_visible(timeout=400):
                        continue
                    aria_dis = (await btn.get_attribute("aria-disabled") or "").lower()
                    if aria_dis == "true" or await btn.get_attribute("disabled") is not None:
                        continue
                    label = clean_text(
                        await btn.inner_text(timeout=500)
                        or await btn.get_attribute("aria-label")
                        or ""
                    )
                    if re.search(r"previous|prev", label, re.I):
                        continue
                    # Ignore gig-carousel / unrelated numbered controls far from reviews
                    if label == str(target) or re.match(r"^(next|next page|>|›)$", label, re.I):
                        pass
                    elif not re.search(r"next", label, re.I):
                        continue
                    await btn.scroll_into_view_if_needed(timeout=2000)
                    await btn.click(timeout=3000)
                    await asyncio.sleep(1.5)
                    await page.mouse.wheel(0, 400)
                    return True
                except Exception:
                    continue
    return False


async def scroll_load_more_reviews(page: Page, max_rounds: int = 40) -> int:
    """
    Fallback when pagination buttons are missing: scroll the reviews area so
    Fiverr lazy-loads additional review cards into the DOM.
    """
    rounds = 0
    last_count = 0
    stagnant = 0
    for _ in range(max_rounds):
        try:
            count = await page.evaluate(
                """() => document.querySelectorAll(
                  '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
                ).length"""
            )
        except Exception:
            count = 0
        if count <= last_count:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
            last_count = count
            rounds += 1
        await page.mouse.wheel(0, 1400)
        await asyncio.sleep(0.55)
        # Keep trying show-more while scrolling
        await click_load_more(page, max_clicks=2)
    return rounds


async def _card_text(card: Locator) -> str:
    try:
        return clean_text(await card.inner_text(timeout=2500))
    except Exception:
        return ""


async def _find_country(card: Locator, card_text: str) -> str:
    """
    Fiverr usually shows country as plain text under the username
    (e.g. "United States") or as a flag alt/title — not "from United States".
    """
    # 1) Flag / img / aria attrs (often "United States" or "Flag of United States")
    attr_nodes = card.locator("img, [aria-label], [title], [data-testid*='country' i]")
    for i in range(min(await attr_nodes.count(), 60)):
        node = attr_nodes.nth(i)
        for attr in ("alt", "aria-label", "title", "data-country", "data-testid"):
            raw = await node.get_attribute(attr) or ""
            c = _normalize_target_country(raw, allow_short_code=True)
            if c:
                return c

    # 2) Dedicated country / location / flag nodes
    for sel in (
        '[class*="country" i]',
        '[class*="location" i]',
        '[class*="flag" i]',
        '[data-testid*="country" i]',
        '[data-testid*="location" i]',
    ):
        loc = card.locator(sel)
        for i in range(min(await loc.count(), 12)):
            t = clean_text(await loc.nth(i).inner_text(timeout=800))
            c = _normalize_target_country(t, allow_short_code=True)
            if c:
                return c
            for attr in ("aria-label", "title", "alt"):
                alt = await loc.nth(i).get_attribute(attr) or ""
                c = _normalize_target_country(alt, allow_short_code=True)
                if c:
                    return c

    # 3) Phrase forms
    m = re.search(
        r"\b(?:from|located in|based in)\s+(United States|U\.S\.A\.|USA|U\.S\.|Canada|CA)\b",
        card_text,
        re.I,
    )
    if m:
        c = _normalize_target_country(m.group(1), allow_short_code=True)
        if c:
            return c

    # 4) Bare country name anywhere in the card text (common Fiverr layout)
    return _normalize_target_country(card_text, allow_short_code=False)


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
    # Ignore tiny placeholders / data URIs (already excluded by http check)
    if re.search(r"data:image|placeholder|1x1|pixel|blank\.", url, re.I):
        return 0
    if reject_urls and _strip_image_url(url) in reject_urls:
        return 0
    if BAD_REVIEW_IMAGE.search(url):
        return 0
    if GIG_IMAGE_HINT.search(url) and not REVIEW_IMAGE_HINT.search(url):
        return 0
    if REVIEW_IMAGE_HINT.search(url):
        return 4
    # Cloudinary/fiverr-res often omit file extensions — still valid delivery thumbnails
    if GENERIC_FIVERR_IMAGE_HOST.search(url) and not GIG_IMAGE_HINT.search(url):
        if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)|/image/upload|/images/", url, re.I):
            return 2
        return 1
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

    # Prefer resolved currentSrc (lazy-loaded) via a single evaluate
    try:
        urls = await card.evaluate(
            """(el) => {
              const out = [];
              for (const img of el.querySelectorAll('img')) {
                for (const u of [img.currentSrc, img.src, img.getAttribute('data-src'),
                                 img.getAttribute('data-lazy-src'), img.getAttribute('data-original')]) {
                  if (u && typeof u === 'string' && u.startsWith('http')) out.push(u);
                }
                const ss = img.getAttribute('srcset') || '';
                if (ss) {
                  const first = ss.split(',')[0].trim().split(/\\s+/)[0];
                  if (first) out.push(first.startsWith('http') ? first : (first.startsWith('//') ? 'https:' + first : first));
                }
              }
              for (const a of el.querySelectorAll('a[href]')) {
                const h = a.getAttribute('href') || '';
                if (/\\.(jpg|jpeg|png|webp)|cloudinary|fiverr-res|attachment|delivery/i.test(h)) out.push(h);
              }
              return out;
            }"""
        )
        for src in urls or []:
            full = absolutize_url(src)
            score = _score_review_image(full, reject_urls)
            if score > best_score:
                best_score = score
                best = full
    except Exception:
        pass

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

    if best and best_score > 0:
        return best
    return ""


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
        for i in range(min(await loc.count(), 500)):
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
    opened_panel = await open_all_reviews_panel(page)
    if opened_panel:
        append_activity(job_id, "Opened full reviews panel (See all reviews)")
    review_page = 1
    total_load_clicks = 0
    seen_page_signatures: set[str] = set()
    consecutive_empty_pages = 0

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
        # Include card count so scroll-expanded DOM does not look like a "repeat"
        signature = f"{len(candidates)}|" + "|".join(
            clean_text(text)[:120].lower() for _card, text in candidates[:10]
        )
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
                append_activity(
                    job_id,
                    f"Review skipped: country={country or 'missing/undetected'}",
                )
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

        advanced = await click_next_review_page(page, review_page)
        if advanced:
            review_page += 1
            await scroll_to_reviews(page)
            continue

        # Retry once after scrolling deeper — pagination can render late
        if review_page <= 2:
            try:
                await page.mouse.wheel(0, 1200)
                await asyncio.sleep(0.6)
            except Exception:
                pass
            advanced = await click_next_review_page(page, review_page)
            if advanced:
                review_page += 1
                await scroll_to_reviews(page)
                continue

        # Many large gigs use "Show More Reviews" instead of page numbers
        before_count = len(candidates)
        more = await click_load_more(
            page, max_clicks=min(25, max(1, config.REVIEW_LOAD_MORE_MAX))
        )
        total_load_clicks += more
        if more > 0:
            append_activity(
                job_id,
                f"No page buttons — expanded via Show More Reviews "
                f"(+{more} clicks, was {before_count} cards)",
            )
            seen_page_signatures.clear()
            review_page += 1
            continue

        # Last resort: scroll/lazy-load
        scroll_rounds = await scroll_load_more_reviews(
            page, max_rounds=min(15, config.REVIEW_SCROLL_LOAD_MAX)
        )
        after_cards = await _collect_review_cards(page)
        if scroll_rounds > 0 and len(after_cards) > before_count:
            append_activity(
                job_id,
                f"Scroll-loaded more reviews "
                f"({scroll_rounds} rounds, {before_count}→{len(after_cards)} cards)",
            )
            seen_page_signatures.clear()
            review_page += 1
            continue

        append_activity(
            job_id,
            f"Review pagination ended after page {review_page} "
            f"(no next page / show-more control)",
        )
        break

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
