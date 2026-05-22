import asyncio
import re
from typing import Optional
from urllib.parse import quote_plus, urlencode, urlparse, parse_qs, urlunparse

from playwright.async_api import Page

import config
from browser import new_page
from db import append_activity
from utils import normalize_fiverr_url
from verification import assert_page_accessible, is_verification_page, wait_until_verification_clears


def build_search_url(keyword: str, page_num: int = 1) -> str:
    q = quote_plus(keyword.strip())
    base = f"{config.FIVERR_ORIGIN}/search/gigs?query={q}&source=top-bar"
    if page_num <= 1:
        return base
    parsed = urlparse(base)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page_num)]
    new_query = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))


async def collect_gig_cards(page: Page, max_on_page: int = 200) -> list[str]:
    await page.wait_for_selector("a[href]", timeout=30_000)
    for _ in range(config.DISCOVERY_SCROLL_LOOPS):
        await page.mouse.wheel(0, 1200)
        await asyncio.sleep(0.35)

    selectors = [
        '[class*="gig-card" i] a[href]',
        '[data-testid*="gig-card" i] a[href]',
        "article a[href]",
        ".basic-gig-card a[href]",
        ".gig-wrapper a[href]",
    ]

    hrefs: list[str] = []
    for selector in selectors:
        links = page.locator(selector)
        count = min(await links.count(), 120)
        for i in range(count):
            href = await links.nth(i).get_attribute("href")
            if href:
                hrefs.append(href)

    if len(hrefs) < 5:
        fallback = page.locator('a[href*="/"]')
        count = min(await fallback.count(), 200)
        for i in range(count):
            href = await fallback.nth(i).get_attribute("href")
            if href:
                hrefs.append(href)

    seen: set[str] = set()
    results: list[str] = []
    skip_re = re.compile(r"/users/|seller_dashboard|inbox|/pro/|/cp/|/categories/", re.I)

    for href in hrefs:
        full = normalize_fiverr_url(href)
        if not full or full in seen or skip_re.search(full):
            continue
        seen.add(full)
        results.append(full)
        if len(results) >= max_on_page:
            break

    return results


async def discover_gig_urls(
    niche: str,
    max_gigs: int,
    job_id: str,
    max_pages: Optional[int] = None,
) -> tuple[list[str], str]:
    """
    Paginate Fiverr search: page 1, 2, 3… until max_gigs or max_pages.
    """
    pages_limit = max_pages or config.MAX_SEARCH_PAGES
    page = await new_page()
    all_urls: list[str] = []
    seen: set[str] = set()
    page_num = 0

    try:
        for page_num in range(1, pages_limit + 1):
            url = build_search_url(niche, page_num)
            print(f"[discovery] Search page {page_num}: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            await asyncio.sleep(config.DISCOVERY_PAGE_WAIT_SEC)

            from verification import try_auto_clear_verification

            await try_auto_clear_verification(page, job_id)

            if await is_verification_page(page):
                cleared = await wait_until_verification_clears(page, job_id, url)
                if not cleared:
                    break

            await assert_page_accessible(page, job_id)
            batch = await collect_gig_cards(page)
            new_count = 0
            for gig_url in batch:
                if gig_url in seen:
                    continue
                seen.add(gig_url)
                all_urls.append(gig_url)
                new_count += 1
                if len(all_urls) >= max_gigs:
                    break

            print(f"[discovery] Page {page_num}: +{new_count} gigs (total {len(all_urls)})")
            append_activity(job_id, f"Search page {page_num}: {new_count} new gigs ({len(all_urls)} total)")

            if len(all_urls) >= max_gigs:
                break
            if new_count == 0 and page_num > 1:
                print("[discovery] No new gigs on page — stopping pagination")
                break

            if page_num < pages_limit:
                next_btn = page.locator(
                    'a[rel="next"], [aria-label*="next" i], button:has-text("Next")'
                ).first
                if await next_btn.count() and await next_btn.is_visible():
                    await next_btn.click()
                    await asyncio.sleep(config.DISCOVERY_PAGE_WAIT_SEC)
                else:
                    # Try explicit page URL
                    next_url = build_search_url(niche, page_num + 1)
                    prev_len = len(all_urls)
                    await page.goto(next_url, wait_until="domcontentloaded")
                    await asyncio.sleep(config.DISCOVERY_PAGE_WAIT_SEC)
                    batch2 = await collect_gig_cards(page)
                    if not batch2:
                        break

        print(f"[discovery] Total {len(all_urls)} gig URLs from {min(page_num, pages_limit)} page(s)")
        return all_urls[:max_gigs], "fiverr_search"
    finally:
        await page.close()
