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
from pathlib import Path
from typing import Optional

from playwright.async_api import Frame, Locator, Page

import config

# ---------------------------------------------------------------------------
# Selectors — ordered from most-specific to broadest
# ---------------------------------------------------------------------------
PRESS_HOLD_SELECTORS = [
    # Exact Fiverr / PerimeterX button labels first (avoid huge parent divs)
    'button:has-text("Press & Hold")',
    '[role="button"]:has-text("Press & Hold")',
    'button:has-text("Press and Hold")',
    '[role="button"]:has-text("Press and Hold")',
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
    # Text-based buttons (keep last — broad matches)
    'button:has-text("Press")',
    'button:has-text("Hold")',
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
    # Live debug screenshots — throttled so mid-scrape clears don't pause for seconds
    last_shot = float(getattr(page, "_fv_verif_shot_at", 0) or 0)
    if time.monotonic() - last_shot > 12:
        try:
            shot_dir = Path(__file__).resolve().parent.parent / "tmp" / "live-gig-test"
            shot_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%H%M%S")
            await page.screenshot(path=str(shot_dir / f"verif_{stamp}.png"), full_page=False)
            setattr(page, "_fv_verif_shot_at", time.monotonic())
            print(f"[verification] screenshot -> {shot_dir / f'verif_{stamp}.png'}")
        except Exception:
            pass
    # Geometry dump (throttled) so we can see what PX actually rendered
    if not getattr(page, "_fv_verif_dump_at", 0) or (
        time.monotonic() - float(getattr(page, "_fv_verif_dump_at", 0)) > 15
    ):
        setattr(page, "_fv_verif_dump_at", time.monotonic())
    else:
        await asyncio.sleep(0.15)
        return
    try:
        info = await page.evaluate(
            """() => {
              const pick = [];
              const nodes = document.querySelectorAll(
                'button,[role="button"],#px-captcha,[id*="px-captcha"],canvas,[class*="captcha" i],[class*="human" i]'
              );
              for (const el of nodes) {
                const r = el.getBoundingClientRect();
                if (r.width < 20 || r.height < 12) continue;
                pick.push({
                  tag: el.tagName,
                  id: el.id || '',
                  text: ((el.innerText || el.textContent || '') + '').replace(/\\s+/g,' ').trim().slice(0,50),
                  x: Math.round(r.left + r.width/2),
                  y: Math.round(r.top + r.height/2),
                  w: Math.round(r.width),
                  h: Math.round(r.height),
                });
              }
              const iframes = [];
              for (const f of Array.from(document.querySelectorAll('iframe'))) {
                try {
                  const r = f.getBoundingClientRect();
                  if (!r || r.width < 1 || r.height < 1) continue;
                  iframes.push({
                    src: (f.src || '').slice(0, 120),
                    x: Math.round(r.left + r.width/2),
                    y: Math.round(r.top + r.height/2),
                    w: Math.round(r.width),
                    h: Math.round(r.height),
                  });
                } catch (e) {}
              }
              return { pick: pick.slice(0, 20), iframes: iframes.slice(0, 8), vw: innerWidth, vh: innerHeight };
            }"""
        )
        print(f"[verification] DOM candidates vw={info.get('vw')} vh={info.get('vh')}")
        for row in info.get("pick") or []:
            print(
                f"[verification]   {row.get('tag')} id={row.get('id')!r} "
                f"text={row.get('text')!r} center=({row.get('x')},{row.get('y')}) "
                f"size={row.get('w')}x{row.get('h')}"
            )
        for fr in info.get("iframes") or []:
            print(
                f"[verification]   iframe center=({fr.get('x')},{fr.get('y')}) "
                f"size={fr.get('w')}x{fr.get('h')} src={fr.get('src')!r}"
            )
    except Exception as err:
        print(f"[verification] DOM dump skipped: {err}")
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
    """Re-read element center using getBoundingClientRect (avoid scroll jumping PX widgets)."""
    try:
        pos = await loc.evaluate("""el => {
            const r = el.getBoundingClientRect();
            // Only nudge into view if mostly off-screen — scrollIntoView can collapse PX iframes
            if (r.bottom < 40 || r.top > (window.innerHeight - 40)) {
              el.scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});
            }
            const r2 = el.getBoundingClientRect();
            return {x: r2.left + r2.width / 2, y: r2.top + r2.height / 2, w: r2.width, h: r2.height};
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
            const compact = (el) => {
              const r = el.getBoundingClientRect();
              return r.width >= 40 && r.width <= 720 && r.height >= 20 && r.height <= 320;
            };

            // Prefer the visible Press & Hold control (not a full-page text wrapper)
            const buttons = Array.from(document.querySelectorAll('[role="button"],button'));
            for (const b of buttons) {
                const txt = ((b.innerText || b.textContent || '') + '').replace(/\\s+/g, ' ').trim().toLowerCase();
                if (/^press\\s*&?\\s*hold$/.test(txt) && compact(b)) {
                    return {sel: '#' + assign(b, '__fv_btn__')};
                }
            }
            for (const b of buttons) {
                const txt = ((b.innerText || b.textContent || '') + '').toLowerCase();
                if ((txt.includes('press') && txt.includes('hold')) && compact(b)) {
                    return {sel: '#' + assign(b, '__fv_btn__')};
                }
            }

            // PerimeterX exact IDs
            let el = document.querySelector('#px-captcha,#px-captcha-container,#px-captcha-wrapper,#px-captcha-button');
            if (el && compact(el)) return {sel: '#' + (el.id || assign(el, '__fv_px__'))};

            // Any element whose ID starts with px
            el = document.querySelector('[id^="px"]');
            if (el && compact(el)) return {sel: '#' + el.id};

            // Human-touch class
            el = document.querySelector('[class*="human-touch"],[class*="humanTouch"],[class*="press-hold"]');
            if (el && compact(el)) return {sel: '#' + assign(el, '__fv_captcha__')};

            // Large visible canvas (PerimeterX renders on canvas)
            const canvases = Array.from(document.querySelectorAll('canvas'));
            for (const c of canvases) {
                if (c.offsetWidth > 80 && c.offsetHeight > 40 && compact(c)) {
                    return {sel: '#' + assign(c, '__fv_canvas__')};
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
async def _is_compact_hold_target(loc: Locator, page: Optional[Page] = None) -> bool:
    """Prefer the actual button, not a full-page wrapper matching 'Press & Hold' text."""
    try:
        box = await loc.bounding_box()
        if not box:
            return False
        # Reject giant overlays / page shells
        if box["width"] > 720 or box["height"] > 320:
            return False
        # Real Fiverr Press & Hold control is a sizable pill, not a tiny top-bar chip
        if box["width"] < 100 or box["height"] < 28:
            return False
        cy = box["y"] + box["height"] / 2.0
        # Reject top-strip hits like (156,51) that never clear the modal
        if cy < 140:
            return False
        if page is not None:
            vp = page.viewport_size or {"height": 900}
            h = float(vp.get("height") or 900)
            if cy < h * 0.22 or cy > h * 0.88:
                return False
        return True
    except Exception:
        return False


async def _before_we_continue_visible(page: Page) -> bool:
    """True when the Fiverr mid-page 'Before we continue…' modal is up."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const hit = (root) => {
                    const t = ((root.innerText || root.textContent || '') + '')
                      .replace(/\\s+/g, ' ').toLowerCase();
                    if (t.includes('before we continue')) return true;
                    if (t.includes('press & hold') && t.includes('not a bot')) return true;
                    if (t.includes('press and hold') && t.includes('human')) return true;
                    return false;
                  };
                  if (hit(document.body || document.documentElement)) return true;
                  for (const el of document.querySelectorAll('*')) {
                    try {
                      if (el.shadowRoot && hit(el.shadowRoot)) return true;
                    } catch (e) {}
                  }
                  return !!document.querySelector(
                    '#px-captcha, [id*="px-captcha"], [role="dialog"] #px-captcha'
                  );
                }"""
            )
        )
    except Exception:
        return False


async def find_press_hold_target(page: Page) -> tuple[Optional[Locator], Optional[Frame]]:
    # 0. "Before we continue…" popup — hold the visible Press & Hold control FIRST.
    #    PX often paints "Press & Hold" on a canvas while DOM text still says
    #    "Loading challenge" — never wait/skip when this modal is present.
    popup_modal = await _before_we_continue_visible(page)

    popup_btn_selectors = (
        '[role="dialog"] button:has-text("Press & Hold")',
        '[role="dialog"] [role="button"]:has-text("Press & Hold")',
        '[aria-modal="true"] button:has-text("Press & Hold")',
        '[aria-modal="true"] [role="button"]:has-text("Press & Hold")',
        'button:has-text("Press & Hold")',
        '[role="button"]:has-text("Press & Hold")',
        # PX host is often the real hold target (canvas / div, not a <button>)
        '[role="dialog"] #px-captcha',
        '[aria-modal="true"] #px-captcha',
        "#px-captcha",
    )
    for frame in page.frames:
        for sel in popup_btn_selectors:
            try:
                loc = frame.locator(sel).first
                if not (await loc.count() and await loc.is_visible()):
                    continue
                # When the modal is up, accept #px-captcha even if text is "Loading"
                if await _is_compact_hold_target(loc, page) or (
                    popup_modal and "px-captcha" in sel
                ):
                    if popup_modal or "Press" in sel or "px-captcha" in sel:
                        print(f"[verification] Target via popup control {sel}")
                        return loc, frame
            except Exception:
                continue
        try:
            loc = frame.get_by_role(
                "button", name=re.compile(r"^\s*press\s*&?\s*hold\s*$", re.I)
            ).first
            if (
                await loc.count()
                and await loc.is_visible()
                and await _is_compact_hold_target(loc, page)
            ):
                print("[verification] Target via role=button Press & Hold")
                return loc, frame
        except Exception:
            pass

    # 1. PerimeterX host widget — hold immediately when modal is up (ignore Loading text)
    for sel in (
        "#px-captcha",
        "#px-captcha-container",
        "#px-captcha-wrapper",
        '[id*="px-captcha"]',
    ):
        try:
            loc = page.locator(sel).first
            if not (await loc.count() and await loc.is_visible()):
                continue
            try:
                txt = ((await loc.inner_text(timeout=600)) or "").replace("\n", " ").strip().lower()
            except Exception:
                txt = ""
            if not popup_modal and "loading" in txt and "press" not in txt:
                continue
            if await _is_compact_hold_target(loc, page) or popup_modal:
                print(
                    f"[verification] Target via host widget {sel} "
                    f"(modal={popup_modal} text={txt[:40]!r})"
                )
                return loc, page.main_frame
        except Exception:
            continue

    # 2. Iterate every frame (includes iframes Playwright can access)
    for frame in page.frames:
        for sel in PRESS_HOLD_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if (
                    await loc.count()
                    and await loc.is_visible()
                    and await _is_compact_hold_target(loc, page)
                ):
                    return loc, frame
            except Exception:
                continue

    # 3. Main page selectors (redundant safety pass)
    for sel in PRESS_HOLD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if (
                await loc.count()
                and await loc.is_visible()
                and await _is_compact_hold_target(loc, page)
            ):
                return loc, page.main_frame
        except Exception:
            continue

    # 3. JS DOM evaluation fallback
    js_loc = await _find_captcha_via_js(page)
    if js_loc and await _is_compact_hold_target(js_loc, page):
        return js_loc, page.main_frame

    # 4. Full-text fallback — still require compact mid-viewport geometry
    try:
        loc = page.get_by_text(re.compile(r"press\s*&?\s*hold", re.I)).first
        if (
            await loc.count()
            and await loc.is_visible()
            and await _is_compact_hold_target(loc, page)
        ):
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
    if y < 140:
        print(f"[verification] Skipping bad element center ({x:.0f},{y:.0f})")
        return False

    print(f"[verification] Playwright hold at ({x:.0f},{y:.0f}) for {hold_seconds:.1f}s")

    # Native Playwright press-and-hold (mousedown → delay → mouseup)
    try:
        box = await loc.bounding_box()
        pos = None
        if box and box.get("width", 0) > 8 and box.get("height", 0) > 8:
            pos = {"x": box["width"] / 2, "y": box["height"] / 2}
        await loc.click(
            delay=int(max(500, hold_seconds * 1000)),
            force=True,
            timeout=int((hold_seconds + 10) * 1000),
            position=pos,
        )
        await asyncio.sleep(1.0)
        if not await _challenge_still_present(page):
            return True
    except Exception as err:
        print(f"[verification] locator.click(delay) failed: {err}")

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


async def _wait_for_press_hold_ready(page: Page, timeout_sec: float = 25.0) -> Optional[tuple[float, float]]:
    """
    Prefer the visible Press & Hold control in the "Before we continue" popup.
    When that modal is present, hold #px-captcha immediately — even if DOM still
    says Loading challenge (PX draws the button on canvas).
    """
    deadline = time.monotonic() + timeout_sec
    last_text = ""
    while time.monotonic() < deadline:
        popup_modal = await _before_we_continue_visible(page)

        # Fast path: Playwright locator across frames
        try:
            loc, _frame = await find_press_hold_target(page)
            if loc:
                box = await loc.bounding_box()
                if box and box["width"] >= 60 and box["height"] >= 20:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    if cy >= 100:
                        print(
                            f"[verification] Captcha ready source=locator "
                            f"modal={popup_modal} center=({cx:.0f},{cy:.0f})"
                        )
                        return float(cx), float(cy)
        except Exception:
            pass

        try:
            info = await page.evaluate(
                """() => {
                  const body = ((document.body && (document.body.innerText || '')) + '')
                    .replace(/\\s+/g, ' ').toLowerCase();
                  const modal = body.includes('before we continue')
                    || (body.includes('press & hold') && body.includes('not a bot'));
                  const labels = ['press & hold', 'press and hold'];
                  const nodes = Array.from(document.querySelectorAll(
                    'button, [role="button"], #px-captcha, [id*="px-captcha"], canvas'
                  ));
                  for (const el of nodes) {
                    const text = ((el.innerText || el.textContent || '') + '')
                      .replace(/\\s+/g, ' ').trim().toLowerCase();
                    const r = el.getBoundingClientRect();
                    if (r.width < 60 || r.height < 20 || r.width > 720 || r.height > 320) continue;
                    if (r.top < 100) continue;
                    if (labels.some((l) => text === l || text.includes(l))) {
                      return {
                        text, x: r.left + r.width / 2, y: r.top + r.height / 2,
                        w: r.width, h: r.height, ready: true, loading: false, source: 'button', modal,
                      };
                    }
                  }
                  const el = document.querySelector(
                    '#px-captcha, #px-captcha-container, #px-captcha-wrapper, [id*="px-captcha"]'
                  );
                  if (!el) return modal ? { text: 'modal', x: innerWidth/2, y: innerHeight*0.48,
                    w: 280, h: 60, ready: true, loading: false, source: 'modal-center', modal: true } : null;
                  const r = el.getBoundingClientRect();
                  if (r.width < 40 || r.height < 20) return null;
                  const text = ((el.innerText || el.textContent || '') + '').replace(/\\s+/g, ' ').trim();
                  return {
                    text,
                    x: r.left + r.width / 2,
                    y: r.top + r.height / 2,
                    w: r.width,
                    h: r.height,
                    loading: /loading\\s*challenge/i.test(text),
                    ready: /press\\s*&?\\s*hold/i.test(text) || modal,
                    source: modal ? 'px-modal' : 'px',
                    modal,
                  };
                }"""
            )
        except Exception:
            info = None
        if info:
            last_text = info.get("text") or last_text
            # Modal up → hold now. Never sit on "Waiting for captcha… Loading"
            if (
                info.get("ready")
                or info.get("modal")
                or popup_modal
                or info.get("source") in ("button", "modal-center", "px-modal")
                or (
                    not info.get("loading")
                    and info.get("w", 0) >= 100
                    and info.get("h", 0) >= 40
                )
            ):
                print(
                    f"[verification] Captcha ready source={info.get('source')} "
                    f"text={last_text[:60]!r} center=({info['x']:.0f},{info['y']:.0f})"
                )
                return float(info["x"]), float(info["y"])
            print(
                f"[verification] Waiting for captcha… text={last_text[:60]!r} "
                f"center=({info['x']:.0f},{info['y']:.0f})"
            )
        await asyncio.sleep(0.35)
    print(f"[verification] Captcha not ready after {timeout_sec:.0f}s (last={last_text[:60]!r})")
    return None


async def _press_at_verification_center(page: Page, hold_seconds: float = 8.0) -> bool:
    """
    Press at the PerimeterX widget center (preferred) or a small viewport sweep.
    """
    captcha_center = await _wait_for_press_hold_ready(page, timeout_sec=10.0)
    points: list[tuple[float, float]] = []
    if captcha_center:
        cx, cy = captcha_center
        points.extend([(cx, cy), (cx, cy - 16), (cx, cy + 16)])
    else:
        vp = page.viewport_size or {"width": 1440, "height": 900}
        points.extend(
            [
                (vp["width"] * 0.36, vp["height"] * 0.40),
                (vp["width"] * 0.50, vp["height"] * 0.45),
            ]
        )

    seen = set()
    for cx, cy in points:
        key = (round(cx), round(cy))
        if key in seen:
            continue
        seen.add(key)
        print(f"[verification] Trying captcha/viewport hold at ({cx:.0f},{cy:.0f})")
        await _hold_at_viewport_coords(page, cx, cy, hold_seconds)
        await asyncio.sleep(0.8)
        if not await _challenge_still_present(page):
            return True
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
# Main press-and-hold entry point
# ---------------------------------------------------------------------------
async def try_press_and_hold(page: Page, hold_seconds: float = 8.0) -> bool:
    return await _legacy_try_press_and_hold(page, hold_seconds)


async def assist_verification_loop(page: Page, max_attempts: int = 10) -> bool:
    return await _legacy_assist_verification_loop(page, max_attempts)


async def _challenge_still_present(page: Page) -> bool:
    try:
        body = (await page.locator("body").inner_text(timeout=2000))[:4000]
        return any(
            re.search(p, body, re.I)
            for p in (
                r"before we continue",
                r"press\s*&?\s*hold",
                r"confirm you are a human",
                r"human touch",
                r"pxcr\d+",
            )
        )
    except Exception:
        return True


async def _legacy_try_press_and_hold(page: Page, hold_seconds: float = 8.0) -> bool:
    await prepare_verification_ui(page)
    # Prefer the known widget center immediately (fast path)
    # Modal visible → hold immediately (2.5s max wait). Never idle on Loading text.
    captcha_center = await _wait_for_press_hold_ready(page, timeout_sec=2.5)
    if captcha_center:
        cx, cy = captcha_center
        print(f"[verification] Fast captcha hold at ({cx:.0f},{cy:.0f})")
        await _hold_at_viewport_coords(page, cx, cy, hold_seconds)
        await asyncio.sleep(1.0)
        if not await _challenge_still_present(page):
            return True

    loc, _frame = await find_press_hold_target(page)
    ok = False

    if loc:
        center_pre = await _get_center_via_js(page, loc)
        if not center_pre:
            box = await loc.bounding_box()
            if box:
                center_pre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        if center_pre and center_pre[1] < 140:
            print(
                f"[verification] Rejecting suspicious hold target at "
                f"({center_pre[0]:.0f},{center_pre[1]:.0f}) — using viewport center"
            )
            loc = None
        else:
            # Short approach only — full reading sim wastes 2–3s per attempt
            if center_pre:
                try:
                    await page.mouse.move(center_pre[0], center_pre[1])
                    await asyncio.sleep(0.25)
                except Exception:
                    pass
            ok = await _hold_with_playwright_mouse(page, loc, hold_seconds)
            if config.ALLOW_OS_MOUSE_AUTOMATION and center_pre:
                coords = await _viewport_to_screen(page, center_pre[0], center_pre[1])
                if coords:
                    ok = _hold_with_pyautogui(coords[0], coords[1], hold_seconds) or ok
            if not ok:
                ok = await _dispatch_pointer_hold(loc, hold_seconds)

    if not loc or (ok and await _challenge_still_present(page)):
        print("[verification] Trying compact captcha/viewport hold")
        ok = await _press_at_verification_center(page, hold_seconds) or ok

    return ok


async def _legacy_assist_verification_loop(page: Page, max_attempts: int = 10) -> bool:
    for attempt in range(max_attempts):
        await prepare_verification_ui(page)
        hold = 6.0 + attempt * 0.5
        if await try_press_and_hold(page, hold_seconds=hold):
            return True
        await asyncio.sleep(0.8)
    return False
