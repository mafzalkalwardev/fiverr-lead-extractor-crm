import "@/lib/load-env";
import { isPythonScraperEngine } from "@/lib/scraper-engine";
import { Worker } from "bullmq";
import { createRedisConnection } from "@/queue/connection";
import { SCRAPE_QUEUE_NAME } from "@/queue/scrapeQueue";
import { closeBrowser, warmBrowser } from "@/scraper/live/browser";
import { processScrapeJob } from "./processJob";

if (isPythonScraperEngine()) {
  console.log(
    "[worker] SCRAPER_ENGINE=python — Node worker disabled. Use: npm run scraper:py"
  );
  process.exit(0);
}

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

async function checkBrowserShutdownRequest() {
  try {
    const reason = await connection.get("browser:shutdown");
    if (!reason) return;
    await connection.del("browser:shutdown");
    console.log(`[worker] Browser shutdown requested: ${reason}`);
    await closeBrowser(true);
  } catch (err) {
    console.warn("[worker] Browser shutdown check failed:", err);
  }
}

setInterval(checkBrowserShutdownRequest, 3_000);

async function shutdown(signal: string) {
  console.log(`[worker] ${signal} received. Closing worker and persistent browser.`);
  await worker.close().catch(() => {});
  await closeBrowser(true).catch(() => {});
  await connection.quit().catch(() => {});
  process.exit(0);
}

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

console.log(`[worker] Started. Redis: ${redisUrl}`);
console.log(`[worker] SCRAPER_MODE=${process.env.SCRAPER_MODE || "playwright"}`);
console.log(`[worker] PLAYWRIGHT_HEADLESS=${process.env.PLAYWRIGHT_HEADLESS ?? "false"}`);
console.log("[worker] Waiting for jobs...");
console.log("[worker] First time? Run: npm run setup:browser (complete Fiverr verification once)");

warmBrowser().catch((err) => {
  console.warn("[worker] Browser warm-up failed (will retry on first job):", err);
});
