import asyncio
import json
import re
from urllib.parse import urlparse

from playwright.async_api import Page

import config
from utils import (
    absolutize_url,
    clean_text,
    is_valid_seller_name,
    normalize_fiverr_url,
    seller_name_from_gig,
    username_from_gig_url,
)
from verification import assert_page_accessible

TITLE_SELECTORS = [
    "h1",
    '[data-testid*="gig-title" i]',
    '[class*="gig-title" i]',
    'meta[property="og:title"]',
]

BAD_GIG_IMAGE = re.compile(
    r"trophy|generic_asset|badge|icon|avatar|profile|\.gif|/assets/|3-Trophy",
    re.I,
)
GIG_IMAGE_GOOD = re.compile(r"/gigs/|/t_delivery|/t_main|/original/|/attachments/", re.I)


def username_from_url(value: str) -> str:
    try:
        path = urlparse(value).path.strip("/").split("/")
        return path[0] if path else ""
    except Exception:
        return ""


async def open_gig_page(page: Page, url: str, job_id: str) -> str:
    target = normalize_fiverr_url(url)
    if not target:
        raise ValueError(f"Invalid Fiverr gig URL: {url}")
    print(f"[gig] Opening: {target}")
    await page.goto(target, wait_until="domcontentloaded", timeout=120_000)
    await asyncio.sleep(config.GIG_PAGE_WAIT_SEC)
    await assert_page_accessible(page, job_id, target)
    try:
        await page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    final = normalize_fiverr_url(page.url) or target
    return final


async def _first_text(page: Page, selectors: list[str]) -> str:
    for sel in selectors:
        if sel.startswith("meta"):
            content = await page.locator(sel).first.get_attribute("content")
            if content:
                t = clean_text(content)
                if t:
                    return re.sub(r"\s*[-|]\s*Fiverr.*$", "", t, flags=re.I).strip()
            continue
        loc = page.locator(sel)
        count = min(await loc.count(), 5)
        for i in range(count):
            try:
                t = clean_text(await loc.nth(i).inner_text(timeout=2000))
                if t and len(t) >= 3:
                    return re.sub(r"\s*[-|]\s*Fiverr.*$", "", t, flags=re.I).strip()
            except Exception:
                pass
    title = clean_text(await page.title())
    return re.sub(r"\s*[-|]\s*Fiverr.*$", "", title, flags=re.I).strip()


async def _extract_seller_display(page: Page, path_user: str, gig_title: str) -> str:
    """Optional display name from seller card — never 'Fiverr'."""
    selectors = [
        f'a[href="/{path_user}"]',
        f'a[href="/{path_user}/"]',
        '[data-testid*="seller" i]',
        '[class*="seller-name" i]',
        '[class*="seller_name" i]',
    ]
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(min(await loc.count(), 15)):
            text = clean_text(await loc.nth(i).inner_text(timeout=1000)).lstrip("@")
            if is_valid_seller_name(text, path_user, gig_title):
                return text

    for script in await page.locator('script[type="application/ld+json"]').all():
        raw = await script.text_content()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key in ("seller", "brand", "author"):
                    nested = item.get(key)
                    if isinstance(nested, dict) and nested.get("name"):
                        name = clean_text(nested["name"])
                        if is_valid_seller_name(name, path_user, gig_title):
                            return name
        except Exception:
            pass
    return ""


async def _main_gig_image(page: Page, gig_url: str) -> str:
    """Real gig thumbnail only — skip trophies/badges."""
    og = await page.locator('meta[property="og:image"]').first.get_attribute("content")
    if og:
        full = absolutize_url(og)
        if full and not BAD_GIG_IMAGE.search(full) and (
            GIG_IMAGE_GOOD.search(full)
            or re.search(r"fiverr|cloudinary", full, re.I)
        ):
            return full

    for sel in ['[class*="gallery" i] img', 'img[src*="cloudinary"]', "main img"]:
        imgs = page.locator(sel)
        for i in range(min(await imgs.count(), 30)):
            src = (
                await imgs.nth(i).get_attribute("src")
                or await imgs.nth(i).get_attribute("data-src")
                or ""
            )
            full = absolutize_url(src)
            if not full or BAD_GIG_IMAGE.search(full):
                continue
            if GIG_IMAGE_GOOD.search(full) or "/gigs/" in full:
                return full
    return ""


async def extract_gig_metadata(page: Page, gig_url: str, job_id: str) -> dict:
    final_url = normalize_fiverr_url(page.url) or normalize_fiverr_url(gig_url)
    if not final_url:
        raise ValueError("Could not determine gig URL")

    gig_title = await _first_text(page, TITLE_SELECTORS)
    path_user = username_from_gig_url(final_url) or username_from_url(final_url)
    if not path_user or path_user.lower() == "fiverr":
        raise ValueError("Could not parse seller username from gig URL")

    gig = {
        "gigUrl": final_url,
        "gigTitle": gig_title,
        "sellerName": path_user,
        "sellerUsername": path_user,
        "sellerDisplayName": path_user,
        "mainGigImage": "",
    }
    seller_username = seller_name_from_gig(gig) or path_user
    seller_display = await _extract_seller_display(page, seller_username, gig_title)
    if not seller_display:
        seller_display = seller_username
    gig["sellerName"] = seller_display
    gig["sellerDisplayName"] = seller_display
    gig["sellerUsername"] = seller_username

    if len(gig_title) < 3:
        raise ValueError("Gig title not found")

    main_image = await _main_gig_image(page, final_url)

    return {
        "gigUrl": final_url,
        "gigTitle": gig_title,
        "sellerName": seller_display,
        "sellerDisplayName": seller_display,
        "sellerUsername": seller_username,
        "mainGigImage": main_image,
    }
