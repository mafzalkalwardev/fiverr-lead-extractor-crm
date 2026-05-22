import "@/lib/load-env";
import { newLivePage, closeBrowser } from "@/scraper/live/browser";
import { buildSearchUrl } from "@/scraper/live/search";

async function main() {
  const page = await newLivePage();
  const url = buildSearchUrl("car wrap");
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  const title = await page.title();
  const body = (await page.locator("body").innerText()).slice(0, 1500);
  console.log("URL:", page.url());
  console.log("Title:", title);
  console.log("Body preview:\n", body);
  await page.screenshot({ path: "debug-fiverr.png", fullPage: false });
  console.log("Screenshot: debug-fiverr.png");
  await page.close();
  await closeBrowser();
}

main().catch(console.error);
