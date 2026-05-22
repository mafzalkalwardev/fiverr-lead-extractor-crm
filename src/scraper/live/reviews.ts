import type { Page, Locator } from "playwright";
import type { ReviewData } from "../types";
import { sleep } from "@/lib/utils";
import { normalizeCountry } from "@/lib/leads";
import { assertPageAccessible } from "./blocked";
import { absolutizeUrl } from "../fiverr/urls";

const REVIEW_CARD_SELECTORS = [
  '[data-testid*="review-card" i]',
  '[class*="review-card" i]',
  '[class*="review-item" i]',
  'article[class*="review" i]',
  'li[class*="review" i]',
  '[data-testid*="review" i]',
  ".review-item",
  "article",
  "li",
];

const COUNTRY_SELECTORS = [
  '[class*="country" i]',
  '[class*="location" i]',
  '[class*="flag" i]',
  '[data-testid*="country" i]',
  '[data-testid*="location" i]',
];

const REVIEWER_SELECTORS = [
  '[data-testid*="reviewer" i] a[href]',
  '[data-testid*="reviewer" i]',
  '[class*="reviewer" i] a[href]',
  '[class*="reviewer" i]',
  '[class*="username" i]',
  '[class*="user-name" i]',
  '[class*="user_name" i]',
  'a[href^="/"] strong',
  'a[href^="/"]',
  "strong",
  "b",
  "h4",
  "h5",
];

const REVIEW_TEXT_SELECTORS = [
  '[data-testid*="review-comment" i]',
  '[data-testid*="review-text" i]',
  '[class*="review-description" i]',
  '[class*="review-text" i]',
  '[class*="comment" i]',
  '[class*="description" i] p',
  '[class*="content" i] p',
  '[dir="auto"]',
  "p",
];

interface RawReview {
  reviewerName: string;
  reviewerCountry: string;
  reviewText: string;
  reviewRating: number;
  reviewDate: string;
  reviewedImageLink: string;
}

interface ReviewCandidate {
  card: Locator;
  text: string;
  countryHint: string;
}

export interface ReviewExtractionResult {
  reviews: ReviewData[];
  reviewsChecked: number;
}

function cleanText(value: string | null | undefined): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function cleanCountryText(value: string): string {
  return cleanText(value)
    .replace(/\bflag\s+of\b/gi, "")
    .replace(/\bflag\b/gi, "")
    .replace(/\bcountry\b/gi, "")
    .replace(/^from\s+/i, "")
    .replace(/^location\s*:?\s*/i, "")
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function textKey(value: string): string {
  return cleanText(value).toLowerCase().slice(0, 180);
}

function normalizeTargetCountry(value: string, allowShortCode: boolean): string {
  const text = cleanCountryText(value);
  if (!text) return "";

  if (/\b(united states|usa|u\.s\.a\.|u\.s\.)\b/i.test(text)) return "United States";
  if (/\bcanada\b/i.test(text)) return "Canada";
  if (allowShortCode && /^(us|u\.s\.|usa|u\.s\.a\.)$/i.test(text)) return "United States";
  if (allowShortCode && /^ca$/i.test(text)) return "Canada";
  return "";
}

async function rawLocatorText(locator: Locator): Promise<string> {
  return (
    (await locator.innerText({ timeout: 1200 }).catch(() => null)) ||
    (await locator.textContent({ timeout: 1200 }).catch(() => null)) ||
    ""
  );
}

async function locatorText(locator: Locator): Promise<string> {
  return cleanText(await rawLocatorText(locator));
}

async function readTexts(root: Locator, selector: string, limit = 12): Promise<string[]> {
  const locator = root.locator(selector);
  const count = Math.min(await locator.count().catch(() => 0), limit);
  const values: string[] = [];

  for (let i = 0; i < count; i++) {
    const raw = await rawLocatorText(locator.nth(i));
    const lines = raw
      .split(/\r?\n/)
      .map(cleanText)
      .filter(Boolean);
    for (const line of lines) values.push(line);
    const compact = cleanText(raw);
    if (compact) values.push(compact);
  }

  return values;
}

async function readAttributes(
  root: Locator,
  selector: string,
  attrs: string[],
  limit = 40
): Promise<string[]> {
  const locator = root.locator(selector);
  const count = Math.min(await locator.count().catch(() => 0), limit);
  const values: string[] = [];

  for (let i = 0; i < count; i++) {
    const item = locator.nth(i);
    for (const attr of attrs) {
      const value = await item.getAttribute(attr).catch(() => null);
      if (value) values.push(value);
    }
  }

  return values;
}

/** Scroll to reviews block */
export async function scrollToReviews(page: Page): Promise<void> {
  const reviewsTab = page.getByRole("tab", { name: /reviews/i }).first();
  if (await reviewsTab.isVisible().catch(() => false)) {
    await reviewsTab.click().catch(() => {});
    await sleep(1200);
  }

  const reviewsBtn = page
    .locator('a:has-text("Reviews"), button:has-text("Reviews")')
    .first();
  if (await reviewsBtn.isVisible().catch(() => false)) {
    await reviewsBtn.click().catch(() => {});
    await sleep(1200);
  }

  const reviewsSection = page
    .locator(
      '#reviews, [id*="review" i], [class*="reviews" i], [data-testid*="review" i]'
    )
    .first();
  if (await reviewsSection.count().catch(() => 0)) {
    await reviewsSection.scrollIntoViewIfNeeded({ timeout: 4000 }).catch(() => {});
  }

  await sleep(2000);

  for (let i = 0; i < 5; i++) {
    await page.mouse.wheel(0, 800);
    await sleep(500);
  }
}

/** Click load-more on reviews (limited) */
export async function clickLoadMoreReviews(page: Page, maxClicks = 8): Promise<void> {
  const buttonText =
    'button:has-text("Show more"), button:has-text("See more"), button:has-text("Load more"), button:has-text("Show More"), button:has-text("More reviews")';

  for (let i = 0; i < maxClicks; i++) {
    const more = page.locator(buttonText).first();
    if (!(await more.isVisible().catch(() => false))) break;
    await more.click().catch(() => {});
    await sleep(1200);
    await page.mouse.wheel(0, 600).catch(() => {});
  }
}

function imageFromSrcset(value: string | null): string {
  if (!value) return "";
  const first = value.split(",").map((part) => part.trim().split(/\s+/)[0]).find(Boolean);
  return first || "";
}

/** Extract image URL from review card */
export async function extractReviewImage(reviewElement: Locator): Promise<string> {
  const images = reviewElement.locator("img");
  const count = Math.min(await images.count().catch(() => 0), 25);

  for (let i = 0; i < count; i++) {
    const img = images.nth(i);
    const src =
      (await img.getAttribute("src").catch(() => null)) ||
      (await img.getAttribute("data-src").catch(() => null)) ||
      imageFromSrcset(await img.getAttribute("srcset").catch(() => null));
    const full = absolutizeUrl(src);
    if (full && !/avatar|profile|icon|flag|badge|svg/i.test(full)) return full;
  }

  return "";
}

async function findCountry(card: Locator, cardText: string): Promise<string> {
  const attrCandidates = await readAttributes(
    card,
    "img, [aria-label], [title]",
    ["alt", "aria-label", "title"],
    60
  );
  const textCandidates: string[] = [];
  for (const selector of COUNTRY_SELECTORS) {
    textCandidates.push(...(await readTexts(card, selector, 12)));
  }

  for (const candidate of [...attrCandidates, ...textCandidates]) {
    const country = normalizeTargetCountry(candidate, true);
    if (country) return country;
  }

  const phraseMatch = cardText.match(
    /\b(?:from|located in|based in)\s+(United States|U\.S\.A\.|U\.S\.|USA|Canada|CA)\b/i
  );
  if (phraseMatch) {
    const country = normalizeTargetCountry(phraseMatch[1], true);
    if (country) return country;
  }

  return normalizeTargetCountry(cardText, false);
}

function parseRatingSource(source: string): number {
  const text = cleanText(source);
  if (!text) return 0;

  const contextual = text.match(/\b([1-5](?:\.\d)?)\b(?=.*\b(?:stars?|rating|out of 5)\b)/i);
  const fraction = text.match(/\b([1-5](?:\.\d)?)\s*\/\s*5\b/i);
  const compact = text.length <= 8 ? text.match(/\b([1-5](?:\.\d)?)\b/) : null;
  const match = contextual || fraction || compact;
  const rating = match ? parseFloat(match[1]) : 0;
  return rating >= 1 && rating <= 5 ? rating : 0;
}

async function findRating(card: Locator, cardText: string): Promise<number> {
  const sources = await readAttributes(
    card,
    '[aria-label*="star" i], [aria-label*="rating" i], [title*="star" i], [title*="rating" i], [class*="star" i], [class*="rating" i]',
    ["aria-label", "title"],
    30
  );
  sources.push(
    ...(await readTexts(
      card,
      '[aria-label*="star" i], [aria-label*="rating" i], [title*="star" i], [title*="rating" i], [class*="star" i], [class*="rating" i]',
      20
    ))
  );

  for (const source of sources) {
    const rating = parseRatingSource(source);
    if (rating) return rating;
  }

  return parseRatingSource(cardText);
}

function isLikelyReviewerName(value: string): boolean {
  const text = cleanText(value).replace(/^@/, "");
  if (text.length < 2 || text.length > 60) return false;
  if (/^(from|seller|buyer|reviews?|helpful|show more|see more|contact|order|rating)$/i.test(text)) {
    return false;
  }
  if (/^(united states|canada|usa|u\.s\.a?\.?|ca)$/i.test(text)) return false;
  if (/\b(stars?|rating|review|from|ago|day|days|week|weeks|month|months|year|years)\b/i.test(text)) {
    return false;
  }
  if (text.split(/\s+/).length > 6) return false;
  return true;
}

async function findReviewerName(card: Locator): Promise<string> {
  for (const selector of REVIEWER_SELECTORS) {
    const locator = card.locator(selector);
    const count = Math.min(await locator.count().catch(() => 0), 10);

    for (let i = 0; i < count; i++) {
      const raw = await rawLocatorText(locator.nth(i));
      const candidates = [
        ...raw.split(/\r?\n/).map(cleanText),
        cleanText(raw),
      ].filter(Boolean);

      for (const candidate of candidates) {
        const value = candidate.replace(/^@/, "");
        if (isLikelyReviewerName(value)) return value;
      }
    }
  }

  return "";
}

function stripKnownReviewChrome(text: string, reviewerName: string, country: string): string {
  let value = cleanText(text);
  for (const token of [reviewerName, country, "United States", "Canada"]) {
    if (token) value = value.replace(new RegExp(escapeRegExp(token), "ig"), " ");
  }
  return cleanText(
    value
      .replace(/\b(?:from|located in|based in)\s+(?:United States|U\.S\.A\.|U\.S\.|USA|Canada|CA)\b/gi, " ")
      .replace(/\b[1-5](?:\.\d)?\s*(?:\/\s*5|stars?|rating)\b/gi, " ")
      .replace(/\b(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\s+ago\b/gi, " ")
      .replace(/\b(show more|see more|helpful)\b/gi, " ")
  );
}

async function findReviewText(
  card: Locator,
  reviewerName: string,
  country: string,
  cardText: string
): Promise<string> {
  const bodyCandidates: string[] = [];

  for (const selector of REVIEW_TEXT_SELECTORS) {
    const texts = await readTexts(card, selector, 20);
    for (const value of texts) {
      const text = cleanText(value);
      if (text.length >= 10 && text.length < 2000) bodyCandidates.push(text);
    }
  }

  const best = bodyCandidates
    .filter((value) => value !== reviewerName && value !== country)
    .filter((value) => !/^(show more|see more|helpful)$/i.test(value))
    .filter((value) => !/^\d+(?:\.\d)?$/.test(value))
    .sort((a, b) => b.length - a.length)[0];

  if (best) return best.slice(0, 2000);

  const fallback = stripKnownReviewChrome(cardText, reviewerName, country);
  return fallback.length >= 10 ? fallback.slice(0, 2000) : "";
}

async function findReviewDate(card: Locator, cardText: string): Promise<string> {
  const time = card.locator("time").first();
  const datetime =
    (await time.getAttribute("datetime").catch(() => null)) ||
    (await time.getAttribute("title").catch(() => null)) ||
    (await locatorText(time).catch(() => ""));
  if (datetime) return datetime;

  const dateTexts = await readTexts(card, '[class*="date" i], [data-testid*="date" i], [class*="time" i]', 10);
  for (const value of dateTexts) {
    if (/\b(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\s+ago\b/i.test(value)) {
      return value;
    }
    if (/\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b/i.test(value)) {
      return value;
    }
  }

  const relative = cardText.match(
    /\b(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\s+ago\b/i
  );
  return relative?.[0] || "";
}

async function collectReviewCandidates(page: Page, maxReviews: number): Promise<ReviewCandidate[]> {
  const maxCards = Math.max(maxReviews * 8, 40);
  const candidates: ReviewCandidate[] = [];
  const seenCards = new Set<string>();

  for (const selector of REVIEW_CARD_SELECTORS) {
    if (candidates.length >= maxCards) break;

    const locator = page.locator(selector);
    const count = Math.min(await locator.count().catch(() => 0), 100);

    for (let i = 0; i < count; i++) {
      if (candidates.length >= maxCards) break;

      const card = locator.nth(i);
      const text = await locatorText(card);
      const key = textKey(text);
      if (text.length < 30 || text.length > 3500 || !key || seenCards.has(key)) continue;

      const className = (await card.getAttribute("class").catch(() => null)) || "";
      const id = (await card.getAttribute("id").catch(() => null)) || "";
      const testId = (await card.getAttribute("data-testid").catch(() => null)) || "";
      const hasReviewMarker = /review/i.test(`${className} ${id} ${testId}`);
      const countryHint = await findCountry(card, text);
      const rating = await findRating(card, text);
      if (!hasReviewMarker && !countryHint && !rating) continue;

      seenCards.add(key);
      candidates.push({ card, text, countryHint });
    }
  }

  return candidates;
}

async function parseReviewCandidate(
  candidate: ReviewCandidate,
  index: number
): Promise<RawReview | null> {
  const reviewerCountry = candidate.countryHint || (await findCountry(candidate.card, candidate.text));
  if (reviewerCountry) {
    console.log(`[live] Review ${index + 1} country found: ${reviewerCountry}`);
  }
  if (!reviewerCountry) return null;

  const targetCountry = normalizeCountry(reviewerCountry);
  if (targetCountry !== "United States" && targetCountry !== "Canada") return null;

  const reviewerName = await findReviewerName(candidate.card);
  const reviewRating = await findRating(candidate.card, candidate.text);
  const reviewText = await findReviewText(
    candidate.card,
    reviewerName,
    targetCountry,
    candidate.text
  );
  const reviewDate = await findReviewDate(candidate.card, candidate.text);
  const reviewedImageLink = await extractReviewImage(candidate.card);

  if (!reviewerName || reviewerName.length < 2) return null;
  if (!reviewRating || reviewRating < 1 || reviewRating > 5) return null;
  if (!reviewText || reviewText.length < 10) return null;

  return {
    reviewerName,
    reviewerCountry: targetCountry,
    reviewText: reviewText.slice(0, 2000),
    reviewRating,
    reviewDate,
    reviewedImageLink,
  };
}

/** Extract visible public reviews and keep only US/Canada reviewers. */
export async function extractReviewsWithStats(
  page: Page,
  maxReviews: number,
  options?: { offlineHtml?: boolean }
): Promise<ReviewExtractionResult> {
  if (maxReviews <= 0) return { reviews: [], reviewsChecked: 0 };

  await scrollToReviews(page);
  await clickLoadMoreReviews(page);
  if (!options?.offlineHtml) {
    await assertPageAccessible(page);
  }

  const candidates = await collectReviewCandidates(page, maxReviews);
  console.log(`[live] Review container count: ${candidates.length}`);

  const raw: RawReview[] = [];
  let reviewsChecked = 0;
  for (let i = 0; i < candidates.length; i++) {
    if (raw.length >= maxReviews) break;
    reviewsChecked += 1;
    const parsed = await parseReviewCandidate(candidates[i], i);
    if (parsed) raw.push(parsed);
  }

  console.log(`[live] Review candidates parsed: ${reviewsChecked}`);

  const seen = new Set<string>();
  const reviews: ReviewData[] = [];
  for (const r of raw) {
    const country = normalizeCountry(r.reviewerCountry);
    if (country !== "United States" && country !== "Canada") continue;

    let reviewDate: Date | undefined;
    if (r.reviewDate) {
      const d = new Date(r.reviewDate);
      if (!isNaN(d.getTime())) reviewDate = d;
    }

    const key = `${r.reviewerName.trim().toLowerCase()}|${r.reviewText.trim().toLowerCase().slice(0, 100)}`;
    if (seen.has(key)) continue;
    seen.add(key);

    reviews.push({
      reviewerName: r.reviewerName.trim(),
      reviewerCountry: country,
      reviewRating: r.reviewRating,
      reviewText: r.reviewText.trim(),
      reviewDate,
      reviewedImageLink: absolutizeUrl(r.reviewedImageLink),
    });
  }

  console.log(`[live] Parsed ${reviews.length} US/Canada reviews`);
  return { reviews, reviewsChecked };
}

/** Extract visible public reviews. */
export async function extractReviews(
  page: Page,
  maxReviews: number,
  options?: { offlineHtml?: boolean }
): Promise<ReviewData[]> {
  const { reviews } = await extractReviewsWithStats(page, maxReviews, options);
  return reviews;
}
