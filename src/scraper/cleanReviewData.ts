import type { ReviewData } from "./types";

/** Normalize and dedupe review records before persistence. */
export function cleanReviewData(reviews: ReviewData[]): ReviewData[] {
  const seen = new Set<string>();
  return reviews
    .map((r) => {
      const reviewRating = Number.isFinite(r.reviewRating)
        ? Math.min(5, Math.max(0, Math.round(r.reviewRating)))
        : 0;

      return {
        ...r,
        reviewerName: r.reviewerName?.trim() || "",
        reviewerCountry: r.reviewerCountry?.trim() || "",
        reviewText: r.reviewText?.trim().slice(0, 2000) || "",
        sellerResponse: r.sellerResponse?.trim() || "",
        reviewRating,
      };
    })
    .filter((r) => {
      const key = `${r.reviewerName}-${r.reviewText.slice(0, 50)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return r.reviewerName.length > 1 && r.reviewerCountry.length > 0 && r.reviewText.length >= 10;
    });
}
