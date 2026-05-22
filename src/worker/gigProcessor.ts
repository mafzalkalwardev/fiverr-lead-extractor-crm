import { sleep } from "@/lib/utils";
import { saveLeadIfQualified, countLeadByCountry } from "@/lib/leads";
import { VERIFICATION_MESSAGE } from "@/lib/extraction-modes";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";
import type { IScrapeJob } from "@/models/ScrapeJob";
import {
  ScraperBlockedError,
  ScraperVerificationRequiredError,
} from "@/scraper/types";
import type { ScraperAdapter } from "@/scraper/types";

export interface GigProcessorState {
  gigsScanned: number;
  reviewsChecked: number;
  usLeads: number;
  canadaLeads: number;
  totalLeads: number;
  failedGigs: number;
}

export async function processGigList(
  job: IScrapeJob,
  jobId: string,
  gigUrls: string[],
  startIndex: number,
  scraper: ScraperAdapter,
  niche: string,
  state: GigProcessorState
): Promise<"completed" | "verification_required" | "blocked" | "stopped"> {
  const totalSteps = Math.max(gigUrls.length, 1);

  for (let i = startIndex; i < gigUrls.length; i++) {
    const current = await ScrapeJob.findById(jobId).select("status totalLeadsFound");
    if (current?.status === "stopped") return "stopped";
    if (state.totalLeads >= job.maxTotalLeads) break;

    const gigUrl = gigUrls[i];
    console.log(`[worker] Gig ${i + 1}/${gigUrls.length}: ${gigUrl}`);

    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "extracting_reviews",
      currentGigLink: gigUrl,
      resumeIndex: i,
      gigQueue: gigUrls,
      progressPercent: Math.round((i / totalSteps) * 100),
    });
    await appendJobLog(jobId, `Opening gig ${i + 1}/${gigUrls.length}`);

    try {
      await sleep(job.delaySeconds * 1000);
      const { gig, reviews } = await scraper.processGig(gigUrl, job.maxReviewsPerGig);

      await ScrapeJob.findByIdAndUpdate(jobId, {
        currentSeller: gig.sellerName || gig.sellerUsername || "",
      });
      await appendJobLog(
        jobId,
        `Seller: ${gig.sellerName || gig.sellerUsername} · ${reviews.length} reviews`
      );

      state.gigsScanned += 1;
      state.reviewsChecked += reviews.length;

      for (const review of reviews) {
        if (state.totalLeads >= job.maxTotalLeads) break;
        const { saved, country } = await saveLeadIfQualified(
          { jobId: job._id, userId: job.userId, niche, gig, review },
          job.targetCountries
        );
        if (saved) {
          state.totalLeads += 1;
          const bucket = countLeadByCountry(country);
          if (bucket === "us") state.usLeads += 1;
          if (bucket === "canada") state.canadaLeads += 1;
        }
      }

      await ScrapeJob.findByIdAndUpdate(jobId, {
        gigsScanned: state.gigsScanned,
        reviewsChecked: state.reviewsChecked,
        usLeadsFound: state.usLeads,
        canadaLeadsFound: state.canadaLeads,
        totalLeadsFound: state.totalLeads,
        resumeIndex: i + 1,
      });
    } catch (err) {
      if (err instanceof ScraperVerificationRequiredError) {
        try {
          const { getBrowserContext } = await import("@/scraper/live/browser");
          const ctx = await getBrowserContext();
          const pages = ctx.pages();
          if (pages[0]) await pages[0].bringToFront().catch(() => {});
        } catch {
          /* ignore */
        }
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "verification_required",
          verificationMessage: VERIFICATION_MESSAGE,
          currentGigLink: gigUrl,
          gigQueue: gigUrls,
          resumeIndex: i,
          gigsScanned: state.gigsScanned,
          reviewsChecked: state.reviewsChecked,
          usLeadsFound: state.usLeads,
          canadaLeadsFound: state.canadaLeads,
          totalLeadsFound: state.totalLeads,
        });
        await appendJobLog(jobId, `Verification required at gig ${i + 1} — use Retry after solving`);
        return "verification_required";
      }
      if (err instanceof ScraperBlockedError) {
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "blocked",
          currentGigLink: gigUrl,
          $push: { errorLog: err.message },
        });
        return "blocked";
      }
      state.failedGigs += 1;
      const msg = err instanceof Error ? err.message : String(err);
      await ScrapeJob.findByIdAndUpdate(jobId, {
        failedGigs: state.failedGigs,
        $push: { errorLog: `${gigUrl}: ${msg}` },
      });
    }
  }

  return "completed";
}
