import { newLivePage } from "../live/browser";
import { extractGigMetadata } from "../live/gig";
import { extractReviews } from "../live/reviews";
import type { GigExtractionResult } from "../types";

/**
 * Parse reviews from user-uploaded Fiverr HTML (no live navigation).
 * Uses Playwright only to parse DOM — does not contact Fiverr servers.
 */
export async function parseGigFromHtml(
  html: string,
  sourceUrl: string
): Promise<GigExtractionResult> {
  if (!sourceUrl) {
    throw new Error("HTML import requires the original Fiverr gig URL");
  }

  const page = await newLivePage();
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  const gig = await extractGigMetadata(page, sourceUrl, { offlineHtml: true });
  if (!gig.gigTitle) {
    const t = await page.title().catch(() => "");
    if (t) gig.gigTitle = t.replace(/\s*\|\s*Fiverr.*$/i, "").trim();
  }
  const reviews = await extractReviews(page, 100, { offlineHtml: true });
  return { gig, reviews };
}
