import mongoose, { Schema, Document, Model, Types } from "mongoose";

export type Sentiment = "positive" | "neutral" | "negative";

export interface IReview extends Document {
  jobId: Types.ObjectId;
  gigId: Types.ObjectId;
  reviewerName: string;
  reviewerCountry: string;
  reviewRating: number;
  reviewText: string;
  reviewDate: Date;
  sellerResponse: string;
  sentiment: Sentiment;
  scrapedAt: Date;
}

const ReviewSchema = new Schema<IReview>(
  {
    jobId: { type: Schema.Types.ObjectId, ref: "ScrapeJob", required: true, index: true },
    gigId: { type: Schema.Types.ObjectId, ref: "Gig", required: true, index: true },
    reviewerName: { type: String, default: "" },
    reviewerCountry: { type: String, default: "" },
    reviewRating: { type: Number, default: 0 },
    reviewText: { type: String, default: "" },
    reviewDate: { type: Date },
    sellerResponse: { type: String, default: "" },
    sentiment: {
      type: String,
      enum: ["positive", "neutral", "negative"],
      default: "neutral",
    },
    scrapedAt: { type: Date, default: Date.now },
  },
  { timestamps: false }
);

const Review: Model<IReview> =
  mongoose.models.Review || mongoose.model<IReview>("Review", ReviewSchema);

export default Review;
