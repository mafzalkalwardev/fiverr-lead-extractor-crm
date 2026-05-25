import mongoose, { Schema, Document, Model, Types } from "mongoose";

export type GigStatus = "pending" | "processing" | "completed" | "failed" | "skipped";

export interface IGigProgress extends Document {
  jobId: Types.ObjectId;
  url: string;
  index: number;
  status: GigStatus;
  retryCount: number;
  lastError: string;
  reviewsParsed: number;
  leadsFound: number;
  startedAt?: Date;
  completedAt?: Date;
}

const GigProgressSchema = new Schema<IGigProgress>(
  {
    jobId: { type: Schema.Types.ObjectId, ref: "ScrapeJob", required: true },
    url: { type: String, required: true },
    index: { type: Number, required: true },
    status: {
      type: String,
      enum: ["pending", "processing", "completed", "failed", "skipped"],
      default: "pending",
    },
    retryCount: { type: Number, default: 0 },
    lastError: { type: String, default: "" },
    reviewsParsed: { type: Number, default: 0 },
    leadsFound: { type: Number, default: 0 },
    startedAt: { type: Date },
    completedAt: { type: Date },
  },
  { timestamps: true }
);

GigProgressSchema.index({ jobId: 1, index: 1 }, { unique: true });
GigProgressSchema.index({ jobId: 1, status: 1 });

if (mongoose.models.GigProgress) {
  delete mongoose.models.GigProgress;
}

const GigProgress: Model<IGigProgress> = mongoose.model<IGigProgress>(
  "GigProgress",
  GigProgressSchema
);

export default GigProgress;
