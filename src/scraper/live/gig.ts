import type { Locator, Page } from "playwright";
import type { GigData } from "../types";
import { sleep } from "@/lib/utils";
import { assertPageAccessible } from "./blocked";
import { absolutizeUrl, normalizeFiverrUrl } from "../fiverr/urls";

const FIVERR_ORIGIN = "https://www.fiverr.com";

const TITLE_SELECTORS = [
  "h1",
  '[data-testid*="gig-title" i]',
  '[class*="gig-title" i]',
  '[class*="title" i] h1',
];

const SELLER_LINK_SELECTORS = [
  '[data-testid*="seller" i] a[href]',
  '[data-testid*="profile" i] a[href]',
  '[class*="seller" i] a[href]',
  '[class*="profile" i] a[href]',
  'a[href^="/"][data-track-tag*="seller" i]',
  '[class*="seller-name" i] a[href]',
  '[class*="seller_name" i] a[href]',
  'a[aria-label*="seller" i]',
  ".seller-name a[href]",
  "main a[href]",
  "a[href]",
];

const IMAGE_SELECTORS = [
  'img[src*="fiverr-res.cloudinary"]',
  '[data-track-tag="gallery"] img',
  '[class*="gallery" i] img',
  '[class*="carousel" i] img',
  'img[src*="cloudinary"]',
  'img[src*="fiverr"]',
];

const BAD_SELLER_TEXT =
  /^(contact me|message|order now|continue|search|fiverr|profile|seller|reviews?|about|english|from|view profile)$/i;

function cleanText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function cleanTitle(value: string): string {
  return cleanText(value)
    .replace(/\s*[-|]\s*Fiverr.*$/i, "")
    .replace(/^Fiverr\s*[-|]\s*/i, "")
    .trim();
}

function usernameFromUrl(value: string): string {
  try {
    const url = new URL(value, FIVERR_ORIGIN);
    if (!url.hostname.includes("fiverr.com")) return "";
    return url.pathname.split("/").filter(Boolean)[0] || "";
  } catch {
    return "";
  }
}

function isLikelySellerName(value: string, gigTitle: string): boolean {
  const text = cleanText(value).replace(/^@/, "");
  if (text.length < 2 || text.length > 80) return false;
  if (BAD_SELLER_TEXT.test(text)) return false;
  if (/\b(starting at|package|basic|standard|premium)\b/i.test(text)) return false;
  if (/\b(?:pkr|usd|eur|gbp|cad|aud|\$|€|£)\b/i.test(text)) return false;
  if (gigTitle && text.toLowerCase() === gigTitle.toLowerCase()) return false;
  if (/\b(order|checkout|login|join|search|category|review|rating)\b/i.test(text)) return false;
  return true;
}

async function locatorText(locator: Locator): Promise<string> {
  const raw =
    (await locator.innerText({ timeout: 1500 }).catch(() => null)) ||
    (await locator.textContent({ timeout: 1500 }).catch(() => null));
  return cleanText(raw);
}

async function firstText(page: Page, selectors: string[]): Promise<string> {
  for (const selector of selectors) {
    const locator = page.locator(selector);
    const count = Math.min(await locator.count().catch(() => 0), 5);
    for (let i = 0; i < count; i++) {
      const text = await locatorText(locator.nth(i));
      if (text) return text;
    }
  }
  return "";
}

async function firstMetaContent(page: Page, selectors: string[]): Promise<string> {
  for (const selector of selectors) {
    const content = await page.locator(selector).first().getAttribute("content").catch(() => null);
    const text = cleanTitle(content || "");
    if (text) return text;
  }
  return "";
}

async function extractSellerNameFromStructuredData(page: Page): Promise<string> {
  const scripts = page.locator('script[type="application/ld+json"]');
  const count = Math.min(await scripts.count().catch(() => 0), 20);

  for (let i = 0; i < count; i++) {
    const raw = await scripts.nth(i).textContent({ timeout: 1000 }).catch(() => null);
    if (!raw) continue;

    try {
      const parsed = JSON.parse(raw);
      const queue: unknown[] = Array.isArray(parsed) ? [...parsed] : [parsed];
      while (queue.length) {
        const item = queue.shift();
        if (!item || typeof item !== "object") continue;
        const record = item as Record<string, unknown>;

        for (const key of ["seller", "brand", "author", "provider"]) {
          const nested = record[key];
          if (nested && typeof nested === "object") {
            const name = cleanText((nested as { name?: unknown }).name as string);
            if (name.length >= 2 && name.length < 80) return name;
            queue.push(nested);
          }
        }
      }
    } catch {
      /* ignore invalid structured data */
    }
  }

  return "";
}

async function extractSeller(page: Page, sellerUsernameFromPath: string, gigTitle: string) {
  let sellerUsername = sellerUsernameFromPath;
  let sellerName = "";

  for (const selector of SELLER_LINK_SELECTORS) {
    const links = page.locator(selector);
    const count = Math.min(await links.count().catch(() => 0), selector === "a[href]" ? 150 : 30);

    for (let i = 0; i < count; i++) {
      const link = links.nth(i);
      const href = await link.getAttribute("href").catch(() => null);
      if (!href) continue;

      const username = usernameFromUrl(href);
      if (!username) continue;
      if (sellerUsernameFromPath && username !== sellerUsernameFromPath) continue;

      const text = (await locatorText(link)).replace(/^@/, "");
      if (!sellerUsername) sellerUsername = username;
      if (isLikelySellerName(text, gigTitle)) {
        sellerName = text;
        sellerUsername = username;
        return { sellerName, sellerUsername };
      }
    }
  }

  const structuredName = await extractSellerNameFromStructuredData(page);
  if (structuredName && isLikelySellerName(structuredName, gigTitle)) {
    sellerName = structuredName;
  }

  if (!sellerName && sellerUsername) {
    sellerName = sellerUsername;
  }

  return { sellerName, sellerUsername };
}

function imageFromSrcset(value: string | null): string {
  if (!value) return "";
  const first = value.split(",").map((part) => part.trim().split(/\s+/)[0]).find(Boolean);
  return first || "";
}

function isUsableGigImage(src: string): boolean {
  if (!src) return false;
  return !/avatar|profile|icon|logo|flag|badge|svg/i.test(src);
}

async function extractMainImage(page: Page): Promise<string> {
  for (const selector of IMAGE_SELECTORS) {
    const images = page.locator(selector);
    const count = Math.min(await images.count().catch(() => 0), 30);

    for (let i = 0; i < count; i++) {
      const image = images.nth(i);
      const src =
        (await image.getAttribute("src").catch(() => null)) ||
        (await image.getAttribute("data-src").catch(() => null)) ||
        imageFromSrcset(await image.getAttribute("srcset").catch(() => null));
      const full = absolutizeUrl(src);
      if (isUsableGigImage(full)) return full;
    }
  }

  return "";
}

/** Navigate to gig page */
export async function openGigPage(page: Page, url: string): Promise<void> {
  const targetUrl = normalizeFiverrUrl(url);
  if (!targetUrl) {
    throw new Error(`Invalid Fiverr gig URL: ${url}`);
  }

  console.log(`[live] Opening gig: ${targetUrl}`);
  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 120_000 });
  await sleep(2000);
  await assertPageAccessible(page);
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.waitForSelector('h1, [data-testid*="gig-title" i], main', { timeout: 30_000 });

  console.log(`[live] Page loaded URL: ${page.url()}`);
  const finalUrl = normalizeFiverrUrl(page.url());
  if (!finalUrl) {
    throw new Error(`Fiverr did not load a gig page. Current URL: ${page.url()}`);
  }
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

  const finalGigUrl = normalizeFiverrUrl(page.url()) || normalizeFiverrUrl(gigUrl);
  if (!finalGigUrl) {
    throw new Error(`selectors failed: could not determine final Fiverr gig URL from ${gigUrl}`);
  }

  const titleFromDom = await firstText(page, TITLE_SELECTORS);
  const titleFromMeta = await firstMetaContent(page, [
    'meta[property="og:title"]',
    'meta[name="twitter:title"]',
    'meta[name="title"]',
  ]);
  const titleFromPage = cleanTitle(await page.title().catch(() => ""));
  const gigTitle = cleanTitle(titleFromDom || titleFromMeta || titleFromPage);

  console.log(`[live] Gig title found: ${gigTitle || "(missing)"}`);

  const sellerUsernameFromPath = usernameFromUrl(finalGigUrl);
  const { sellerName, sellerUsername } = await extractSeller(page, sellerUsernameFromPath, gigTitle);
  console.log(
    `[live] Seller found: name="${sellerName || "(missing)"}" username="${sellerUsername || "(missing)"}"`
  );

  if (!gigTitle || gigTitle.length < 3) {
    throw new Error("selectors failed: gig title not found");
  }
  if (!sellerUsername && !sellerName) {
    throw new Error("selectors failed: seller not found");
  }

  return {
    gigUrl: finalGigUrl,
    gigTitle,
    sellerName: sellerName || sellerUsername,
    sellerUsername,
    sellerDisplayName: sellerName || sellerUsername,
    mainGigImage: await extractMainImage(page),
  };
}
