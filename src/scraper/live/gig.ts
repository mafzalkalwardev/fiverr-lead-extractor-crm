import type { Page } from "playwright";
import type { GigData } from "../types";
import { sleep } from "@/lib/utils";
import { assertPageAccessible } from "./blocked";
import { absolutizeUrl } from "../fiverr/urls";

/** Navigate to gig page */
export async function openGigPage(page: Page, url: string): Promise<void> {
  console.log(`[live] Opening gig: ${url}`);
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await sleep(2000);
  await assertPageAccessible(page);
  await page.waitForSelector("h1", { timeout: 25_000 }).catch(() => {});
}

/** Extract seller, title, main image from current gig page (already open) */
export async function extractGigMetadata(
  page: Page,
  gigUrl: string,
  options?: { offlineHtml?: boolean }
): Promise<GigData> {
  if (!options?.offlineHtml) {
    await assertPageAccessible(page);
  }

  const data = await page.evaluate(() => {
    const h1 = document.querySelector("h1");
    const title = h1?.textContent?.trim() || "";

    let sellerName = "";
    let sellerUsername = "";

    const sellerSelectors = [
      'a[href^="/"][data-track-tag*="seller"]',
      'header a[href^="/"]',
      '[class*="seller-name"] a',
      '[class*="seller_name"]',
      'a[aria-label*="seller" i]',
      '.seller-name a',
    ];

    for (const sel of sellerSelectors) {
      const el = document.querySelector(sel) as HTMLAnchorElement | null;
      if (el) {
        const name = el.textContent?.trim() || "";
        const href = el.getAttribute("href") || "";
        const parts = href.split("/").filter(Boolean);
        if (parts.length >= 1 && parts[0] !== "search" && parts[0] !== "categories") {
          sellerUsername = parts[0];
          if (name && name.length < 80) sellerName = name;
          break;
        }
      }
    }

    let mainImage = "";
    const imgSelectors = [
      '[data-track-tag="gallery"] img',
      '[class*="gallery"] img',
      '[class*="carousel"] img',
      'img[src*="fiverr-res.cloudinary"]',
      'img[src*="fiverr"]',
    ];
    for (const sel of imgSelectors) {
      const img = document.querySelector(sel) as HTMLImageElement | null;
      const src = img?.src || img?.getAttribute("data-src") || "";
      if (src && !/avatar|icon|logo|profile/i.test(src)) {
        mainImage = src;
        break;
      }
    }

    return { title, sellerName, sellerUsername, mainImage };
  });

  const pathParts = new URL(gigUrl).pathname.split("/").filter(Boolean);
  const sellerUsername = data.sellerUsername || pathParts[0] || "";
  const sellerName = (data.sellerName || sellerUsername).trim();

  return {
    gigUrl,
    gigTitle: data.title.trim(),
    sellerName,
    sellerUsername,
    mainGigImage: absolutizeUrl(data.mainImage),
  };
}
