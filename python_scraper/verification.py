import asyncio
import re
from typing import Optional

from playwright.async_api import Page

import config
from browser import close_extra_pages
from db import append_activity, get_job, update_job
from verification_assist import (
    prepare_verification_ui,
    try_press_and_hold,
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
]


def _matches_verification_text(text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in VERIFICATION_PATTERNS)


async def is_verification_page(page: Page) -> bool:
    if page.is_closed():
        return False
    await asyncio.sleep(0.3)
    title = await page.title()
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


async def _cleanup_extra_tabs(original: Page, target: Page) -> None:
    keep = original if not original.is_closed() else target
    if target is not keep and not target.is_closed():
        try:
            await target.close()
        except Exception:
            pass
    try:
        await close_extra_pages(keep)
    except Exception:
        pass


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


async def try_auto_clear_verification(page: Page, job_id: str = "") -> bool:
    """Detect verification and optionally make one bounded assist pass."""
    target = await find_context_verification_page(page)
    if not target:
        return True

    if job_id:
        append_activity(job_id, "Fiverr verification detected - waiting in the browser window")

    if job_id and target is not page:
        append_activity(job_id, "Verification challenge tab detected")

    await prepare_verification_ui(target)

    attempts = max(0, config.AUTO_VERIFICATION_MAX_ATTEMPTS)
    if attempts <= 0:
        if job_id:
            append_activity(job_id, "Auto press-and-hold is off; solve verification once and leave the window open")
        return False

    for attempt in range(attempts):
        hold = config.PRESS_HOLD_SECONDS + min(attempt * 0.5, 3)
        pressed = await try_press_and_hold(target, hold_seconds=hold)
        if job_id:
            append_activity(
                job_id,
                f"Verification assist attempt {attempt + 1}/{attempts} {'pressed target' if pressed else 'target not found'}",
            )
        await asyncio.sleep(config.AUTO_VERIFICATION_RECHECK_SEC)
        if not await is_verification_page(target):
            if job_id:
                append_activity(job_id, "Verification cleared automatically")
            await _cleanup_extra_tabs(page, target)
            return True

    if job_id:
        append_activity(job_id, "Verification still present - waiting without refreshing the page")
    cleared = not await is_verification_page(target)
    if cleared:
        await _cleanup_extra_tabs(page, target)
    return cleared


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
    append_activity(job_id, "Fiverr verification - waiting for completion in the browser")

    append_activity(job_id, "Verification pause active - the scraper will wait without refreshing the challenge")

    elapsed = 0.0
    interval = config.VERIFICATION_POLL_SEC
    timeout = config.VERIFICATION_TIMEOUT_SEC
    auto_attempted = False
    navigated_after_clear = False
    last_wait_log = 0.0

    while elapsed < timeout:
        current = get_job(job_id)
        if current and current.get("status") == "stopped":
            append_activity(job_id, "Verification wait stopped by user")
            return False

        challenge_page = await find_context_verification_page(page)
        if challenge_page:
            if not auto_attempted:
                await try_auto_clear_verification(page, job_id)
                auto_attempted = True
            elif elapsed - last_wait_log >= 20:
                append_activity(job_id, "Still waiting for verification to clear - no refresh will be sent")
                last_wait_log = elapsed

            await asyncio.sleep(interval)
            elapsed += interval
            continue

        if await is_gig_page_visible(page):
            append_activity(job_id, "Verification cleared - continuing")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        if gig_url and not navigated_after_clear:
            append_activity(job_id, "Verification page closed - returning to the saved gig URL once")
            try:
                await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                append_activity(job_id, "Saved gig URL did not reload yet; still waiting")
            navigated_after_clear = True
            gig_url = None
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
