import asyncio
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

import config

_context: Optional[BrowserContext] = None
_playwright = None
_launch_lock = asyncio.Lock()

LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


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


def release_profile_lock(profile_dir: Path) -> None:
    """Remove stale Chromium lock files after a crashed run."""
    for name in LOCK_FILES:
        target = profile_dir / name
        if target.exists():
            try:
                target.unlink()
                print(f"[browser] Removed stale lock: {name}")
            except OSError as e:
                print(f"[browser] Could not remove {name}: {e}")


async def reset_browser() -> None:
    global _context, _playwright
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


def _launch_kwargs(channel: Optional[str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
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
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-translate",
            "--metrics-recording-only",
            "--mute-audio",
        ],
        "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        "ignore_default_args": ["--enable-automation"],
    }
    if channel:
        kwargs["channel"] = channel
    return kwargs


async def _launch_persistent(channel: Optional[str]) -> BrowserContext:
    global _playwright
    if not _playwright:
        _playwright = await async_playwright().start()

    label = channel or "playwright-chromium"
    print(
        f"[browser] Launching ({label}) profile={config.BROWSER_PROFILE_DIR} "
        f"headless={config.PLAYWRIGHT_HEADLESS}"
    )
    ctx = await _playwright.chromium.launch_persistent_context(
        str(config.BROWSER_PROFILE_DIR),
        **_launch_kwargs(channel),
    )
    ctx.on("close", lambda: _set_context_none())
    if config.BLOCK_HEAVY_RESOURCES:
        await _install_resource_filter(ctx)
    return ctx


async def _install_resource_filter(ctx: BrowserContext) -> None:
    """Block images/fonts/media to cut bandwidth and RAM (review URLs still come from DOM)."""

    async def handler(route) -> None:
        if route.request.resource_type in ("image", "font", "media"):
            await route.abort()
        else:
            await route.continue_()

    await ctx.route("**/*", handler)


async def launch_browser() -> BrowserContext:
    global _context

    async with _launch_lock:
        if _context and _context_alive(_context):
            return _context

        if _context:
            await reset_browser()

        config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        # Build launch attempts: bundled Chromium first (most reliable on Windows)
        attempts: list[Optional[str]] = []
        if config.PLAYWRIGHT_CHANNEL:
            attempts.append(config.PLAYWRIGHT_CHANNEL)
        attempts.append(None)  # bundled Playwright Chromium

        last_err: Optional[Exception] = None
        for channel in attempts:
            for clear_lock in (False, True):
                if clear_lock:
                    release_profile_lock(config.BROWSER_PROFILE_DIR)
                try:
                    _context = await _launch_persistent(channel)
                    return _context
                except Exception as err:
                    last_err = err
                    if is_profile_in_use_error(err):
                        print(f"[browser] Profile busy ({channel or 'chromium'}), retrying…")
                        await reset_browser()
                        continue
                    raise

        hint = (
            "Close all Chrome/Chromium windows opened for this app, then run again. "
            "Or set PYTHON_USE_SYSTEM_CHROME=false in .env (default)."
        )
        raise RuntimeError(f"Could not launch browser. {hint}") from last_err


def _set_context_none():
    global _context
    _context = None


async def new_page() -> Page:
    for attempt in range(3):
        try:
            ctx = await launch_browser()
            page = await ctx.new_page()
            page.set_default_timeout(60_000)
            page.set_default_navigation_timeout(90_000)
            return page
        except Exception as err:
            if attempt < 2 and (is_browser_closed_error(err) or is_profile_in_use_error(err)):
                print("[browser] Relaunching after error…")
                await reset_browser()
                release_profile_lock(config.BROWSER_PROFILE_DIR)
                continue
            raise
    raise RuntimeError("Failed to open browser page")


async def warm_browser() -> None:
    try:
        ctx = await launch_browser()
        if not ctx.pages:
            page = await ctx.new_page()
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=30_000)
        print("[browser] Ready — keep this browser window open while jobs run")
    except Exception as err:
        print(f"[browser] Warm-up failed (will retry on first job): {err}")
