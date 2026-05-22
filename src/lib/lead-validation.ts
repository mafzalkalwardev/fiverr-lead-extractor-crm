import { isDemoPlaceholderUrl } from "@/scraper/fiverr/urls";
import type { GigData, ReviewData } from "@/scraper/types";

const FAKE_NAME_PATTERNS = [
  /^\[?demo\]?/i,
  /^demo\s/i,
  /demo_seller/i,
  /^fake/i,
  /^test\s*user/i,
  /^buyer$/i,
  /^user\d*$/i,
  /^placeholder/i,
];

const FAKE_TEXT_PATTERNS = [/\[DEMO\]/i, /demo\.ftsolutions/i, /lorem ipsum/i];

/** Strict validation — only real Fiverr-extracted data may be saved */
export function isValidRealLead(gig: GigData, review: ReviewData): boolean {
  if (!gig.gigUrl?.includes("fiverr.com")) return false;
  if (isDemoPlaceholderUrl(gig.gigUrl) || isDemoPlaceholderUrl(gig.mainGigImage)) return false;
  if (isDemoPlaceholderUrl(review.reviewedImageLink)) return false;
  if (/\/demo_seller_|\/demo\//i.test(gig.gigUrl)) return false;

  const seller = (gig.sellerName || gig.sellerUsername || "").trim();
  if (!seller || seller.length < 2) return false;
  if (FAKE_NAME_PATTERNS.some((p) => p.test(seller))) return false;

  const title = (gig.gigTitle || "").trim();
  if (!title || title.length < 3) return false;
  if (FAKE_TEXT_PATTERNS.some((p) => p.test(title))) return false;

  const reviewer = (review.reviewerName || "").trim();
  if (!reviewer || reviewer.length < 2) return false;
  if (FAKE_NAME_PATTERNS.some((p) => p.test(reviewer))) return false;

  const text = (review.reviewText || "").trim();
  if (!text || text.length < 10) return false;
  if (FAKE_TEXT_PATTERNS.some((p) => p.test(text))) return false;

  if (!review.reviewerCountry?.trim()) return false;

  return true;
}
