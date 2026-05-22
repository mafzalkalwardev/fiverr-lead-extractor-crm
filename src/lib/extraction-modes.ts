export const EXTRACTION_MODES = ["live", "manual_urls", "html_import"] as const;
export type ExtractionMode = (typeof EXTRACTION_MODES)[number];

export const EXTRACTION_MODE_LABELS: Record<ExtractionMode, string> = {
  live: "Live Mode (Playwright search)",
  manual_urls: "Manual Browser Mode (paste gig URLs)",
  html_import: "HTML Import Mode (upload saved pages)",
};

export const VERIFICATION_MESSAGE =
  "Fiverr verification required. Complete it in the opened browser, then click Retry.";

export function parseGigUrlsFromText(text: string): string[] {
  const urls = text.match(/https?:\/\/[^\s]+/g) || [];
  const seen = new Set<string>();
  return urls
    .map((u) => u.replace(/[),.;]+$/, "").trim())
    .filter((u) => u.includes("fiverr.com") && !seen.has(u) && seen.add(u));
}

export function isLegacyDemoJob(job: {
  niche?: string;
  extractionMode?: string;
  isLegacyDemo?: boolean;
}): boolean {
  if (job.isLegacyDemo) return true;
  if (job.extractionMode === "demo") return true;
  return /\[DEMO\]/i.test(job.niche || "");
}
