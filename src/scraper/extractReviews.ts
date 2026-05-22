import { createScraper } from "./factory";
/** Extract public reviews from a gig page. */
export async function extractReviews(gigUrl: string, maxReviews: number) {
  const scraper = createScraper();
  return scraper.extractReviews(gigUrl, maxReviews);
}
