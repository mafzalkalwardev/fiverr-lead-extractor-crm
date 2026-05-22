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

/** Human verification required — user must complete in browser, then Retry */
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

export interface ScraperAdapter {
  searchFiverrGigs(keyword: string, maxGigs: number): Promise<GigSearchResult[]>;
  processGig(gigUrl: string, maxReviewsPerGig: number): Promise<GigExtractionResult>;
  extractGigData(gigUrl: string): Promise<GigData>;
  extractReviews(gigUrl: string, maxReviews: number): Promise<ReviewData[]>;
}
