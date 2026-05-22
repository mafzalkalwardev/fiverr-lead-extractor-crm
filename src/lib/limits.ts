/** Enforce server-side caps from env */
export function clampJobLimits(input: {
  maxGigs: number;
  maxReviewsPerGig: number;
  maxTotalLeads: number;
  delaySeconds: number;
}) {
  const maxGigsLimit = Number(process.env.MAX_GIGS_LIMIT) || 50;
  const maxReviewsLimit = Number(process.env.MAX_REVIEWS_PER_GIG_LIMIT) || 50;
  const maxLeadsLimit = Number(process.env.MAX_TOTAL_LEADS_LIMIT) || 500;
  const defaultDelay = Number(process.env.DEFAULT_DELAY_SECONDS) || 3;

  return {
    maxGigs: Math.min(Math.max(1, input.maxGigs), maxGigsLimit),
    maxReviewsPerGig: Math.min(Math.max(1, input.maxReviewsPerGig), maxReviewsLimit),
    maxTotalLeads: Math.min(Math.max(1, input.maxTotalLeads), maxLeadsLimit),
    delaySeconds: Math.max(defaultDelay, input.delaySeconds),
  };
}
