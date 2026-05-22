"""
Assist Fiverr 'Press & Hold' verification using Playwright mouse + pyautogui (Windows).
"""
import asyncio
import re
import sys
import time
from typing import Optional

from playwright.async_api import Frame, Locator, Page

PRESS_HOLD_SELECTORS = [
    "#px-captcha",
    '[id*="px-captcha" i]',
    '[id*="px" i]',
    "iframe[src*='captcha']",
    "iframe[src*='perimeterx']",
    "iframe[title*='challenge' i]",
    '[class*="hold" i]',
    'button:has-text("Press")',
    'p:has-text("Press")',
]


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
    try:
        await page.bring_to_front()
        for p in page.context.pages:
            await p.bring_to_front()
    except Exception:
        pass
    _focus_browser_on_windows()
    await asyncio.sleep(0.4)


async def find_press_hold_target(page: Page) -> tuple[Optional[Locator], Optional[Frame]]:
    for frame in page.frames:
        for sel in PRESS_HOLD_SELECTORS:
            loc = frame.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    return loc, frame
            except Exception:
                continue
        loc = frame.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
        try:
            if await loc.count() and await loc.is_visible():
                return loc, frame
        except Exception:
            continue

    for sel in PRESS_HOLD_SELECTORS:
        loc = page.locator(sel).first
        try:
            if await loc.count() and await loc.is_visible():
                return loc, page.main_frame
        except Exception:
            continue

    loc = page.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
    if await loc.count() and await loc.is_visible():
        return loc, page.main_frame
    return None, None


async def _hold_with_playwright_mouse(
    page: Page, loc: Locator, hold_seconds: float = 6.0
) -> bool:
    box = await loc.bounding_box()
    if not box or box["width"] < 8:
        return False
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    print(f"[verification] Playwright hold at ({x:.0f},{y:.0f}) for {hold_seconds:.1f}s")
    await page.mouse.move(x, y)
    await page.mouse.down()
    await asyncio.sleep(hold_seconds)
    await page.mouse.up()
    await asyncio.sleep(1.0)
    return True


def _hold_with_pyautogui(screen_x: float, screen_y: float, hold_seconds: float = 6.0) -> bool:
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


async def try_press_and_hold(page: Page, hold_seconds: float = 6.0) -> bool:
    await prepare_verification_ui(page)

    loc, _frame = await find_press_hold_target(page)
    if not loc:
        return False

    box = await loc.bounding_box()
    if not box:
        return False

    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2

    ok = await _hold_with_playwright_mouse(page, loc, hold_seconds)
    coords = await _viewport_to_screen(page, cx, cy)
    if coords:
        ok = _hold_with_pyautogui(coords[0], coords[1], hold_seconds) or ok
    return ok


async def assist_verification_loop(page: Page, max_attempts: int = 10) -> bool:
    for attempt in range(max_attempts):
        await prepare_verification_ui(page)
        hold = 5.5 + attempt * 0.4
        if await try_press_and_hold(page, hold_seconds=hold):
            await asyncio.sleep(2)
        else:
            await asyncio.sleep(0.8)
    return False
