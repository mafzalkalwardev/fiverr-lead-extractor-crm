import path from "path";
import { chromium, type BrowserContext, type Page } from "playwright";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

const KEEP_ALIVE_INTERVAL_MS = 15_000;

export function isBrowserClosedError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /has been closed|Target.*closed|browser has been closed|Browser closed|context.*closed/i.test(msg);
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

function pageIsUsable(page: Page | null): page is Page {
  return !!page && !page.isClosed();
}

function configurePage(page: Page): Page {
  page.setDefaultTimeout(60_000);
  page.setDefaultNavigationTimeout(120_000);
  return page;
}

export class BrowserManager {
  private context: BrowserContext | null = null;
  private activePage: Page | null = null;
  private launching: Promise<BrowserContext> | null = null;
  private keepAliveTimer: NodeJS.Timeout | null = null;
  private pausedForVerification = false;

  async getPersistentContext(): Promise<BrowserContext> {
    if (this.context && contextIsAlive(this.context)) {
      console.log("[browser] Persistent context reused");
      return this.context;
    }

    if (this.context) {
      console.warn("[browser] Persistent context reference was stale; reconnecting to profile");
      this.context = null;
      this.activePage = null;
    }

    if (this.launching) return this.launching;

    this.launching = (async () => {
      const profileDir = getProfileDir();
      const headless = isHeadless();
      console.log(`[browser] Creating persistent browser context`);
      console.log(`[browser] Persistent profile loaded: ${profileDir}`);

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

      ctx.on("page", (page) => {
        this.activePage = configurePage(page);
        page.on("close", () => {
          if (this.activePage === page) this.activePage = null;
          console.warn("[browser] Active page closed by user or browser");
        });
      });
      ctx.on("close", () => {
        console.warn("[browser] Persistent browser context closed");
        this.context = null;
        this.activePage = null;
        this.pausedForVerification = false;
      });

      this.context = ctx;
      const existing = ctx.pages().find((page) => !page.isClosed());
      if (existing) this.activePage = configurePage(existing);
      this.keepBrowserAlive();

      console.log(`[browser] Browser created (headless=${headless})`);
      return ctx;
    })();

    try {
      return await this.launching;
    } finally {
      this.launching = null;
    }
  }

  async getOrCreatePage(): Promise<Page> {
    const ctx = await this.getPersistentContext();

    if (pageIsUsable(this.activePage)) {
      console.log("[browser] Reusing existing Fiverr page");
      return configurePage(this.activePage);
    }

    const existing = ctx.pages().find((page) => !page.isClosed());
    if (existing) {
      this.activePage = configurePage(existing);
      console.log("[browser] Reconnected to existing persistent page");
      return this.activePage;
    }

    this.activePage = configurePage(await ctx.newPage());
    console.log("[browser] Created persistent page");
    return this.activePage;
  }

  keepBrowserAlive(): void {
    if (this.keepAliveTimer) return;
    this.keepAliveTimer = setInterval(() => {
      void (async () => {
        try {
          if (!this.context || !contextIsAlive(this.context)) return;
          await this.getOrCreatePage();
        } catch (err) {
          console.warn("[browser] Keep-alive check failed:", err);
        }
      })();
    }, KEEP_ALIVE_INTERVAL_MS);
    this.keepAliveTimer.unref?.();
    console.log("[browser] Keep-alive enabled");
  }

  async pauseWithoutClosing(reason = "verification_required"): Promise<void> {
    this.pausedForVerification = true;
    const page = await this.getOrCreatePage();
    await page.bringToFront().catch(() => {});
    console.log(`[browser] Verification detected; waiting for user (${reason})`);
    console.log("[browser] Browser remains open. Do NOT close the Chrome window.");
  }

  async continueExistingSession(): Promise<Page> {
    const page = await this.getOrCreatePage();
    await page.bringToFront().catch(() => {});
    this.pausedForVerification = false;
    console.log("[browser] Session resumed using existing persistent page");
    return page;
  }

  async closeBrowser(reason = "manual stop or app shutdown"): Promise<void> {
    console.log(`[browser] Closing persistent browser (${reason})`);
    if (this.keepAliveTimer) {
      clearInterval(this.keepAliveTimer);
      this.keepAliveTimer = null;
    }
    this.launching = null;
    const ctx = this.context;
    this.context = null;
    this.activePage = null;
    this.pausedForVerification = false;
    await ctx?.close().catch(() => {});
  }
}

export const browserManager = new BrowserManager();

export async function getPersistentContext(): Promise<BrowserContext> {
  return browserManager.getPersistentContext();
}

export async function getOrCreatePage(): Promise<Page> {
  return browserManager.getOrCreatePage();
}

export function keepBrowserAlive(): void {
  browserManager.keepBrowserAlive();
}

export async function pauseWithoutClosing(reason?: string): Promise<void> {
  await browserManager.pauseWithoutClosing(reason);
}

export async function continueExistingSession(): Promise<Page> {
  return browserManager.continueExistingSession();
}

export async function launchBrowser(): Promise<BrowserContext> {
  return getPersistentContext();
}

export async function getBrowserContext(): Promise<BrowserContext> {
  return getPersistentContext();
}

/** Pre-open browser when worker starts so first job does not hit a dead session. */
export async function warmBrowser(): Promise<void> {
  await getPersistentContext();
  await getOrCreatePage();
  console.log("[browser] Ready - keep this window open while jobs run");
}

export async function newLivePage(): Promise<Page> {
  try {
    return await continueExistingSession();
  } catch (err) {
    if (isBrowserClosedError(err)) {
      console.warn("[browser] Existing session unavailable; reconnecting to persistent profile");
      return getOrCreatePage();
    }
    throw err;
  }
}

export async function resetBrowser(): Promise<void> {
  await browserManager.closeBrowser("reset requested");
}

export async function closeBrowser(force = false): Promise<void> {
  if (!force && process.env.KEEP_BROWSER_PROFILE === "true") {
    console.log("[browser] closeBrowser skipped; persistent session stays alive");
    return;
  }
  await browserManager.closeBrowser(force ? "forced close" : "close requested");
}
