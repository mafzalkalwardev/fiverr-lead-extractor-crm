export const EXTRACTION_MODES = ["live", "manual_urls", "html_import"] as const;
export type ExtractionMode = (typeof EXTRACTION_MODES)[number];

export const EXTRACTION_MODE_LABELS: Record<ExtractionMode, string> = {
  live: "Automatic Search (recommended)",
  manual_urls: "Paste Gig Links",
  html_import: "HTML Import (admin only)",
};

/** Modes shown on Create Job — no HTML upload for end clients */
export const CLIENT_EXTRACTION_MODES = ["live", "manual_urls"] as const;

export const VERIFICATION_MESSAGE =
  "Complete Fiverr verification in opened browser. Do NOT close browser window. When verification is complete, click Retry.";

export function parseGigUrlsFromText(text: string): string[] {
  const urls = text.match(/https?:\/\/[^\s]+/g) || [];
  const seen = new Set<string>();
  return urls
    .map((u) => u.replace(/[),.;]+$/, "").trim())
    .filter((u) => u.includes("fiverr.com") && !seen.has(u) && seen.add(u));
}
