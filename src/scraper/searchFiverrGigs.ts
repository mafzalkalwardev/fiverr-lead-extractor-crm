import { createScraper } from "./factory";

/** Search Fiverr for gig URLs by niche keyword */
export async function searchFiverrGigs(keyword: string, maxGigs: number) {
  const scraper = createScraper();
  return scraper.searchFiverrGigs(keyword, maxGigs);
}
