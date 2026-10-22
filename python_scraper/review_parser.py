import asyncio
import re
import time
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
    normalize_fiverr_url,
    parse_review_date,
    parse_rating_after_country,
    reviewer_name_before_country,
)
from db import (
    append_activity,
    get_job,
    lead_keys_for_gig,
    save_gig_review_checkpoint,
    set_heartbeat,
    update_job,
)
from page_data import extract_reviews_from_page_json
from typing import Optional

from verification import (
    VerificationRequiredError,
    assert_page_accessible,
    find_context_verification_page,
    is_verification_page,
)

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
    # Prefer shared normalizer (includes localized Fiverr country labels)
    from utils import normalize_country as _norm_country

    mapped = _norm_country(text)
    if mapped in ("United States", "Canada"):
        return mapped
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


async def read_listed_review_count(page: Page) -> int:
    """
    Read the review count shown on the gig (near the star rating / 'See all reviews').
    Used as the target number of reviews to walk through before stopping.
    """
    try:
        count = await page.evaluate(
            """() => {
              const parseCount = (raw) => {
                if (!raw) return 0;
                const t = String(raw).replace(/\\s+/g, ' ').trim();
                // 2.9k / 2,9k style
                let m = t.match(/(\\d+(?:[.,]\\d+)?)\\s*([kKmM])\\b/);
                if (m) {
                  let n = parseFloat(m[1].replace(',', '.'));
                  const u = m[2].toLowerCase();
                  if (u === 'k') n *= 1000;
                  if (u === 'm') n *= 1000000;
                  return Math.round(n);
                }
                m = t.match(/(\\d{1,3}(?:,\\d{3})+|\\d{4,7}|\\d{1,3})/);
                if (!m) return 0;
                return parseInt(m[1].replace(/,/g, ''), 10) || 0;
              };

              const candidates = [];
              const push = (n, source) => {
                if (n >= 5 && n <= 500000) candidates.push({ n, source });
              };

              // JSON-LD AggregateRating
              for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                try {
                  const data = JSON.parse(s.textContent || '');
                  const items = Array.isArray(data) ? data : [data];
                  for (const it of items) {
                    const ar = it && (it.aggregateRating || it.AggregateRating);
                    if (!ar) continue;
                    push(parseCount(ar.ratingCount || ar.reviewCount || ar.ratingcount), 'jsonld');
                  }
                } catch (e) {}
              }

              // Visible UI near top / reviews header
              const nodes = document.querySelectorAll(
                'a, button, span, p, div, [role="button"], [data-testid*="review" i], [class*="rating" i], [class*="review" i]'
              );
              for (const el of nodes) {
                const r = el.getBoundingClientRect();
                if (r.width < 8 || r.height < 8) continue;
                // Prefer header / mid page — skip deep footer noise
                if (r.top > Math.min(innerHeight * 1.8, 2200)) continue;
                const label = ((el.innerText || el.getAttribute('aria-label') || '') + '')
                  .replace(/\\s+/g, ' ').trim();
                if (!label || label.length > 80) continue;
                if (!/review/i.test(label) && !/\\(\\s*[\\d,.]+\\s*[kKmM]?\\s*\\)/.test(label)) continue;
                // "(2,934 reviews)" / "2934 Reviews" / "See all reviews (120)"
                let m = label.match(/([\\d,.]+\\s*[kKmM]?)\\s*reviews?\\b/i);
                if (!m) m = label.match(/\\(\\s*([\\d,.]+\\s*[kKmM]?)\\s*\\)/);
                if (!m) continue;
                push(parseCount(m[1]), 'dom:' + label.slice(0, 40));
              }

              if (!candidates.length) return 0;
              // Prefer the largest plausible count (gig total, not "5 reviews" chips)
              candidates.sort((a, b) => b.n - a.n);
              return candidates[0].n;
            }"""
        )
    except Exception:
        count = 0
    try:
        return max(0, int(count or 0))
    except Exception:
        return 0


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


async def _raise_if_verification(
    page: Page,
    *,
    thorough: bool = False,
    job_id: str = "",
    return_url: Optional[str] = None,
) -> None:
    """
    When a challenge appears mid-scrape: wait/clear in place when job_id is known
    (keeps us on the gig). Only raise when we cannot wait here.
    Mid-page Press & Hold is caught by the fast JS path even when thorough=False.
    """
    try:
        # Respect thorough: full body.inner_text on every card/Show More was stalling runs
        challenged = await is_verification_page(page, thorough=thorough)
        if not challenged and thorough:
            challenged = await find_context_verification_page(page) is not None
        if not challenged:
            return
        if job_id:
            await assert_page_accessible(page, job_id, return_url)
            return
        raise VerificationRequiredError(
            "Fiverr verification appeared during review loading"
        )
    except VerificationRequiredError:
        raise
    except Exception as err:
        print(f"[reviews] verification check error: {err}")


async def _review_list_fingerprint(page: Page) -> str:
    """Detect list changes even when Fiverr keeps ~10 cards and replaces them."""
    try:
        return await page.evaluate(
            """() => {
              const cards = Array.from(document.querySelectorAll(
                '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
              ));
              const slice = (arr) => arr.map(c => ((c.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 50)));
              const head = slice(cards.slice(0, 4));
              const tail = slice(cards.slice(-3));
              return cards.length + '|' + head.join('~') + '|' + tail.join('~');
            }"""
        )
    except Exception:
        return ""


async def click_load_more(
    page: Page,
    max_clicks: int = 50,
    *,
    job_id: str = "",
    return_url: Optional[str] = None,
) -> int:
    """
    Expand the reviews list via 'Show More Reviews' / similar.
    Large gigs often have NO page numbers — only this button (adds ~5 cards/click).
    Fiverr may REPLACE the visible ~10 cards instead of appending — detect that too.
    """
    clicks = 0
    stagnant = 0
    load_more_re = re.compile(
        r"^(show more reviews|load more reviews|see more reviews|more reviews|"
        r"show more|load more)$",
        re.I,
    )

    for _ in range(max_clicks):
        try:
            # Every expand — clear Press & Hold popup immediately if it appeared
            # Fast check each click; thorough only every few expands (full body read is slow)
            await _raise_if_verification(
                page,
                thorough=(clicks == 0 or clicks % 5 == 0),
                job_id=job_id,
                return_url=return_url,
            )
            if clicks and clicks % 10 == 0:
                try:
                    set_heartbeat()
                except Exception:
                    pass

            before_fp = await _review_list_fingerprint(page)
            before = 0
            try:
                before = int(str(before_fp).split("|", 1)[0] or "0")
            except Exception:
                before = 0

            clicked = False
            for loc in (
                page.get_by_role("button", name=re.compile(r"show more reviews", re.I)),
                page.locator('button:has-text("Show More Reviews")'),
                page.locator('button:has-text("Load More Reviews")'),
                page.locator('button:has-text("More Reviews")'),
            ):
                try:
                    btn = loc.first
                    if not await btn.count() or not await btn.is_visible(timeout=500):
                        continue
                    label = clean_text(await btn.inner_text(timeout=600) or "")
                    if not load_more_re.match(label) and "review" not in label.lower():
                        continue
                    marker = " ".join(
                        clean_text(await btn.get_attribute(a) or "")
                        for a in ("class", "id", "data-testid")
                    )
                    if re.search(r"expand-description|gig-description|package", marker, re.I):
                        continue
                    await btn.scroll_into_view_if_needed(timeout=2500)
                    await btn.click(timeout=3500)
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
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
                await _raise_if_verification(
                    page, thorough=False, job_id=job_id, return_url=return_url
                )
                break
            clicks += 1
            await asyncio.sleep(0.25)
            after_fp = await _review_list_fingerprint(page)
            after = 0
            try:
                after = int(str(after_fp).split("|", 1)[0] or "0")
            except Exception:
                after = 0

            content_changed = bool(after_fp) and after_fp != before_fp
            grew = after > before
            if grew or content_changed:
                stagnant = 0
                continue

            # Popup often blocks growth — clear then retry before counting stagnant
            await _raise_if_verification(
                page, thorough=True, job_id=job_id, return_url=return_url
            )
            await page.mouse.wheel(0, 900)
            await asyncio.sleep(0.3)
            after_fp2 = await _review_list_fingerprint(page)
            if after_fp2 and after_fp2 != before_fp:
                stagnant = 0
                continue
            stagnant += 1
            # Need a few failed expands — one flaky click must not end the gig early
            if stagnant >= 4:
                break
        except VerificationRequiredError:
            raise
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
            # Keep reviews modal + Press & Hold / PX popup open
            if (
                "review" in text
                or "press" in text and "hold" in text
                or "before we continue" in text
                or "px-captcha" in text
                or await dlg.locator(
                    '#px-captcha, [data-testid*="review" i], [class*="review-card" i]'
                ).count()
            ):
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
            try:
                t = clean_text(await loc.nth(i).inner_text(timeout=500))
            except Exception:
                continue
            c = _normalize_target_country(t, allow_short_code=True)
            if c:
                return c
            for attr in ("aria-label", "title", "alt"):
                try:
                    alt = await loc.nth(i).get_attribute(attr) or ""
                except Exception:
                    alt = ""
                c = _normalize_target_country(alt, allow_short_code=True)
                if c:
                    return c

    # 3) Phrase forms (English + common Fiverr localizations)
    m = re.search(
        r"\b(?:from|located in|based in|de|desde|von|da)\s+"
        r"(United States|U\.S\.A\.|USA|U\.S\.|Canada|CA|"
        r"Estados Unidos|États[\-\s]?Unis|Etats[\-\s]?Unis|Vereinigte Staaten|"
        r"Stati Uniti|Canadá|Kanada)\b",
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


def _pick_best_image_url(
    urls: list[str] | None, reject_urls: set[str] | None = None
) -> str:
    best = ""
    best_score = 0
    for src in urls or []:
        full = absolutize_url(src)
        score = _score_review_image(full, reject_urls)
        if score > best_score:
            best_score = score
            best = full
    return best if best_score > 0 else ""


def _image_from_json_reviews(
    reviewer: str, text: str, json_reviews: list[dict]
) -> str:
    """Fallback when DOM lazy-load misses a delivery thumbnail that page JSON already has."""
    rev = clean_text(reviewer).lower()
    text_key = clean_text(text)[:80].lower()
    for jr in json_reviews:
        img = absolutize_url(jr.get("reviewedImageLink") or "")
        if not img or not is_valid_review_image(img):
            continue
        jr_name = clean_text(jr.get("reviewerName") or "").lower()
        jr_text = clean_text(jr.get("reviewText") or "")[:80].lower()
        if rev and jr_name == rev:
            return img
        if text_key and jr_text and (text_key[:50] in jr_text or jr_text[:50] in text_key):
            return img
    return ""


async def _review_delivery_image(card: Locator, reject_urls: set[str] | None = None) -> str:
    """Review attachment / delivery image — prefer one JS pass; heavy hover only on miss."""
    try:
        await card.scroll_into_view_if_needed(timeout=1200)
        await asyncio.sleep(0.08)
    except Exception:
        pass

    # Prefer resolved currentSrc (lazy-loaded), including parent review wrapper + siblings
    try:
        urls = await card.evaluate(
            """(el) => {
              const abs = (u) => {
                if (!u || typeof u !== 'string') return '';
                if (u.startsWith('http')) return u;
                if (u.startsWith('//')) return 'https:' + u;
                return '';
              };
              const pushSrcset = (ss, out) => {
                if (!ss) return;
                for (const part of ss.split(',')) {
                  const first = part.trim().split(/\\s+/)[0];
                  const a = abs(first);
                  if (a) out.push(a);
                }
              };
              const roots = [el];
              const wrap = el.closest(
                '[data-testid*="review-card" i], [class*="review-item-component-wrapper" i], [class*="review-card" i]'
              );
              if (wrap && wrap !== el) roots.push(wrap);
              if (el.parentElement && !roots.includes(el.parentElement)) {
                roots.push(el.parentElement);
              }
              let sib = el.nextElementSibling;
              for (let i = 0; i < 2 && sib; i++, sib = sib.nextElementSibling) {
                roots.push(sib);
              }
              const out = [];
              for (const root of roots) {
                for (const img of root.querySelectorAll('img, picture source, source')) {
                  for (const u of [
                    img.currentSrc, img.src,
                    img.getAttribute('data-src'),
                    img.getAttribute('data-lazy-src'),
                    img.getAttribute('data-original'),
                    img.getAttribute('data-url'),
                  ]) {
                    const a = abs(u);
                    if (a) out.push(a);
                  }
                  pushSrcset(img.getAttribute('srcset') || '', out);
                  pushSrcset(img.getAttribute('data-srcset') || '', out);
                }
                for (const a of root.querySelectorAll('a[href]')) {
                  const h = a.getAttribute('href') || '';
                  if (/\\.(jpg|jpeg|png|webp)|cloudinary|fiverr-res|attachment|delivery|t_smartwm/i.test(h)) {
                    const absH = abs(h.startsWith('/') ? (location.origin + h) : h) || h;
                    if (absH.startsWith('http')) out.push(absH);
                  }
                }
                for (const node of root.querySelectorAll('[style*="background"]')) {
                  const style = node.getAttribute('style') || '';
                  const m = style.match(/url\\([\"']?([^\"')]+)/i);
                  if (m) {
                    const a = abs(m[1]);
                    if (a) out.push(a);
                  }
                }
              }
              return out;
            }"""
        )
        best = _pick_best_image_url(urls, reject_urls)
        if best:
            return best
    except Exception:
        pass

    # Light fallback only — full per-img Playwright loops made US cards feel "stuck"
    try:
        media = card.locator(
            '[class*="attachment" i] img, [data-testid*="attachment" i] img, '
            '[class*="media" i] img'
        ).first
        if await media.count():
            try:
                await media.hover(timeout=500)
                await asyncio.sleep(0.12)
            except Exception:
                pass
        urls = await card.evaluate(
            """(el) => {
              const out = [];
              for (const img of el.querySelectorAll('img')) {
                for (const u of [img.currentSrc, img.src, img.getAttribute('data-src')]) {
                  if (u && u.startsWith('http')) out.push(u);
                }
              }
              return out;
            }"""
        )
        return _pick_best_image_url(urls, reject_urls)
    except Exception:
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
    """
    Batch-read review cards in one JS pass. Per-card Playwright inner_text/_find_country
    used to take minutes after Show More (100–200 DOM cards) with no UI updates.
    """
    scan_cap = max(100, int(getattr(config, "REVIEW_CARD_SCAN_MAX", 5000)))
    selectors = list(REVIEW_CARD_SELECTORS)
    try:
        payload = await page.evaluate(
            """({ selectors, scanCap }) => {
              const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
              for (let si = 0; si < selectors.length; si++) {
                const sel = selectors[si];
                let nodes;
                try { nodes = Array.from(document.querySelectorAll(sel)); }
                catch (e) { continue; }
                if (!nodes.length) continue;
                const seen = new Set();
                const items = [];
                const limit = Math.min(nodes.length, scanCap);
                for (let i = 0; i < limit; i++) {
                  const el = nodes[i];
                  const text = clean(el.innerText || el.textContent || '');
                  if (text.length < 40 || text.length > 4500) continue;
                  const key = text.slice(0, 100).toLowerCase();
                  if (seen.has(key)) continue;
                  const className = ((el.className || '') + '').toString().toLowerCase();
                  if (className.includes('review-item-description')) continue;
                  if (si >= 3) {
                    const countryHits = (text.match(/\\b(United States|USA|U\\.S\\.?|Canada|United Kingdom|Germany|France|India|Australia)\\b/gi) || []).length;
                    if (countryHits > 3 && !className.includes('review')) continue;
                  }
                  if (!className.includes('review') && si >= 2) {
                    // Weak selectors only: require a country-ish token in text
                    if (!/\\b(United States|USA|Canada|United Kingdom|Germany|India|Australia|France|Netherlands|Italy|Spain)\\b/i.test(text)) {
                      continue;
                    }
                  }
                  seen.add(key);
                  items.push({ index: i, text, className });
                }
                if (items.length && si < 3) {
                  return { selector: sel, selectorIndex: si, items };
                }
                if (items.length) {
                  return { selector: sel, selectorIndex: si, items };
                }
              }
              return { selector: '', selectorIndex: 0, items: [] };
            }""",
            {"selectors": selectors, "scanCap": scan_cap},
        )
    except Exception:
        payload = None

    out: list[tuple[Locator, str, str]] = []
    if payload and payload.get("selector") and payload.get("items"):
        loc = page.locator(str(payload["selector"]))
        for item in payload["items"]:
            try:
                idx = int(item.get("index", -1))
                text = clean_text(item.get("text") or "")
                class_name = clean_text(item.get("className") or "").lower()
                if idx < 0 or len(text) < 40:
                    continue
                out.append((loc.nth(idx), text, class_name))
            except Exception:
                continue
    else:
        # Fallback: sparse Playwright walk (slow path)
        seen: set[str] = set()
        for selector_index, sel in enumerate(REVIEW_CARD_SELECTORS):
            loc = page.locator(sel)
            try:
                count = min(await loc.count(), scan_cap)
            except Exception:
                count = 0
            for i in range(count):
                try:
                    card = loc.nth(i)
                    text = await _card_text(card)
                    if len(text) < 40 or len(text) > 4500:
                        continue
                    key = text[:100].lower()
                    if key in seen:
                        continue
                    class_name = (await card.get_attribute("class") or "").lower()
                    if "review-item-description" in class_name:
                        continue
                    if selector_index >= 2 and "review" not in class_name:
                        if not _normalize_target_country(text) and _country_mention_count(text) < 1:
                            continue
                    if (
                        selector_index >= 3
                        and _country_mention_count(text) > 3
                        and "review" not in class_name
                    ):
                        continue
                    seen.add(key)
                    out.append((card, text, class_name))
                except Exception:
                    continue
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
    on_review=None,
    gig_url: str = "",
) -> tuple[list[dict], int]:
    """
    Load all review pages on the current gig page, then return US/CA reviews.
    max_reviews <= 0 means no cap.

    on_review: optional callback(review_dict) -> bool.
    Return False from the callback to stop extraction early (e.g. lead limit).
    gig_url: pasted/target gig link — used to clear verification without leaving the gig.
    """
    unlimited = max_reviews <= 0
    if not unlimited and max_reviews < 1:
        max_reviews = 500
    stop_requested = False
    return_url = gig_url or ""

    def _emit(review: dict) -> bool:
        nonlocal stop_requested
        if on_review is None:
            return True
        try:
            cont = on_review(review)
        except Exception as err:
            append_activity(job_id, f"Live lead save error: {err}")
            return True
        if cont is False:
            stop_requested = True
            return False
        return True

    with_images = review_image_mode != "without_image"
    reject_image_urls = {
        _strip_image_url(absolutize_url(main_gig_image)),
    } - {""}

    # Resume after verification / interrupt: keep scanned count + skip already-saved leads
    gig_key = normalize_fiverr_url(return_url) or clean_text(return_url)
    resume_checked = 0
    resume_page = 1
    resume_clicks = 0
    resume_fps: list[str] = []
    try:
        job_doc = get_job(job_id) or {}
        ckpt = job_doc.get("gigReviewCheckpoint") or {}
        ckpt_url = normalize_fiverr_url(ckpt.get("gigUrl") or "") or clean_text(
            ckpt.get("gigUrl") or ""
        )
        if gig_key and ckpt_url and gig_key.rstrip("/").lower() == ckpt_url.rstrip("/").lower():
            resume_checked = max(0, int(ckpt.get("checked") or 0))
            resume_page = max(1, int(ckpt.get("reviewPage") or 1))
            resume_clicks = max(0, int(ckpt.get("loadClicks") or 0))
            raw_fps = ckpt.get("processedFps") or []
            if isinstance(raw_fps, list):
                resume_fps = [str(x) for x in raw_fps if x]
        # Fallback: same gig link with a live counter already past the JSON warm-up
        if resume_checked <= 0 and gig_key:
            cur_link = normalize_fiverr_url(job_doc.get("currentGigLink") or "") or ""
            live_checked = int(job_doc.get("reviewsChecked") or 0)
            # reviewsChecked is progress_base + gig-local; recover gig-local
            gig_local = max(0, live_checked - max(0, int(progress_base)))
            if (
                cur_link
                and cur_link.rstrip("/").lower() == gig_key.rstrip("/").lower()
                and gig_local > 20
            ):
                resume_checked = gig_local
                resume_page = max(1, int(job_doc.get("currentReviewPage") or 1))
    except Exception:
        resume_fps = []

    seen_keys: set[str] = set()
    seen_text_keys: set[str] = set()
    if job_id and gig_key:
        try:
            db_keys, db_text = lead_keys_for_gig(job_id, gig_key)
            seen_keys |= db_keys
            seen_text_keys |= db_text
        except Exception:
            pass

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

    # Never reset Live Monitor to ~10 after verification — resume prior scan depth
    if resume_checked > 0:
        checked = resume_checked
        append_activity(
            job_id,
            f"Resuming this gig after interrupt/verification — "
            f"continuing from ~{resume_checked} reviews already scanned "
            f"(not restarting from 0; {len(seen_keys)} leads already known for this gig)",
        )
        try:
            update_job(
                job_id,
                {
                    "reviewsChecked": progress_base + checked,
                    "totalReviewsParsed": progress_base + checked,
                    "currentReviewPage": resume_page,
                },
            )
        except Exception:
            pass
    else:
        checked = len(json_reviews)

    if json_reviews:
        mode_note = "with review image links" if with_images else "without review image links"
        if resume_checked <= 0:
            append_activity(
                job_id,
                f"JSON reviews parsed: {len(parsed)}/{len(json_reviews)} US/CA reviews ({mode_note})",
            )
            for jr in list(parsed):
                key = (
                    f"{clean_text(jr['reviewerName']).lower()}|"
                    f"{clean_text(jr['reviewText'])[:100].lower()}"
                )
                seen_keys.add(key)
                seen_text_keys.add(clean_text(jr["reviewText"])[:140].lower())
                if not _emit(jr):
                    break
            if stop_requested:
                return parsed, checked
        else:
            # Resume: remember JSON keys but do not re-save (avoids looking like a restart)
            for jr in parsed:
                seen_keys.add(
                    f"{clean_text(jr['reviewerName']).lower()}|"
                    f"{clean_text(jr['reviewText'])[:100].lower()}"
                )
                seen_text_keys.add(clean_text(jr["reviewText"])[:140].lower())
            append_activity(
                job_id,
                f"JSON reviews available: {len(parsed)}/{len(json_reviews)} "
                f"(skipped re-save on resume; already have {len(seen_keys)} keys)",
            )

    await scroll_to_reviews(page)
    # Read listed total BEFORE opening the panel (count is on the gig header)
    listed_review_count = await read_listed_review_count(page)
    opened_panel = await open_all_reviews_panel(page)
    if opened_panel:
        append_activity(job_id, "Opened full reviews panel (See all reviews)")
    # Panel / "See all reviews (N)" can expose a better count
    listed_review_count = max(listed_review_count, await read_listed_review_count(page))
    if listed_review_count > 0:
        if resume_checked <= 0:
            append_activity(
                job_id,
                f"Gig lists ~{listed_review_count:,} reviews — will scan through them "
                "and extract all targeted US/CA leads",
            )
        else:
            append_activity(
                job_id,
                f"Gig lists ~{listed_review_count:,} reviews — resuming scan "
                f"({resume_checked}/{listed_review_count} already checked)",
            )
        update_job(
            job_id,
            {
                "listedReviewCount": listed_review_count,
                "currentGigListedReviews": listed_review_count,
            },
        )
    else:
        append_activity(
            job_id,
            "Could not read gig review count from header — scanning until list ends",
        )
    # Stop early only after covering most of the listed total (or list truly ends)
    listed_coverage_target = (
        max(1, int(listed_review_count * 0.92)) if listed_review_count > 0 else 0
    )
    review_page = resume_page if resume_checked > 0 else 1
    total_load_clicks = 0
    # Fast-forward Show More toward prior depth so we don't re-walk page 1 for hours
    if resume_checked > 40:
        ff_clicks = min(
            max(resume_clicks, resume_checked // 5),
            max(12, int(getattr(config, "REVIEW_LOAD_MORE_MAX", 400) // 2)),
        )
        ff_clicks = min(ff_clicks, 120)
        if ff_clicks > 0:
            append_activity(
                job_id,
                f"Fast-forwarding ~{ff_clicks} Show More click(s) to resume depth…",
            )
            got = await click_load_more(
                page,
                max_clicks=ff_clicks,
                job_id=job_id,
                return_url=return_url or None,
            )
            total_load_clicks += got
            review_page = max(review_page, 1 + got)
    seen_page_signatures: set[str] = set()
    consecutive_empty_pages = 0
    stagnant_rounds = 0
    # Show More that does not surface unseen cards (Fiverr often recycles the same DOM)
    useless_expand_streak = 0
    useless_expand_max = max(2, int(getattr(config, "REVIEW_USELESS_EXPAND_MAX", 4)))
    checked_at_last_progress = checked
    # Cards already fully evaluated (kept or skipped) — avoid re-work that feels "stuck"
    processed_card_fps: set[str] = set(resume_fps if resume_checked > 0 else [])
    # US/CA cards missing images: retry a few times, then stop re-scanning forever
    no_image_attempts: dict[str, int] = {}
    skip_stats = {"country": 0, "image": 0, "dup": 0, "other": 0}
    skip_log_every = max(5, int(getattr(config, "REVIEW_SKIP_LOG_EVERY", 25)))
    burst = max(1, int(getattr(config, "REVIEW_LOAD_MORE_BURST", 3)))
    verif_every = max(8, int(getattr(config, "REVIEW_VERIF_CHECK_EVERY", 12)))
    # Push scan progress to Live Monitor while walking cards (not only at page end)
    live_push_every = max(1, int(getattr(config, "REVIEW_LIVE_PUSH_EVERY", 1)))
    live_push_min_sec = float(getattr(config, "REVIEW_LIVE_PUSH_MIN_SEC", 0.35))
    last_live_push = 0.0
    last_checkpoint_mono = 0.0

    def _card_fp(card_text: str) -> str:
        return clean_text(card_text)[:120].lower()

    def _push_live_scan(
        *,
        force: bool = False,
        last_label: str = "",
        last_country: str = "",
    ) -> None:
        nonlocal last_live_push, last_checkpoint_mono
        now = time.monotonic()
        # Throttle DB writes (~3/sec) so Live Monitor stays smooth without overload
        if not force and (now - last_live_push) < live_push_min_sec:
            return
        if not force and live_push_every > 1 and checked % live_push_every != 0:
            return
        last_live_push = now
        fields = {
            "currentReviewPage": review_page,
            "totalReviewsParsed": progress_base + checked,
            "reviewsChecked": progress_base + checked,
            "status": "extracting_reviews",
            "listedReviewCount": listed_review_count or None,
        }
        # Always pair label + country so UI never shows stale "non-target · United States"
        if last_label or last_country:
            fields["lastScannedReview"] = (last_label or "—")[:80]
            fields["lastScannedCountry"] = (last_country or "")[:40]
        try:
            update_job(job_id, fields)
            # Keep status banner green while a long card walk is in progress
            set_heartbeat()
        except Exception:
            pass
        # Persist resume checkpoint every ~15s so verification cannot wipe progress
        if return_url and (force or (now - last_checkpoint_mono) >= 15.0):
            last_checkpoint_mono = now
            try:
                save_gig_review_checkpoint(
                    job_id,
                    gig_url=return_url,
                    checked=checked,
                    review_page=review_page,
                    load_clicks=total_load_clicks,
                    processed_fps=processed_card_fps,
                    progress_base=progress_base,
                )
            except Exception:
                pass

    def _note_skip(kind: str, detail: str = "") -> None:
        skip_stats[kind] = skip_stats.get(kind, 0) + 1
        total_skips = sum(skip_stats.values())
        if total_skips % skip_log_every == 0:
            append_activity(
                job_id,
                f"Skip summary: country={skip_stats['country']} noImage={skip_stats['image']} "
                f"dup={skip_stats['dup']} other={skip_stats['other']}"
                + (f" | last={detail}" if detail else ""),
            )

    while True:
        if review_page > max(1, config.REVIEW_MAX_PAGES):
            append_activity(
                job_id,
                f"Review pagination stopped at safety limit ({config.REVIEW_MAX_PAGES} pages)",
            )
            break

        try:
            set_heartbeat()
        except Exception:
            pass
        update_job(
            job_id,
            {
                "currentReviewPage": review_page,
                "totalReviewsParsed": progress_base + checked,
                "reviewsChecked": progress_base + checked,
                "status": "extracting_reviews",
            },
        )

        # Checkpoint before any verification wait so a Press & Hold cannot wipe progress
        if return_url and checked > 0:
            try:
                save_gig_review_checkpoint(
                    job_id,
                    gig_url=return_url,
                    checked=checked,
                    review_page=review_page,
                    load_clicks=total_load_clicks,
                    processed_fps=processed_card_fps,
                    progress_base=progress_base,
                )
            except Exception:
                pass

        # Thorough verification only periodically — every-page full body reads stalled after Show More
        await _raise_if_verification(
            page,
            thorough=(review_page == 1 or review_page % 4 == 0),
            job_id=job_id,
            return_url=return_url or None,
        )
        if review_page == 1 or review_page % 5 == 0:
            await assert_page_accessible(page, job_id, return_url or None)

        # Scan FIRST, then expand a tiny burst. Expanding 20× before scan drops
        # reviews Fiverr swaps out of the DOM — that was the "missing reviews" bug.
        collect_t0 = time.monotonic()
        candidates = await _collect_review_cards(page)
        collect_ms = int((time.monotonic() - collect_t0) * 1000)
        unseen_estimate = sum(1 for _c, t in candidates if _card_fp(t) not in processed_card_fps)
        # Always log right after Show More / collect so Live Monitor never looks frozen
        if (
            review_page == 1
            or review_page % 2 == 0
            or total_load_clicks == 0
            or unseen_estimate > 0
        ):
            append_activity(
                job_id,
                f"Review page {review_page}: {len(candidates)} in DOM, "
                f"~{unseen_estimate} new to scan "
                f"(scanned={checked}, kept={len(parsed)}, showMore={total_load_clicks}, "
                f"collect={collect_ms}ms)",
            )

        signature = f"{len(candidates)}|" + "|".join(
            clean_text(text)[:80].lower() for _card, text in candidates[:8]
        )
        kept_before_page = len(parsed)
        new_keys_before = len(seen_keys)
        new_card_fps = 0

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

        for card, card_text in candidates:
            try:
                fp = _card_fp(card_text)
                if fp in processed_card_fps:
                    continue

                checked += 1
                if checked == 1 or checked % verif_every == 0:
                    await _raise_if_verification(
                        page,
                        thorough=False,
                        job_id=job_id,
                        return_url=return_url or None,
                    )

                new_card_fps += 1
                processed_card_fps.add(fp)
                # Tick Live Monitor immediately so "Reviews scanned" moves per card
                _push_live_scan(force=(checked == 1 or checked % 3 == 0))
                if new_card_fps == 1 or new_card_fps % 10 == 0:
                    append_activity(
                        job_id,
                        f"Scanning new cards… {new_card_fps}/{max(unseen_estimate, new_card_fps)} "
                        f"this round (total scanned {checked}"
                        + (
                            f"/{listed_review_count}"
                            if listed_review_count > 0
                            else ""
                        )
                        + ")",
                    )

                country = await _find_country(card, card_text)
                norm = normalize_country(country)
                if norm not in ("United States", "Canada"):
                    _note_skip("country", country or "missing")
                    _push_live_scan(last_label=country or "non-target", last_country=country or "")
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
                    _note_skip("other", "bad reviewer")
                    _push_live_scan(last_label="bad reviewer", last_country=norm)
                    continue

                rating = parse_rating_after_country(card_text)
                text = await _review_text(card, card_text, reviewer, norm)
                if len(text) < 15:
                    _note_skip("other", f"short:{reviewer}")
                    _push_live_scan(last_label=reviewer or "short", last_country=norm)
                    continue

                key = f"{reviewer.strip().lower()}|{text[:100].lower()}"
                text_key = clean_text(text)[:140].lower()
                if key in seen_keys or text_key in seen_text_keys:
                    _note_skip("dup", reviewer)
                    _push_live_scan(last_label=f"dup:{reviewer}", last_country=norm)
                    continue

                image = ""
                if with_images:
                    image = await _review_delivery_image(card, reject_image_urls)
                    if image and not is_valid_review_image(image):
                        image = ""
                    if not image:
                        # One short retry — long sleeps here stacked into multi-minute stalls
                        try:
                            await card.scroll_into_view_if_needed(timeout=800)
                            await asyncio.sleep(0.2)
                        except Exception:
                            pass
                        image = await _review_delivery_image(card, reject_image_urls)
                        if image and not is_valid_review_image(image):
                            image = ""
                    if not image:
                        # Page JSON often has attachment URLs even when DOM thumbs are lazy
                        image = _image_from_json_reviews(reviewer, text, json_reviews)
                        if image and _strip_image_url(image) in reject_image_urls:
                            image = ""
                        if image and not is_valid_review_image(image):
                            image = ""
                    if not image:
                        tries = no_image_attempts.get(fp, 0) + 1
                        no_image_attempts[fp] = tries
                        if tries < 2:
                            # One re-try after further expand/scroll — then lock the card
                            processed_card_fps.discard(fp)
                        _note_skip("image", reviewer)
                        _push_live_scan(
                            force=True,
                            last_label=f"noImage:{reviewer}",
                            last_country=norm,
                        )
                        continue

                review_date = await _review_date(card, card_text)
                seen_keys.add(key)
                seen_text_keys.add(text_key)
                _push_live_scan(force=True, last_label=reviewer, last_country=norm)

                append_activity(
                    job_id,
                    f"Reviewer extracted: {reviewer} | country={norm} | rating={rating} | page={review_page}",
                )
                review_row = {
                    "reviewerName": reviewer,
                    "reviewerCountry": norm,
                    "reviewText": text,
                    "reviewRating": rating,
                    "reviewDate": review_date,
                    "reviewedImageLink": image if with_images else "",
                    "cardText": card_text,
                    "reviewPage": review_page,
                }
                parsed.append(review_row)
                if not _emit(review_row):
                    break

                if not unlimited and len(parsed) >= max_reviews:
                    break
            except VerificationRequiredError:
                if return_url:
                    try:
                        save_gig_review_checkpoint(
                            job_id,
                            gig_url=return_url,
                            checked=checked,
                            review_page=review_page,
                            load_clicks=total_load_clicks,
                            processed_fps=processed_card_fps,
                            progress_base=progress_base,
                        )
                    except Exception:
                        pass
                raise
            except Exception:
                _note_skip("other", "stale-card")
                continue

        kept_on_page = len(parsed) - kept_before_page
        new_unique = len(seen_keys) - new_keys_before
        covered = (
            listed_review_count > 0 and checked >= listed_coverage_target
        )
        update_job(
            job_id,
            {
                "currentReviewPage": review_page,
                "totalReviewsParsed": progress_base + checked,
                "reviewsChecked": progress_base + checked,
                "listedReviewCount": listed_review_count or None,
            },
        )
        coverage_note = (
            f"; scanned {checked}/{listed_review_count} listed"
            if listed_review_count > 0
            else f"; scanned={checked}"
        )
        append_activity(
            job_id,
            f"Review page {review_page}: kept {kept_on_page} US/CA "
            f"(+{new_unique} new keys, +{new_card_fps} new cards); total kept {len(parsed)}; "
            f"DOM cards={len(candidates)}{coverage_note}",
        )

        if stop_requested or (not unlimited and len(parsed) >= max_reviews):
            break

        # Listed total reached — finish once expand also stops producing cards
        if covered and new_card_fps == 0 and new_unique == 0:
            append_activity(
                job_id,
                f"Reached listed review count (~{listed_review_count:,}): "
                f"scanned {checked}, kept {len(parsed)} targeted US/CA",
            )
            break

        # Never dismiss verification / reviews dialogs here — only image galleries
        await _close_open_dialogs(page)
        await _raise_if_verification(
            page,
            thorough=(review_page % 3 == 0),
            job_id=job_id,
            return_url=return_url or None,
        )

        # Progress = new card content seen this round (not only kept US/CA+image).
        # Stopping on zero kept was quitting while Show More still had more reviews.
        if new_card_fps > 0 or new_unique > 0:
            stagnant_rounds = 0
            useless_expand_streak = 0
            checked_at_last_progress = checked
        else:
            stagnant_rounds += 1
        if signature:
            seen_page_signatures.add(signature)

        advanced = await click_next_review_page(page, review_page)
        if advanced:
            stagnant_rounds = 0
            useless_expand_streak = 0
            review_page += 1
            continue

        # Small expand AFTER scan so replaced cards were already harvested
        load_clicks = await click_load_more(
            page, max_clicks=burst, job_id=job_id, return_url=return_url or None
        )
        total_load_clicks += load_clicks
        if load_clicks > 0:
            # Probe immediately: Fiverr often "succeeds" Show More while recycling
            # the same cards — that used to reset stagnant and spin for hours.
            try:
                await asyncio.sleep(0.45)
            except Exception:
                pass
            probe_cards = await _collect_review_cards(page)
            unseen_after = sum(
                1 for _c, t in probe_cards if _card_fp(t) not in processed_card_fps
            )
            if unseen_after > 0:
                useless_expand_streak = 0
                stagnant_rounds = 0
                append_activity(
                    job_id,
                    f"Show More +{load_clicks} (total clicks={total_load_clicks}) — "
                    f"~{unseen_after} new card(s) to scan"
                    + (
                        f" ({checked}/{listed_review_count} listed)"
                        if listed_review_count > 0
                        else ""
                    ),
                )
                review_page += 1
                continue

            useless_expand_streak += 1
            stagnant_rounds += 1
            append_activity(
                job_id,
                f"Show More +{load_clicks} produced 0 new cards "
                f"(useless streak {useless_expand_streak}/{useless_expand_max}; "
                f"total clicks={total_load_clicks}; scanned={checked}"
                + (f"/{listed_review_count}" if listed_review_count > 0 else "")
                + ") — not resetting progress",
            )
            if useless_expand_streak >= useless_expand_max:
                append_activity(
                    job_id,
                    f"Leaving gig — Show More stuck recycling the same reviews "
                    f"(scanned {checked}"
                    + (f"/{listed_review_count} listed" if listed_review_count > 0 else "")
                    + f", kept {len(parsed)} US/CA, clicks={total_load_clicks}). "
                    "Moving to next gig.",
                )
                break
            # Fall through to stagnant / scroll fallbacks (do NOT continue forever)

        before_count = len(candidates)
        scroll_rounds = await scroll_load_more_reviews(
            page, max_rounds=min(8, config.REVIEW_SCROLL_LOAD_MAX)
        )
        after_cards = await _collect_review_cards(page)
        after_new = sum(
            1 for _c, t in after_cards if _card_fp(t) not in processed_card_fps
        )
        if scroll_rounds > 0 and (len(after_cards) > before_count or after_new > 0):
            append_activity(
                job_id,
                f"Scroll-loaded more reviews "
                f"({scroll_rounds} rounds, {before_count}→{len(after_cards)} cards, "
                f"unseen≈{after_new})",
            )
            review_page += 1
            stagnant_rounds = 0
            useless_expand_streak = 0
            continue

        # Hard stop: many clicks but scanned count not moving (classic client stuck)
        if (
            total_load_clicks >= 24
            and checked <= checked_at_last_progress
            and new_card_fps == 0
        ):
            append_activity(
                job_id,
                f"Leaving gig — scanned stuck at {checked} after "
                f"{total_load_clicks} Show More clicks with no new cards. Moving on.",
            )
            break

        # Only stop when expand/scroll cannot surface new card content.
        # Keep listed-coverage patience modest — never multi-hour spin.
        stagnant_limit = 6 if (
            listed_review_count > 0 and checked < listed_coverage_target
        ) else 4
        if stagnant_rounds >= stagnant_limit:
            append_activity(
                job_id,
                f"Review pagination ended after page {review_page} "
                f"(no new review cards for {stagnant_rounds} rounds; "
                f"clicks={total_load_clicks}"
                + (
                    f"; covered {checked}/{listed_review_count} listed"
                    if listed_review_count > 0
                    else ""
                )
                + "). Moving to next gig.",
            )
            break
        review_page += 1

    if not unlimited:
        parsed = parsed[:max_reviews]

    append_activity(
        job_id,
        f"Reviews on gig: {len(parsed)} US/CA ({checked} reviews scanned"
        + (f" of ~{listed_review_count:,} listed" if listed_review_count > 0 else "")
        + f", review pages={review_page}, imageMode={review_image_mode})",
    )
    print(
        f"[reviews] {len(parsed)} US/CA leads ({review_image_mode}) "
        f"({checked} cards checked"
        + (f"/{listed_review_count} listed" if listed_review_count > 0 else "")
        + f", pages={review_page}, load-more={total_load_clicks})"
    )
    return parsed, checked
