import ScrapeJob from "@/models/ScrapeJob";

export async function appendJobLog(jobId: string, message: string): Promise<void> {
  const line = `[${new Date().toISOString().slice(11, 19)}] ${message}`;
  console.log(`[job ${jobId}] ${message}`);
  await ScrapeJob.findByIdAndUpdate(jobId, {
    $push: { activityLog: { $each: [line], $slice: -50 } },
  });
}
