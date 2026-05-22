import mongoose, { Schema, Document, Model, Types } from "mongoose";

export interface IFailedUrl extends Document {
  jobId: Types.ObjectId;
  url: string;
  reason: string;
  retryCount: number;
}

const FailedUrlSchema = new Schema<IFailedUrl>(
  {
    jobId: { type: Schema.Types.ObjectId, ref: "ScrapeJob", required: true, index: true },
    url: { type: String, required: true },
    reason: { type: String, default: "" },
    retryCount: { type: Number, default: 0 },
  },
  { timestamps: true }
);

const FailedUrl: Model<IFailedUrl> =
  mongoose.models.FailedUrl || mongoose.model<IFailedUrl>("FailedUrl", FailedUrlSchema);

export default FailedUrl;
