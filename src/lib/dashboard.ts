import ScrapeJob from "@/models/ScrapeJob";
import Lead from "@/models/Lead";
import type { Types } from "mongoose";

export interface DashboardStats {
  totalJobs: number;
  totalLeads: number;
  runningJobs: number;
  failedGigs: number;
  completedJobs: number;
  usLeads: number;
  canadaLeads: number;
}

export async function getDashboardStats(
  userId: Types.ObjectId,
  isAdmin = false
): Promise<DashboardStats> {
  const jobQuery = isAdmin ? {} : { userId };
  const jobs = await ScrapeJob.find(jobQuery).lean();

  const leadQuery = isAdmin ? {} : { userId };
  const [totalLeads, usLeads, canadaLeads] = await Promise.all([
    Lead.countDocuments(leadQuery),
    Lead.countDocuments({ ...leadQuery, country: "United States" }),
    Lead.countDocuments({ ...leadQuery, country: "Canada" }),
  ]);

  return {
    totalJobs: jobs.length,
    totalLeads,
    runningJobs: jobs.filter((j) => j.status === "running").length,
    failedGigs: jobs.reduce((s, j) => s + (j.failedGigs ?? 0), 0),
    completedJobs: jobs.filter((j) => j.status === "completed").length,
    usLeads,
    canadaLeads,
  };
}

export function normalizeJob(doc: Record<string, unknown>) {
  const errors =
    (doc.errorLog as string[]) ||
    (doc.errors as string[]) ||
    (doc.jobErrors as string[]) ||
    [];

  const job = {
    ...doc,
    niche: (doc.niche as string) || (doc.keyword as string) || (doc.category as string) || "",
    extractionMode: (doc.extractionMode as string) || "live",
    targetCountries: (doc.targetCountries as string[]) || ["United States", "Canada"],
    gigsScanned: (doc.gigsScanned as number) ?? 0,
    reviewsChecked: (doc.reviewsChecked as number) ?? 0,
    usLeadsFound: (doc.usLeadsFound as number) ?? 0,
    canadaLeadsFound: (doc.canadaLeadsFound as number) ?? 0,
    totalLeadsFound: (doc.totalLeadsFound as number) ?? 0,
    failedGigs: (doc.failedGigs as number) ?? 0,
    currentGigLink: (doc.currentGigLink as string) || "",
    currentSeller: (doc.currentSeller as string) || "",
    currentSellerUsername: (doc.currentSellerUsername as string) || "",
    currentGigNumber: (doc.currentGigNumber as number) ?? 0,
    totalGigs: (doc.totalGigs as number) ?? ((doc.gigQueue as string[]) || []).length,
    currentReviewPage: (doc.currentReviewPage as number) ?? 0,
    totalReviewsParsed: (doc.totalReviewsParsed as number) ?? (doc.reviewsChecked as number) ?? 0,
    progressPercent: (doc.progressPercent as number) ?? 0,
    gigQueue: (doc.gigQueue as string[]) || [],
    resumeIndex: (doc.resumeIndex as number) ?? 0,
    verificationMessage: (doc.verificationMessage as string) || "",
    discoverySource: (doc.discoverySource as string) || "",
    urlsDiscovered: (doc.urlsDiscovered as number) ?? 0,
    activityLog: (doc.activityLog as string[]) || [],
    errors,
    jobErrors: errors,
  };

  return job;
}
