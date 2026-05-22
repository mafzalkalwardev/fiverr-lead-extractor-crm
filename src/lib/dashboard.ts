import ScrapeJob from "@/models/ScrapeJob";
import Lead from "@/models/Lead";
import { isLegacyDemoJob } from "@/lib/extraction-modes";
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
  const jobQuery = isAdmin ? { isLegacyDemo: { $ne: true } } : { userId, isLegacyDemo: { $ne: true } };
  const jobs = await ScrapeJob.find(jobQuery).lean();

  const leadQuery = isAdmin
    ? { reviewerName: { $not: /\[DEMO\]/i }, gigLink: { $not: /demo_seller|demo\.ftsolutions/i } }
    : {
        userId,
        reviewerName: { $not: /\[DEMO\]/i },
        gigLink: { $not: /demo_seller|demo\.ftsolutions/i },
      };
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
    progressPercent: (doc.progressPercent as number) ?? 0,
    gigQueue: (doc.gigQueue as string[]) || [],
    resumeIndex: (doc.resumeIndex as number) ?? 0,
    verificationMessage: (doc.verificationMessage as string) || "",
    discoverySource: (doc.discoverySource as string) || "",
    urlsDiscovered: (doc.urlsDiscovered as number) ?? 0,
    activityLog: (doc.activityLog as string[]) || [],
    isLegacyDemo:
      (doc.isLegacyDemo as boolean) ||
      isLegacyDemoJob({
        niche: doc.niche as string,
        extractionMode: doc.extractionMode as string,
      }),
    errors,
    jobErrors: errors,
  };

  return job;
}
