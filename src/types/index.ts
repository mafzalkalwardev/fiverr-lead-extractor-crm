export interface User {
  _id: string;
  id?: string;
  name: string;
  email: string;
  role: "admin" | "user";
  status: "active" | "inactive";
  lastLogin?: string;
  createdAt?: string;
}

export type ExtractionMode = "live" | "manual_urls" | "html_import";

export interface ScrapeJob {
  _id: string;
  niche: string;
  extractionMode: ExtractionMode;
  targetCountries: string[];
  maxGigs: number;
  maxReviewsPerGig: number;
  maxTotalLeads: number;
  delaySeconds: number;
  status: string;
  currentGigLink: string;
  currentSeller: string;
  gigsScanned: number;
  reviewsChecked: number;
  usLeadsFound: number;
  canadaLeadsFound: number;
  totalLeadsFound: number;
  failedGigs: number;
  progressPercent: number;
  errors: string[];
  jobErrors?: string[];
  gigQueue?: string[];
  resumeIndex?: number;
  verificationMessage?: string;
  discoverySource?: string;
  urlsDiscovered?: number;
  activityLog?: string[];
  isLegacyDemo?: boolean;
  createdAt: string;
  updatedAt: string;
  userId?: string;
}

export interface Lead {
  _id: string;
  sellerName: string;
  gigLink: string;
  gigTitle: string;
  reviewerName: string;
  country: string;
  review: string;
  reviewRating: number;
  reviewDate?: string;
  reviewedImageLink: string;
  mainGigImage: string;
  serviceNiche: string;
  scrapedAt: string;
  jobId?: string;
}

export interface ActivityLogEntry {
  _id: string;
  userId?: { name: string; email: string };
  action: string;
  details: string;
  createdAt: string;
}

export interface DashboardStats {
  totalJobs: number;
  totalLeads: number;
  runningJobs: number;
  failedGigs: number;
  completedJobs: number;
  usLeads: number;
  canadaLeads: number;
}
