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

  const hrefs = await page.evaluate(() => {
    const selectors = [
      '[class*="gig-card"] a[href]',
      '[class*="GigCard"] a[href]',
      'article a[href*="/"]',
      '[data-testid*="gig"] a[href]',
      ".basic-gig-card a[href]",
      ".gig-wrapper a[href]",
    ];
    const found: string[] = [];
    for (const sel of selectors) {
      document.querySelectorAll(sel).forEach((a) => {
        const href = (a as HTMLAnchorElement).href || (a as HTMLAnchorElement).getAttribute("href");
        if (href) found.push(href);
      });
    }
    if (found.length < 3) {
      document.querySelectorAll('a[href*="/"]').forEach((a) => {
        const href = (a as HTMLAnchorElement).href || (a as HTMLAnchorElement).getAttribute("href");
        if (href) found.push(href);
      });
    }
    return found;
  });

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
