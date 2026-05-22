import Lead from "@/models/Lead";
import type { ReviewData, GigData } from "@/scraper/types";
import { isValidRealLead } from "./lead-validation";
import type { Types } from "mongoose";

/** Dedupe: Gig Link + Reviewer Name + Review */
export function buildDedupeKey(
  gigLink: string,
  reviewerName: string,
  review: string
): string {
  return [gigLink, reviewerName, review]
    .map((s) => s.trim().toLowerCase())
    .join("|||");
}

export function normalizeCountry(country: string): string {
  const c = country.trim();
  if (!c) return "";
  if (/^us$|^usa$|^u\.s\.?$|^united states/i.test(c)) return "United States";
  if (/^ca$|^canada$/i.test(c)) return "Canada";
  return c;
}

export function isTargetCountry(
  reviewerCountry: string,
  targetCountries: string[]
): boolean {
  const country = normalizeCountry(reviewerCountry);
  if (!country) return false;
  const targets = targetCountries.map(normalizeCountry);
  return targets.some((t) => t.toLowerCase() === country.toLowerCase());
}

export interface LeadInput {
  jobId: Types.ObjectId;
  userId: Types.ObjectId;
  niche: string;
  gig: GigData;
  review: ReviewData;
}

export async function saveLeadIfQualified(
  input: LeadInput,
  targetCountries: string[]
): Promise<{ saved: boolean; country: string }> {
  const country = normalizeCountry(input.review.reviewerCountry);
  if (!country || !isTargetCountry(country, targetCountries)) {
    return { saved: false, country };
  }

  if (!isValidRealLead(input.gig, input.review)) {
    return { saved: false, country };
  }

  const sellerName = (input.gig.sellerName || input.gig.sellerUsername || "").trim();
  const dedupeKey = buildDedupeKey(
    input.gig.gigUrl,
    input.review.reviewerName.trim(),
    input.review.reviewText.trim()
  );

  try {
    await Lead.create({
      jobId: input.jobId,
      userId: input.userId,
      sellerName,
      gigLink: input.gig.gigUrl.trim(),
      gigTitle: input.gig.gigTitle.trim(),
      reviewerName: input.review.reviewerName.trim(),
      country,
      review: input.review.reviewText.trim(),
      reviewRating: input.review.reviewRating,
      reviewDate: input.review.reviewDate,
      reviewedImageLink: (input.review.reviewedImageLink || "").trim(),
      mainGigImage: (input.gig.mainGigImage || "").trim(),
      serviceNiche: input.niche,
      scrapedAt: new Date(),
      dedupeKey,
    });
    return { saved: true, country };
  } catch (err) {
    if ((err as { code?: number }).code === 11000) {
      return { saved: false, country };
    }
    throw err;
  }
}

export function countLeadByCountry(country: string): "us" | "canada" | "other" {
  const c = normalizeCountry(country).toLowerCase();
  if (c === "united states") return "us";
  if (c === "canada") return "canada";
  return "other";
}
