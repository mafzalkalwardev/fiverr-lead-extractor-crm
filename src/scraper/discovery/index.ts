import { newLivePage } from "../live/browser";
import { runSearch } from "../live/search";
import { discoverGigsViaHttpSearch } from "./httpSearch";
import { discoverGigsViaSearx } from "./searx";
import {
  ScraperBlockedError,
  ScraperVerificationRequiredError,
} from "../types";

export type DiscoverySource = "fiverr_search" | "search_engine" | "manual" | "cached_queue";

export interface DiscoveryResult {
  gigUrls: string[];
  source: DiscoverySource;
  blockedOnFiverr: boolean;
}

export async function discoverGigUrls(
  niche: string,
  maxGigs: number,
  existingQueue: string[] = []
): Promise<DiscoveryResult> {
  if (existingQueue.length > 0) {
    return { gigUrls: existingQueue, source: "cached_queue", blockedOnFiverr: false };
  }

  // 1) SearX JSON (reliable, no Fiverr hit)
  const searxUrls = await discoverGigsViaSearx(niche, maxGigs);
  if (searxUrls.length > 0) {
    return { gigUrls: searxUrls, source: "search_engine", blockedOnFiverr: false };
  }

  // 2) HTTP HTML search fallback
  const httpUrls = await discoverGigsViaHttpSearch(niche, maxGigs);
  if (httpUrls.length > 0) {
    return { gigUrls: httpUrls, source: "search_engine", blockedOnFiverr: false };
  }

  // 2) Fiverr search via Playwright
  const fiverrPage = await newLivePage();
  try {
    const results = await runSearch(fiverrPage, niche, maxGigs);
    const urls = results.map((r) => r.gigUrl).filter(Boolean);
    if (urls.length > 0) {
      return { gigUrls: urls, source: "fiverr_search", blockedOnFiverr: false };
    }
  } catch (err) {
    if (err instanceof ScraperVerificationRequiredError) {
      throw err;
    }
    if (!(err instanceof ScraperBlockedError)) {
      console.warn("[discovery] Fiverr search error:", err);
    }
  } finally {
    await fiverrPage.close();
  }

  return { gigUrls: [], source: "search_engine", blockedOnFiverr: true };
}
