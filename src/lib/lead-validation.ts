import type { GigData, ReviewData } from "@/scraper/types";

function isFiverrUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && (url.hostname === "fiverr.com" || url.hostname.endsWith(".fiverr.com"));
  } catch {
    return false;
  }
}

/** Strict validation: only complete Fiverr-extracted leads may be saved. */
export function isValidRealLead(gig: GigData, review: ReviewData): boolean {
  if (!isFiverrUrl(gig.gigUrl)) return false;

  const seller = (gig.sellerName || gig.sellerUsername || "").trim();
  if (!seller || seller.length < 2) return false;

  const title = (gig.gigTitle || "").trim();
  if (!title || title.length < 3) return false;

  const reviewer = (review.reviewerName || "").trim();
  if (!reviewer || reviewer.length < 2) return false;

  const text = (review.reviewText || "").trim();
  if (!text || text.length < 10) return false;

  if (!review.reviewerCountry?.trim()) return false;
  if (!Number.isFinite(review.reviewRating) || review.reviewRating <= 0 || review.reviewRating > 5) return false;

  return true;
}
