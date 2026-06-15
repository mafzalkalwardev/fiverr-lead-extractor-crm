import { Types } from "mongoose";
import ScrapeJob, { type IScrapeJob } from "@/models/ScrapeJob";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";

export interface ContinuableJobSummary {
  _id: string;
  niche: string;
  status: string;
  createdAt: string;
  totalInQueue: number;
  processedCount: number;
  remainingCount: number;
  totalLeadsFound: number;
}

/** Gig URLs not yet processed in a job's saved queue. */
export function getUnprocessedQueueTail(job: {
  gigQueue?: string[];
  manualGigUrls?: string[];
  resumeIndex?: number;
}): string[] {
  const raw = job.gigQueue?.length ? job.gigQueue : job.manualGigUrls || [];
  const queue = raw
    .map((u) => normalizeFiverrUrl(u) || u)
    .filter(Boolean) as string[];
  const idx = Math.max(0, Math.min(job.resumeIndex ?? 0, queue.length));
  const tail = queue.slice(idx);
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const url of tail) {
    if (seen.has(url)) continue;
    seen.add(url);
    deduped.push(url);
  }
  return deduped;
}

function nicheRegex(niche: string): RegExp {
  const parts = niche.trim().split(/\s+/).map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^\\s*${parts.join("\\s+")}\\s*$`, "i");
}

const CONTINUABLE_STATUSES = [
  "completed",
  "lead_limit_reached",
  "stopped",
  "paused",
  "retry_required",
  "verification_required",
  "failed",
  "blocked",
];

export async function findContinuableJobs(
  userId: Types.ObjectId,
  niche: string,
  isAdmin = false
): Promise<ContinuableJobSummary[]> {
  const match = nicheRegex(niche);
  const query = {
    ...(isAdmin ? {} : { userId }),
    extractionMode: "live",
    status: { $in: CONTINUABLE_STATUSES },
    $or: [{ niche: match }, { keyword: match }, { category: match }],
  };

  const jobs = await ScrapeJob.find(query).sort({ createdAt: -1 }).limit(20).lean();

  return jobs
    .map((doc) => {
      const queue = (doc.gigQueue as string[]) || [];
      const resumeIndex = (doc.resumeIndex as number) ?? 0;
      const remaining = getUnprocessedQueueTail({
        gigQueue: queue,
        resumeIndex,
      });
      if (remaining.length === 0) return null;
      return {
        _id: String(doc._id),
        niche: (doc.niche as string) || "",
        status: doc.status as string,
        createdAt: (doc.createdAt as Date)?.toISOString?.() || "",
        totalInQueue: queue.length,
        processedCount: Math.min(resumeIndex, queue.length),
        remainingCount: remaining.length,
        totalLeadsFound: (doc.totalLeadsFound as number) ?? 0,
      };
    })
    .filter((j): j is ContinuableJobSummary => j !== null);
}

export async function loadContinuationQueue(
  userId: Types.ObjectId,
  sourceJobId: string,
  isAdmin = false
): Promise<{ tail: string[]; source: IScrapeJob }> {
  const query = isAdmin
    ? { _id: sourceJobId }
    : { _id: sourceJobId, userId };

  const source = await ScrapeJob.findOne(query);
  if (!source) {
    throw new Error("Source job not found");
  }
  if (source.extractionMode !== "live") {
    throw new Error("Only live search jobs can be continued");
  }

  const tail = getUnprocessedQueueTail(source);
  if (tail.length === 0) {
    throw new Error("Selected job has no unprocessed gigs remaining");
  }

  return { tail, source };
}
