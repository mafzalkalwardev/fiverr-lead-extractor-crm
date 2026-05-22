/**
 * End-to-end test: discovery + manual gig extraction
 * Run: npx tsx scripts/test-e2e.ts
 */
import "@/lib/load-env";
import { connectDB } from "@/lib/db";
import { discoverGigUrls } from "@/scraper/discovery";
import { createScraper, closeScraper } from "@/scraper/factory";
import { processScrapeJob } from "@/worker/processJob";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";
import ScrapeJob from "@/models/ScrapeJob";
import User from "@/models/User";
import Lead from "@/models/Lead";

const NICHE = "car wrap";
const TEST_GIGS = [
  "https://www.fiverr.com/graphicdesignbd/design-car-wrap-vehicle-wrap-van-wrap-truck-wrap-bus-wrap",
  "https://www.fiverr.com/rahatmasum/design-car-wrap-van-wrap-truck-wrap-bus-wrap-vehicle-wrap",
];

async function main() {
  console.log("=== E2E Test ===\n");
  await connectDB();

  // 1. Search engine discovery
  console.log("1) Testing gig discovery...");
  try {
    const d = await discoverGigUrls(NICHE, 5);
    console.log(`   Source: ${d.source}, URLs: ${d.gigUrls.length}`);
    d.gigUrls.slice(0, 3).forEach((u, i) => console.log(`   ${i + 1}. ${u}`));
  } catch (e) {
    console.log("   Discovery error:", e instanceof Error ? e.message : e);
  }

  // 2. Single gig extraction
  console.log("\n2) Testing single gig extraction...");
  const scraper = createScraper();
  const testUrl = TEST_GIGS[0];
  try {
    const { gig, reviews } = await scraper.processGig(testUrl, 15);
    console.log(`   Seller: ${gig.sellerName}`);
    console.log(`   Title: ${gig.gigTitle?.slice(0, 60)}`);
    console.log(`   Reviews: ${reviews.length}`);
    const usCa = reviews.filter((r) => /united states|canada/i.test(r.reviewerCountry));
    console.log(`   US/CA reviews: ${usCa.length}`);
    if (usCa[0]) {
      console.log(`   Sample: ${usCa[0].reviewerName} (${usCa[0].reviewerCountry})`);
    }
  } catch (e) {
    console.log("   Gig error:", e instanceof Error ? e.message : e);
  }

  // 3. Full job via worker pipeline (manual URLs)
  console.log("\n3) Testing full job (manual_urls)...");
  const user = await User.findOne({ email: "admin@ftsolutions.local" });
  if (!user) {
    console.log("   SKIP: run npm run seed:admin first");
    process.exit(1);
  }

  const job = await ScrapeJob.create({
    userId: user._id,
    niche: NICHE,
    extractionMode: "manual_urls",
    manualGigUrls: TEST_GIGS,
    gigQueue: TEST_GIGS,
    targetCountries: ["United States", "Canada"],
    maxGigs: 2,
    maxReviewsPerGig: 10,
    maxTotalLeads: 20,
    delaySeconds: 2,
    status: "pending",
  });
  const jobId = job._id.toString();
  console.log(`   Job created: ${jobId}`);

  await processScrapeJob(jobId);

  const final = await ScrapeJob.findById(jobId).lean();
  const leadCount = await Lead.countDocuments({ jobId: job._id });
  console.log(`   Final status: ${final?.status}`);
  console.log(`   Gigs scanned: ${final?.gigsScanned}, Leads: ${leadCount}`);
  console.log(`   US: ${final?.usLeadsFound}, CA: ${final?.canadaLeadsFound}`);

  if (leadCount > 0) {
    const sample = await Lead.findOne({ jobId: job._id }).lean();
    console.log(`   Sample lead: ${sample?.reviewerName} | ${sample?.country}`);
    console.log(`   Gig link: ${sample?.gigLink?.slice(0, 70)}`);
  }

  await closeScraper(true);
  console.log("\n=== Done ===");
  process.exit(leadCount > 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
