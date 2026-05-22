import path from "path";
import { chromium, type BrowserContext, type Page } from "playwright";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

let sharedContext: BrowserContext | null = null;
let launching: Promise<BrowserContext> | null = null;

export function isBrowserClosedError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /has been closed|Target.*closed|browser has been closed|Browser closed/i.test(msg);
}

export function isHeadless(): boolean {
  if (process.env.PLAYWRIGHT_HEADLESS === "true") return true;
  if (process.env.PLAYWRIGHT_HEADLESS === "false") return false;
  return process.env.NODE_ENV === "production";
}

export function getProfileDir(): string {
  return path.join(process.cwd(), "browser-profile");
}

function contextIsAlive(ctx: BrowserContext): boolean {
  try {
    const browser = ctx.browser();
    return browser !== null && browser.isConnected();
  } catch {
    return false;
  }
}

function attachCloseHandler(ctx: BrowserContext): void {
  ctx.on("close", () => {
    if (sharedContext === ctx) sharedContext = null;
  });
}

/** Drop stale reference when user closed the Chrome window */
export async function resetBrowser(): Promise<void> {
  launching = null;
  if (!sharedContext) return;
  const ctx = sharedContext;
  sharedContext = null;
  await ctx.close().catch(() => {});
}

export async function launchBrowser(): Promise<BrowserContext> {
  if (sharedContext && contextIsAlive(sharedContext)) {
    return sharedContext;
  }

  if (sharedContext) {
    await resetBrowser();
  }

  if (launching) return launching;

  launching = (async () => {
    const profileDir = getProfileDir();
    const headless = isHeadless();
    console.log(`[browser] Launching Chrome profile: ${profileDir} (headless=${headless})`);

    const ctx = await chromium.launchPersistentContext(profileDir, {
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

    attachCloseHandler(ctx);
    sharedContext = ctx;
    return ctx;
  })();

  try {
    return await launching;
  } finally {
    launching = null;
  }
}

export async function getBrowserContext(): Promise<BrowserContext> {
  return launchBrowser();
}

/** Pre-open browser when worker starts so first job does not hit a dead session */
export async function warmBrowser(): Promise<void> {
  const ctx = await launchBrowser();
  const pages = ctx.pages();
  if (pages.length === 0) {
    const page = await ctx.newPage();
    await page.goto("about:blank").catch(() => {});
  }
  console.log("[browser] Ready — keep this window open while jobs run");
}

export async function newLivePage(): Promise<Page> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const ctx = await launchBrowser();
      const page = await ctx.newPage();
      page.setDefaultTimeout(60_000);
      page.setDefaultNavigationTimeout(90_000);
      return page;
    } catch (err) {
      lastErr = err;
      if (attempt === 0 && isBrowserClosedError(err)) {
        console.warn("[browser] Session closed — relaunching Chrome…");
        await resetBrowser();
        continue;
      }
      throw err;
    }
  }
  throw lastErr;
}

export async function closeBrowser(force = false): Promise<void> {
  if (!force && process.env.KEEP_BROWSER_PROFILE === "true") return;
  await resetBrowser();
}
