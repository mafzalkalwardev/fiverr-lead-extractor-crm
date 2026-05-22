/**
 * Quick test: manual URL job (most reliable).
 * Edit GIG_URLS below, then: npm run test:manual
 */
import "@/lib/load-env";
import { connectDB } from "@/lib/db";
import { processScrapeJob } from "../src/worker/processJob";
import ScrapeJob from "@/models/ScrapeJob";
import User from "@/models/User";
import Lead from "@/models/Lead";

// Paste real Fiverr gig URLs here (from your normal browser)
const GIG_URLS = [
  "https://www.fiverr.com/search/gigs?query=car%20wrap",
];

async function main() {
  if (GIG_URLS[0]?.includes("/search/")) {
    console.error("Replace GIG_URLS with actual gig URLs like:");
    console.error("https://www.fiverr.com/USERNAME/gig-slug");
    process.exit(1);
  }

  await connectDB();
  const user = await User.findOne({ email: process.env.ADMIN_EMAIL || "admin@ftsolutions.local" });
  if (!user) {
    console.error("Run: npm run seed:admin");
    process.exit(1);
  }

  const job = await ScrapeJob.create({
    userId: user._id,
    niche: "car wrap",
    extractionMode: "manual_urls",
    manualGigUrls: GIG_URLS,
    gigQueue: GIG_URLS,
    targetCountries: ["United States", "Canada"],
    maxGigs: GIG_URLS.length,
    maxReviewsPerGig: 15,
    maxTotalLeads: 50,
    delaySeconds: 3,
    status: "pending",
  });

  console.log("Job:", job._id.toString());
  await processScrapeJob(job._id.toString());

  const final = await ScrapeJob.findById(job._id);
  const leads = await Lead.countDocuments({ jobId: job._id });
  console.log("Status:", final?.status);
  console.log("Leads:", leads, "| Gigs:", final?.gigsScanned);
  process.exit(leads > 0 ? 0 : 1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
