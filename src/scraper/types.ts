/** Shared scraper interfaces */

export interface GigSearchResult {
  gigUrl: string;
  gigTitle?: string;
}

export interface GigData {
  gigUrl: string;
  gigTitle: string;
  sellerName: string;
  sellerUsername: string;
  sellerDisplayName?: string;
  mainGigImage: string;
  sellerLevel?: string;
  sellerRating?: number;
  totalReviews?: number;
  startingPrice?: string;
  deliveryTime?: string;
}

export interface ReviewData {
  reviewerName: string;
  reviewerCountry: string;
  reviewRating: number;
  reviewText: string;
  reviewDate?: Date;
  reviewedImageLink: string;
  sellerResponse?: string;
}

/** Hard block — not user-solvable via Retry */
export class ScraperBlockedError extends Error {
  constructor(message = "Access blocked by Fiverr.") {
    super(message);
    this.name = "ScraperBlockedError";
  }
}

/** Human verification required — user must complete it in the opened browser. */
export class ScraperVerificationRequiredError extends Error {
  constructor(message = "Fiverr human verification required.") {
    super(message);
    this.name = "ScraperVerificationRequiredError";
  }
}

export interface GigExtractionResult {
  gig: GigData;
  reviews: ReviewData[];
  reviewsChecked?: number;
}

export interface ReviewExtractionOptions {
  offlineHtml?: boolean;
  reviewImageMode?: "with_image" | "without_image";
}

export interface ScraperAdapter {
  searchFiverrGigs(keyword: string, maxGigs: number): Promise<GigSearchResult[]>;
  processGig(
    gigUrl: string,
    maxReviewsPerGig: number,
    options?: ReviewExtractionOptions
  ): Promise<GigExtractionResult>;
  extractGigData(gigUrl: string): Promise<GigData>;
  extractReviews(
    gigUrl: string,
    maxReviews: number,
    options?: ReviewExtractionOptions
  ): Promise<ReviewData[]>;
}
