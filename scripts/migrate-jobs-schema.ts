/**
 * Migrate legacy ScrapeJob docs: keyword/category -> niche, jobErrors -> errors
 * Run: npx tsx scripts/migrate-jobs-schema.ts
 */
import "@/lib/load-env";
import { connectDB } from "@/lib/db";
import mongoose from "mongoose";

async function main() {
  await connectDB();
  const col = mongoose.connection.collection("scrapejobs");

  const cursor = col.find({});
  let updated = 0;
  for await (const doc of cursor) {
    const set: Record<string, unknown> = {};
    if (!doc.niche && doc.keyword) set.niche = doc.keyword;
    if (!doc.niche && doc.category) set.niche = doc.category;
    if (!doc.errors && doc.jobErrors) set.errors = doc.jobErrors;
    if (doc.keyword !== undefined || doc.category !== undefined) {
      await col.updateOne(
        { _id: doc._id },
        {
          $set: Object.keys(set).length ? set : {},
          $unset: { keyword: "", category: "" },
        }
      );
      updated++;
    } else if (Object.keys(set).length) {
      await col.updateOne({ _id: doc._id }, { $set: set });
      updated++;
    }
  }
  console.log(`Migrated ${updated} job documents`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
