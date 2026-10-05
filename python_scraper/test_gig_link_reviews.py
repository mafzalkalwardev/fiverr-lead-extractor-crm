"""
One-off live test: open a gig and report review/country/image extraction.
Does not require MongoDB.

Usage:
    cd python_scraper
    ..\\venv\\Scripts\\python.exe -u test_gig_link_reviews.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

# Keep the test short — only a few review pages
os.environ.setdefault("REVIEW_MAX_PAGES", "8")
os.environ.setdefault("REVIEW_SCROLL_LOAD_MAX", "5")
os.environ.setdefault("REVIEW_LOAD_MORE_MAX", "30")
os.environ.setdefault("PYTHON_VERIFICATION_TIMEOUT_SEC", "180")

import config
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


async def dump_first_page(page) -> None:
    from review_parser import (
        _collect_review_cards,
        _find_country,
        _review_delivery_image,
        _reviewer_before_country_dom,
        _reviewer_name,
        scroll_to_reviews,
    )

    await scroll_to_reviews(page)
    cards = await _collect_review_cards(page)
    print(f"\n[test] First-page review blocks found: {len(cards)}", flush=True)
    us_ca = 0
    with_img = 0
    keepable = 0
    for i, (card, text) in enumerate(cards[:20], 1):
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
            f"  #{i:02d} keep={keep} country={norm or country or '-'} "
            f"name={reviewer if name_ok else (reviewer or '-')!s} "
            f"image={'OK' if img_ok else 'NO'} "
            f"img={(image[:70] + '...') if image and len(image) > 70 else (image or '-')}",
            flush=True,
        )
        print(f"       text={text[:90].replace(chr(10), ' ')!r}", flush=True)
    print(
        f"[test] Among first {min(20, len(cards))}: "
        f"US/CA={us_ca}, valid_image={with_img}, keepable={keepable}",
        flush=True,
    )


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
        print("[test] Opening gig…", flush=True)
        await page.goto(clean, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(config.GIG_PAGE_WAIT_SEC)
        print(f"[test] Loaded: {page.url}", flush=True)
        print(f"[test] Title: {await page.title()}", flush=True)

        challenge = await is_verification_page(page) or await find_context_verification_page(page)
        if challenge:
            print(
                "\n[test] Fiverr verification detected.\n"
                "       Auto press-and-hold will try; if it fails, complete it\n"
                "       manually in the Chromium window.\n",
                flush=True,
            )
            cleared = await wait_until_verification_clears(page, JOB_ID, clean)
            print(f"[test] Verification cleared={cleared} title={await page.title()!r}", flush=True)
            if not cleared:
                print("[test] Challenge not cleared — cannot scrape reviews.", flush=True)
                return 3
            # Reload gig after challenge
            await page.goto(clean, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(1.5)

        await dump_first_page(page)

        print("\n[test] Running extract_reviews (max 3 pages, with_image)…", flush=True)
        reviews, checked = await extract_reviews(
            page,
            max_reviews=20,
            job_id=JOB_ID,
            seller_username="hamzagraphics",
            review_image_mode="with_image",
        )
        print(f"\n[test] RESULT: kept={len(reviews)} US/CA+image leads, scanned={checked}", flush=True)
        for i, r in enumerate(reviews[:10], 1):
            print(
                f"  lead#{i} {r.get('reviewerName')} | {r.get('reviewerCountry')} | "
                f"rating={r.get('reviewRating')} | page={r.get('reviewPage')} | "
                f"img={(r.get('reviewedImageLink') or '')[:60]}",
                flush=True,
            )
        if len(reviews) > 10:
            print(f"  … +{len(reviews) - 10} more", flush=True)
        return 0 if reviews else 2
    except Exception as err:
        print(f"[test] FAILED: {type(err).__name__}: {err}", flush=True)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        for p in patches:
            p.stop()
        try:
            await reset_browser()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
