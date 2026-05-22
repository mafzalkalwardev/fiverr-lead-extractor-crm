/** Live scraper mode. */

export type ScraperMode = "playwright";

export function getScraperMode(): ScraperMode {
  const mode = (process.env.SCRAPER_MODE || "playwright").toLowerCase();
  if (mode !== "playwright") {
    throw new Error(`SCRAPER_MODE must be playwright; received ${mode}`);
  }
  return "playwright";
}

export function assertLiveScraperMode(): void {
  getScraperMode();
}

export function isPlaywrightMode(): boolean {
  return true;
}
