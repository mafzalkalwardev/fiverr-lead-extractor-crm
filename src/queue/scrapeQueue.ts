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
  const bullJob = await queue.add(
    "process",
    { jobId },
    { jobId: `scrape-${jobId}` }
  );
  console.log(`[queue] Added job scrape-${jobId} bullId=${bullJob.id}`);
}
