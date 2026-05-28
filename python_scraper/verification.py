import asyncio
import re
from typing import Optional

from playwright.async_api import Page

import config
from db import append_activity, get_job, set_heartbeat, update_job
from utils import normalize_fiverr_url
from verification_assist import prepare_verification_ui, try_press_and_hold

VERIFICATION_PATTERNS = [
    r"human touch",
    r"press\s*&\s*hold",
    r"press and hold",
    r"human verification",
    r"complete the task",
    r"pxcr\d+",
    r"#px-captcha",
    r"perimeterx",
    r"checking your browser",
    r"just a moment",
    r"enable javascript",
    r"cf-browser-verification",
    r"ddos.?protection",
    r"datadome",
    r"browser integrity check",
]

MAX_RESUME_NAVIGATION_ATTEMPTS = 4
RESUME_NAVIGATION_INTERVAL_SEC = 8.0
VERIFICATION_WAIT_LOG_INTERVAL_SEC = 20.0
AUTO_RETRY_INTERVAL_SEC = config.AUTO_VERIFICATION_RETRY_INTERVAL_SEC


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


isVerificationPage = is_verification_page


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


async def is_gig_page_ready(page: Page, resume_url: Optional[str] = None) -> bool:
    if page.is_closed():
        return False
    if await is_verification_page(page):
        return False
    if await is_hard_blocked(page):
        return False

    target_norm = normalize_fiverr_url(resume_url or "")
    current_norm = normalize_fiverr_url(page.url)
    if target_norm and current_norm and target_norm != current_norm:
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


async def is_gig_page_visible(page: Page) -> bool:
    return await is_gig_page_ready(page)


isGigPageReady = is_gig_page_ready


async def is_expected_resume_page(page: Page, resume_url: Optional[str]) -> bool:
    if page.is_closed() or await is_verification_page(page):
        return False

    current_url = page.url
    if not resume_url:
        return await is_gig_page_ready(page)

    if "/search/" in resume_url:
        if "fiverr.com" not in current_url or "/search/" not in current_url:
            return False
        try:
            return await page.locator("a[href]").count() > 0
        except Exception:
            return True

    return await is_gig_page_ready(page, resume_url)


async def _find_ready_resume_page(page: Page, resume_url: Optional[str]) -> Optional[Page]:
    if page.is_closed():
        return None
    pages = [p for p in list(page.context.pages) if not p.is_closed()]
    ordered = [page] + [p for p in reversed(pages) if p is not page]
    for candidate in ordered:
        try:
            if await is_expected_resume_page(candidate, resume_url):
                return candidate
        except Exception:
            continue
    return None


async def try_auto_clear_verification(
    page: Page,
    job_id: str = "",
    attempt_number: int = 1,
    max_attempts: Optional[int] = None,
) -> bool:
    """
    Run one page-scoped press-and-hold cycle.
    Returns True only when all verification pages are gone.
    """
    target = await find_context_verification_page(page)
    if not target:
        return True

    attempts = max(
        0,
        config.AUTO_VERIFICATION_MAX_ATTEMPTS if max_attempts is None else max_attempts,
    )
    if attempts <= 0 or attempt_number > attempts:
        if job_id:
            append_activity(
                job_id,
                "Auto press-and-hold is off or exhausted; still watching for manual completion",
            )
        await prepare_verification_ui(target)
        return False

    if job_id:
        append_activity(job_id, "Verification detected - running automatic press-and-hold")
    if job_id and target is not page:
        append_activity(job_id, "Verification challenge is on a separate tab - switching to it")

    await prepare_verification_ui(target)

    hold = config.PRESS_HOLD_SECONDS + min((attempt_number - 1) * 0.6, 4.0)
    pressed = await try_press_and_hold(target, hold_seconds=hold)
    if job_id:
        status = "pressed target" if pressed else "target not found"
        append_activity(
            job_id,
            f"Auto-verification attempt {attempt_number}/{attempts}: {status} "
            f"(hold={hold:.1f}s)",
        )

    await asyncio.sleep(config.AUTO_VERIFICATION_RECHECK_SEC)
    remaining_challenge = await find_context_verification_page(page)
    cleared = remaining_challenge is None
    if cleared and job_id:
        append_activity(job_id, "Verification cleared automatically")
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
    append_activity(job_id, "Fiverr verification detected - waiting for browser verification")

    elapsed = 0.0
    interval = config.VERIFICATION_POLL_SEC
    timeout = config.VERIFICATION_TIMEOUT_SEC
    resume_attempts = 0
    last_resume_navigation = -999.0
    last_wait_log = 0.0
    last_heartbeat = 0.0
    last_auto_attempt = -5.0  # first attempt fires after ~5s (not immediately)
    auto_attempts = 0
    max_auto_attempts = max(0, config.AUTO_VERIFICATION_MAX_ATTEMPTS)
    detected_url = ""

    while elapsed < timeout:
        if elapsed - last_heartbeat >= 20.0:
            try:
                set_heartbeat()
            except Exception:
                pass
            last_heartbeat = elapsed

        current = get_job(job_id)
        if current and current.get("status") == "stopped":
            append_activity(job_id, "Verification wait stopped by user")
            return False

        challenge_page = await find_context_verification_page(page)

        if challenge_page:
            if challenge_page.url != detected_url:
                detected_url = challenge_page.url
                append_activity(job_id, f"Verification detected at {detected_url}")
                try:
                    await prepare_verification_ui(challenge_page)
                except Exception:
                    pass

            auto_due = (
                max_auto_attempts > 0
                and auto_attempts < max_auto_attempts
                and elapsed - last_auto_attempt >= AUTO_RETRY_INTERVAL_SEC
            )
            if auto_due:
                auto_attempts += 1
                last_auto_attempt = elapsed
                cleared = await try_auto_clear_verification(
                    page,
                    job_id,
                    auto_attempts,
                    max_auto_attempts,
                )
                if not cleared:
                    append_activity(
                        job_id,
                        "Verification still present - waiting before next check",
                    )
                    await asyncio.sleep(interval)
                    elapsed += interval
                    continue
                append_activity(job_id, "Verification cleared - checking target Fiverr page")
            else:
                if elapsed - last_wait_log >= VERIFICATION_WAIT_LOG_INTERVAL_SEC:
                    if auto_attempts >= max_auto_attempts and max_auto_attempts > 0:
                        msg = "Still waiting for Fiverr verification to clear after auto attempts"
                    elif max_auto_attempts <= 0:
                        msg = "Still waiting for Fiverr verification to clear in the browser window"
                    else:
                        remaining = max(0, AUTO_RETRY_INTERVAL_SEC - (elapsed - last_auto_attempt))
                        msg = (
                            "Still waiting for Fiverr verification to clear "
                            f"(next auto attempt in {remaining:.0f}s)"
                        )
                    append_activity(job_id, msg)
                    last_wait_log = elapsed

                await asyncio.sleep(interval)
                elapsed += interval
                continue

        ready_page = await _find_ready_resume_page(page, gig_url)
        if ready_page and ready_page is page:
            append_activity(job_id, "Verification cleared - extraction resumed")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        if ready_page and gig_url:
            append_activity(
                job_id,
                "Verification cleared - returning scraper tab to target Fiverr URL",
            )
            try:
                await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
                await asyncio.sleep(config.GIG_PAGE_WAIT_SEC)
            except Exception:
                append_activity(job_id, "Target gig URL did not reload yet - still waiting")
            if await is_expected_resume_page(page, gig_url):
                append_activity(job_id, "Verification cleared - extraction resumed")
                update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
                return True

        if await is_expected_resume_page(page, gig_url):
            append_activity(job_id, "Verification cleared - extraction resumed")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

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
                f"Verification cleared - returning to Fiverr URL "
                f"({resume_attempts}/{MAX_RESUME_NAVIGATION_ATTEMPTS})",
            )
            try:
                await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                append_activity(job_id, "Fiverr URL did not reload yet - still waiting")
            await asyncio.sleep(interval)
            elapsed += interval
            continue

        await asyncio.sleep(interval)
        elapsed += interval

    append_activity(
        job_id,
        f"Verification timed out after {int(timeout)}s - current gig will be skipped",
    )
    update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
    return False


waitForVerificationToClear = wait_until_verification_clears


async def assert_page_accessible(page: Page, job_id: str, return_url: Optional[str] = None) -> None:
    challenge_page = await find_context_verification_page(page)
    if challenge_page:
        resume_url = return_url
        if not resume_url and challenge_page is not page:
            resume_url = page.url
        cleared = await wait_until_verification_clears(page, job_id, resume_url)
        if not cleared:
            raise VerificationRequiredError("Fiverr verification timed out", timed_out=True)
    if await is_hard_blocked(page):
        raise BlockedError("Fiverr access denied.")


class VerificationRequiredError(Exception):
    def __init__(self, message: str = "", timed_out: bool = False):
        super().__init__(message or "Fiverr verification required")
        self.timed_out = timed_out


class BlockedError(Exception):
    pass
