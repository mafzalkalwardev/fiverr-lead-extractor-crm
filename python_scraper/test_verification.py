"""
Standalone verification test - run this directly to confirm verification detection.

Usage:
    cd python_scraper
    python test_verification.py

What it does:
  1. Opens the existing Fiverr browser profile (preserves cookies / login)
  2. Navigates to a Fiverr gig search page most likely to trigger PerimeterX
  3. Waits up to 30s for a verification challenge to appear
  4. Reports exactly what happened and leaves the browser open for manual verification
"""
import asyncio
import sys
from pathlib import Path

# Make sure we can import the scraper modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from browser import get_work_page, reset_browser
from verification import (
    find_context_verification_page,
    is_verification_page,
)
from verification_assist import find_press_hold_target


TEST_URL = "https://www.fiverr.com/search/gigs?query=web+scraping&source=top-bar"
WAIT_FOR_CHALLENGE_SEC = 30


async def run_test() -> None:
    print("[test] Opening browser with saved profile…")
    page = await get_work_page()
    print(f"[test] Navigating to {TEST_URL}")
    try:
        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=60_000)
    except Exception as err:
        print(f"[test] Navigation warning: {err}")

    print(f"[test] Watching for verification challenge (up to {WAIT_FOR_CHALLENGE_SEC}s)…")
    challenge_page = None
    for _ in range(WAIT_FOR_CHALLENGE_SEC * 2):
        if await is_verification_page(page):
            challenge_page = page
            break
        cand = await find_context_verification_page(page)
        if cand:
            challenge_page = cand
            break
        await asyncio.sleep(0.5)

    if not challenge_page:
        print(
            "[test] No verification challenge appeared within the wait window.\n"
            "       This is GOOD — no block was triggered.\n"
            "       To force a test: manually navigate to a Fiverr gig, trigger a challenge,\n"
            "       then re-run this script while the challenge window is open."
        )
        return

    print(f"[test] Challenge detected on: {challenge_page.url}")
    print(f"[test] Challenge page title: {await challenge_page.title()}")

    # Check what DOM elements are visible
    loc, frame = await find_press_hold_target(challenge_page)
    if loc:
        box = await loc.bounding_box()
        print(f"[test] Press-hold target FOUND via selector — bounding box: {box}")
    else:
        print(
            "[test] No DOM target found (expected for cross-origin iframe / canvas-only challenge)\n"
            "       Will fall back to viewport-center coordinates."
        )

    # Dump body text for debugging
    try:
        body = (await challenge_page.locator("body").inner_text(timeout=3000))[:2000]
        print(f"[test] Page body preview:\n---\n{body}\n---")
    except Exception:
        pass

    print(
        "[test] Verification challenge is visible.\n"
        "       Complete it in the scraper browser window; the app worker will resume after it clears."
    )

    await asyncio.sleep(3)
    await reset_browser()


if __name__ == "__main__":
    asyncio.run(run_test())
