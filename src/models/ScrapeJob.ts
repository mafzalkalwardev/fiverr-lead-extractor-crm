import mongoose, { Schema, Document, Model, Types } from "mongoose";
import type { ExtractionMode } from "@/lib/extraction-modes";

export type JobStatus =
  | "pending"
  | "running"
  | "discovering_gigs"
  | "extracting_reviews"
  | "verification_required"
  | "blocked"
  | "completed"
  | "failed"
  | "stopped";

export type DiscoverySource = "fiverr_search" | "search_engine" | "manual" | "cached_queue" | "";

export interface IScrapeJob extends Document {
  userId: Types.ObjectId;
  niche: string;
  extractionMode: ExtractionMode;
  targetCountries: string[];
  maxGigs: number;
  maxReviewsPerGig: number;
  maxTotalLeads: number;
  delaySeconds: number;
  status: JobStatus;
  currentGigLink: string;
  currentSeller: string;
  gigsScanned: number;
  reviewsChecked: number;
  usLeadsFound: number;
  canadaLeadsFound: number;
  totalLeadsFound: number;
  failedGigs: number;
  progressPercent: number;
  errorLog: string[];
  /** Queue of gig URLs to process (resume after verification) */
  gigQueue: string[];
  resumeIndex: number;
  manualGigUrls: string[];
  htmlFiles: { filename: string; gigUrl: string; storedPath: string }[];
  verificationMessage: string;
  discoverySource: DiscoverySource;
  urlsDiscovered: number;
  /** Live discovery: current Fiverr search results page being scraped */
  currentSearchPage?: number;
  discoveryPagesScanned?: number;
  discoveryPageLimit?: number;
  activityLog: string[];
  keyword?: string;
  category?: string;
  createdAt: Date;
  updatedAt: Date;
}

const ScrapeJobSchema = new Schema<IScrapeJob>(
  {
    userId: { type: Schema.Types.ObjectId, ref: "User", required: true, index: true },
    niche: { type: String, required: true, trim: true },
    extractionMode: {
      type: String,
      enum: ["live", "manual_urls", "html_import"],
      default: "live",
    },
    targetCountries: { type: [String], default: ["United States", "Canada"] },
    maxGigs: { type: Number, default: 0 },
    maxReviewsPerGig: { type: Number, default: 0 },
    maxTotalLeads: { type: Number, default: 100 },
    delaySeconds: { type: Number, default: 1 },
    status: {
      type: String,
      enum: [
        "pending",
        "running",
        "discovering_gigs",
        "extracting_reviews",
        "verification_required",
        "blocked",
        "completed",
        "failed",
        "stopped",
      ],
      default: "pending",
    },
    currentGigLink: { type: String, default: "" },
    currentSeller: { type: String, default: "" },
    gigsScanned: { type: Number, default: 0 },
    reviewsChecked: { type: Number, default: 0 },
    usLeadsFound: { type: Number, default: 0 },
    canadaLeadsFound: { type: Number, default: 0 },
    totalLeadsFound: { type: Number, default: 0 },
    failedGigs: { type: Number, default: 0 },
    progressPercent: { type: Number, default: 0 },
    errorLog: { type: [String], default: [] },
    gigQueue: { type: [String], default: [] },
    resumeIndex: { type: Number, default: 0 },
    manualGigUrls: { type: [String], default: [] },
    htmlFiles: {
      type: [
        {
          filename: String,
          gigUrl: String,
          storedPath: String,
        },
      ],
      default: [],
    },
    verificationMessage: { type: String, default: "" },
    discoverySource: { type: String, default: "" },
    urlsDiscovered: { type: Number, default: 0 },
    currentSearchPage: { type: Number, default: 0 },
    discoveryPagesScanned: { type: Number, default: 0 },
    discoveryPageLimit: { type: Number, default: 0 },
    activityLog: { type: [String], default: [] },
    keyword: { type: String, required: false },
    category: { type: String, required: false },
  },
  { timestamps: true }
);

ScrapeJobSchema.pre("validate", function (next) {
  const doc = this as IScrapeJob;
  if (!doc.niche?.trim()) {
    if (doc.keyword?.trim()) doc.niche = doc.keyword.trim();
    else if (doc.category?.trim()) doc.niche = doc.category.trim();
  }
  next();
});

if (mongoose.models.ScrapeJob) {
  delete mongoose.models.ScrapeJob;
}

const ScrapeJob: Model<IScrapeJob> = mongoose.model<IScrapeJob>("ScrapeJob", ScrapeJobSchema);

export default ScrapeJob;
