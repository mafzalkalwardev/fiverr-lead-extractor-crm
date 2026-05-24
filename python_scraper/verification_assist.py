"""
Assist Fiverr verification by focusing the scraper browser and locating the challenge.

Strategy (in order):
  1. CSS selectors across all frames (PerimeterX, generic captcha)
  2. JS DOM evaluation fallback (canvas, hidden IDs, dynamic classes)
  3. Text-content search across all frames
  4. Playwright mouse hold with natural wiggle simulation
  5. Explicit pointer-event dispatch if mouse hold returns no result

OS-level mouse automation is disabled for client delivery.
"""
import asyncio
import random
import re
import sys
import time
from typing import Optional

from playwright.async_api import Frame, Locator, Page

import config

# ---------------------------------------------------------------------------
# Selectors — ordered from most-specific to broadest
# ---------------------------------------------------------------------------
PRESS_HOLD_SELECTORS = [
    # PerimeterX primary IDs
    "#px-captcha",
    "#px-captcha-wrapper",
    "#px-captcha-container",
    "#px-captcha-button",
    '[id^="px-captcha"]',
    '[id*="px-captcha"]',
    # PerimeterX dynamic / partial
    '[id^="px"]',
    '[class*="px-captcha"]',
    # Canvas targets (PerimeterX often uses canvas)
    "canvas",
    # Fiverr human-touch specific
    '[class*="human-touch"]',
    '[class*="humanTouch"]',
    '[id*="human"]',
    # Generic captcha classes
    '[class*="captcha-button"]',
    '[class*="press-hold"]',
    '[class*="hold-button"]',
    '[class*="challenge-button"]',
    # Iframe containers (we'll navigate inside them separately)
    "iframe[src*='captcha']",
    "iframe[src*='perimeterx']",
    "iframe[src*='px-cloud']",
    "iframe[title*='challenge' i]",
    "iframe[title*='captcha' i]",
    # Aria / role
    '[aria-label*="press" i]',
    '[aria-label*="hold" i]',
    '[role="button"]:has-text("Press")',
    '[role="button"]:has-text("Hold")',
    # Class wildcards
    '[class*="hold" i]',
    '[class*="captcha" i]',
    '[class*="challenge" i]',
    # Text-based buttons
    'button:has-text("Press")',
    'button:has-text("Hold")',
    'div:has-text("Press & Hold")',
    'p:has-text("Press")',
]


# ---------------------------------------------------------------------------
# Window focus helper
# ---------------------------------------------------------------------------
def _focus_browser_on_windows() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        targets = ("chromium", "chrome", "fiverr")

        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            if any(t in title for t in targets):
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
                return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as err:
        print(f"[verification] Window focus skipped: {err}")


async def prepare_verification_ui(page: Page) -> None:
    if config.FOCUS_BROWSER_ON_VERIFICATION:
        try:
            await page.bring_to_front()
        except Exception:
            pass
        _focus_browser_on_windows()
    await asyncio.sleep(0.4)


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------
async def _scroll_element_into_view(loc: Locator) -> None:
    """Scroll element to center of viewport so mouse coordinates are valid."""
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await asyncio.sleep(0.25)
    except Exception:
        pass


async def _get_center_via_js(page: Page, loc: Locator) -> Optional[tuple[float, float]]:
    """Re-read element center after scroll using getBoundingClientRect for accuracy."""
    try:
        pos = await loc.evaluate("""el => {
            el.scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});
            const r = el.getBoundingClientRect();
            return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
        }""")
        if pos and pos.get("w", 0) >= 8 and pos.get("h", 0) >= 8:
            return float(pos["x"]), float(pos["y"])
    except Exception:
        pass
    return None


async def _find_captcha_via_js(page: Page) -> Optional[Locator]:
    """
    JS DOM evaluation fallback — finds captcha elements that CSS selectors miss
    (dynamically assigned IDs, shadow-DOM-adjacent, canvas inside container).
    Assigns a known ID so Playwright can address it.
    """
    try:
        result = await page.evaluate("""() => {
            const assign = (el, id) => { el.id = id; return id; };

            // PerimeterX exact IDs
            let el = document.querySelector('#px-captcha,#px-captcha-container,#px-captcha-wrapper,#px-captcha-button');
            if (el) return {sel: '#' + el.id};

            // Any element whose ID starts with px
            el = document.querySelector('[id^="px"]');
            if (el && el.offsetWidth > 30) return {sel: '#' + el.id};

            // Human-touch class
            el = document.querySelector('[class*="human-touch"],[class*="humanTouch"],[class*="press-hold"]');
            if (el) return {sel: '#' + assign(el, '__fv_captcha__')};

            // Large visible canvas (PerimeterX renders on canvas)
            const canvases = Array.from(document.querySelectorAll('canvas'));
            for (const c of canvases) {
                if (c.offsetWidth > 80 && c.offsetHeight > 40) {
                    return {sel: '#' + assign(c, '__fv_canvas__')};
                }
            }

            // Any role=button with press/hold text
            const buttons = Array.from(document.querySelectorAll('[role="button"],button'));
            for (const b of buttons) {
                const txt = (b.textContent || '').toLowerCase();
                if (txt.includes('press') || txt.includes('hold')) {
                    return {sel: '#' + assign(b, '__fv_btn__')};
                }
            }

            return null;
        }""")
        if result and result.get("sel"):
            loc = page.locator(result["sel"]).first
            if await loc.count():
                return loc
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Element finder — tries all frames then JS fallback
# ---------------------------------------------------------------------------
async def find_press_hold_target(page: Page) -> tuple[Optional[Locator], Optional[Frame]]:
    # 1. Iterate every frame (includes iframes Playwright can access)
    for frame in page.frames:
        for sel in PRESS_HOLD_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    return loc, frame
            except Exception:
                continue
        # Text search within frame
        try:
            loc = frame.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
            if await loc.count() and await loc.is_visible():
                return loc, frame
        except Exception:
            pass

    # 2. Main page selectors (redundant safety pass)
    for sel in PRESS_HOLD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                return loc, page.main_frame
        except Exception:
            continue

    # 3. JS DOM evaluation fallback
    js_loc = await _find_captcha_via_js(page)
    if js_loc:
        return js_loc, page.main_frame

    # 4. Full-text fallback on main page
    try:
        loc = page.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
        if await loc.count() and await loc.is_visible():
            return loc, page.main_frame
    except Exception:
        pass

    return None, None


# ---------------------------------------------------------------------------
# Mouse hold — natural movement + wiggle
# ---------------------------------------------------------------------------
async def _hold_with_playwright_mouse(
    page: Page, loc: Locator, hold_seconds: float = 8.0
) -> bool:
    # Scroll into view first so coordinates are in viewport
    await _scroll_element_into_view(loc)

    # Try JS-accurate center first, fall back to bounding_box
    center = await _get_center_via_js(page, loc)
    if not center:
        box = await loc.bounding_box()
        if not box or box["width"] < 8:
            return False
        center = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    x, y = center
    print(f"[verification] Playwright hold at ({x:.0f},{y:.0f}) for {hold_seconds:.1f}s")

    try:
        # Natural approach movement before pressing
        await page.mouse.move(x - random.uniform(8, 20), y - random.uniform(4, 12))
        await asyncio.sleep(random.uniform(0.06, 0.12))
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.08, 0.15))

        await page.mouse.down()
        end_at = time.monotonic() + hold_seconds
        last_wiggle = time.monotonic()
        direction = 1

        while time.monotonic() < end_at:
            remaining = end_at - time.monotonic()
            sleep_ms = random.uniform(0.06, 0.14)
            await asyncio.sleep(min(sleep_ms, max(0.02, remaining)))

            # Wiggle every 200-450 ms to appear human
            if time.monotonic() - last_wiggle >= random.uniform(0.2, 0.45):
                direction *= -1
                dx = direction * random.uniform(0.3, 1.5)
                dy = random.uniform(-0.6, 0.6)
                await page.mouse.move(x + dx, y + dy)
                last_wiggle = time.monotonic()

    finally:
        try:
            await page.mouse.up()
        except Exception:
            pass

    await asyncio.sleep(1.2)
    return True


# ---------------------------------------------------------------------------
# Pointer-event dispatch fallback (synthetic events — last resort)
# ---------------------------------------------------------------------------
async def _dispatch_pointer_hold(loc: Locator, hold_seconds: float = 8.0) -> bool:
    """
    Directly dispatch pointerdown/up events on the element.
    Less convincing than real mouse but works when viewport coords are off.
    """
    try:
        await loc.dispatch_event("pointerover")
        await loc.dispatch_event("pointerenter")
        await asyncio.sleep(0.05)
        await loc.dispatch_event("pointerdown", {"button": 0, "buttons": 1, "bubbles": True})
        await loc.dispatch_event("mousedown", {"button": 0, "buttons": 1, "bubbles": True})
        await asyncio.sleep(hold_seconds)
        await loc.dispatch_event("pointerup", {"button": 0, "buttons": 0, "bubbles": True})
        await loc.dispatch_event("mouseup", {"button": 0, "buttons": 0, "bubbles": True})
        await loc.dispatch_event("click", {"bubbles": True})
        return True
    except Exception as err:
        print(f"[verification] Pointer dispatch error: {err}")
        return False


# ---------------------------------------------------------------------------
# PyAutoGUI OS-level fallback (disabled unless ALLOW_OS_MOUSE_AUTOMATION=true)
# ---------------------------------------------------------------------------
def _hold_with_pyautogui(screen_x: float, screen_y: float, hold_seconds: float = 8.0) -> bool:
    if not config.ALLOW_OS_MOUSE_AUTOMATION:
        return False
    try:
        import pyautogui
    except ImportError:
        print("[verification] Install pyautogui: pip install pyautogui")
        return False

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    print(f"[verification] pyautogui hold at ({screen_x:.0f},{screen_y:.0f}) for {hold_seconds:.1f}s")
    pyautogui.moveTo(screen_x, screen_y, duration=0.25)
    pyautogui.mouseDown()
    time.sleep(hold_seconds)
    pyautogui.mouseUp()
    time.sleep(0.8)
    return True


async def _viewport_to_screen(page: Page, x: float, y: float) -> Optional[tuple[float, float]]:
    try:
        offset = await page.evaluate(
            """() => ({
                sx: window.screenX + (window.outerWidth - window.innerWidth) / 2,
                sy: window.screenY + (window.outerHeight - window.innerHeight)
            })"""
        )
        return offset["sx"] + x, offset["sy"] + y
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Viewport-coordinate fallback — used when no DOM element can be found
# (cross-origin iframe, canvas-only PerimeterX, fully dynamic DOM)
# ---------------------------------------------------------------------------
async def _hold_at_viewport_coords(
    page: Page, x: float, y: float, hold_seconds: float = 8.0
) -> bool:
    """Legacy coordinate helper retained for old debug scripts."""
    print(f"[verification] Coordinate hold at ({x:.0f},{y:.0f}) for {hold_seconds:.1f}s")
    try:
        await page.mouse.move(x - random.uniform(8, 18), y - random.uniform(4, 10))
        await asyncio.sleep(random.uniform(0.06, 0.12))
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.08, 0.15))
        await page.mouse.down()
        end_at = time.monotonic() + hold_seconds
        direction = 1
        last_wiggle = time.monotonic()
        while time.monotonic() < end_at:
            remaining = end_at - time.monotonic()
            await asyncio.sleep(min(random.uniform(0.07, 0.13), max(0.02, remaining)))
            if time.monotonic() - last_wiggle >= random.uniform(0.25, 0.45):
                direction *= -1
                await page.mouse.move(
                    x + direction * random.uniform(0.3, 1.4),
                    y + random.uniform(-0.5, 0.5),
                )
                last_wiggle = time.monotonic()
    finally:
        try:
            await page.mouse.up()
        except Exception:
            pass
    await asyncio.sleep(1.2)
    return True


async def _press_at_verification_center(page: Page, hold_seconds: float = 8.0) -> bool:
    """
    Last-resort: press at the visual center of the verification page.
    Fiverr's PerimeterX PRESS & HOLD button is typically centered
    horizontally and sits in the upper-center of the visible area.
    We try three vertical positions to hit it.
    """
    vp = page.viewport_size or {"width": 1440, "height": 900}
    cx = vp["width"] / 2
    # Try multiple vertical positions — PerimeterX button varies by version and Fiverr layout
    # Fiverr typically shows it around 50-60% height; broader sweep for resilience
    for y_ratio in (0.55, 0.50, 0.42, 0.60, 0.35, 0.65):
        cy = vp["height"] * y_ratio
        print(f"[verification] Trying viewport-center hold at ({cx:.0f},{cy:.0f})")
        await _hold_at_viewport_coords(page, cx, cy, hold_seconds)
        await asyncio.sleep(1.5)
        # Check if challenge cleared after this press
        try:
            body = (await page.locator("body").inner_text(timeout=2000))[:3000]
            if not any(
                re.search(p, body, re.I)
                for p in (r"press\s*&?\s*hold", r"human touch", r"pxcr\d+")
            ):
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Human pre-press simulation — PerimeterX flags instant clicks as bots
# ---------------------------------------------------------------------------
async def _simulate_human_reading(page: Page, target_x: Optional[float] = None, target_y: Optional[float] = None) -> None:
    """
    Move mouse naturally for 2-3 seconds before pressing.
    PerimeterX monitors time-on-page and mouse movement before a press;
    an instant click after page load is a bot signal.
    """
    vp = page.viewport_size or {"width": 1440, "height": 900}
    cx = target_x or (vp["width"] / 2)
    cy = target_y or (vp["height"] * 0.5)

    # Start from a random corner-ish position
    start_x = random.uniform(vp["width"] * 0.2, vp["width"] * 0.4)
    start_y = random.uniform(vp["height"] * 0.2, vp["height"] * 0.4)

    try:
        # Move to starting position
        await page.mouse.move(start_x, start_y)
        await asyncio.sleep(random.uniform(0.3, 0.6))

        # A couple of small random wanders (simulates eyes scanning the page)
        for _ in range(random.randint(2, 4)):
            wx = start_x + random.uniform(-60, 60)
            wy = start_y + random.uniform(-40, 40)
            await page.mouse.move(wx, wy)
            await asyncio.sleep(random.uniform(0.2, 0.5))

        # Slow drift toward the target
        steps = random.randint(4, 7)
        for i in range(steps):
            progress = (i + 1) / steps
            ix = start_x + (cx - start_x) * progress + random.uniform(-8, 8)
            iy = start_y + (cy - start_y) * progress + random.uniform(-5, 5)
            await page.mouse.move(ix, iy)
            await asyncio.sleep(random.uniform(0.1, 0.25))

        # Hover over target for a moment before pressing
        await page.mouse.move(cx, cy)
        await asyncio.sleep(random.uniform(0.4, 0.8))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Client-safe verification entry point
# ---------------------------------------------------------------------------
async def try_press_and_hold(page: Page, hold_seconds: float = 8.0) -> bool:
    print("[verification] Automatic press-and-hold is disabled; waiting for client verification")
    await prepare_verification_ui(page)
    return False


async def assist_verification_loop(page: Page, max_attempts: int = 10) -> bool:
    await prepare_verification_ui(page)
    return False


async def _legacy_try_press_and_hold(page: Page, hold_seconds: float = 8.0) -> bool:
    await prepare_verification_ui(page)

    loc, _frame = await find_press_hold_target(page)

    if loc:
        # Simulate human reading/scanning the page before pressing
        center_pre = await _get_center_via_js(page, loc)
        if not center_pre:
            box = await loc.bounding_box()
            if box:
                center_pre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await _simulate_human_reading(page, *(center_pre or ()))

        # Primary: Playwright page-scoped mouse on found element
        ok = await _hold_with_playwright_mouse(page, loc, hold_seconds)

        # Secondary: OS-level PyAutoGUI (if explicitly enabled)
        if config.ALLOW_OS_MOUSE_AUTOMATION:
            center = await _get_center_via_js(page, loc)
            if not center:
                box = await loc.bounding_box()
                if box:
                    center = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            if center:
                coords = await _viewport_to_screen(page, center[0], center[1])
                if coords:
                    ok = _hold_with_pyautogui(coords[0], coords[1], hold_seconds) or ok

        # Tertiary: synthetic pointer-event dispatch
        if not ok:
            print("[verification] Mouse hold failed — trying pointer event dispatch")
            ok = await _dispatch_pointer_hold(loc, hold_seconds)
    else:
        # Element not found (cross-origin iframe / canvas / dynamic DOM)
        # Simulate human reading before falling back to coordinate press
        print("[verification] Element not found — trying viewport-center press")
        await _simulate_human_reading(page)
        ok = await _press_at_verification_center(page, hold_seconds)

    return ok


async def _legacy_assist_verification_loop(page: Page, max_attempts: int = 10) -> bool:
    for attempt in range(max_attempts):
        await prepare_verification_ui(page)
        hold = 6.0 + attempt * 0.5
        if await try_press_and_hold(page, hold_seconds=hold):
            return True
        await asyncio.sleep(0.8)
    return False
