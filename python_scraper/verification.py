import asyncio
import re
from typing import Optional

from playwright.async_api import Page

import config
from db import append_activity, update_job
from verification_assist import (
    assist_verification_loop,
    prepare_verification_ui,
    try_press_and_hold,
)


async def is_verification_page(page: Page) -> bool:
    await asyncio.sleep(0.3)
    title = await page.title()
    body = ""
    try:
        body = (await page.locator("body").inner_text(timeout=3000))[:8000]
    except Exception:
        pass

    patterns = [
        r"human touch",
        r"press\s*&\s*hold",
        r"press and hold",
        r"human verification",
        r"complete the task",
        r"pxcr\d+",
        r"#px-captcha",
        r"perimeterx",
    ]
    text = f"{title}\n{body}"
    return any(re.search(p, text, re.I) for p in patterns)


async def is_hard_blocked(page: Page) -> bool:
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
    """Attempt Press & Hold automatically whenever verification UI appears."""
    if not await is_verification_page(page):
        return True

    if job_id:
        append_activity(job_id, "Auto verification — Press & Hold assist")

    await prepare_verification_ui(page)

    for attempt in range(10):
        hold = config.PRESS_HOLD_SECONDS + min(attempt * 0.5, 3)
        await try_press_and_hold(page, hold_seconds=hold)
        await assist_verification_loop(page, max_attempts=4)
        await asyncio.sleep(1.2)
        if not await is_verification_page(page):
            if job_id:
                append_activity(job_id, "Verification cleared automatically")
            return True

    return not await is_verification_page(page)


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
    append_activity(job_id, "Fiverr verification — auto assist running")

    elapsed = 0.0
    interval = config.VERIFICATION_POLL_SEC
    timeout = config.VERIFICATION_TIMEOUT_SEC

    while elapsed < timeout:
        if await is_gig_page_visible(page):
            append_activity(job_id, "Verification cleared — continuing")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        await try_auto_clear_verification(page, job_id)
        await asyncio.sleep(interval)
        elapsed += interval

        if gig_url and int(elapsed) % 15 == 0:
            try:
                await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
                await try_auto_clear_verification(page, job_id)
            except Exception:
                pass

    append_activity(job_id, "Verification timed out — click Retry after solving in browser")
    return False


async def assert_page_accessible(page: Page, job_id: str) -> None:
    if await is_verification_page(page):
        cleared = await try_auto_clear_verification(page, job_id)
        if not cleared:
            cleared = await wait_until_verification_clears(page, job_id, page.url)
        if not cleared:
            raise VerificationRequiredError()
    if await is_hard_blocked(page):
        raise BlockedError("Fiverr access denied.")


class VerificationRequiredError(Exception):
    pass


class BlockedError(Exception):
    pass
