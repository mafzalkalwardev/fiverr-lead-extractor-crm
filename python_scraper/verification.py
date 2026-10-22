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
    r"before we continue",
    r"press\s*&\s*hold",
    r"press and hold",
    r"confirm you are a human",
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


async def is_verification_page(page: Page, *, thorough: bool = False) -> bool:
    if page.is_closed():
        return False
    # Fast JS path — catches "Before we continue" / Press & Hold even in shadow DOM
    try:
        if await page.evaluate(
            """() => {
              const t = ((document.body && (document.body.innerText || document.body.textContent)) || '')
                .replace(/\\s+/g, ' ').toLowerCase();
              if (t.includes('before we continue')) return true;
              if (t.includes('press & hold') && (t.includes('not a bot') || t.includes('human'))) return true;
              if (t.includes('press and hold') && t.includes('human')) return true;
              const px = document.querySelector('#px-captcha, [id*="px-captcha"]');
              if (px) {
                const r = px.getBoundingClientRect();
                if (r.width > 40 && r.height > 20) return true;
              }
              return false;
            }"""
        ):
            return True
    except Exception:
        pass
    # Fast path — includes popup/modal overlays that appear mid-extraction
    try:
        if await page.locator("#px-captcha").first.is_visible(timeout=200):
            return True
    except Exception:
        pass
    try:
        # Fiverr often mounts Press & Hold inside a dialog over the reviews list
        popup = page.locator(
            '[role="dialog"]:has(#px-captcha), '
            '[role="dialog"]:has-text("Before we continue"), '
            '[role="dialog"]:has-text("Press & Hold"), '
            '[aria-modal="true"]:has-text("Press & Hold"), '
            '[aria-modal="true"]:has(#px-captcha)'
        ).first
        if await popup.count() and await popup.is_visible(timeout=200):
            return True
    except Exception:
        pass
    try:
        if await page.get_by_text(re.compile(r"before we continue", re.I)).first.is_visible(
            timeout=200
        ):
            return True
    except Exception:
        pass
    # Always treat visible Press & Hold as verification (same as full-page challenge)
    try:
        if await page.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first.is_visible(
            timeout=200
        ):
            return True
    except Exception:
        pass
    if not thorough:
        return False
    try:
        title = await page.title()
    except Exception:
        title = ""
    body = ""
    try:
        body = (await page.locator("body").inner_text(timeout=2000))[:8000]
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
            if await is_verification_page(candidate, thorough=False):
                return candidate
        except Exception:
            pass
        # Avoid full body.inner_text on every poll — that stalled Show More → scan gaps
        try:
            url = (candidate.url or "").lower()
            title = (await candidate.title() or "").lower()
        except Exception:
            url, title = "", ""
        if not any(
            k in url or k in title
            for k in ("captcha", "challenge", "human", "press", "verification", "px")
        ):
            continue
        body = ""
        try:
            body = (await candidate.locator("body").inner_text(timeout=600))[:2500]
        except Exception:
            pass
        text = f"{url}\n{title}\n{body}"
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


def urls_match_same_gig(current: str, target: str) -> bool:
    """True when both URLs point at the same gig path (ignore query/hash drift)."""
    a = normalize_fiverr_url(current or "") or ""
    b = normalize_fiverr_url(target or "") or ""
    if a and b:
        return a.rstrip("/").lower() == b.rstrip("/").lower()
    # Fallback: path prefix compare when normalize fails (e.g. mid-redirect)
    try:
        from urllib.parse import urlparse

        pa = urlparse(current or "").path.rstrip("/").lower()
        pb = urlparse(target or "").path.rstrip("/").lower()
        return bool(pa and pb and (pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/")))
    except Exception:
        return False


def is_off_gig_listing_url(url: str) -> bool:
    """Detect accidental landings on search/categories (the 'gigs page' bounce)."""
    u = (url or "").lower()
    if "/search/" in u or "/categories/" in u:
        return True
    if re.search(r"fiverr\.com/?($|\?)", u):
        return True
    return False


async def ensure_on_gig_url(page: Page, gig_url: Optional[str], job_id: str = "") -> bool:
    """
    If Fiverr bounced us to /search/gigs (or home), return to the target gig.
    No-op when already on the gig — avoids the stop → gigs page → come back glitch.
    """
    if page.is_closed() or not gig_url:
        return False
    current = page.url or ""
    if urls_match_same_gig(current, gig_url) and not is_off_gig_listing_url(current):
        return True
    if job_id:
        append_activity(
            job_id,
            "Left gig page (search/home redirect) — returning to target gig without full restart",
        )
    try:
        await page.goto(gig_url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(config.GIG_PAGE_WAIT_SEC)
    except Exception as err:
        print(f"[verification] ensure_on_gig_url failed: {err}")
        return False
    return urls_match_same_gig(page.url, gig_url)


async def is_gig_page_ready(page: Page, resume_url: Optional[str] = None) -> bool:
    if page.is_closed():
        return False
    if await is_verification_page(page):
        return False
    if await is_hard_blocked(page):
        return False

    if is_off_gig_listing_url(page.url):
        return False

    target_norm = normalize_fiverr_url(resume_url or "")
    current_norm = normalize_fiverr_url(page.url)
    if target_norm and current_norm and not urls_match_same_gig(page.url, resume_url or ""):
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
    gig_url: Optional[str] = None,
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
    if attempts <= 0:
        if job_id:
            append_activity(
                job_id,
                "Auto press-and-hold is off; still watching for manual completion",
            )
        await prepare_verification_ui(target)
        return False

    wave = max(1, int(attempt_number))
    if job_id:
        append_activity(job_id, "Verification detected - running automatic press-and-hold")
    if job_id and target is not page:
        append_activity(job_id, "Verification challenge is on a separate tab - switching to it")

    # Never reopen/reload while "Before we continue" is up — hold the control instead.
    # Only treat pure full-page Loading (no modal) as stuck.
    try:
        stuck_loading = await target.evaluate(
            """() => {
              const body = ((document.body && (document.body.innerText || '')) + '')
                .replace(/\\s+/g, ' ').toLowerCase();
              if (body.includes('before we continue')) return false;
              if (body.includes('press & hold') && body.includes('not a bot')) return false;
              const buttons = Array.from(document.querySelectorAll(
                'button, [role="button"], #px-captcha, [id*="px-captcha"]'
              ));
              for (const el of buttons) {
                const t = ((el.innerText || el.textContent || '') + '')
                  .replace(/\\s+/g, ' ').trim().toLowerCase();
                const r = el.getBoundingClientRect();
                if (r.width < 60 || r.height < 20 || r.top < 100) continue;
                if (/press\\s*&?\\s*hold/.test(t) || el.id.includes('px-captcha')) return false;
              }
              const el = document.querySelector('#px-captcha, [id*="px-captcha"]');
              if (!el) return false;
              const text = ((el.innerText || el.textContent || '') + '');
              if (/press\\s*&?\\s*hold/i.test(text)) return false;
              return /loading\\s*challenge/i.test(text);
            }"""
        )
    except Exception:
        stuck_loading = False
    if stuck_loading and wave % 2 == 1:
        if gig_url:
            if job_id:
                append_activity(
                    job_id,
                    "Challenge stuck on Loading — reopening target gig (not search/gigs)",
                )
            try:
                await target.goto(gig_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.0)
            except Exception as err:
                print(f"[verification] Gig reopen after stuck loading failed: {err}")
        else:
            if job_id:
                append_activity(
                    job_id,
                    "Challenge stuck on Loading — soft refresh on current page",
                )
            try:
                await target.reload(wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.0)
            except Exception as err:
                print(f"[verification] Reload after stuck loading failed: {err}")

    # If PX already bounced us to search/home, get back before holding
    if gig_url and is_off_gig_listing_url(target.url):
        await ensure_on_gig_url(target, gig_url, job_id)

    await prepare_verification_ui(target)

    hold = config.PRESS_HOLD_SECONDS + min((wave - 1) * 0.4, 2.5)
    pressed = await try_press_and_hold(target, hold_seconds=hold)
    if job_id:
        status = "pressed target" if pressed else "target not found"
        append_activity(
            job_id,
            f"Auto-verification attempt {wave}/{attempts}: {status} "
            f"(hold={hold:.1f}s)",
        )

    await asyncio.sleep(config.AUTO_VERIFICATION_RECHECK_SEC)
    if gig_url and is_off_gig_listing_url(page.url):
        await ensure_on_gig_url(page, gig_url, job_id)
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
    last_auto_attempt = -999.0  # clear Press & Hold immediately — do not sit idle
    auto_attempts = 0
    max_auto_attempts = max(0, config.AUTO_VERIFICATION_MAX_ATTEMPTS)
    detected_url = ""

    while elapsed < timeout:
        if elapsed - last_heartbeat >= 15.0:
            try:
                set_heartbeat()
            except Exception:
                pass
            # Keep job.updatedAt fresh so stale-reset does not steal a live wait
            try:
                update_job(job_id, {"status": "verification_required"})
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

            # Keep auto-retrying for the whole wait window. Exhausting at 8 left the
            # Press & Hold modal on screen for a long time while the job looked "stuck".
            auto_due = (
                max_auto_attempts > 0
                and elapsed - last_auto_attempt >= AUTO_RETRY_INTERVAL_SEC
            )
            if auto_due:
                auto_attempts += 1
                last_auto_attempt = elapsed
                # Ramp hold duration within each wave of max_auto_attempts, then repeat
                attempt_number = ((auto_attempts - 1) % max_auto_attempts) + 1
                cleared = await try_auto_clear_verification(
                    page,
                    job_id,
                    attempt_number,
                    max_auto_attempts,
                    gig_url=gig_url,
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

        # Already on the gig — resume immediately (do not goto /search or reload)
        if gig_url and urls_match_same_gig(page.url, gig_url) and not await is_verification_page(page):
            append_activity(job_id, "Verification cleared - still on gig, resuming extraction")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        ready_page = await _find_ready_resume_page(page, gig_url)
        if ready_page and ready_page is page:
            append_activity(job_id, "Verification cleared - extraction resumed")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        if ready_page and gig_url and ready_page is not page:
            # Prefer switching back to the gig tab over navigating the challenge tab away
            try:
                await ready_page.bring_to_front()
            except Exception:
                pass
            if await is_expected_resume_page(ready_page, gig_url):
                append_activity(job_id, "Verification cleared - extraction resumed on gig tab")
                update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
                return True

        if await is_expected_resume_page(page, gig_url):
            append_activity(job_id, "Verification cleared - extraction resumed")
            update_job(job_id, {"status": "extracting_reviews", "verificationMessage": ""})
            return True

        # Only navigate when we actually left the gig (search/home bounce)
        can_resume_navigate = (
            gig_url
            and resume_attempts < MAX_RESUME_NAVIGATION_ATTEMPTS
            and elapsed - last_resume_navigation >= RESUME_NAVIGATION_INTERVAL_SEC
            and (
                is_off_gig_listing_url(page.url)
                or not urls_match_same_gig(page.url, gig_url)
            )
        )
        if can_resume_navigate:
            resume_attempts += 1
            last_resume_navigation = elapsed
            append_activity(
                job_id,
                f"Verification cleared - restoring gig URL "
                f"({resume_attempts}/{MAX_RESUME_NAVIGATION_ATTEMPTS})",
            )
            await ensure_on_gig_url(page, gig_url, job_id)
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
