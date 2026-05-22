import type { ScraperAdapter } from "./types";
import { LiveFiverrScraper } from "./live/scraper";
import { assertLiveScraperMode } from "@/lib/scraper-mode";

let liveInstance: LiveFiverrScraper | null = null;

/**
 * LIVE-ONLY scraper factory.
 * SCRAPER_MODE must be "playwright". Demo/mock scrapers are disabled.
 */
export function createScraper(): ScraperAdapter {
  assertLiveScraperMode();
  if (!liveInstance) liveInstance = new LiveFiverrScraper();
  return liveInstance;
}

export async function closeScraper(force = false): Promise<void> {
  if (liveInstance) {
    await liveInstance.close(force);
    if (force) liveInstance = null;
  }
}
