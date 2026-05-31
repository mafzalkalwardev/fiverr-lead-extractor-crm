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
        # Must match the bundled Chromium version (Playwright 1.55 = Chromium 136)
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "viewport": {
            "width": config.BROWSER_WINDOW_WIDTH,
            "height": config.BROWSER_WINDOW_HEIGHT,
        },
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-sync",
            "--disable-translate",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=IsolateOrigins,site-per-process",
            f"--window-size={config.BROWSER_WINDOW_WIDTH},{config.BROWSER_WINDOW_HEIGHT}",
            f"--window-position={config.BROWSER_WINDOW_X},{config.BROWSER_WINDOW_Y}",
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


def _set_page_defaults(page: Page) -> None:
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(90_000)


async def _safe_close_page(page: Page) -> None:
    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        pass


async def _normalize_single_tab(
    ctx: BrowserContext, keep: Optional[Page] = None
) -> Page:
    """Keep one controlled scraper tab and close stale/popup tabs."""
    global _work_page

    pages = [p for p in list(ctx.pages) if not p.is_closed()]
    if keep and not keep.is_closed() and keep in pages:
        primary = keep
    elif _work_page and not _work_page.is_closed() and _work_page in pages:
        primary = _work_page
    elif pages:
        primary = pages[0]
    else:
        primary = await ctx.new_page()
        pages = [primary]

    for extra in pages:
        if extra is primary:
            continue
        await _safe_close_page(extra)

    _set_page_defaults(primary)
    _work_page = primary
    return primary


async def close_extra_pages(keep: Page) -> Page:
    """Public helper for verification code after a challenge opens a new tab."""
    if keep.is_closed():
        return await get_work_page()
    return await _normalize_single_tab(keep.context, keep)


_VERIF_KEYWORDS = (
    "captcha", "perimeterx", "px-captcha", "human-touch", "humantouch",
    "human_touch", "verification", "challenge", "press-hold", "press_hold",
)


async def _auto_close_new_tab(new_page: Page) -> None:
    """
    Automatically close spurious new tabs that Fiverr opens via target=_blank.
    Verification/captcha tabs are kept open so the verification watcher can
    detect and press them; everything else is closed immediately.
    """
    await asyncio.sleep(0.5)
    if new_page.is_closed():
        return
    url = (new_page.url or "").lower()
    if any(k in url for k in _VERIF_KEYWORDS):
        return  # keep captcha/challenge tabs for the verification watcher
    try:
        title = (await new_page.title()).lower()
        if any(k in title for k in _VERIF_KEYWORDS):
            return
    except Exception:
        pass
    await _safe_close_page(new_page)


async def launch_browser() -> BrowserContext:
    """Launch scraper Chromium once (bundled Playwright only)."""
    global _context, _playwright

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
                _context.on("page", lambda p: asyncio.create_task(_auto_close_new_tab(p)))
                await _context.add_init_script("""
                    try {
                        // Hide automation signals
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        delete navigator.__proto__.webdriver;

                        // Realistic plugin list
                        Object.defineProperty(navigator, 'plugins', {get: () => {
                            const arr = [
                                {name:'Chrome PDF Plugin',filename:'internal-pdf-viewer'},
                                {name:'Chrome PDF Viewer',filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                                {name:'Native Client',filename:'internal-nacl-plugin'}
                            ];
                            arr.__proto__ = PluginArray.prototype;
                            return arr;
                        }});
                        Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
                        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
                        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});

                        // Chrome runtime object (real Chrome has this)
                        if (!window.chrome) window.chrome = {};
                        if (!window.chrome.runtime) window.chrome.runtime = {};
                        window.chrome.runtime.sendMessage = () => {};

                        // Permissions API — real Chrome returns 'prompt' for notifications
                        const origQuery = window.Permissions && window.Permissions.prototype.query;
                        if (origQuery) {
                            window.Permissions.prototype.query = function(params) {
                                if (params && params.name === 'notifications') {
                                    return Promise.resolve({state: 'prompt', onchange: null});
                                }
                                return origQuery.call(this, params);
                            };
                        }

                        // Force all navigation to stay in the current tab.
                        // Verification/captcha tabs are allowed through so the
                        // verification watcher can detect them; all other links
                        // that Fiverr tries to open as target=_blank are
                        // redirected to the same tab so reviews are not lost.
                        (function() {
                            var VERIF = ['human_touch','verification','challenge','press-hold','press_hold'];
                            function isVerif(url) {
                                var u = (url || '').toLowerCase();
                                return VERIF.some(function(k){ return u.indexOf(k) !== -1; });
                            }
                            // Override window.open
                            var _origOpen = window.open;
                            window.open = function(url, name, features) {
                                if (url && !isVerif(String(url))) {
                                    window.location.href = url;
                                    return window;
                                }
                                return _origOpen ? _origOpen.call(window, url, name, features) : null;
                            };
                            // Rewrite target=_blank on click before the browser acts on it
                            document.addEventListener('click', function(e) {
                                var el = e.target;
                                while (el && el.tagName !== 'A') el = el.parentElement;
                                if (el && el.target === '_blank' && el.href && !isVerif(el.href)) {
                                    el.target = '_self';
                                }
                            }, true);
                        })();
                    } catch(e) {}
                """)
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
                await _normalize_single_tab(ctx, _work_page)
                return _work_page

            _work_page = await _normalize_single_tab(ctx)
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

