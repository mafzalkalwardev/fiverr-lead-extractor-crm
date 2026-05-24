import asyncio
import re
from typing import Optional

from playwright.async_api import Page

import config
from db import append_activity, get_job, set_heartbeat, update_job
from utils import normalize_fiverr_url
from verification_assist import (
    prepare_verification_ui,
)

VERIFICATION_PATTERNS = [
    r"human touch",
    r"press\s*&\s*hold",
    r"press and hold",
    r"human verification",
    r"complete the task",
    r"pxcr\d+",
    r"#px-captcha",
    r"perimeterx",
    # Cloudflare / generic challenges
    r"checking your browser",
    r"just a moment",
    r"enable javascript",
    r"cf-browser-verification",
    r"ddos.?protection",
    # DataDome
    r"datadome",
    r"browser integrity check",
]

MAX_RESUME_NAVIGATION_ATTEMPTS = 4
RESUME_NAVIGATION_INTERVAL_SEC = 8.0
# Verification wait loop logs every N seconds while the challenge persists.
VERIFICATION_WAIT_LOG_INTERVAL_SEC = 20.0


def _matches_verification_text(text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in VERIFICATION_PATTERNS)


async def is_verification_page(page: Page) -> bool:
    if page.is_closed():
        return False
    await asyncio.sleep(0.3)
    try:
        title = await page.title()
    except Exception:
        title = ""
    body = ""
    try:
        body = (await page.locator("body").inner_text(timeout=3000))[:8000]
    except Exception:
        pass

    text = f"{page.url}\n{title}\n{body}"
    return _matches_verification_text(text)


async def find_context_verification_page(page: Page) -> Optional[Page]:
    """Find a Fiverr verification tab even when Chrome switched it away from us."""
    if page.is_closed():
        return None

    pages = [p for p in list(page.context.pages) if not p.is_closed()]
    ordered = [page] + [p for p in reversed(pages) if p is not page]
    for candidate in ordered:
        try:
            title = await candidate.title()
        except Exception:
            title = ""
        body = ""
        try:
            body = (await candidate.locator("body").inner_text(timeout=800))[:2500]
        except Exception:
            pass
        text = f"{candidate.url}\n{title}\n{body}"
        if _matches_verification_text(text):
            return candidate
    return None


async def is_hard_blocked(page: Page) -> bool:
    if page.is_closed():
        return False
    url = page.url
    body = ""
    try:
        body = (await page.locator("body").inner_text(timeout=3000))[:5000]
    except Exception:
        pass
    return bool(
        re.search(r"access denied|unusual traffic|sign in to continue", body, re.I)
        or re.search(r"challenge", url, re.I)
    )


async def is_gig_page_visible(page: Page) -> bool:
    if page.is_closed():
        return False
    if await is_verification_page(page):
        return False
    if await is_hard_blocked(page):
        return False
    try:
        h1 = page.locator("h1").first
        if await h1.count() and await h1.is_visible():
            text = (await h1.inner_text()).strip()
            if len(text) >= 3 and not re.match(r"^\d+(\.\d+)?$", text):
                return True
    except Exception:
        pass
    url = page.url
    return "fiverr.com" in url and "/search/" not in url and "human touch" not in url.lower()


async def is_expected_resume_page(page: Page, resume_url: Optional[str]) -> bool:
    if page.is_closed() or await is_verification_page(page):
        return False

    current_url = page.url
    if not resume_url:
        return await is_gig_page_visible(page)

    if "/search/" in resume_url:
        if "fiverr.com" not in current_url or "/search/" not in current_url:
            return False
        try:
            return await page.locator("a[href]").count() > 0
        except Exception:
            return True

    target_norm = normalize_fiverr_url(resume_url)
    current_norm = normalize_fiverr_url(current_url)
    if target_norm and current_norm:
        return target_norm == current_norm and await is_gig_page_visible(page)

    return await is_gig_page_visible(page)


async def try_auto_clear_verification(page: Page, job_id: str = "") -> bool:
    """
    Prepare the browser for human verification and report whether it is already clear.
    """
    target = await find_context_verification_page(page)
    if not target:
        return True  # Already cleared

    if job_id:
        append_activity(job_id, "Verification detected - waiting for browser verification")

    if job_id and target is not page:
        append_activity(job_id, "Verification challenge is on a separate tab - switching to it")

    await prepare_verification_ui(target)

    if job_id:
        append_activity(
            job_id,
            "Waiting for the client to complete Fiverr verification in the browser window",
        )
    return not await is_verification_page(target)


async def wait_until_verification_clears(
    page: Page,
    job_id: str,
    gig_url: Optional[str] = None,
) -> bool:
    update_job(
        job_id,
        {
            "status": "verification_required",
            "verificationMessage": config.VERIFICATION_MESSAGE,
        },
    )
    append_activity(job_id, "Fiverr verification detected - waiting for browser verification")

    elapsed = 0.0
    interval = config.VERIFICATION_POLL_SEC
    timeout = config.VERIFICATION_TIMEOUT_SEC
    resume_attempts = 0
    last_resume_navigation = -999.0
    last_wait_log = 0.0
    last_heartbeat = 0.0

    while elapsed < timeout:
        # Keep scraper heartbeat alive so UI doesn't show "offline" during wait
        if elapsed - last_heartbeat >= 20.0:
            try:
                set_heartbeat()
            except Exception:
                pass
            last_heartbeat = elapsed

        # Respect user stop
        current = get_job(job_id)
        if current and current.get("status") == "stopped":
            append_activity(job_id, "Verification wait stopped by user")
            return False

        challenge_page = await find_context_verification_page(page)

        if challenge_page:
            if elapsed - last_wait_log >= VERIFICATION_WAIT_LOG_INTERVAL_SEC:
                append_activity(
                    job_id,
                    "Still waiting for Fiverr verification to clear in the browser window",
                )
                last_wait_log = elapsed

            await asyncio.sleep(interval)
            elapsed += interval
            continue

        # Challenge page gone — check if we're on the right page
        if await is_expected_resume_page(page, gig_url):
            append_activity(job_id, "Verification cleared - continuing scrape")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        # Not on challenge and not on expected page — try navigating back
        can_resume_navigate = (
            gig_url
            and resume_attempts < MAX_RESUME_NAVIGATION_ATTEMPTS
            and elapsed - last_resume_navigation >= RESUME_NAVIGATION_INTERVAL_SEC
        )
        if can_resume_navigate:
            resume_attempts += 1
            last_resume_navigation = elapsed
            append_activity(
                job_id,
                f"Verification cleared - returning to gig URL "
                f"({resume_attempts}/{MAX_RESUME_NAVIGATION_ATTEMPTS})",
            )
            try:
                await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                append_activity(job_id, "Gig URL did not reload yet - still waiting")
            await asyncio.sleep(interval)
            elapsed += interval
            continue

        await asyncio.sleep(interval)
        elapsed += interval

    append_activity(job_id, "Verification timed out - click Retry after solving in browser")
    return False


async def assert_page_accessible(page: Page, job_id: str, return_url: Optional[str] = None) -> None:
    challenge_page = await find_context_verification_page(page)
    if challenge_page:
        resume_url = return_url
        if not resume_url and challenge_page is not page:
            resume_url = page.url
        cleared = await wait_until_verification_clears(page, job_id, resume_url)
        if not cleared:
            raise VerificationRequiredError()
    if await is_hard_blocked(page):
        raise BlockedError("Fiverr access denied.")


class VerificationRequiredError(Exception):
    pass


class BlockedError(Exception):
    pass
