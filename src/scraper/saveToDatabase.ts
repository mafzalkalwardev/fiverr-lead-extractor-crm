import Gig from "@/models/Gig";
import Review from "@/models/Review";
import type { GigData, ReviewData } from "./types";
import { cleanReviewData } from "./cleanReviewData";
import { detectSentiment } from "./detectSentiment";
import type { Types } from "mongoose";

interface SaveGigInput {
  jobId: Types.ObjectId;
  keyword: string;
  category: string;
  gigData: GigData;
}

interface SaveReviewsInput {
  jobId: Types.ObjectId;
  gigId: Types.ObjectId;
  reviews: ReviewData[];
}

/** Persist gig + reviews to MongoDB. */
export async function saveToDatabase(
  gigInput: SaveGigInput,
  reviewsInput: SaveReviewsInput
): Promise<{ gigId: Types.ObjectId; reviewCount: number }> {
  const gig = await Gig.findOneAndUpdate(
    { jobId: gigInput.jobId, gigUrl: gigInput.gigData.gigUrl },
    {
      jobId: gigInput.jobId,
      keyword: gigInput.keyword,
      category: gigInput.category,
      ...gigInput.gigData,
      scrapedAt: new Date(),
    },
    { upsert: true, new: true }
  );

  const cleaned = cleanReviewData(reviewsInput.reviews);
  let reviewCount = 0;

  const targetGigId = reviewsInput.gigId.toString() === reviewsInput.jobId.toString()
    ? gig._id
    : reviewsInput.gigId;

  for (const r of cleaned) {
    await Review.create({
      jobId: reviewsInput.jobId,
      gigId: targetGigId,
      reviewerName: r.reviewerName,
      reviewerCountry: r.reviewerCountry,
      reviewRating: r.reviewRating,
      reviewText: r.reviewText,
      reviewDate: r.reviewDate,
      sellerResponse: r.sellerResponse,
      sentiment: detectSentiment(r.reviewText, r.reviewRating),
      scrapedAt: new Date(),
    });
    reviewCount++;
  }

  return { gigId: gig._id, reviewCount };
}
