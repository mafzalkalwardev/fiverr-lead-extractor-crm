import mongoose, { Schema, Document, Model, Types } from "mongoose";

export interface ILead extends Document {
  jobId: Types.ObjectId;
  userId: Types.ObjectId;
  sellerName: string;
  sellerUsername: string;
  gigLink: string;
  gigTitle: string;
  reviewerName: string;
  country: string;
  review: string;
  reviewRating: number;
  reviewDate?: Date;
  reviewedImageLink: string;
  mainGigImage: string;
  serviceNiche: string;
  scrapedAt: Date;
  dedupeKey: string;
}

const LeadSchema = new Schema<ILead>(
  {
    jobId: { type: Schema.Types.ObjectId, ref: "ScrapeJob", required: true, index: true },
    userId: { type: Schema.Types.ObjectId, ref: "User", required: true, index: true },
    sellerName: { type: String, default: "" },
    sellerUsername: { type: String, default: "" },
    gigLink: { type: String, required: true },
    gigTitle: { type: String, default: "" },
    reviewerName: { type: String, default: "" },
    country: { type: String, default: "" },
    review: { type: String, default: "" },
    reviewRating: { type: Number, default: 0 },
    reviewDate: { type: Date },
    reviewedImageLink: { type: String, default: "" },
    mainGigImage: { type: String, default: "" },
    serviceNiche: { type: String, default: "" },
    scrapedAt: { type: Date, default: Date.now },
    dedupeKey: { type: String, required: true, index: true },
  },
  { timestamps: false }
);

LeadSchema.index({ jobId: 1, dedupeKey: 1 }, { unique: true });

const Lead: Model<ILead> =
  mongoose.models.Lead || mongoose.model<ILead>("Lead", LeadSchema);

export default Lead;
