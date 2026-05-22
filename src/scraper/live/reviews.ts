import type { Page, Locator } from "playwright";
import type { ReviewData } from "../types";
import { sleep } from "@/lib/utils";
import { normalizeCountry } from "@/lib/leads";
import { assertPageAccessible } from "./blocked";
import { absolutizeUrl } from "../fiverr/urls";

/** Scroll to reviews block */
export async function scrollToReviews(page: Page): Promise<void> {
  const reviewsTab = page.getByRole("tab", { name: /reviews/i }).first();
  if (await reviewsTab.isVisible().catch(() => false)) {
    await reviewsTab.click().catch(() => {});
    await sleep(1200);
  }

  const reviewsBtn = page.locator('a:has-text("Reviews"), button:has-text("Reviews")').first();
  if (await reviewsBtn.isVisible().catch(() => false)) {
    await reviewsBtn.click().catch(() => {});
    await sleep(1200);
  }

  await page.evaluate(() => {
    const el =
      document.querySelector("#reviews") ||
      document.querySelector('[id*="review" i]') ||
      document.querySelector('[class*="reviews" i]') ||
      document.querySelector('[data-testid*="review" i]');
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  await sleep(2000);

  for (let i = 0; i < 3; i++) {
    await page.mouse.wheel(0, 600);
    await sleep(400);
  }
}

/** Click load-more on reviews (limited) */
export async function clickLoadMoreReviews(page: Page, maxClicks = 6): Promise<void> {
  for (let i = 0; i < maxClicks; i++) {
    const more = page
      .locator(
        'button:has-text("Show more"), button:has-text("See more"), button:has-text("Load more"), button:has-text("Show More")'
      )
      .first();
    if (!(await more.isVisible().catch(() => false))) break;
    await more.click().catch(() => {});
    await sleep(1000);
  }
}

/** Extract image URL from review card */
export async function extractReviewImage(reviewElement: Locator): Promise<string> {
  const img = reviewElement.locator("img").first();
  const src =
    (await img.getAttribute("src").catch(() => null)) ||
    (await img.getAttribute("data-src").catch(() => null));
  if (!src || /avatar|profile|icon|flag/i.test(src)) return "";
  return absolutizeUrl(src);
}

interface RawReview {
  reviewerName: string;
  reviewerCountry: string;
  reviewText: string;
  reviewRating: number;
  reviewDate: string;
  reviewedImageLink: string;
}

/** Extract visible public reviews — no synthetic data */
export async function extractReviews(
  page: Page,
  maxReviews: number,
  options?: { offlineHtml?: boolean }
): Promise<ReviewData[]> {
  await scrollToReviews(page);
  await clickLoadMoreReviews(page);
  if (!options?.offlineHtml) {
    await assertPageAccessible(page);
  }

  const raw: RawReview[] = await page.evaluate((max) => {
    const results: RawReview[] = [];
    const cardSelectors = [
      '[class*="review-card"]',
      'article[class*="review"]',
      'li[class*="review"]',
      '[data-testid*="review"]',
      ".review-item",
    ];

    let cards: Element[] = [];
    for (const sel of cardSelectors) {
      const found = Array.from(document.querySelectorAll(sel));
      if (found.length > cards.length) cards = found;
    }

    const parseCard = (card: Element): RawReview | null => {
      const text = card.textContent?.replace(/\s+/g, " ").trim() || "";
      if (text.length < 20) return null;

      let reviewerName = "";
      const nameEl = card.querySelector(
        '[class*="username"], [class*="user-name"], [class*="reviewer"], a[href*="/"] strong, strong, b, h4, h5'
      );
      if (nameEl) reviewerName = nameEl.textContent?.trim() || "";

      let reviewerCountry = "";
      const countryEl = card.querySelector(
        '[class*="country"], [class*="location"], [class*="flag"], img[alt*="flag" i]'
      );
      if (countryEl) {
        reviewerCountry =
          countryEl.getAttribute("alt")?.replace(/flag/gi, "").trim() ||
          countryEl.textContent?.trim() ||
          "";
      }
      const fromMatch = text.match(/\bfrom\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\s+\d|\s*·|,|\.|$)/i);
      if (fromMatch) reviewerCountry = fromMatch[1].trim();

      let reviewRating = 0;
      const aria = card.querySelector('[aria-label*="star" i], [aria-label*="rating" i]');
      const ariaLabel = aria?.getAttribute("aria-label") || "";
      const ratingMatch = ariaLabel.match(/(\d(?:\.\d)?)/);
      if (ratingMatch) reviewRating = parseFloat(ratingMatch[1]);

      let reviewText = "";
      const bodyEl = card.querySelector(
        '[class*="review-description"], [class*="review-text"], [class*="comment"], p'
      );
      if (bodyEl) reviewText = bodyEl.textContent?.trim() || "";
      if (!reviewText || reviewText.length < 10) {
        reviewText = text.replace(reviewerName, "").trim().slice(0, 2000);
      }

      let reviewDate = "";
      const timeEl = card.querySelector("time");
      if (timeEl) {
        reviewDate = timeEl.getAttribute("datetime") || timeEl.textContent?.trim() || "";
      }

      let reviewedImageLink = "";
      const imgs = card.querySelectorAll("img");
      for (const img of imgs) {
        const src = (img as HTMLImageElement).src || img.getAttribute("data-src") || "";
        if (src && !/avatar|profile|icon|flag|svg/i.test(src)) {
          reviewedImageLink = src;
          break;
        }
      }

      if (!reviewerName || reviewerName.length < 2) return null;
      if (!reviewText || reviewText.length < 10) return null;

      return {
        reviewerName,
        reviewerCountry,
        reviewText: reviewText.slice(0, 2000),
        reviewRating,
        reviewDate,
        reviewedImageLink,
      };
    };

    for (const card of cards) {
      if (results.length >= max) break;
      const r = parseCard(card);
      if (r) results.push(r);
    }
    return results;
  }, maxReviews);

  const reviews: ReviewData[] = [];
  for (const r of raw) {
    const country = normalizeCountry(r.reviewerCountry);
    if (!country) continue;

    let reviewDate = new Date();
    if (r.reviewDate) {
      const d = new Date(r.reviewDate);
      if (!isNaN(d.getTime())) reviewDate = d;
    }

    reviews.push({
      reviewerName: r.reviewerName.trim(),
      reviewerCountry: country,
      reviewRating: r.reviewRating || 0,
      reviewText: r.reviewText.trim(),
      reviewDate,
      reviewedImageLink: absolutizeUrl(r.reviewedImageLink),
    });
  }

  console.log(`[live] Parsed ${reviews.length} reviews with country`);
  return reviews;
}
