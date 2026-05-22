/** Live scraper mode — demo/mock modes are disabled */

export type ScraperMode = "playwright";

export function getScraperMode(): ScraperMode {
  const mode = (process.env.SCRAPER_MODE || "playwright").toLowerCase();
  if (mode === "demo" || mode === "mock" || mode === "test") {
    throw new Error(
      `SCRAPER_MODE=${mode} is disabled. This app only supports live extraction. Set SCRAPER_MODE=playwright`
    );
  }
  return "playwright";
}

export function assertLiveScraperMode(): void {
  getScraperMode();
}

export function isPlaywrightMode(): boolean {
  return true;
}
