import type { Page } from "playwright";
import { sleep } from "@/lib/utils";
import { normalizeFiverrUrl } from "../fiverr/urls";

export async function discoverGigsViaBing(
  page: Page,
  niche: string,
  maxGigs: number
): Promise<string[]> {
  const query = `site:fiverr.com ${niche} "I will"`;
  const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}&count=30`;
  console.log(`[discovery] Bing: ${query}`);

  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await sleep(2500);

  const hrefs = await page.evaluate(() => {
    return Array.from(document.querySelectorAll("a[href]")).map(
      (a) => (a as HTMLAnchorElement).href
    );
  });

  const seen = new Set<string>();
  const results: string[] = [];

  for (const href of hrefs) {
    const full = normalizeFiverrUrl(href);
    if (!full || seen.has(full)) continue;
    if (full.includes("/search/") || full.includes("/users/")) continue;
    seen.add(full);
    results.push(full);
    if (results.length >= maxGigs) break;
  }

  console.log(`[discovery] Bing found ${results.length} URLs`);
  return results;
}
