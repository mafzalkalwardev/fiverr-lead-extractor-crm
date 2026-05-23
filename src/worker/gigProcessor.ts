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
import { getOrCreatePage, isBrowserClosedError, pauseWithoutClosing } from "@/scraper/live/browser";
import { waitForVerificationToClear } from "@/scraper/live/verification";

export interface GigProcessorState {
  gigsScanned: number;
  reviewsChecked: number;
  usLeads: number;
  canadaLeads: number;
  totalLeads: number;
  failedGigs: number;
}

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

export async function processGigList(
  job: IScrapeJob,
  jobId: string,
  gigUrls: string[],
  startIndex: number,
  scraper: ScraperAdapter,
  niche: string,
  state: GigProcessorState
): Promise<"completed" | "verification_required" | "stopped"> {
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
      currentGigNumber: i + 1,
      totalGigs: gigUrls.length,
      currentReviewPage: 0,
      resumeIndex: i,
      gigQueue: gigUrls,
      progressPercent: Math.round((i / totalSteps) * 100),
    });
    await appendJobLog(jobId, `Opening real Fiverr gig ${i + 1}/${gigUrls.length}: ${gigUrl}`);

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
          { jobId: job._id, userId: job.userId, niche, gig, review: reviewForSave },
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
      }

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
        `Gig complete: saved=${savedForGig}, skipped=${skippedForGig}, totalLeads=${state.totalLeads}`
      );
    } catch (err) {
      if (err instanceof ScraperVerificationRequiredError) {
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

      state.failedGigs += 1;
      const msg = err instanceof Error ? err.message : String(err);
      await ScrapeJob.findByIdAndUpdate(jobId, {
        failedGigs: state.failedGigs,
        $push: { errorLog: `${gigUrl}: ${msg}` },
      });
      await appendJobLog(
        jobId,
        `${/selectors failed/i.test(msg) ? "selectors failed" : "Gig failed"}: ${gigUrl} | ${msg}`
      );
    }
  }

  return "completed";
}
