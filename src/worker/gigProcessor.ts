import { sleep } from "@/lib/utils";
import { saveLeadIfQualified, countLeadByCountry } from "@/lib/leads";
import { VERIFICATION_MESSAGE } from "@/lib/extraction-modes";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";
import GigProgress from "@/models/GigProgress";
import type { IScrapeJob } from "@/models/ScrapeJob";
import {
  ScraperBlockedError,
  ScraperVerificationRequiredError,
} from "@/scraper/types";
import type { ScraperAdapter } from "@/scraper/types";
import {
  getOrCreatePage,
  isBrowserClosedError,
  pauseWithoutClosing,
} from "@/scraper/live/browser";
import { waitForVerificationToClear } from "@/scraper/live/verification";
import { isNetworkTimeoutError } from "@/scraper/live/scraper";

export interface GigProcessorState {
  gigsScanned: number;
  reviewsChecked: number;
  usLeads: number;
  canadaLeads: number;
  totalLeads: number;
  failedGigs: number;
}

export type GigListOutcome =
  | "completed"
  | "verification_required"
  | "stopped"
  | "paused"
  | "retry_required";

async function bringWorkerBrowserToFront(): Promise<void> {
  try {
    const { getBrowserContext } = await import("@/scraper/live/browser");
    const ctx = await getBrowserContext();
    const pages = ctx.pages();
    if (pages[0]) await pages[0].bringToFront().catch(() => {});
  } catch {
    /* ignore */
  }
}

async function waitForFiverrVerification(params: {
  jobId: string;
  gigUrl: string;
  gigUrls: string[];
  index: number;
  state: GigProcessorState;
  message: string;
}): Promise<"cleared" | "stopped"> {
  const { jobId, gigUrl, gigUrls, index, state, message } = params;

  await pauseWithoutClosing(message);
  await bringWorkerBrowserToFront();
  await ScrapeJob.findByIdAndUpdate(jobId, {
    status: "verification_required",
    verificationMessage: VERIFICATION_MESSAGE,
    currentGigLink: gigUrl,
    gigQueue: gigUrls,
    resumeIndex: index,
    gigsScanned: state.gigsScanned,
    reviewsChecked: state.reviewsChecked,
    usLeadsFound: state.usLeads,
    canadaLeadsFound: state.canadaLeads,
    totalLeadsFound: state.totalLeads,
  });
  await appendJobLog(
    jobId,
    `Verification required at gig ${index + 1}: ${message}. Complete it in the opened browser; the app will continue automatically.`
  );

  const page = await getOrCreatePage();
  const result = await waitForVerificationToClear(page, jobId);
  if (result === "stopped") return "stopped";

  await ScrapeJob.findByIdAndUpdate(jobId, {
    status: "extracting_reviews",
    verificationMessage: "",
    currentGigLink: gigUrl,
    resumeIndex: index,
  });
  await appendJobLog(jobId, "Extraction resumed after Fiverr verification.");
  return "cleared";
}

async function markGigProcessing(jobId: string, index: number): Promise<void> {
  try {
    await GigProgress.findOneAndUpdate(
      { jobId, index },
      { $set: { status: "processing", startedAt: new Date() } }
    );
  } catch {
    /* best-effort */
  }
}

async function markGigCompleted(
  jobId: string,
  index: number,
  reviewsParsed: number,
  leadsFound: number
): Promise<void> {
  try {
    await GigProgress.findOneAndUpdate(
      { jobId, index },
      {
        $set: {
          status: "completed",
          completedAt: new Date(),
          reviewsParsed,
          leadsFound,
        },
      }
    );
  } catch {
    /* best-effort */
  }
}

async function markGigFailed(
  jobId: string,
  index: number,
  error: string
): Promise<void> {
  try {
    await GigProgress.findOneAndUpdate(
      { jobId, index },
      {
        $set: { status: "failed", lastError: error.slice(0, 500) },
        $inc: { retryCount: 1 },
      }
    );
  } catch {
    /* best-effort */
  }
}

async function resetGigToPending(jobId: string, index: number): Promise<void> {
  try {
    await GigProgress.findOneAndUpdate(
      { jobId, index },
      { $set: { status: "pending" } }
    );
  } catch {
    /* best-effort */
  }
}

export async function processGigList(
  job: IScrapeJob,
  jobId: string,
  gigUrls: string[],
  startIndex: number,
  scraper: ScraperAdapter,
  niche: string,
  state: GigProcessorState
): Promise<GigListOutcome> {
  const totalSteps = Math.max(gigUrls.length, 1);

  for (let i = startIndex; i < gigUrls.length; i++) {
    // Skip gigs already completed (safety net)
    const gigProg = await GigProgress.findOne(
      { jobId, index: i },
      { status: 1 }
    ).lean();
    if (gigProg?.status === "completed" || gigProg?.status === "skipped") {
      await appendJobLog(
        jobId,
        `Skipped gig ${i + 1}/${gigUrls.length} (already ${gigProg.status})`
      );
      continue;
    }

    // Check for control signals before each gig
    const current = await ScrapeJob.findById(jobId).select("status").lean();
    if (current?.status === "stopped") return "stopped";
    if (current?.status === "paused") {
      await appendJobLog(
        jobId,
        `Job paused at gig ${i + 1}/${gigUrls.length}. Will resume from here.`
      );
      return "paused";
    }

    if (state.totalLeads >= job.maxTotalLeads) break;

    const gigUrl = gigUrls[i];
    console.log(`[worker] Gig ${i + 1}/${gigUrls.length}: ${gigUrl}`);

    await markGigProcessing(jobId, i);

    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "extracting_reviews",
      currentGigLink: gigUrl,
      currentGigNumber: i + 1,
      totalGigs: gigUrls.length,
      currentReviewPage: 0,
      resumeIndex: i,
      gigQueue: gigUrls,
      progressPercent: Math.round((i / totalSteps) * 100),
    });
    await appendJobLog(
      jobId,
      `Opening real Fiverr gig ${i + 1}/${gigUrls.length}: ${gigUrl}`
    );

    try {
      await appendJobLog(jobId, `Waiting ${job.delaySeconds}s before navigation`);
      await sleep(job.delaySeconds * 1000);

      const { gig, reviews, reviewsChecked } = await scraper.processGig(
        gigUrl,
        job.maxReviewsPerGig,
        { reviewImageMode: job.reviewImageMode || "with_image" }
      );
      const seller = gig.sellerName || gig.sellerUsername || "";

      await ScrapeJob.findByIdAndUpdate(jobId, {
        currentGigLink: gig.gigUrl,
        currentSeller: seller,
        currentSellerUsername: gig.sellerUsername || seller,
        currentReviewPage: reviews.length ? 1 : 0,
        totalReviewsParsed: state.reviewsChecked + (reviewsChecked ?? reviews.length),
      });
      await appendJobLog(
        jobId,
        `Gig loaded: ${gig.gigUrl} | seller="${seller}" | title="${gig.gigTitle.slice(0, 90)}"`
      );
      await appendJobLog(jobId, `Seller extracted: ${seller || "unknown"}`);
      await appendJobLog(
        jobId,
        `Reviews extracted: parsed ${reviewsChecked ?? reviews.length} review blocks; kept ${reviews.length} US/Canada reviews with country/rating`
      );

      state.gigsScanned += 1;
      state.reviewsChecked += reviewsChecked ?? reviews.length;

      let savedForGig = 0;
      let skippedForGig = 0;

      for (let reviewIndex = 0; reviewIndex < reviews.length; reviewIndex++) {
        const review = reviews[reviewIndex];
        if (state.totalLeads >= job.maxTotalLeads) break;
        const reviewForSave =
          (job.reviewImageMode || "with_image") === "without_image"
            ? { ...review, reviewedImageLink: "" }
            : review;

        await appendJobLog(
          jobId,
          `Review ${reviewIndex + 1}/${reviews.length}: reviewer="${review.reviewerName}" country="${review.reviewerCountry}" rating=${review.reviewRating}`
        );

        const { saved, country, reason } = await saveLeadIfQualified(
          {
            jobId: job._id,
            userId: job.userId,
            niche,
            gig,
            review: reviewForSave,
          },
          job.targetCountries
        );

        if (saved) {
          state.totalLeads += 1;
          savedForGig += 1;
          const bucket = countLeadByCountry(country);
          if (bucket === "us") state.usLeads += 1;
          if (bucket === "canada") state.canadaLeads += 1;
          await appendJobLog(jobId, `Saved lead: ${review.reviewerName} (${country})`);
        } else {
          skippedForGig += 1;
          await appendJobLog(
            jobId,
            `Skipped review: ${review.reviewerName || "missing reviewer"} (${country || "missing country"}) reason=${reason}`
          );
        }

        // Persist progress every 5 reviews for real-time visibility
        if ((reviewIndex + 1) % 5 === 0) {
          await ScrapeJob.findByIdAndUpdate(jobId, {
            currentReviewPage: reviewIndex + 1,
            totalReviewsParsed: state.reviewsChecked,
            totalLeadsFound: state.totalLeads,
            usLeadsFound: state.usLeads,
            canadaLeadsFound: state.canadaLeads,
          });
        }
      }

      await markGigCompleted(jobId, i, reviewsChecked ?? reviews.length, savedForGig);

      await ScrapeJob.findByIdAndUpdate(jobId, {
        gigsScanned: state.gigsScanned,
        reviewsChecked: state.reviewsChecked,
        usLeadsFound: state.usLeads,
        canadaLeadsFound: state.canadaLeads,
        totalLeadsFound: state.totalLeads,
        totalReviewsParsed: state.reviewsChecked,
        resumeIndex: i + 1,
      });

      console.log(`[worker] Leads saved count for gig: ${savedForGig}`);
      await appendJobLog(jobId, `Leads saved: ${savedForGig}`);
      await appendJobLog(
        jobId,
        `Gig ${i + 1}/${gigUrls.length} complete: saved=${savedForGig}, skipped=${skippedForGig}, totalLeads=${state.totalLeads}`
      );
    } catch (err) {
      if (err instanceof ScraperVerificationRequiredError) {
        await resetGigToPending(jobId, i);
        const result = await waitForFiverrVerification({
          jobId,
          gigUrl,
          gigUrls,
          index: i,
          state,
          message: err.message,
        });
        if (result === "stopped") return "stopped";
        i -= 1;
        continue;
      }

      if (err instanceof ScraperBlockedError) {
        await resetGigToPending(jobId, i);
        const result = await waitForFiverrVerification({
          jobId,
          gigUrl,
          gigUrls,
          index: i,
          state,
          message: err.message,
        });
        if (result === "stopped") return "stopped";
        i -= 1;
        continue;
      }

      if (isBrowserClosedError(err)) {
        await resetGigToPending(jobId, i);
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "verification_required",
          verificationMessage: VERIFICATION_MESSAGE,
          currentGigLink: gigUrl,
          gigQueue: gigUrls,
          resumeIndex: i,
        });
        await appendJobLog(
          jobId,
          "Browser/session was closed. Retry will reconnect to the same persistent profile, but do not close Chrome during verification."
        );
        return "verification_required";
      }

      const msg = err instanceof Error ? err.message : String(err);

      // Network timeout: set retry_required so user can retry without losing progress
      if (isNetworkTimeoutError(err)) {
        await resetGigToPending(jobId, i);
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "retry_required",
          lastError: msg.slice(0, 500),
          currentGigLink: gigUrl,
          gigQueue: gigUrls,
          resumeIndex: i,
          $push: { errorLog: `Network timeout at gig ${i + 1}/${gigUrls.length}: ${msg}` },
        });
        await appendJobLog(
          jobId,
          `Network timeout at gig ${i + 1}/${gigUrls.length}: ${msg}. Click Retry to continue from this gig.`
        );
        return "retry_required";
      }

      state.failedGigs += 1;
      await markGigFailed(jobId, i, msg);
      await ScrapeJob.findByIdAndUpdate(jobId, {
        failedGigs: state.failedGigs,
        $push: { errorLog: `${gigUrl}: ${msg}` },
      });
      await appendJobLog(
        jobId,
        `${/selectors failed/i.test(msg) ? "selectors failed" : "Gig failed"}: gig ${i + 1}/${gigUrls.length} | ${gigUrl} | ${msg}`
      );
    }
  }

  return "completed";
}
