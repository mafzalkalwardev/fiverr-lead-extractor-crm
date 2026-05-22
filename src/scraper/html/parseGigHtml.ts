import { newLivePage } from "../live/browser";
import { extractGigMetadata } from "../live/gig";
import { extractReviews } from "../live/reviews";
import type { GigExtractionResult } from "../types";
import { absolutizeUrl } from "../fiverr/urls";

/**
 * Parse reviews from user-uploaded Fiverr HTML (no live navigation).
 * Uses Playwright only to parse DOM — does not contact Fiverr servers.
 */
export async function parseGigFromHtml(
  html: string,
  sourceUrl: string
): Promise<GigExtractionResult> {
  const page = await newLivePage();
  try {
    await page.setContent(html, { waitUntil: "domcontentloaded" });
    const gigUrl = absolutizeUrl(sourceUrl) || sourceUrl;
    const gig = await extractGigMetadata(page, gigUrl, { offlineHtml: true });
    if (!gig.gigTitle) {
      const t = await page.title().catch(() => "");
      if (t) gig.gigTitle = t.replace(/\s*\|\s*Fiverr.*$/i, "").trim();
    }
    const reviews = await extractReviews(page, 100, { offlineHtml: true });
    return { gig, reviews };
  } finally {
    await page.close();
  }
}
