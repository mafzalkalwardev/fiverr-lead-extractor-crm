import mongoose, { Schema, Document, Model, Types } from "mongoose";

export interface IGig extends Document {
  jobId: Types.ObjectId;
  keyword: string;
  category: string;
  gigUrl: string;
  gigTitle: string;
  sellerUsername: string;
  sellerLevel: string;
  sellerRating: number;
  totalReviews: number;
  startingPrice: string;
  deliveryTime: string;
  scrapedAt: Date;
}

const GigSchema = new Schema<IGig>(
  {
    jobId: { type: Schema.Types.ObjectId, ref: "ScrapeJob", required: true, index: true },
    keyword: { type: String, default: "" },
    category: { type: String, default: "" },
    gigUrl: { type: String, required: true },
    gigTitle: { type: String, default: "" },
    sellerUsername: { type: String, default: "" },
    sellerLevel: { type: String, default: "" },
    sellerRating: { type: Number, default: 0 },
    totalReviews: { type: Number, default: 0 },
    startingPrice: { type: String, default: "" },
    deliveryTime: { type: String, default: "" },
    scrapedAt: { type: Date, default: Date.now },
  },
  { timestamps: false }
);

GigSchema.index({ jobId: 1, gigUrl: 1 }, { unique: true });

const Gig: Model<IGig> = mongoose.models.Gig || mongoose.model<IGig>("Gig", GigSchema);

export default Gig;
