import { NextResponse } from "next/server";
import { connectDB, isDbConnectionError } from "@/lib/db";
import { createRedisConnection, isRedisConnectionError } from "@/queue/connection";
import { getScraperMode } from "@/lib/scraper-mode";

export async function GET() {
  let mongoOk = false;
  let redisOk = false;
  let workerAlive = false;

  try {
    await connectDB();
    mongoOk = true;
  } catch (e) {
    if (!isDbConnectionError(e)) console.error("[system/status] mongo:", e);
  }

  try {
    const redis = createRedisConnection();
    await redis.ping();
    const hb = await redis.get("worker:heartbeat");
    if (hb) {
      const age = Date.now() - parseInt(hb, 10);
      workerAlive = age < 35_000;
    }
    redisOk = true;
    await redis.quit();
  } catch (e) {
    if (!isRedisConnectionError(e)) console.error("[system/status] redis:", e);
  }

  return NextResponse.json({
    mongo: mongoOk,
    redis: redisOk,
    worker: workerAlive,
    scraperMode: getScraperMode(),
    message: workerAlive
      ? "Worker is running"
      : "Worker not detected — run: npm run worker",
  });
}
