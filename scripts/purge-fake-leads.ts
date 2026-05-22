/**
 * Remove leads that match demo/fake patterns from MongoDB.
 * Run: npx tsx scripts/purge-fake-leads.ts
 */
import "@/lib/load-env";
import { connectDB } from "@/lib/db";
import Lead from "@/models/Lead";

async function main() {
  await connectDB();
  const result = await Lead.deleteMany({
    $or: [
      { gigLink: /demo\.ftsolutions\.local/i },
      { gigLink: /demo_seller/i },
      { sellerName: /\[DEMO\]/i },
      { reviewerName: /\[DEMO\]/i },
      { review: /\[DEMO\]/i },
      { gigLink: /example\.com/i },
    ],
  });
  console.log(`Purged ${result.deletedCount} fake/demo leads`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
