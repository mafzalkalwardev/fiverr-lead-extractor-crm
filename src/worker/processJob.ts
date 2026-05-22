import "@/lib/load-env";
import fs from "fs/promises";
import { connectDB } from "@/lib/db";
import { logActivity } from "@/lib/activityLog";
import { appendJobLog } from "@/lib/jobLog";
import { parseGigFromHtml } from "@/scraper/html/parseGigHtml";
import { discoverGigUrls } from "@/scraper/discovery";
import { saveLeadIfQualified, countLeadByCountry } from "@/lib/leads";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";
import ScrapeJob from "@/models/ScrapeJob";
import { createScraper, closeScraper } from "@/scraper/factory";
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
    await logActivity(
      "records_extracted",
      `Job ${jobId} completed: ${totalLeads} leads`,
      userId as import("mongoose").Types.ObjectId
    );
  }
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
    await appendJobLog(jobId, `Started · mode=${job.extractionMode} · niche="${niche}"`);
    await ScrapeJob.findByIdAndUpdate(jobId, { status: "running", verificationMessage: "" });

    if (job.extractionMode === "html_import") {
      await processHtmlImportJob(job, jobId, niche, state);
      return;
    }

    const scraper = createScraper();

    if (job.extractionMode === "manual_urls") {
      const urls = (job.manualGigUrls?.length ? job.manualGigUrls : job.gigQueue) || [];
      const normalized = urls.map((u) => normalizeFiverrUrl(u) || u).filter(Boolean);
      await appendJobLog(jobId, `Manual URLs: ${normalized.length} gigs`);
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

    // Live mode — discover then extract
    let gigUrls = job.gigQueue || [];
    let startIndex = job.resumeIndex || 0;

    if (gigUrls.length === 0) {
      await ScrapeJob.findByIdAndUpdate(jobId, { status: "discovering_gigs" });
      await appendJobLog(jobId, "Discovering gig URLs (Fiverr search → search engine fallback)");

      try {
        const discovery = await discoverGigUrls(niche, job.maxGigs, []);
        gigUrls = discovery.gigUrls;
        await ScrapeJob.findByIdAndUpdate(jobId, {
          discoverySource: discovery.source,
          urlsDiscovered: gigUrls.length,
          gigQueue: gigUrls,
          resumeIndex: 0,
        });
        await appendJobLog(
          jobId,
          `Discovery: ${discovery.source} · ${gigUrls.length} URLs found`
        );

        if (gigUrls.length === 0) {
          await ScrapeJob.findByIdAndUpdate(jobId, {
            status: "verification_required",
            verificationMessage: VERIFICATION_MESSAGE,
            $push: {
              errorLog:
                "No gig URLs discovered. Complete Fiverr verification in the Chrome window, then Retry. Or use Paste Gig Links mode.",
            },
          });
          await appendJobLog(jobId, "No URLs — paused for verification");
          finalStatus = "verification_required";
          return;
        }
      } catch (err) {
        if (err instanceof ScraperVerificationRequiredError) {
          await ScrapeJob.findByIdAndUpdate(jobId, {
            status: "verification_required",
            verificationMessage: VERIFICATION_MESSAGE,
          });
          await appendJobLog(jobId, "Fiverr verification required — click Retry after solving");
          finalStatus = "verification_required";
          return;
        }
        throw err;
      }
      startIndex = 0;
    } else {
      await appendJobLog(jobId, `Resuming queue · ${gigUrls.length} URLs from index ${startIndex}`);
    }

    await ScrapeJob.findByIdAndUpdate(jobId, { status: "extracting_reviews" });
    await appendJobLog(jobId, `Extracting reviews from gig pages`);

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
    if (err instanceof ScraperVerificationRequiredError) {
      await ScrapeJob.findByIdAndUpdate(jobId, {
        status: "verification_required",
        verificationMessage: VERIFICATION_MESSAGE,
      });
      await appendJobLog(jobId, "Verification required on gig page");
      finalStatus = "verification_required";
      return;
    }
    const msg = err instanceof Error ? err.message : String(err);
    const { isBrowserClosedError, resetBrowser } = await import("@/scraper/live/browser");
    if (isBrowserClosedError(err)) {
      await resetBrowser();
      await ScrapeJob.findByIdAndUpdate(jobId, {
        status: "verification_required",
        verificationMessage: VERIFICATION_MESSAGE,
        $push: {
          errorLog:
            "Browser window was closed. Click Retry — keep the Chrome window open while extracting.",
        },
      });
      await appendJobLog(jobId, "Browser closed — click Retry (do not close Chrome during jobs)");
      finalStatus = "verification_required";
      return;
    }
    await ScrapeJob.findByIdAndUpdate(jobId, { status: "failed", $push: { errorLog: msg } });
    await appendJobLog(jobId, `Failed: ${msg}`);
    throw err;
  } finally {
    if (finalStatus !== "verification_required") {
      await closeScraper();
    }
  }
}

async function processHtmlImportJob(
  job: import("@/models/ScrapeJob").IScrapeJob,
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
  const start = job.resumeIndex || 0;

  for (let i = start; i < files.length; i++) {
    const file = files[i];
    const html = await fs.readFile(file.storedPath, "utf-8");
    const sourceUrl = file.gigUrl || `https://www.fiverr.com/imported/${i + 1}`;

    await ScrapeJob.findByIdAndUpdate(jobId, {
      currentGigLink: sourceUrl,
      resumeIndex: i,
      progressPercent: Math.round((i / files.length) * 100),
    });
    await appendJobLog(jobId, `Parsing HTML: ${file.filename}`);

    try {
      const { gig, reviews } = await parseGigFromHtml(html, sourceUrl);
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
          await appendJobLog(jobId, `Lead saved: ${review.reviewerName} (${country})`);
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
    }
  }

  await finishJob(jobId, job.userId, "completed", state.totalLeads);
}
