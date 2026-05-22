import type { Page } from "playwright";
import type { GigSearchResult } from "../types";
import { sleep } from "@/lib/utils";
import { assertPageAccessible } from "./blocked";
import { normalizeFiverrUrl } from "../fiverr/urls";

const FIVERR_ORIGIN = "https://www.fiverr.com";

/** Build real Fiverr search URL */
export function buildSearchUrl(keyword: string): string {
  const q = encodeURIComponent(keyword.trim());
  return `${FIVERR_ORIGIN}/search/gigs?query=${q}&source=top-bar`;
}

/** Collect real gig card links from search results */
export async function collectGigCards(page: Page, maxGigs: number): Promise<GigSearchResult[]> {
  await page.waitForSelector("a[href]", { timeout: 30_000 }).catch(() => {});

  for (let i = 0; i < 5; i++) {
    await page.mouse.wheel(0, 1000);
    await sleep(600);
  }

  const selectors = [
    '[class*="gig-card" i] a[href]',
    'article a[href*="/"]',
    '[data-testid*="gig" i] a[href]',
    ".basic-gig-card a[href]",
    ".gig-wrapper a[href]",
  ];
  const hrefs: string[] = [];

  for (const selector of selectors) {
    const links = page.locator(selector);
    const count = Math.min(await links.count().catch(() => 0), 150);
    for (let i = 0; i < count; i++) {
      const href = await links.nth(i).getAttribute("href").catch(() => null);
      if (href) hrefs.push(href);
    }
  }

  if (hrefs.length < 3) {
    const fallbackLinks = page.locator('a[href*="/"]');
    const count = Math.min(await fallbackLinks.count().catch(() => 0), 250);
    for (let i = 0; i < count; i++) {
      const href = await fallbackLinks.nth(i).getAttribute("href").catch(() => null);
      if (href) hrefs.push(href);
    }
  }

  const seen = new Set<string>();
  const results: GigSearchResult[] = [];

  for (const href of hrefs) {
    const full = normalizeFiverrUrl(href);
    if (!full || seen.has(full)) continue;
    if (/\/users\//i.test(full) || /seller_dashboard|inbox|pro\/|\/cp\//i.test(full)) continue;
    seen.add(full);
    results.push({ gigUrl: full });
    if (results.length >= maxGigs) break;
  }

  console.log(`[live] Collected ${results.length} gig URLs from search`);
  return results;
}

export async function runSearch(page: Page, keyword: string, maxGigs: number): Promise<GigSearchResult[]> {
  const url = buildSearchUrl(keyword);
  console.log(`[live] Opening search: ${url}`);
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await sleep(2500);
  await assertPageAccessible(page);
  return collectGigCards(page, maxGigs);
}
