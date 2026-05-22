import path from "path";
import { chromium, type BrowserContext, type Page } from "playwright";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

let sharedContext: BrowserContext | null = null;

export function isHeadless(): boolean {
  if (process.env.PLAYWRIGHT_HEADLESS === "true") return true;
  if (process.env.PLAYWRIGHT_HEADLESS === "false") return false;
  return process.env.NODE_ENV === "production";
}

/** Persistent profile — login/verify once, reuse for all jobs */
export function getProfileDir(): string {
  return path.join(process.cwd(), "browser-profile");
}

export async function launchBrowser(): Promise<BrowserContext> {
  if (sharedContext) return sharedContext;

  const profileDir = getProfileDir();
  const headless = isHeadless();
  console.log(`[browser] Persistent profile: ${profileDir} (headless=${headless})`);

  sharedContext = await chromium.launchPersistentContext(profileDir, {
    headless,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    userAgent: USER_AGENT,
    viewport: { width: 1440, height: 900 },
    locale: "en-US",
    timezoneId: "America/New_York",
    args: ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    extraHTTPHeaders: { "Accept-Language": "en-US,en;q=0.9" },
    ignoreDefaultArgs: ["--enable-automation"],
  });

  return sharedContext;
}

export async function getBrowserContext(): Promise<BrowserContext> {
  return launchBrowser();
}

export async function newLivePage(): Promise<Page> {
  const ctx = await getBrowserContext();
  const page = await ctx.newPage();
  page.setDefaultTimeout(60_000);
  page.setDefaultNavigationTimeout(90_000);
  return page;
}

/** Keep profile open after verification — user retries in same session */
export async function closeBrowser(force = false): Promise<void> {
  if (!force && process.env.KEEP_BROWSER_PROFILE === "true") return;
  if (sharedContext) {
    await sharedContext.close().catch(() => {});
    sharedContext = null;
  }
}
