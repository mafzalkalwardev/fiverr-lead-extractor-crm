"""
Assist Fiverr 'Press & Hold' verification using Playwright mouse + optional pyautogui.
"""
import asyncio
import re
import time
from typing import Optional

from playwright.async_api import Page

PRESS_HOLD_SELECTORS = [
    'p:has-text("Press")',
    'button:has-text("Press")',
    '[class*="hold" i]',
    "#px-captcha",
    '[id*="px" i]',
]


async def find_press_hold_locator(page: Page):
    for sel in PRESS_HOLD_SELECTORS:
        loc = page.locator(sel).first
        try:
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            continue
    # Obfuscated class from Fiverr (changes often) — match by text
    loc = page.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
    if await loc.count() and await loc.is_visible():
        return loc
    return None


async def _hold_with_playwright_mouse(page: Page, hold_seconds: float = 5.0) -> bool:
    loc = await find_press_hold_locator(page)
    if not loc:
        return False
    box = await loc.bounding_box()
    if not box or box["width"] < 10:
        return False
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    print(f"[verification] Press & Hold via Playwright at ({x:.0f}, {y:.0f}) for {hold_seconds}s")
    await page.mouse.move(x, y)
    await page.mouse.down()
    await asyncio.sleep(hold_seconds)
    await page.mouse.up()
    await asyncio.sleep(1.5)
    return True


def _hold_with_pyautogui(screen_x: float, screen_y: float, hold_seconds: float = 5.0) -> bool:
    try:
        import pyautogui
    except ImportError:
        print("[verification] pyautogui not installed — pip install pyautogui")
        return False

    pyautogui.FAILSAFE = True
    print(f"[verification] Press & Hold via pyautogui at ({screen_x:.0f}, {screen_y:.0f})")
    pyautogui.moveTo(screen_x, screen_y, duration=0.3)
    pyautogui.mouseDown()
    time.sleep(hold_seconds)
    pyautogui.mouseUp()
    time.sleep(1.0)
    return True


async def _viewport_to_screen(page: Page, x: float, y: float) -> Optional[tuple[float, float]]:
    """Convert viewport coordinates to screen coordinates for pyautogui."""
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


async def try_press_and_hold(page: Page, hold_seconds: float = 5.0) -> bool:
    """Find Press & Hold control and simulate a long press."""
    loc = await find_press_hold_locator(page)
    if not loc:
        return False

    if await _hold_with_playwright_mouse(page, hold_seconds):
        return True

    box = await loc.bounding_box()
    if not box:
        return False
    coords = await _viewport_to_screen(
        page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    )
    if coords:
        return _hold_with_pyautogui(coords[0], coords[1], hold_seconds)
    return False


async def assist_verification_loop(page: Page, max_attempts: int = 8) -> bool:
    """Retry press-and-hold a few times while verification UI is visible."""
    for attempt in range(max_attempts):
        if await try_press_and_hold(page, hold_seconds=4.5 + attempt * 0.5):
            await asyncio.sleep(2)
        else:
            await asyncio.sleep(1)
    return False
