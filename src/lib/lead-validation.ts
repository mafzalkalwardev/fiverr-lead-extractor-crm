import type { GigData, ReviewData } from "@/scraper/types";

const BAD_SELLER = /^(fiverr|customer support|seller|reviews?)$/i;
const BAD_REVIEWER = /^(fiverr|seller|\d+(\.\d+)?)$/i;
const REVIEW_IMAGE =
  /delivery|attachments|t_delivery|t_smartwm|\/image\/upload\/|cloudinary|fiverr-res|fiverrstatic|review/i;

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

  const seller = (gig.sellerUsername || gig.sellerName || "").trim();
  if (!seller || seller.length < 2 || BAD_SELLER.test(seller)) return false;

  const title = (gig.gigTitle || "").trim();
  if (!title || title.length < 3) return false;

  const reviewer = (review.reviewerName || "").trim();
  if (!reviewer || reviewer.length < 2 || BAD_REVIEWER.test(reviewer)) return false;

  const text = (review.reviewText || "").trim();
  if (!text || text.length < 15) return false;

  if (!review.reviewerCountry?.trim()) return false;
  if (!Number.isFinite(review.reviewRating) || review.reviewRating <= 0 || review.reviewRating > 5) return false;

  const img = (review.reviewedImageLink || "").trim();
  const lower = img.toLowerCase();
  if (!img.startsWith("http") || /trophy|generic_asset|avatar|profile|\.gif/i.test(img)) {
    return false;
  }
  if (!REVIEW_IMAGE.test(img) && !(lower.includes("fiverr") && /\.(jpg|jpeg|png|webp)/i.test(img))) {
    return false;
  }

  return true;
}
