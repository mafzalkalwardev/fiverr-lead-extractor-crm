import { createScraper } from "./factory";
import type { GigData } from "./types";

/** Extract public gig metadata from a gig URL. */
export async function extractGigData(gigUrl: string): Promise<GigData> {
  const scraper = createScraper();
  return scraper.extractGigData(gigUrl);
}
