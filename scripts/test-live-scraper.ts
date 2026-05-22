/**
 * Smoke test: real Fiverr search.
 * Run: npx tsx scripts/test-live-scraper.ts
 */
import "@/lib/load-env";
import { LiveFiverrScraper } from "@/scraper/live/scraper";

async function main() {
  const scraper = new LiveFiverrScraper();
  const keyword = process.argv[2] || "car wrap";
  console.log(`Testing LIVE search for: ${keyword}`);

  const gigs = await scraper.searchFiverrGigs(keyword, 3);
  console.log("Gig URLs found:", gigs.length);
  gigs.forEach((g, i) => console.log(`  ${i + 1}. ${g.gigUrl}`));

  if (gigs.length === 0) {
    console.error("FAIL: No gig URLs — blocked or selectors need update");
    process.exit(1);
  }

  const first = gigs[0].gigUrl;
  const { gig, reviews } = await scraper.processGig(first, 5);
  console.log("\nGig metadata:");
  console.log("  Seller:", gig.sellerName);
  console.log("  Title:", gig.gigTitle?.slice(0, 80));
  console.log("  Image:", gig.mainGigImage?.slice(0, 80) || "(none)");
  console.log(`\nReviews parsed: ${reviews.length}`);
  reviews.slice(0, 3).forEach((r, i) => {
    console.log(`  ${i + 1}. ${r.reviewerName} | ${r.reviewerCountry} | ${r.reviewText.slice(0, 60)}...`);
  });

  await scraper.close();
  console.log("\nPASS: Live scraper returned real Fiverr data");
  process.exit(0);
}

main().catch((e) => {
  console.error("FAIL:", e);
  process.exit(1);
});
