import type { Page } from "playwright";
import { sleep } from "@/lib/utils";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";
import { normalizeFiverrUrl } from "../fiverr/urls";

const VERIFICATION_TEXT =
  /press\s*(?:&|and)\s*hold|human verification|verify you are human|checking your browser|perimeterx|captcha|access denied|human touch|complete the task|px-captcha/i;

async function pageText(page: Page, limit = 8000): Promise<string> {
  const title = await page.title().catch(() => "");
  const body = await page.locator("body").innerText({ timeout: 1500 }).catch(() => "");
  return `${title}\n${body}`.slice(0, limit);
}

async function hasAny(page: Page, selector: string): Promise<boolean> {
  return (await page.locator(selector).count().catch(() => 0)) > 0;
}

export async function isVerificationPage(page: Page): Promise<boolean> {
  const url = page.url();
  const text = await pageText(page);
  if (VERIFICATION_TEXT.test(`${url}\n${text}`)) return true;

  return hasAny(
    page,
    [
      "#px-captcha",
      '[id*="captcha" i]',
      '[class*="captcha" i]',
      'iframe[src*="captcha" i]',
      'iframe[src*="perimeterx" i]',
      'iframe[src*="px-captcha" i]',
    ].join(", ")
  );
}

export async function isGigPageReady(page: Page): Promise<boolean> {
  if (!normalizeFiverrUrl(page.url())) return false;
  if (await isVerificationPage(page)) return false;

  const titleText =
    (await page.locator("h1").first().innerText({ timeout: 1500 }).catch(() => "")) ||
    (await page
      .locator('[data-testid*="gig-title" i], [class*="gig-title" i]')
      .first()
      .innerText({ timeout: 1500 })
      .catch(() => ""));
  if (titleText.replace(/\s+/g, " ").trim().length < 3) return false;

  const hasSellerSignal = await hasAny(
    page,
    [
      '[data-testid*="seller" i] a[href]',
      '[data-testid*="profile" i] a[href]',
      '[class*="seller" i] a[href]',
      '[class*="profile" i] a[href]',
      'a[aria-label*="seller" i]',
      "main a[href]",
    ].join(", ")
  );

  const hasReviewOrRatingSignal = await hasAny(
    page,
    [
      '[id*="review" i]',
      '[class*="review" i]',
      '[data-testid*="review" i]',
      '[aria-label*="rating" i]',
      '[class*="rating" i]',
      '[class*="star" i]',
    ].join(", ")
  );

  return hasSellerSignal || hasReviewOrRatingSignal;
}

export async function waitForVerificationToClear(
  page: Page,
  jobId: string
): Promise<"cleared" | "stopped"> {
  await appendJobLog(jobId, "Waiting for Fiverr verification...");

  while (true) {
    const job = await ScrapeJob.findById(jobId).select("status currentGigLink").lean();
    if (!job || job.status === "stopped") {
      await appendJobLog(jobId, "Verification watcher stopped because the job was stopped.");
      return "stopped";
    }

    if (await isVerificationPage(page)) {
      await appendJobLog(jobId, "Waiting for Fiverr verification...");
      await sleep(2000);
      continue;
    }

    // Verification page is gone, captcha solved
    await ScrapeJob.findByIdAndUpdate(jobId, {
      status: "extracting_reviews",
      verificationMessage: "",
    });
    await appendJobLog(jobId, "Verification completed. Continuing extraction...");
    
    if (job.currentGigLink) {
      try {
        await appendJobLog(jobId, "Redirecting back to target gig URL...");
        await page.goto(job.currentGigLink, { waitUntil: "domcontentloaded", timeout: 45000 });
        await sleep(2500);
      } catch (err) {
        await appendJobLog(jobId, "Failed to navigate back automatically. Will retry...");
      }
    }
    
    return "cleared";
  }
}
