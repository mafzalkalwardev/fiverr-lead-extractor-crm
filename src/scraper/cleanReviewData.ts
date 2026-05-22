import type { ReviewData } from "./types";

/** Normalize and dedupe review records before persistence. */
export function cleanReviewData(reviews: ReviewData[]): ReviewData[] {
  const seen = new Set<string>();
  return reviews
    .map((r) => ({
      ...r,
      reviewerName: r.reviewerName?.trim() || "Anonymous",
      reviewerCountry: r.reviewerCountry?.trim() || "Unknown",
      reviewText: r.reviewText?.trim().slice(0, 2000) || "",
      sellerResponse: r.sellerResponse?.trim() || "",
      reviewRating: Math.min(5, Math.max(1, Math.round(r.reviewRating) || 5)),
    }))
    .filter((r) => {
      const key = `${r.reviewerName}-${r.reviewText.slice(0, 50)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return r.reviewText.length > 0;
    });
}
