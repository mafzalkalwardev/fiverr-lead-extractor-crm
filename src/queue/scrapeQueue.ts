import "@/lib/load-env";
import { Queue } from "bullmq";
import { createRedisConnection } from "./connection";

export const SCRAPE_QUEUE_NAME = "scrape-jobs";

let scrapeQueue: Queue | null = null;

export function getScrapeQueue(): Queue {
  if (!scrapeQueue) {
    scrapeQueue = new Queue(SCRAPE_QUEUE_NAME, {
      connection: createRedisConnection(),
      defaultJobOptions: {
        removeOnComplete: 100,
        removeOnFail: 50,
        attempts: 1,
      },
    });
  }
  return scrapeQueue;
}

export async function enqueueScrapeJob(jobId: string): Promise<void> {
  const queue = getScrapeQueue();
  const bullId = `scrape-${jobId}`;
  const existing = await queue.getJob(bullId);
  if (existing) {
    const state = await existing.getState();
    if (state === "active") {
      console.log(`[queue] Job ${bullId} is already active; not adding duplicate`);
      return;
    }
    await existing.remove().catch((err) => {
      console.warn(`[queue] Could not remove existing job ${bullId} (${state}):`, err);
    });
  }

  const bullJob = await queue.add(
    "process",
    { jobId },
    { jobId: bullId }
  );
  console.log(`[queue] Added job scrape-${jobId} bullId=${bullJob.id}`);
}
