import { sleep } from "@/lib/utils";
import type {
  GigData,
  GigExtractionResult,
  GigSearchResult,
  ReviewData,
  ScraperAdapter,
} from "../types";
import { closeBrowser, newLivePage } from "./browser";
import { runSearch } from "./search";
import { openGigPage, extractGigMetadata } from "./gig";
import { extractReviews } from "./reviews";
import { ScraperBlockedError } from "../types";

const MAX_RETRIES = 2;

async function withRetry<T>(label: string, fn: () => Promise<T>): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (err instanceof ScraperBlockedError) throw err;
      console.warn(`[live] ${label} attempt ${attempt + 1} failed:`, err);
      if (attempt < MAX_RETRIES) await sleep(2000 * (attempt + 1));
    }
  }
  throw lastErr;
}

/**
 * LIVE-ONLY Fiverr scraper.
 * Never generates, seeds, or falls back to fake data.
 */
export class LiveFiverrScraper implements ScraperAdapter {
  async searchFiverrGigs(keyword: string, maxGigs: number): Promise<GigSearchResult[]> {
    const page = await newLivePage();
    try {
      return await withRetry("search", () => runSearch(page, keyword, maxGigs));
    } finally {
      await page.close();
    }
  }

  async processGig(gigUrl: string, maxReviewsPerGig: number): Promise<GigExtractionResult> {
    const page = await newLivePage();
    try {
      return await withRetry(`gig ${gigUrl}`, async () => {
        await openGigPage(page, gigUrl);
        const gig = await extractGigMetadata(page, gigUrl);

        if (!gig.gigTitle || gig.gigTitle.length < 3) {
          throw new Error(`Missing gig title at ${gigUrl}`);
        }
        if (!gig.sellerName && !gig.sellerUsername) {
          throw new Error(`Missing seller at ${gigUrl}`);
        }

        const reviews = maxReviewsPerGig > 0 ? await extractReviews(page, maxReviewsPerGig) : [];
        return { gig, reviews };
      });
    } finally {
      await page.close();
    }
  }

  async extractGigData(gigUrl: string): Promise<GigData> {
    return this.processGig(gigUrl, 0).then((r) => r.gig);
  }

  async extractReviews(gigUrl: string, maxReviews: number): Promise<ReviewData[]> {
    const page = await newLivePage();
    try {
      await openGigPage(page, gigUrl);
      return extractReviews(page, maxReviews);
    } finally {
      await page.close();
    }
  }

  async close(force = false): Promise<void> {
    await closeBrowser(force);
  }
}
