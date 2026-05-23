import { NextResponse } from "next/server";
import mongoose from "mongoose";
import { connectDB, isDbConnectionError } from "@/lib/db";
import { createRedisConnection, isRedisConnectionError } from "@/queue/connection";
import { getScraperEngine } from "@/lib/scraper-engine";
import { getScraperMode } from "@/lib/scraper-mode";

const PYTHON_HEARTBEAT_ID = "python_scraper";
const HEARTBEAT_MAX_AGE_MS = 35_000;

type HeartbeatDoc = {
  _id: string;
  ts?: Date | string | number;
};

export async function GET() {
  let mongoOk = false;
  let redisOk = false;
  let workerAlive = false;
  let scraperEngine: "python" | "node" | "none" = "none";

  try {
    await connectDB();
    mongoOk = true;

    const db = mongoose.connection.db;
    if (db) {
      const hb = await db
        .collection<HeartbeatDoc>("system_heartbeats")
        .findOne({ _id: PYTHON_HEARTBEAT_ID });
      if (hb?.ts) {
        const ts = hb.ts instanceof Date ? hb.ts.getTime() : new Date(String(hb.ts)).getTime();
        if (Date.now() - ts < HEARTBEAT_MAX_AGE_MS) {
          workerAlive = true;
          scraperEngine = "python";
        }
      }
    }
  } catch (e) {
    if (!isDbConnectionError(e)) console.error("[system/status] mongo:", e);
  }

  if (!workerAlive) {
    try {
      const redis = createRedisConnection();
      await redis.ping();
      const hb = await redis.get("worker:heartbeat");
      if (hb) {
        const age = Date.now() - parseInt(hb, 10);
        if (age < HEARTBEAT_MAX_AGE_MS) {
          workerAlive = true;
          scraperEngine = "node";
        }
      }
      redisOk = true;
      await redis.quit();
    } catch (e) {
      if (!isRedisConnectionError(e)) console.error("[system/status] redis:", e);
    }
  }

  const message = workerAlive
    ? scraperEngine === "python"
      ? "Python scraper is running"
      : "Node worker is running (legacy)"
    : "Scraper not running - start: npm run scraper:py";

  const configuredEngine = getScraperEngine();

  return NextResponse.json({
    mongo: mongoOk,
    redis: redisOk,
    worker: workerAlive,
    scraperEngine,
    configuredEngine,
    scraperMode: getScraperMode(),
    message:
      configuredEngine === "python" && scraperEngine === "node"
        ? "Warning: Node worker is running but SCRAPER_ENGINE=python. Stop npm run worker."
        : message,
  });
}
