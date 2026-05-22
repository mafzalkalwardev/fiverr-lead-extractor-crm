import "@/lib/load-env";
import fs from "fs/promises";
import { connectDB } from "@/lib/db";
import { logActivity } from "@/lib/activityLog";
import { appendJobLog } from "@/lib/jobLog";
import { parseGigFromHtml } from "@/scraper/html/parseGigHtml";
import { discoverGigUrls } from "@/scraper/discovery";
import { saveLeadIfQualified, countLeadByCountry } from "@/lib/leads";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";
import ScrapeJob, { type IScrapeJob } from "@/models/ScrapeJob";
import { createScraper, closeScraper } from "@/scraper/factory";
import { pauseWithoutClosing } from "@/scraper/live/browser";
import { processGigList, type GigProcessorState } from "./gigProcessor";
import {
  ScraperBlockedError,
  ScraperVerificationRequiredError,
} from "@/scraper/types";
import { VERIFICATION_MESSAGE } from "@/lib/extraction-modes";

function initialState(job: {
  gigsScanned?: number;
  reviewsChecked?: number;
  usLeadsFound?: number;
  canadaLeadsFound?: number;
  totalLeadsFound?: number;
  failedGigs?: number;
}): GigProcessorState {
  return {
    gigsScanned: job.gigsScanned || 0,
    reviewsChecked: job.reviewsChecked || 0,
    usLeads: job.usLeadsFound || 0,
    canadaLeads: job.canadaLeadsFound || 0,
    totalLeads: job.totalLeadsFound || 0,
    failedGigs: job.failedGigs || 0,
  };
}

async function finishJob(
  jobId: string,
  userId: unknown,
  outcome: string,
  totalLeads: number
) {
  if (outcome === "completed") {
    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "completed",
      progressPercent: 100,
      currentGigLink: "",
      currentSeller: "",
      verificationMessage: "",
    });
    await appendJobLog(jobId, `Job completed | totalLeads=${totalLeads}`);
    await logActivity(
      "records_extracted",
      `Job ${jobId} completed: ${totalLeads} leads`,
      userId as import("mongoose").Types.ObjectId
    );
  }
}

async function setVerificationRequired(jobId: string, message: string, extra?: Record<string, unknown>) {
  await ScrapeJob.findByIdAndUpdate(jobId, {
    status: "verification_required",
    verificationMessage: VERIFICATION_MESSAGE,
    ...extra,
    $push: { errorLog: message },
  });
  await appendJobLog(jobId, `Verification required: ${message}`);
}

export async function processScrapeJob(jobId: string): Promise<void> {
  await connectDB();
  const job = await ScrapeJob.findById(jobId);
  if (!job) throw new Error(`Job ${jobId} not found`);

  const niche = (job.niche || "").trim();
  if (!niche) {
    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "failed",
      $push: { errorLog: "Job missing niche" },
    });
    return;
  }

  const state = initialState(job);
  let finalStatus = "running";

  try {
    await appendJobLog(jobId, `Started | mode=${job.extractionMode} | niche="${niche}"`);
    await appendJobLog(
      jobId,
      `Targets=${job.targetCountries.join(", ")} | maxGigs=${job.maxGigs} | maxReviewsPerGig=${job.maxReviewsPerGig} | maxTotalLeads=${job.maxTotalLeads}`
    );
    if ((job.resumeIndex || 0) > 0 || (job.gigQueue?.length || 0) > 0) {
      await appendJobLog(jobId, "Session resumed. Scraping will continue from saved queue progress.");
    }
    await ScrapeJob.findByIdAndUpdate(jobId, { status: "running", verificationMessage: "" });

    if (job.extractionMode === "html_import") {
      await processHtmlImportJob(job, jobId, niche, state);
      return;
    }

    const scraper = createScraper();

    if (job.extractionMode === "manual_urls") {
      const urls = (job.manualGigUrls?.length ? job.manualGigUrls : job.gigQueue) || [];
      const normalized = urls.flatMap((u) => {
        const normalizedUrl = normalizeFiverrUrl(u);
        return normalizedUrl ? [normalizedUrl] : [];
      });
      const skipped = urls.length - normalized.length;

      await appendJobLog(jobId, `Manual URLs accepted: ${normalized.length} real Fiverr gigs`);
      if (skipped > 0) {
        await appendJobLog(jobId, `Manual URLs skipped as invalid/non-gig: ${skipped}`);
      }

      if (normalized.length === 0) {
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "failed",
          $push: { errorLog: "No valid Fiverr gig URLs to process" },
        });
        await appendJobLog(jobId, "No valid Fiverr gig URLs to process");
        return;
      }

      await ScrapeJob.findByIdAndUpdate(jobId, {
        status: "extracting_reviews",
        discoverySource: "manual",
        urlsDiscovered: normalized.length,
        gigQueue: normalized,
      });

      const outcome = await processGigList(
        job,
        jobId,
        normalized,
        job.resumeIndex || 0,
        scraper,
        niche,
        state
      );
      finalStatus = outcome;
      await finishJob(jobId, job.userId, outcome, state.totalLeads);
      return;
    }

    let gigUrls = job.gigQueue || [];
    let startIndex = job.resumeIndex || 0;

    if (gigUrls.length === 0) {
      await ScrapeJob.findByIdAndUpdate(jobId, { status: "discovering_gigs" });
      await appendJobLog(jobId, "Discovering real Fiverr gig URLs");

      try {
        const discovery = await discoverGigUrls(niche, job.maxGigs, []);
        gigUrls = discovery.gigUrls;
        await ScrapeJob.findByIdAndUpdate(jobId, {
          discoverySource: discovery.source,
          urlsDiscovered: gigUrls.length,
          gigQueue: gigUrls,
          resumeIndex: 0,
        });
        await appendJobLog(jobId, `Discovery source=${discovery.source} | URLs found=${gigUrls.length}`);
        for (const [idx, url] of gigUrls.slice(0, 10).entries()) {
          await appendJobLog(jobId, `Discovered URL ${idx + 1}: ${url}`);
        }

        if (gigUrls.length === 0) {
          await setVerificationRequired(
            jobId,
            "No gig URLs discovered. Complete Fiverr verification in Chrome; Retry remains available as a manual backup. Or use Paste Gig Links mode."
          );
          finalStatus = "verification_required";
          return;
        }
      } catch (err) {
        if (err instanceof ScraperVerificationRequiredError || err instanceof ScraperBlockedError) {
          const msg = err instanceof Error ? err.message : String(err);
          await pauseWithoutClosing(msg);
          await setVerificationRequired(jobId, `Fiverr blocked discovery: ${msg}`);
          finalStatus = "verification_required";
          return;
        }
        throw err;
      }
      startIndex = 0;
    } else {
      await appendJobLog(jobId, `Resuming queue | URLs=${gigUrls.length} | startIndex=${startIndex}`);
    }

    await ScrapeJob.findByIdAndUpdate(jobId, { status: "extracting_reviews" });
    await appendJobLog(jobId, "Extracting seller metadata and real reviews from gig pages");

    const outcome = await processGigList(
      job,
      jobId,
      gigUrls,
      startIndex,
      scraper,
      niche,
      state
    );
    finalStatus = outcome;
    await finishJob(jobId, job.userId, outcome, state.totalLeads);
  } catch (err) {
    if (err instanceof ScraperVerificationRequiredError || err instanceof ScraperBlockedError) {
      const msg = err instanceof Error ? err.message : String(err);
      await pauseWithoutClosing(msg);
      await setVerificationRequired(jobId, `Fiverr page blocked: ${msg}`);
      finalStatus = "verification_required";
      return;
    }

    const msg = err instanceof Error ? err.message : String(err);
    const { isBrowserClosedError } = await import("@/scraper/live/browser");
    if (isBrowserClosedError(err)) {
      await setVerificationRequired(
        jobId,
        "Browser/session was closed. Retry will reconnect to the same persistent profile, but do not close Chrome during verification."
      );
      finalStatus = "verification_required";
      return;
    }

    await ScrapeJob.findByIdAndUpdate(jobId, { status: "failed", $push: { errorLog: msg } });
    await appendJobLog(jobId, `Failed: ${msg}`);
    throw err;
  } finally {
    if (finalStatus === "stopped") {
      await closeScraper(true);
    } else if (finalStatus !== "verification_required") {
      await closeScraper();
    }
  }
}

async function processHtmlImportJob(
  job: IScrapeJob,
  jobId: string,
  niche: string,
  state: GigProcessorState
) {
  const files = job.htmlFiles || [];
  if (files.length === 0) {
    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "failed",
      $push: { errorLog: "No HTML files uploaded" },
    });
    return;
  }

  await ScrapeJob.findByIdAndUpdate(jobId, { status: "extracting_reviews" });
  await appendJobLog(jobId, `Parsing ${files.length} uploaded Fiverr HTML files`);
  const start = job.resumeIndex || 0;

  for (let i = start; i < files.length; i++) {
    const file = files[i];
    const html = await fs.readFile(file.storedPath, "utf-8");
    const sourceUrl = normalizeFiverrUrl(file.gigUrl);

    if (!sourceUrl) {
      state.failedGigs += 1;
      await ScrapeJob.findByIdAndUpdate(jobId, {
        failedGigs: state.failedGigs,
        resumeIndex: i + 1,
        $push: { errorLog: `${file.filename}: missing original Fiverr gig URL` },
      });
      await appendJobLog(jobId, `Skipped HTML without original Fiverr gig URL: ${file.filename}`);
      continue;
    }

    await ScrapeJob.findByIdAndUpdate(jobId, {
      currentGigLink: sourceUrl,
      resumeIndex: i,
      progressPercent: Math.round((i / files.length) * 100),
    });
    await appendJobLog(jobId, `Parsing HTML ${i + 1}/${files.length}: ${file.filename} | ${sourceUrl}`);

    try {
      const { gig, reviews } = await parseGigFromHtml(html, sourceUrl);
      await appendJobLog(
        jobId,
        `HTML gig parsed: ${gig.gigUrl} | seller="${gig.sellerName || gig.sellerUsername}" | reviews=${reviews.length}`
      );
      state.gigsScanned += 1;
      state.reviewsChecked += reviews.length;

      for (const review of reviews) {
        if (state.totalLeads >= job.maxTotalLeads) break;
        const { saved, country, reason } = await saveLeadIfQualified(
          { jobId: job._id, userId: job.userId, niche, gig, review },
          job.targetCountries
        );
        if (saved) {
          state.totalLeads += 1;
          const bucket = countLeadByCountry(country);
          if (bucket === "us") state.usLeads += 1;
          if (bucket === "canada") state.canadaLeads += 1;
          await appendJobLog(jobId, `Lead saved: ${review.reviewerName} (${country})`);
        } else {
          await appendJobLog(
            jobId,
            `Review skipped: ${review.reviewerName || "missing reviewer"} (${country || "missing country"}) reason=${reason}`
          );
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
      state.failedGigs += 1;
      const msg = err instanceof Error ? err.message : String(err);
      await ScrapeJob.findByIdAndUpdate(jobId, {
        failedGigs: state.failedGigs,
        $push: { errorLog: `${file.filename}: ${msg}` },
      });
      await appendJobLog(jobId, `HTML parse failed: ${file.filename} | ${msg}`);
    }
  }

  await finishJob(jobId, job.userId, "completed", state.totalLeads);
}
