import { sleep } from "@/lib/utils";
import type {
  GigData,
  GigExtractionResult,
  GigSearchResult,
  ReviewExtractionOptions,
  ReviewData,
  ScraperAdapter,
} from "../types";
import { closeBrowser, newLivePage } from "./browser";
import { runSearch } from "./search";
import { openGigPage, extractGigMetadata } from "./gig";
import { extractReviews, extractReviewsWithStats } from "./reviews";
import { saveFailedGigArtifacts } from "./debug";
import { ScraperBlockedError, ScraperVerificationRequiredError } from "../types";

/** Errors that are NOT worth retrying — throw immediately */
function isTerminalError(err: unknown): boolean {
  return (
    err instanceof ScraperBlockedError ||
    err instanceof ScraperVerificationRequiredError
  );
}

/**
 * Detect network / connectivity timeouts.
 * These get more retries and longer waits than selector failures.
 */
export function isNetworkTimeoutError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /timeout \d+ms exceeded|navigation timeout|net::err_|etimedout|econnrefused|econnreset|socket hang up|network change|internet disconnected|err_connection/i.test(
    msg
  );
}

const NETWORK_RETRIES = 3;
const NETWORK_WAIT_MS = 10_000;
const SELECTOR_RETRIES = 2;
const SELECTOR_WAIT_MS = 2_000;

/**
 * Retry wrapper.
 * Network timeouts: 3 retries × 10 s
 * Other failures:   2 retries × 2 s / 4 s (existing behaviour)
 * Blocked/verification: throw immediately (no retry)
 */
async function withRetry<T>(label: string, fn: () => Promise<T>): Promise<T> {
  let lastErr: unknown;

  // First attempt
  try {
    return await fn();
  } catch (err) {
    if (isTerminalError(err)) throw err;
    lastErr = err;
  }

  const maxRetries = isNetworkTimeoutError(lastErr)
    ? NETWORK_RETRIES
    : SELECTOR_RETRIES;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const waitMs = isNetworkTimeoutError(lastErr)
      ? NETWORK_WAIT_MS
      : SELECTOR_WAIT_MS * attempt;

    console.warn(
      `[live] ${label} retry attempt ${attempt}/${maxRetries} (${isNetworkTimeoutError(lastErr) ? "network" : "selector"}) — waiting ${waitMs / 1000}s`
    );
    await sleep(waitMs);

    try {
      return await fn();
    } catch (err) {
      if (isTerminalError(err)) throw err;
      lastErr = err;
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

  async processGig(
    gigUrl: string,
    maxReviewsPerGig: number,
    options?: ReviewExtractionOptions
  ): Promise<GigExtractionResult> {
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

        const reviewResult = await extractReviewsWithStats(page, maxReviewsPerGig, options);
        return {
          gig,
          reviews: reviewResult.reviews,
          reviewsChecked: reviewResult.reviewsChecked,
        };
      } catch (err) {
        if (isTerminalError(err)) throw err;

        const msg = err instanceof Error ? err.message : String(err);
        const artifacts = await saveFailedGigArtifacts(page).catch(() => null);
        const artifactMessage = artifacts
          ? ` screenshot=${artifacts.screenshotPath} html=${artifacts.htmlPath}`
          : "";

        if (isNetworkTimeoutError(err)) {
          console.warn(`[live] network timeout for ${gigUrl}: ${msg}`);
          throw err; // re-throw so withRetry's network path picks it up
        }

        console.warn(`[live] selectors failed for ${gigUrl}: ${msg}${artifactMessage}`);
        throw new Error(`selectors failed: ${msg}${artifactMessage}`);
      }
    });
  }

  async extractGigData(gigUrl: string): Promise<GigData> {
    return this.processGig(gigUrl, 0).then((r) => r.gig);
  }

  async extractReviews(
    gigUrl: string,
    maxReviews: number,
    options?: ReviewExtractionOptions
  ): Promise<ReviewData[]> {
    const page = await newLivePage();
    await openGigPage(page, gigUrl);
    return extractReviews(page, maxReviews, options);
  }

  async close(force = false): Promise<void> {
    await closeBrowser(force);
  }
}
