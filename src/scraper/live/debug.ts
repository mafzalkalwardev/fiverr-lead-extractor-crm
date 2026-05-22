import fs from "fs/promises";
import path from "path";
import type { Page } from "playwright";

export interface FailedGigArtifacts {
  screenshotPath: string;
  htmlPath: string;
}

function artifactTimestamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

/** Save page artifacts for selector failures without crashing artifact cleanup. */
export async function saveFailedGigArtifacts(page: Page): Promise<FailedGigArtifacts> {
  const dir = path.join(process.cwd(), "test-results");
  await fs.mkdir(dir, { recursive: true });

  const timestamp = artifactTimestamp();
  const screenshotPath = path.join(dir, `failed-gig-${timestamp}.png`);
  const htmlPath = path.join(dir, `failed-gig-${timestamp}.html`);

  await page.screenshot({ path: screenshotPath, fullPage: true }).catch((err) => {
    console.warn("[live] Failed to save selector failure screenshot:", err);
  });

  const html = await page.content().catch((err) => {
    console.warn("[live] Failed to read selector failure HTML:", err);
    return "";
  });
  if (html) {
    await fs.writeFile(htmlPath, html, "utf-8").catch((err) => {
      console.warn("[live] Failed to save selector failure HTML:", err);
    });
  }

  return { screenshotPath, htmlPath };
}
