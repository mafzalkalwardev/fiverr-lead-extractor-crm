/**
 * ONE-TIME SETUP: Open Fiverr in persistent browser, complete verification manually.
 * Run: npm run setup:browser
 * Then keep PLAYWRIGHT_HEADLESS=false and npm run worker
 */
import "@/lib/load-env";
import readline from "readline";
import { launchBrowser, getProfileDir, closeBrowser } from "../src/scraper/live/browser";
import { assertPageAccessible, isVerificationRequired } from "../src/scraper/live/blocked";

async function waitForEnter(msg: string) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await new Promise<void>((resolve) => {
    rl.question(msg, () => {
      rl.close();
      resolve();
    });
  });
}

async function main() {
  process.env.PLAYWRIGHT_HEADLESS = "false";
  process.env.KEEP_BROWSER_PROFILE = "true";

  console.log("\n=== Fiverr Browser Profile Setup ===\n");
  console.log("Profile folder:", getProfileDir());
  console.log("A Chromium window will open.\n");
  console.log("1. Complete any 'Press & Hold' / human verification on Fiverr");
  console.log("2. Make sure you can browse fiverr.com normally");
  console.log("3. Return here and press ENTER\n");

  const ctx = await launchBrowser();
  const page = await ctx.newPage();
  await page.goto("https://www.fiverr.com", { waitUntil: "domcontentloaded", timeout: 120_000 });

  const needsVerify = await isVerificationRequired(page);
  if (needsVerify) {
    console.log("\n>>> Verification detected. Complete it in the browser window.\n");
  } else {
    console.log("\n>>> Fiverr loaded — looks OK. Browse to confirm.\n");
  }

  await waitForEnter("Press ENTER when Fiverr works in the browser (no CAPTCHA block): ");

  await page.goto("https://www.fiverr.com/search/gigs?query=car%20wrap", {
    waitUntil: "domcontentloaded",
    timeout: 120_000,
  });

  try {
    await assertPageAccessible(page);
    console.log("\nSUCCESS: Search page accessible. Profile is ready for jobs.\n");
  } catch {
    console.log("\nWARNING: Search still blocked. Use Manual URL or HTML Import mode for jobs.\n");
    console.log("You can re-run: npm run setup:browser\n");
  }

  await waitForEnter("Press ENTER to close setup (profile saved): ");
  await closeBrowser(true);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
