import asyncio

import re

from typing import Optional

from urllib.parse import quote_plus, urlencode, urlparse, parse_qs, urlunparse



from playwright.async_api import Page



import config

from browser import get_work_page

from db import append_activity, update_job

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





def _pages_limit(max_pages: Optional[int]) -> int:

    """0 = scrape until last page (safety cap)."""

    if max_pages is not None and max_pages > 0:

        return max_pages

    if config.MAX_SEARCH_PAGES > 0:

        return config.MAX_SEARCH_PAGES

    return config.MAX_SEARCH_PAGES_SAFETY





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





async def _has_next_page(page: Page, niche: str, current_page: int) -> bool:

    next_btn = page.locator(

        'a[rel="next"], [aria-label*="next" i], button:has-text("Next")'

    ).first

    if await next_btn.count() and await next_btn.is_visible():

        return True

    disabled_next = page.locator(

        '[aria-label*="next" i][disabled], [aria-label*="next" i][aria-disabled="true"]'

    ).first

    if await disabled_next.count():

        return False

    return current_page < 200





async def discover_gig_urls(

    niche: str,

    max_gigs: int,

    job_id: str,

    max_pages: Optional[int] = None,

    exclude_urls: Optional[set[str]] = None,

) -> tuple[list[str], str]:

    """

    Paginate Fiverr search until max_gigs, configured page limit, or last page.

    """

    limit = _pages_limit(max_pages)
    unlimited_pages = config.MAX_SEARCH_PAGES <= 0 and (max_pages is None or max_pages <= 0)
    unlimited_gigs = max_gigs <= 0

    page = await get_work_page()
    excluded = set(exclude_urls or set())

    all_urls: list[str] = []

    seen: set[str] = set()

    page_num = 0

    empty_streak = 0
    skipped_existing_total = 0



    while page_num < limit:

        page_num += 1

        url = build_search_url(niche, page_num)

        print(f"[discovery] Search page {page_num}: {url}")



        update_job(

            job_id,

            {

                "status": "discovering_gigs",

                "currentSearchPage": page_num,

                "discoveryPageLimit": limit if not unlimited_pages else 0,

            },

        )

        append_activity(job_id, f"Scraping search page {page_num}…")



        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)

        await asyncio.sleep(config.DISCOVERY_PAGE_WAIT_SEC)



        if await is_verification_page(page):

            cleared = await wait_until_verification_clears(page, job_id, url)

            if not cleared:

                break



        await assert_page_accessible(page, job_id, url)

        batch = await collect_gig_cards(page)

        new_count = 0
        skipped_existing = 0

        for gig_url in batch:

            if gig_url in seen:

                continue

            seen.add(gig_url)

            if gig_url in excluded:
                skipped_existing += 1
                skipped_existing_total += 1
                continue

            all_urls.append(gig_url)

            new_count += 1

            if not unlimited_gigs and len(all_urls) >= max_gigs:
                break

        print(
            f"[discovery] Page {page_num}: +{new_count} gigs "
            f"(total {len(all_urls)}, skipped existing {skipped_existing})"
        )

        append_activity(

            job_id,

            f"Search page {page_num}: +{new_count} new gigs ({len(all_urls)} total, skipped {skipped_existing} already used)",

        )
        update_job(
            job_id,
            {
                "skippedExistingGigs": skipped_existing_total,
                "gigQueue": all_urls,
                "urlsDiscovered": len(all_urls),
                "totalGigs": len(all_urls),
            },
        )



        if not unlimited_gigs and len(all_urls) >= max_gigs:
            break

        if new_count == 0 and skipped_existing == 0:

            empty_streak += 1

        else:

            empty_streak = 0



        if empty_streak >= 2:

            print("[discovery] No new gigs on consecutive pages — end of results")

            append_activity(job_id, f"Finished search at page {page_num} (no more gigs)")

            break



        if page_num >= limit:

            break



        if not await _has_next_page(page, niche, page_num):

            append_activity(job_id, f"Finished search at page {page_num} (last page)")

            break



    pages_done = page_num

    print(f"[discovery] Total {len(all_urls)} gig URLs from {pages_done} page(s)")

    update_job(

        job_id,

        {"currentSearchPage": pages_done, "discoveryPagesScanned": pages_done},

    )

    if unlimited_gigs:
        return all_urls, "fiverr_search"
    return all_urls[:max_gigs], "fiverr_search"

