import type { GigData, ReviewData } from "@/scraper/types";

const BAD_SELLER = /^(fiverr|customer support|seller|reviews?)$/i;
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

export function usernameFromGigUrl(url: string): string {
  try {
    const parts = new URL(url).pathname.split("/").filter(Boolean);
    if (!parts.length) return "";
    const first = parts[0].toLowerCase();
    if (BLOCKED_PATH_PREFIXES.has(first)) return "";
    return parts[0];
  } catch {
    return "";
  }
}
const BAD_REVIEWER = /^(fiverr|seller|buyer|repeat client|seller'?s response|seller response|\d+(\.\d+)?|[1-5](?:\.\d)?\s*(?:stars?|rating|\/\s*5)?)$/i;

function looksLikeRating(value: string): boolean {
  const n = value.trim();
  if (!n) return true;
  if (/^\d+(\.\d+)?$/.test(n)) return true;
  if (/^[1-5](?:\.\d)?$/.test(n)) return true;
  return false;
}

function slugKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function nameIsSeller(name: string, sellerUsername: string): boolean {
  const seller = slugKey(sellerUsername);
  if (!seller) return false;
  return slugKey(name) === seller;
}

function inferReviewerFromText(reviewText: string, sellerUsername: string): string {
  const text = reviewText.trim();
  if (text.length < 20) return "";
  const patterns = [
    /(?:great experience with|experience with|pleasure with|working with|thanks to|recommend)\s+([A-Za-z][A-Za-z0-9_'. -]{1,50})/i,
    /^([A-Za-z][A-Za-z0-9_'.-]*(?:\s+[A-Za-z][A-Za-z0-9_.'-]+){0,3})\s+(?:did|was|is|has|truly|really|always|delivered|provided|went|made|took|helped|gave|exceptional|fantastic|great|excellent|outstanding|once|just|another|absolute)\b/i,
    /^([A-Za-z][A-Za-z0-9_'.-]{1,40})\s+truly\b/i,
  ];
  for (const pat of patterns) {
    const m = text.match(pat);
    if (!m) continue;
    const name = m[1].trim().replace(/^@/, "").replace(/\.$/, "");
    if (nameIsSeller(name, sellerUsername)) continue;
    if (name.length >= 2 && !looksLikeRating(name) && !BAD_REVIEWER.test(name)) return name;
  }
  return "";
}

function reviewerNameBeforeCountry(text: string): string {
  const raw = text.trim();
  const m = raw.match(/\b(United States|USA|U\.S\.?|Canada)\b/i);
  if (!m || m.index === undefined || m.index <= 0) return "";
  let before = raw.slice(0, m.index).trim().replace(/^[1-5](?:\.\d)?\s*/, "");
  before = before.replace(/\brepeat client\b/gi, " ").trim();
  const words = before.split(/\s+/);
  for (let n = Math.min(4, words.length); n >= 1; n--) {
    const cand = words.slice(-n).join(" ").replace(/^[A-Z]\s+(?=[A-Za-z0-9_'.-]{2,})/, "");
    if (cand.length >= 2 && !looksLikeRating(cand) && !BAD_REVIEWER.test(cand)) return cand;
  }
  return before.length >= 2 && !looksLikeRating(before) && !BAD_REVIEWER.test(before) ? before : "";
}

export function sellerNameFromGig(gig: Pick<GigData, "gigUrl">): string {
  const slug = usernameFromGigUrl(gig.gigUrl);
  if (!slug || slug.toLowerCase() === "fiverr" || looksLikeRating(slug)) return "";
  return slug;
}

export function resolveReviewerName(
  review: Pick<ReviewData, "reviewerName" | "reviewText">,
  gig: Pick<GigData, "gigUrl" | "sellerUsername" | "sellerName">
): string {
  const seller = usernameFromGigUrl(gig.gigUrl) || (gig.sellerUsername || "").trim();
  const cardText = (review.reviewText || "").trim();
  const fromCountry = reviewerNameBeforeCountry(cardText);
  if (fromCountry) return fromCountry;
  const raw = (review.reviewerName || "").trim().replace(/^@/, "");
  if (raw && !looksLikeRating(raw) && !BAD_REVIEWER.test(raw)) return raw;
  return inferReviewerFromText(review.reviewText || "", seller);
}
const REVIEW_IMAGE = /delivery|attachments|attachment|t_delivery|t_smartwm|review/i;
const GENERIC_FIVERR_IMAGE_HOST = /cloudinary|fiverr-res|fiverrstatic/i;
const GIG_IMAGE_MARKER = /\/gigs\/|t_main|gig_card|gig-card|gig_cards|gig-cards/i;

function isFiverrUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && (url.hostname === "fiverr.com" || url.hostname.endsWith(".fiverr.com"));
  } catch {
    return false;
  }
}

/** Strict validation: only complete Fiverr-extracted leads may be saved. */
export function isValidRealLead(gig: GigData, review: ReviewData): boolean {
  if (!isFiverrUrl(gig.gigUrl)) return false;

  const seller = sellerNameFromGig(gig);
  if (!seller || seller.length < 2 || BAD_SELLER.test(seller)) return false;

  const title = (gig.gigTitle || "").trim();
  if (!title || title.length < 3) return false;

  const reviewer = resolveReviewerName(review, gig);
  if (!reviewer || reviewer.length < 2 || BAD_REVIEWER.test(reviewer) || looksLikeRating(reviewer))
    return false;

  const text = (review.reviewText || "").trim();
  if (!text || text.length < 15) return false;

  const country = review.reviewerCountry?.trim();
  if (country !== "United States" && country !== "Canada") return false;
  if (!Number.isFinite(review.reviewRating) || review.reviewRating <= 0 || review.reviewRating > 5) return false;

  const img = (review.reviewedImageLink || "").trim();
  if (!img) return true;
  if (!img.startsWith("http") || /trophy|generic_asset|avatar|profile|seller|agency|\.gif/i.test(img)) {
    return false;
  }
  if (GIG_IMAGE_MARKER.test(img) && !REVIEW_IMAGE.test(img)) {
    return false;
  }
  if (
    !REVIEW_IMAGE.test(img) &&
    !(GENERIC_FIVERR_IMAGE_HOST.test(img) && /\.(jpg|jpeg|png|webp)/i.test(img) && !GIG_IMAGE_MARKER.test(img))
  ) {
    return false;
  }

  return true;
}
