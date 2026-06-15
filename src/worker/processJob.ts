import "@/lib/load-env";
import { isPythonScraperEngine } from "@/lib/scraper-engine";
import fs from "fs/promises";
import { Types } from "mongoose";
import { connectDB } from "@/lib/db";
import { logActivity } from "@/lib/activityLog";
import { appendJobLog } from "@/lib/jobLog";
import { parseGigFromHtml } from "@/scraper/html/parseGigHtml";
import { discoverGigUrls } from "@/scraper/discovery";
import { saveLeadIfQualified, countLeadByCountry } from "@/lib/leads";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";
import ScrapeJob, { type IScrapeJob } from "@/models/ScrapeJob";
import GigProgress from "@/models/GigProgress";
import { createScraper, closeScraper } from "@/scraper/factory";
import { pauseWithoutClosing } from "@/scraper/live/browser";
import { processGigList, type GigProcessorState, type GigListOutcome } from "./gigProcessor";
import {
  ScraperBlockedError,
  ScraperVerificationRequiredError,
} from "@/scraper/types";
import { VERIFICATION_MESSAGE } from "@/lib/extraction-modes";

/** Gigs stuck in "processing" longer than this are reset to "pending" */
const STUCK_GIG_MS = 30 * 60 * 1000;

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
      currentSellerUsername: "",
      verificationMessage: "",
    });
    await appendJobLog(jobId, `Job completed | totalLeads=${totalLeads}`);
    await logActivity(
      "records_extracted",
      `Job ${jobId} completed: ${totalLeads} leads`,
      userId as import("mongoose").Types.ObjectId
    );
  } else if (outcome === "lead_limit_reached") {
    await appendJobLog(
      jobId,
      `Job paused at lead limit | totalLeads=${totalLeads} | remaining gigs saved in queue`
    );
  }
}

async function setVerificationRequired(
  jobId: string,
  message: string,
  extra?: Record<string, unknown>
) {
  await ScrapeJob.findByIdAndUpdate(jobId, {
    status: "verification_required",
    verificationMessage: VERIFICATION_MESSAGE,
    ...extra,
    $push: { errorLog: message },
  });
  await appendJobLog(jobId, `Verification required: ${message}`);
}

/**
 * Ensure GigProgress records exist for all URLs.
 * Uses upsert with $setOnInsert so existing records are never overwritten.
 */
async function ensureGigProgressRecords(
  jobId: string,
  gigUrls: string[]
): Promise<void> {
  if (gigUrls.length === 0) return;
  const jobObjId = new Types.ObjectId(jobId);
  for (const [index, url] of gigUrls.entries()) {
    await GigProgress.updateOne(
      { jobId: jobObjId, index },
      {
        $setOnInsert: {
          jobId: jobObjId,
          url,
          index,
          status: "pending" as const,
          retryCount: 0,
          reviewsParsed: 0,
          leadsFound: 0,
        },
      },
      { upsert: true }
    );
  }
}

/**
 * Reset gigs that have been stuck in "processing" state for too long.
 * Called on every job pickup to handle crashes that left gigs mid-flight.
 */
async function resetProcessingGigs(jobId: string): Promise<number> {
  const threshold = new Date(Date.now() - STUCK_GIG_MS);
  const result = await GigProgress.updateMany(
    {
      jobId,
      status: "processing",
      $or: [
        { startedAt: { $lt: threshold } },
        { startedAt: { $exists: false } },
      ],
    },
    { $set: { status: "pending" } }
  );
  return result.modifiedCount;
}

/**
 * Find the first gig index that still needs processing.
 * Returns totalCount when all gigs are done (signals loop exit).
 */
async function findResumeIndex(
  jobId: string,
  totalCount: number
): Promise<number> {
  const first = await GigProgress.findOne(
    { jobId, status: { $in: ["pending", "failed"] } },
    { index: 1 }
  ).sort({ index: 1 });
  return first?.index ?? totalCount;
}

export async function processScrapeJob(jobId: string): Promise<void> {
  if (isPythonScraperEngine()) {
    console.log(
      `[worker] Skip ${jobId} — Python scraper handles jobs (SCRAPER_ENGINE=python)`
    );
    return;
  }

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
  let finalStatus: GigListOutcome | "running" | "verification_required" = "running";

  try {
    await appendJobLog(
      jobId,
      `Started | mode=${job.extractionMode} | niche="${niche}"`
    );
    await appendJobLog(
      jobId,
      `Review image option=${job.reviewImageMode || "with_image"}`
    );
    await appendJobLog(
      jobId,
      `Targets=${job.targetCountries.join(", ")} | maxGigs=${job.maxGigs} | maxReviewsPerGig=${job.maxReviewsPerGig} | maxTotalLeads=${job.maxTotalLeads}`
    );
    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "running",
      verificationMessage: "",
    });

    if (job.extractionMode === "html_import") {
      await processHtmlImportJob(job, jobId, niche, state);
      return;
    }

    const scraper = createScraper();

    if (job.extractionMode === "manual_urls") {
      const urls =
        (job.manualGigUrls?.length ? job.manualGigUrls : job.gigQueue) || [];
      const normalized = urls.flatMap((u) => {
        const normalizedUrl = normalizeFiverrUrl(u);
        return normalizedUrl ? [normalizedUrl] : [];
      });
      const skipped = urls.length - normalized.length;

      if (skipped > 0) {
        await appendJobLog(
          jobId,
          `Manual URLs skipped as invalid/non-gig: ${skipped}`
        );
      }

      if (normalized.length === 0) {
        await ScrapeJob.findByIdAndUpdate(jobId, {
          status: "failed",
          $push: { errorLog: "No valid Fiverr gig URLs to process" },
        });
        await appendJobLog(jobId, "No valid Fiverr gig URLs to process");
        return;
      }

      // Ensure GigProgress records exist, then find where to resume
      await ensureGigProgressRecords(jobId, normalized);
      const stuckCount = await resetProcessingGigs(jobId);
      if (stuckCount > 0) {
        await appendJobLog(
          jobId,
          `Reset ${stuckCount} stuck gig(s) to pending for retry`
        );
      }
      const startIndex = await findResumeIndex(jobId, normalized.length);

      await ScrapeJob.findByIdAndUpdate(jobId, {
        status: "extracting_reviews",
        discoverySource: "manual",
        urlsDiscovered: normalized.length,
        gigQueue: normalized,
        resumeIndex: startIndex,
        totalGigs: normalized.length,
      });

      if (startIndex >= normalized.length) {
        await appendJobLog(
          jobId,
          `All ${normalized.length} gigs already completed — nothing to resume`
        );
        await finishJob(jobId, job.userId, "completed", state.totalLeads);
        return;
      }

      if (startIndex > 0) {
        await appendJobLog(
          jobId,
          `Resumed from gig ${startIndex + 1}/${normalized.length} (skipping ${startIndex} already-completed gigs)`
        );
      } else {
        await appendJobLog(
          jobId,
          `Manual URLs accepted: ${normalized.length} real Fiverr gigs`
        );
      }

      const outcome = await processGigList(
        job,
        jobId,
        normalized,
        startIndex,
        scraper,
        niche,
        state
      );
      finalStatus = outcome;
      await finishJob(jobId, job.userId, outcome, state.totalLeads);
      return;
    }

    // ── Live mode ──────────────────────────────────────────────────────────
    // Check if URLs were already discovered for this job
    const existingProgressCount = await GigProgress.countDocuments({ jobId });

    let gigUrls: string[];
    let startIndex: number;

    if (existingProgressCount > 0) {
      // URLs already discovered — load them from GigProgress in original order
      const stuckCount = await resetProcessingGigs(jobId);
      if (stuckCount > 0) {
        await appendJobLog(
          jobId,
          `Reset ${stuckCount} stuck gig(s) to pending for retry`
        );
      }

      const progressRecords = await GigProgress.find({ jobId })
        .sort({ index: 1 })
        .lean();
      gigUrls = progressRecords.map((r) => r.url);

      const completedCount = progressRecords.filter(
        (r) => r.status === "completed" || r.status === "skipped"
      ).length;
      const remainingCount = progressRecords.filter(
        (r) => r.status === "pending" || r.status === "failed"
      ).length;

      startIndex = await findResumeIndex(jobId, gigUrls.length);

      // Sync gigQueue and resumeIndex into ScrapeJob for UI display
      await ScrapeJob.findByIdAndUpdate(jobId, {
        gigQueue: gigUrls,
        resumeIndex: startIndex,
        urlsDiscovered: gigUrls.length,
        totalGigs: gigUrls.length,
      });

      if (startIndex >= gigUrls.length) {
        await appendJobLog(
          jobId,
          `All ${gigUrls.length} gigs already completed — nothing to resume`
        );
        await finishJob(jobId, job.userId, "completed", state.totalLeads);
        return;
      }

      await appendJobLog(
        jobId,
        `Resuming job | totalGigs=${gigUrls.length} | completed=${completedCount} | remaining=${remainingCount}`
      );
      await appendJobLog(
        jobId,
        `Resumed from gig ${startIndex + 1}/${gigUrls.length} (skipping ${startIndex} already-completed gigs)`
      );
    } else {
      // No GigProgress records — need to discover URLs first
      await ScrapeJob.findByIdAndUpdate(jobId, {
        status: "discovering_gigs",
      });
      await appendJobLog(jobId, "Discovering real Fiverr gig URLs");

      try {
        const discovery = await discoverGigUrls(niche, job.maxGigs, []);
        gigUrls = discovery.gigUrls;

        await ScrapeJob.findByIdAndUpdate(jobId, {
          discoverySource: discovery.source,
          urlsDiscovered: gigUrls.length,
          gigQueue: gigUrls,
          resumeIndex: 0,
          totalGigs: gigUrls.length,
        });

        await appendJobLog(
          jobId,
          `Discovered ${gigUrls.length} URLs | source=${discovery.source}`
        );
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

        // Persist per-gig progress records immediately after discovery
        await ensureGigProgressRecords(jobId, gigUrls);
        startIndex = 0;
      } catch (err) {
        if (
          err instanceof ScraperVerificationRequiredError ||
          err instanceof ScraperBlockedError
        ) {
          const msg = err instanceof Error ? err.message : String(err);
          await pauseWithoutClosing(msg);
          await setVerificationRequired(
            jobId,
            `Fiverr blocked discovery: ${msg}`
          );
          finalStatus = "verification_required";
          return;
        }
        throw err;
      }
    }

    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "extracting_reviews",
    });
    await appendJobLog(
      jobId,
      "Extracting seller metadata and real reviews from gig pages"
    );

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
    if (
      err instanceof ScraperVerificationRequiredError ||
      err instanceof ScraperBlockedError
    ) {
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

    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "failed",
      $push: { errorLog: msg },
    });
    await appendJobLog(jobId, `Failed: ${msg}`);
    throw err;
  } finally {
    if (finalStatus === "stopped") {
      // Force-close: user explicitly stopped, tear down Playwright
      await closeScraper(true);
    } else if (
      finalStatus === "verification_required" ||
      finalStatus === "retry_required" ||
      finalStatus === "paused"
    ) {
      // Keep browser alive — user will Resume / Retry shortly
    } else {
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
        $push: {
          errorLog: `${file.filename}: missing original Fiverr gig URL`,
        },
      });
      await appendJobLog(
        jobId,
        `Skipped HTML without original Fiverr gig URL: ${file.filename}`
      );
      continue;
    }

    await ScrapeJob.findByIdAndUpdate(jobId, {
      currentGigLink: sourceUrl,
      resumeIndex: i,
      progressPercent: Math.round((i / files.length) * 100),
    });
    await appendJobLog(
      jobId,
      `Parsing HTML ${i + 1}/${files.length}: ${file.filename} | ${sourceUrl}`
    );

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
          await appendJobLog(
            jobId,
            `Lead saved: ${review.reviewerName} (${country})`
          );
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
      await appendJobLog(
        jobId,
        `HTML parse failed: ${file.filename} | ${msg}`
      );
    }
  }

  await finishJob(jobId, job.userId, "completed", state.totalLeads);
}
