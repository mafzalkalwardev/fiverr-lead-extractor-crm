/** Enforce server-side caps from env. Use 0 for maxGigs = all gigs from all search pages. */
export function clampJobLimits(input: {
  maxGigs: number;
  maxReviewsPerGig: number;
  maxTotalLeads: number;
  delaySeconds: number;
}) {
  const maxGigsLimit = Number(process.env.MAX_GIGS_LIMIT ?? 0);
  const maxReviewsLimit = Number(process.env.MAX_REVIEWS_PER_GIG_LIMIT) || 500;
  const maxLeadsLimit = Number(process.env.MAX_TOTAL_LEADS_LIMIT) || 500;
  const minDelay = Number(process.env.DEFAULT_DELAY_SECONDS) || 1;

  const maxReviewsPerGig =
    input.maxReviewsPerGig <= 0
      ? 0
      : Math.min(Math.max(1, input.maxReviewsPerGig), maxReviewsLimit);

  let maxGigs = 0;
  if (input.maxGigs > 0) {
    const cap = maxGigsLimit > 0 ? maxGigsLimit : 99999;
    maxGigs = Math.min(Math.max(1, input.maxGigs), cap);
  }

  return {
    maxGigs,
    maxReviewsPerGig,
    maxTotalLeads: Math.min(Math.max(1, input.maxTotalLeads), maxLeadsLimit),
    delaySeconds: Math.max(minDelay, Math.min(input.delaySeconds, 30)),
  };
}
