import "@/lib/load-env";
import { connectDB } from "@/lib/db";
import mongoose from "mongoose";

async function main() {
  await connectDB();
  const col = mongoose.connection.collection("scrapejobs");
  const result = await col.updateMany(
    {
      $or: [
        { niche: /\[DEMO\]/i },
        { keyword: /\[DEMO\]/i },
        { extractionMode: "demo" },
      ],
    },
    { $set: { isLegacyDemo: true } }
  );
  console.log(`Marked ${result.modifiedCount} legacy demo jobs`);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
