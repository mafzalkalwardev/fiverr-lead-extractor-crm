import "@/lib/load-env";
import { Worker } from "bullmq";
import { createRedisConnection } from "@/queue/connection";
import { SCRAPE_QUEUE_NAME } from "@/queue/scrapeQueue";
import { warmBrowser } from "@/scraper/live/browser";
import { processScrapeJob } from "./processJob";

const connection = createRedisConnection();
const redisUrl = process.env.REDIS_URL || "redis://127.0.0.1:6380";

async function setHeartbeat() {
  try {
    await connection.set("worker:heartbeat", String(Date.now()), "EX", 30);
  } catch {
    /* ignore */
  }
}

const worker = new Worker(
  SCRAPE_QUEUE_NAME,
  async (bullJob) => {
    const { jobId } = bullJob.data as { jobId: string };
    console.log(`[worker] Bull job received scrape-${jobId}`);
    await setHeartbeat();
    await processScrapeJob(jobId);
    console.log(`[worker] Finished scrape job ${jobId}`);
  },
  { connection, concurrency: 1 }
);

worker.on("failed", (job, err) => {
  console.error(`[worker] Bull job ${job?.id} failed:`, err.message);
});

worker.on("completed", (job) => {
  console.log(`[worker] Bull job ${job?.id} completed`);
});

setInterval(setHeartbeat, 10_000);
setHeartbeat();

console.log(`[worker] Started. Redis: ${redisUrl}`);
console.log(`[worker] SCRAPER_MODE=${process.env.SCRAPER_MODE || "playwright"}`);
console.log(`[worker] PLAYWRIGHT_HEADLESS=${process.env.PLAYWRIGHT_HEADLESS ?? "false"}`);
console.log("[worker] Waiting for jobs...");
console.log("[worker] First time? Run: npm run setup:browser (complete Fiverr verification once)");

warmBrowser().catch((err) => {
  console.warn("[worker] Browser warm-up failed (will retry on first job):", err);
});
