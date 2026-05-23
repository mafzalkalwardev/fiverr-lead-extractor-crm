export const EXTRACTION_MODES = ["live", "manual_urls", "html_import"] as const;
export type ExtractionMode = (typeof EXTRACTION_MODES)[number];

export const EXTRACTION_MODE_LABELS: Record<ExtractionMode, string> = {
  live: "Automatic Search (recommended)",
  manual_urls: "Paste Gig Links",
  html_import: "HTML Import (admin only)",
};

/** Modes shown on Create Job — no HTML upload for end clients */
export const CLIENT_EXTRACTION_MODES = ["live", "manual_urls"] as const;

export const REVIEW_IMAGE_MODES = ["with_image", "without_image"] as const;
export type ReviewImageMode = (typeof REVIEW_IMAGE_MODES)[number];

export const REVIEW_IMAGE_MODE_LABELS: Record<ReviewImageMode, string> = {
  with_image: "With review image link",
  without_image: "Without review image link",
};

export const VERIFICATION_MESSAGE =
  "Complete Fiverr verification in the opened browser. The app will continue automatically. Do NOT close browser window.";

export function parseGigUrlsFromText(text: string): string[] {
  const urls = text.match(/https?:\/\/[^\s]+/g) || [];
  const seen = new Set<string>();
  return urls
    .map((u) => u.replace(/[),.;]+$/, "").trim())
    .filter((u) => u.includes("fiverr.com") && !seen.has(u) && seen.add(u));
}
