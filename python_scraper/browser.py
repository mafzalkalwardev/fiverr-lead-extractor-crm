import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

import config

_context: Optional[BrowserContext] = None
_playwright = None
_launch_lock = asyncio.Lock()
_work_page: Optional[Page] = None

LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")
LOCK_GLOBS = ("**/SingletonLock", "**/SingletonCookie", "**/SingletonSocket")


def is_browser_closed_error(err: Exception) -> bool:
    msg = str(err)
    return "has been closed" in msg or ("Target" in msg and "closed" in msg)


def is_profile_in_use_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "existing browser session" in msg
        or "profile is already in use" in msg
        or "singletonlock" in msg
        or "user data directory is already in use" in msg
    )


def release_profile_lock(profile_dir: Path) -> int:
    removed = 0
    if not profile_dir.exists():
        return 0

    candidates: list[Path] = []
    for name in LOCK_FILES:
        candidates.extend([profile_dir / name, profile_dir / "Default" / name])
    for pattern in LOCK_GLOBS:
        try:
            candidates.extend(profile_dir.glob(pattern))
        except OSError:
            pass

    seen: set[str] = set()
    for target in candidates:
        key = str(target)
        if key in seen or not target.exists():
            continue
        seen.add(key)
        try:
            target.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def kill_playwright_chrome_only() -> None:
    """Kill only Chromium launched for this app (not the user's normal Chrome)."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" -EA 0 | "
                    "Where-Object { $_.CommandLine -match 'browser-profile-py|ms-playwright' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA 0 }"
                ),
            ],
            cwd=str(config.ROOT_DIR),
            timeout=15,
            capture_output=True,
        )
    except Exception:
        pass


def prepare_browser_profile(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    release_profile_lock(profile_dir)


async def reset_browser() -> None:
    global _context, _playwright, _work_page
    _work_page = None
    if _context:
        try:
            await _context.close()
        except Exception:
            pass
        _context = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _context_alive(ctx: BrowserContext) -> bool:
    try:
        browser = ctx.browser
        return browser is not None and browser.is_connected()
    except Exception:
        return False


def _launch_kwargs() -> dict[str, Any]:
    return {
        "headless": config.PLAYWRIGHT_HEADLESS,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        "ignore_default_args": ["--enable-automation"],
    }


async def _install_resource_filter(ctx: BrowserContext) -> None:
    async def handler(route) -> None:
        req = route.request
        url = (req.url or "").lower()
        if req.resource_type in ("image", "media"):
            if "fiverr" in url or "cloudinary" in url:
                await route.continue_()
            else:
                await route.abort()
            return
        if req.resource_type == "font" and "fiverr" not in url:
            await route.abort()
            return
        await route.continue_()

    await ctx.route("**/*", handler)


async def _normalize_single_tab(ctx: BrowserContext) -> Page:
    """One window, one tab — close any extra tabs Playwright opens."""
    pages = list(ctx.pages)
    for extra in pages[1:]:
        try:
            await extra.close()
        except Exception:
            pass
    if ctx.pages:
        return ctx.pages[0]
    page = await ctx.new_page()
    return page


async def launch_browser() -> BrowserContext:
    """Launch scraper Chromium once (bundled Playwright only)."""
    global _context

    async with _launch_lock:
        if _context and _context_alive(_context):
            return _context

        if _context:
            await reset_browser()

        prepare_browser_profile(config.BROWSER_PROFILE_DIR)

        if not _playwright:
            _playwright = await async_playwright().start()

        last_err: Optional[Exception] = None
        for clear_lock in (False, True):
            if clear_lock:
                release_profile_lock(config.BROWSER_PROFILE_DIR)
                kill_playwright_chrome_only()
            try:
                print(
                    f"[browser] Opening Fiverr scraper window "
                    f"(profile={config.BROWSER_PROFILE_DIR.name})"
                )
                _context = await _playwright.chromium.launch_persistent_context(
                    str(config.BROWSER_PROFILE_DIR),
                    **_launch_kwargs(),
                )
                _context.on("close", lambda: _set_context_none())
                if config.BLOCK_HEAVY_RESOURCES:
                    await _install_resource_filter(_context)
                await _normalize_single_tab(_context)
                return _context
            except Exception as err:
                last_err = err
                await reset_browser()
                if not is_profile_in_use_error(err):
                    break

        hint = "Run: npm run free:browser — then start your job again."
        raise RuntimeError(f"Could not launch browser. {hint}") from last_err


def _set_context_none():
    global _context, _work_page
    _context = None
    _work_page = None


async def get_work_page() -> Page:
    """
    Single scraper tab for the whole job (discovery + all gigs).
    Browser window opens on first call — when a job starts, not at app startup.
    """
    global _work_page

    for attempt in range(3):
        try:
            ctx = await launch_browser()
            if _work_page and not _work_page.is_closed():
                return _work_page

            _work_page = await _normalize_single_tab(ctx)
            _work_page.set_default_timeout(60_000)
            _work_page.set_default_navigation_timeout(90_000)
            return _work_page
        except Exception as err:
            if attempt < 2 and (
                is_browser_closed_error(err) or is_profile_in_use_error(err)
            ):
                await reset_browser()
                release_profile_lock(config.BROWSER_PROFILE_DIR)
                continue
            raise
    raise RuntimeError("Failed to open scraper page")


async def new_page() -> Page:
    """Backward compatible — returns the shared work tab (no extra windows)."""
    return await get_work_page()


async def release_work_page_after_job() -> None:
    """Keep browser window open but clear tab reference for next job."""
    global _work_page
    _work_page = None


async def warm_browser() -> None:
    """No-op: browser opens only when a scrape job starts."""
    print("[browser] Waiting for a job — scraper window opens when you start a job")

