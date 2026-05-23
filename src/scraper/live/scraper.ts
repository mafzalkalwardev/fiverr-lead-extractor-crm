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
import { extractReviews, extractReviewsWithStats } from "./reviews";
import { saveFailedGigArtifacts } from "./debug";
import { ScraperBlockedError, ScraperVerificationRequiredError } from "../types";

const MAX_RETRIES = 2;

async function withRetry<T>(label: string, fn: () => Promise<T>): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (err instanceof ScraperBlockedError || err instanceof ScraperVerificationRequiredError) {
        throw err;
      }
      console.warn(`[live] ${label} attempt ${attempt + 1} failed:`, err);
      if (attempt < MAX_RETRIES) await sleep(2000 * (attempt + 1));
    }
  }
  throw lastErr;
}

/** LIVE-ONLY Fiverr scraper. */
export class LiveFiverrScraper implements ScraperAdapter {
  async searchFiverrGigs(keyword: string, maxGigs: number): Promise<GigSearchResult[]> {
    const page = await newLivePage();
    return withRetry("search", () => runSearch(page, keyword, maxGigs));
  }

  async processGig(gigUrl: string, maxReviewsPerGig: number): Promise<GigExtractionResult> {
    const page = await newLivePage();
    return withRetry(`gig ${gigUrl}`, async () => {
      try {
        await openGigPage(page, gigUrl);
        const gig = await extractGigMetadata(page, gigUrl);

        if (!gig.gigTitle || gig.gigTitle.length < 3) {
          throw new Error(`selectors failed: missing gig title at ${gigUrl}`);
        }
        if (!gig.sellerName && !gig.sellerUsername) {
          throw new Error(`selectors failed: missing seller at ${gigUrl}`);
        }

        const reviewResult = await extractReviewsWithStats(page, maxReviewsPerGig);
        return {
          gig,
          reviews: reviewResult.reviews,
          reviewsChecked: reviewResult.reviewsChecked,
        };
      } catch (err) {
        if (err instanceof ScraperBlockedError || err instanceof ScraperVerificationRequiredError) {
          throw err;
        }

        const msg = err instanceof Error ? err.message : String(err);
        const artifacts = await saveFailedGigArtifacts(page).catch(() => null);
        const artifactMessage = artifacts
          ? ` screenshot=${artifacts.screenshotPath} html=${artifacts.htmlPath}`
          : "";
        console.warn(`[live] selectors failed for ${gigUrl}: ${msg}${artifactMessage}`);
        throw new Error(`selectors failed: ${msg}${artifactMessage}`);
      }
    });
  }

  async extractGigData(gigUrl: string): Promise<GigData> {
    return this.processGig(gigUrl, 0).then((r) => r.gig);
  }

  async extractReviews(gigUrl: string, maxReviews: number): Promise<ReviewData[]> {
    const page = await newLivePage();
    await openGigPage(page, gigUrl);
    return extractReviews(page, maxReviews);
  }

  async close(force = false): Promise<void> {
    await closeBrowser(force);
  }
}
