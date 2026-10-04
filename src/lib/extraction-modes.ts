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
  // Accept http(s), www., and bare fiverr.com/seller/gig paths pasted one per line
  const raw = text
    .split(/[\n\r,;\t]+/)
    .map((line) => line.trim())
    .filter(Boolean);

  const urls: string[] = [];
  for (const line of raw) {
    const match = line.match(/https?:\/\/[^\s]+/i);
    if (match) {
      urls.push(match[0].replace(/[),.;]+$/, "").trim());
      continue;
    }
    if (/^(www\.)?fiverr\.com\//i.test(line)) {
      urls.push(`https://${line.replace(/^www\./i, "")}`);
      continue;
    }
    if (/^[a-zA-Z0-9._-]+\/[a-zA-Z0-9._-]+/.test(line) && !line.includes(" ")) {
      // seller/gig-slug without host
      urls.push(`https://www.fiverr.com/${line}`);
    }
  }

  const seen = new Set<string>();
  return urls.filter((u) => {
    const key = u.toLowerCase();
    if (!key.includes("fiverr.com") || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
