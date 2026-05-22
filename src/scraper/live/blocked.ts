import type { Page } from "playwright";
import { ScraperVerificationRequiredError } from "../types";

/** Press & hold / CAPTCHA / human touch — user must solve manually */
export async function isVerificationRequired(page: Page): Promise<boolean> {
  await page.waitForTimeout(500);
  const title = await page.title().catch(() => "");
  const body = (await page.locator("body").innerText().catch(() => "")).slice(0, 8000);

  return (
    /human touch/i.test(title) ||
    /human touch/i.test(body) ||
    /press\s*&\s*hold/i.test(body) ||
    /press and hold/i.test(body) ||
    /human verification/i.test(body) ||
    /complete the task/i.test(body) ||
    /pxcr\d+/i.test(body) ||
    /#px-captcha/i.test(body)
  );
}

/** Access denied without interactive verification */
export async function isHardBlocked(page: Page): Promise<boolean> {
  const url = page.url();
  const body = (await page.locator("body").innerText().catch(() => "")).slice(0, 5000);
  return (
    /access denied/i.test(body) ||
    /unusual traffic/i.test(body) ||
    /sign in to continue/i.test(body) ||
    /challenge/i.test(url)
  );
}

export async function assertPageAccessible(page: Page): Promise<void> {
  if (await isVerificationRequired(page)) {
    throw new ScraperVerificationRequiredError();
  }
  if (await isHardBlocked(page)) {
    throw new ScraperVerificationRequiredError(
      "Fiverr access denied or sign-in verification required. Complete verification in the browser window, then Retry."
    );
  }
}
