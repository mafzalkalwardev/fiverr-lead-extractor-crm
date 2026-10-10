"""
Live end-to-end test for Paste Gig Links review extraction.

Uses the saved Playwright profile (login cookies). Browser stays headed
so you can watch / complete login or verification if needed.

Usage:
    cd python_scraper
    ..\\venv\\Scripts\\python.exe -u test_gig_link_reviews.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

os.environ["PLAYWRIGHT_HEADLESS"] = "false"
os.environ.setdefault("REVIEW_MAX_PAGES", "12")
os.environ.setdefault("REVIEW_SCROLL_LOAD_MAX", "10")
os.environ.setdefault("REVIEW_LOAD_MORE_MAX", "40")
os.environ.setdefault("PYTHON_VERIFICATION_TIMEOUT_SEC", "240")

import config

# Force reload headless flag from env we just set
config.PLAYWRIGHT_HEADLESS = False

from browser import get_work_page, kill_playwright_chrome_only, prepare_browser_profile, reset_browser
from utils import (
    is_valid_review_image,
    is_valid_reviewer_name,
    looks_like_rating,
    normalize_country,
    normalize_fiverr_url,
    reviewer_name_before_country,
)

GIG_URL = (
    "https://www.fiverr.com/hamzagraphics/"
    "design-professional-business-card-according-to-your-business"
)
JOB_ID = "000000000000000000000001"
OUT_DIR = Path(__file__).resolve().parent.parent / "tmp" / "live-gig-test"
LOGIN_WAIT_SEC = 180
MAX_LEADS = 30


def _noop_activity(job_id: str, message: str) -> None:
    print(f"[job] {message}", flush=True)


def _noop_update(job_id: str, fields: dict) -> None:
    interesting = {
        k: fields[k]
        for k in ("currentReviewPage", "totalReviewsParsed", "status", "verificationMessage")
        if k in fields
    }
    if interesting:
        print(f"[job] update {interesting}", flush=True)


def _noop_get_job(_job_id: str):
    return {"status": "running"}


def _noop_heartbeat() -> None:
    return None


async def _skip_assert(*_args, **_kwargs):
    return None


async def _shot(page, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
        print(f"[test] screenshot -> {path}", flush=True)
    except Exception as err:
        print(f"[test] screenshot failed ({name}): {err}", flush=True)


async def _is_logged_in(page) -> bool:
    try:
        # Logged-in UI markers
        for sel in (
            '[data-testid="user-menu"]',
            'button[aria-label*="Account" i]',
            'a[href*="/users/"]',
            '[class*="user-menu" i]',
            'img[alt*="avatar" i]',
        ):
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=800):
                return True
        # Sign-in button visible => logged out
        sign_in = page.get_by_role("link", name=re.compile(r"^sign in$", re.I)).first
        if await sign_in.count() and await sign_in.is_visible(timeout=800):
            return False
        body = (await page.content())[:6000].lower()
        if "sign in" in body and "join" in body and "inbox" not in body:
            return False
        # Cookie hint
        cookies = await page.context.cookies("https://www.fiverr.com")
        names = {c.get("name", "") for c in cookies}
        if any(n.lower() in names or n in names for n in ("authenticated", "fvrr_user", "user_data")):
            return True
        if any("session" in n.lower() or "auth" in n.lower() for n in names):
            return True
    except Exception:
        pass
    return False


# late import for regex used above
import re  # noqa: E402


async def ensure_login(page) -> bool:
    print("[test] Checking Fiverr login state…", flush=True)
    await page.goto("https://www.fiverr.com/", wait_until="domcontentloaded", timeout=60_000)
    await asyncio.sleep(2)
    await _shot(page, "01_home")

    if await _is_logged_in(page):
        print("[test] Already logged in (profile cookies).", flush=True)
        return True

    print(
        "\n[test] NOT logged in.\n"
        "       Log into Fiverr in the Chromium window that just opened.\n"
        f"       Waiting up to {LOGIN_WAIT_SEC}s…\n",
        flush=True,
    )
    for i in range(LOGIN_WAIT_SEC):
        if await _is_logged_in(page):
            print(f"[test] Login detected after {i}s.", flush=True)
            await _shot(page, "02_logged_in")
            return True
        if i % 15 == 0:
            print(f"[test] Waiting for login… ({i}s) title={await page.title()!r}", flush=True)
        await asyncio.sleep(1)

    print("[test] Login not detected — continuing anyway (may hit more blocks).", flush=True)
    await _shot(page, "02_login_timeout")
    return False


async def dump_first_page(page) -> dict:
    from review_parser import (
        _collect_review_cards,
        _find_country,
        _review_delivery_image,
        _reviewer_before_country_dom,
        _reviewer_name,
        open_all_reviews_panel,
        scroll_to_reviews,
    )

    await scroll_to_reviews(page)
    opened = await open_all_reviews_panel(page)
    print(f"[test] open_all_reviews_panel={opened}", flush=True)
    await _shot(page, "04_reviews_area")

    cards = await _collect_review_cards(page)
    print(f"\n[test] Review blocks found (pre-expand): {len(cards)}", flush=True)
    us_ca = with_img = keepable = 0
    for i, (card, text) in enumerate(cards[:15], 1):
        country = await _find_country(card, text)
        norm = normalize_country(country)
        image = await _review_delivery_image(card)
        img_ok = bool(image and is_valid_review_image(image))
        reviewer = await _reviewer_before_country_dom(card)
        if not reviewer:
            reviewer = reviewer_name_before_country(text)
        if not reviewer:
            reviewer = await _reviewer_name(card, text, "hamzagraphics")
        name_ok = bool(
            reviewer and not looks_like_rating(reviewer) and is_valid_reviewer_name(reviewer)
        )
        keep = norm in ("United States", "Canada") and img_ok and name_ok
        if norm in ("United States", "Canada"):
            us_ca += 1
        if img_ok:
            with_img += 1
        if keep:
            keepable += 1
        print(
            f"  #{i:02d} keep={keep} country={norm or '-'} name={reviewer or '-'} "
            f"image={'OK' if img_ok else 'NO'}",
            flush=True,
        )
    summary = {
        "cards": len(cards),
        "us_ca": us_ca,
        "with_img": with_img,
        "keepable": keepable,
    }
    print(f"[test] pre-expand summary: {summary}", flush=True)
    return summary


async def run() -> int:
    from review_parser import extract_reviews
    from verification import (
        find_context_verification_page,
        is_verification_page,
        wait_until_verification_clears,
    )

    clean = normalize_fiverr_url(GIG_URL) or GIG_URL
    print(f"[test] Gig: {clean}", flush=True)
    print(f"[test] Profile: {config.BROWSER_PROFILE_DIR}", flush=True)
    print(f"[test] Headless: {config.PLAYWRIGHT_HEADLESS}", flush=True)
    print(f"[test] Started: {datetime.now().isoformat(timespec='seconds')}", flush=True)

    kill_playwright_chrome_only()
    prepare_browser_profile(config.BROWSER_PROFILE_DIR)

    patches = [
        patch("review_parser.append_activity", _noop_activity),
        patch("review_parser.update_job", _noop_update),
        patch("review_parser.assert_page_accessible", _skip_assert),
        patch("verification.append_activity", _noop_activity),
        patch("verification.update_job", _noop_update),
        patch("verification.get_job", _noop_get_job),
        patch("verification.set_heartbeat", _noop_heartbeat),
    ]
    for p in patches:
        p.start()

    try:
        page = await get_work_page()
        logged_in = await ensure_login(page)

        print("[test] Opening gig…", flush=True)
        await page.goto(clean, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(config.GIG_PAGE_WAIT_SEC)
        print(f"[test] Loaded: {page.url}", flush=True)
        print(f"[test] Title: {await page.title()}", flush=True)
        await _shot(page, "03_gig")

        challenge = await is_verification_page(page) or await find_context_verification_page(page)
        if challenge:
            print(
                "\n[test] Verification detected — auto press-and-hold will try;\n"
                "       complete it manually in the window if needed.\n",
                flush=True,
            )
            cleared = await wait_until_verification_clears(page, JOB_ID, clean)
            print(f"[test] Verification cleared={cleared} title={await page.title()!r}", flush=True)
            await _shot(page, "03b_after_verification")
            if not cleared:
                print("[test] Challenge not cleared — aborting.", flush=True)
                return 3
            await page.goto(clean, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(1.5)

        await dump_first_page(page)

        print(
            f"\n[test] Running extract_reviews (with_image, max_leads={MAX_LEADS}, "
            f"load_more_max={config.REVIEW_LOAD_MORE_MAX})…",
            flush=True,
        )
        reviews, checked = await extract_reviews(
            page,
            max_reviews=MAX_LEADS,
            job_id=JOB_ID,
            seller_username="hamzagraphics",
            review_image_mode="with_image",
        )
        await _shot(page, "05_after_extract")

        print(
            f"\n[test] RESULT logged_in={logged_in} kept={len(reviews)} "
            f"US/CA+image leads, scanned={checked}",
            flush=True,
        )
        for i, r in enumerate(reviews[:15], 1):
            print(
                f"  lead#{i} {r.get('reviewerName')} | {r.get('reviewerCountry')} | "
                f"rating={r.get('reviewRating')} | page={r.get('reviewPage')} | "
                f"img={(r.get('reviewedImageLink') or '')[:70]}",
                flush=True,
            )
        if len(reviews) > 15:
            print(f"  … +{len(reviews) - 15} more", flush=True)

        # Soft success criteria for this gig
        if len(reviews) >= 5 and checked >= 30:
            print("[test] PASS — extraction working with login profile.", flush=True)
            return 0
        if len(reviews) >= 1:
            print("[test] PARTIAL — some leads kept but volume looks low.", flush=True)
            return 2
        print("[test] FAIL — 0 leads kept.", flush=True)
        return 2
    except Exception as err:
        print(f"[test] FAILED: {type(err).__name__}: {err}", flush=True)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        for p in patches:
            p.stop()
        print("[test] Leaving browser open 20s so you can inspect…", flush=True)
        await asyncio.sleep(20)
        try:
            await reset_browser()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
