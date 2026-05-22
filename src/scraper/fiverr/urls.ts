const FIVERR_ORIGIN = "https://www.fiverr.com";

const BLOCKED_PATH_PREFIXES = new Set([
  "search",
  "categories",
  "users",
  "support",
  "login",
  "join",
  "inbox",
  "collections",
  "pro",
  "cp",
  "cart",
  "checkout",
]);

/** Build Fiverr search URL for a niche keyword */
export function buildFiverrSearchUrl(keyword: string): string {
  const q = encodeURIComponent(keyword.trim());
  return `${FIVERR_ORIGIN}/search/gigs?query=${q}&source=top-bar`;
}

/** Normalize relative Fiverr paths to full HTTPS URLs */
export function normalizeFiverrUrl(href: string): string | null {
  if (!href || href.startsWith("javascript:")) return null;
  try {
    const url = href.startsWith("http")
      ? new URL(href)
      : new URL(href, FIVERR_ORIGIN);
    if (!url.hostname.includes("fiverr.com")) return null;
    url.hash = "";
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length < 2) return null;
    if (BLOCKED_PATH_PREFIXES.has(parts[0].toLowerCase())) return null;
    // Gig: /seller_username/gig-slug (min 2 segments, seller not a reserved word)
    if (parts.length >= 2 && !BLOCKED_PATH_PREFIXES.has(parts[0].toLowerCase())) {
      return `${FIVERR_ORIGIN}/${parts.join("/")}`;
    }
    return null;
  } catch {
    return null;
  }
}

export function isDemoPlaceholderUrl(url: string): boolean {
  if (!url) return false;
  return /demo\.ftsolutions\.local|example\.com|placeholder/i.test(url);
}

export function absolutizeUrl(src: string | null | undefined): string {
  if (!src) return "";
  if (src.startsWith("//")) return `https:${src}`;
  if (src.startsWith("/")) return `${FIVERR_ORIGIN}${src}`;
  return src;
}
