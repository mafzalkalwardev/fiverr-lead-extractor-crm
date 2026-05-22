import type { Page } from "playwright";
import { sleep } from "@/lib/utils";
import { normalizeFiverrUrl } from "../fiverr/urls";

/** Discover public Fiverr gig URLs via search engine (not Fiverr search page) */
export async function discoverGigsViaSearchEngine(
  page: Page,
  niche: string,
  maxGigs: number
): Promise<string[]> {
  const query = `site:fiverr.com "${niche}" "I will"`;
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  console.log(`[discovery] Search engine query: ${query}`);

  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await sleep(2500);

  const hrefs = await page.evaluate(() => {
    const links: string[] = [];
    document.querySelectorAll("a.result__a, a[href]").forEach((a) => {
      const href = (a as HTMLAnchorElement).href || a.getAttribute("href") || "";
      if (href) links.push(href);
    });
    return links;
  });

  const seen = new Set<string>();
  const results: string[] = [];

  for (const href of hrefs) {
    let raw = href;
    if (href.includes("uddg=")) {
      try {
        const u = new URL(href);
        raw = decodeURIComponent(u.searchParams.get("uddg") || href);
      } catch {
        /* keep href */
      }
    }
    const full = normalizeFiverrUrl(raw);
    if (!full || seen.has(full)) continue;
    if (!/\/[a-z0-9_-]+\/[a-z0-9_-]+/i.test(full)) continue;
    seen.add(full);
    results.push(full);
    if (results.length >= maxGigs) break;
  }

  console.log(`[discovery] Search engine found ${results.length} Fiverr URLs`);
  return results;
}
