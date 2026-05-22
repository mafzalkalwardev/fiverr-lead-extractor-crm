import FailedUrl from "@/models/FailedUrl";
import ScrapeJob from "@/models/ScrapeJob";
import { extractGigData } from "./extractGigData";
import { extractReviews } from "./extractReviews";
import { saveLeadIfQualified } from "@/lib/leads";
import type { Types } from "mongoose";

const MAX_RETRIES = Number(process.env.MAX_RETRIES) || 3;

/** Retry previously failed gig URLs for a job */
export async function retryFailedUrls(jobId: Types.ObjectId): Promise<number> {
  const job = await ScrapeJob.findById(jobId);
  if (!job) return 0;

  const failed = await FailedUrl.find({ jobId, retryCount: { $lt: MAX_RETRIES } });
  let recovered = 0;

  for (const item of failed) {
    try {
      const gigData = await extractGigData(item.url);
      const reviews = await extractReviews(item.url, job.maxReviewsPerGig);
      for (const review of reviews) {
        const { saved } = await saveLeadIfQualified(
          { jobId, userId: job.userId, niche: job.niche, gig: gigData, review },
          job.targetCountries
        );
        if (saved) recovered++;
      }
      await FailedUrl.deleteOne({ _id: item._id });
    } catch (err) {
      item.retryCount += 1;
      item.reason = err instanceof Error ? err.message : String(err);
      await item.save();
    }
  }

  return recovered;
}
