import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { logActivity } from "@/lib/activityLog";
import { appendJobLog } from "@/lib/jobLog";
import { createRedisConnection } from "@/queue/connection";
import ScrapeJob from "@/models/ScrapeJob";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const query =
      user.role === "admin" ? { _id: id } : { _id: id, userId: user._id };
    const job = await ScrapeJob.findOneAndUpdate(
      query,
      { status: "stopped" },
      { new: true }
    );

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    await logActivity("job_stopped", `Job ${id} stopped`, user._id);
    await appendJobLog(id, "Manual stop requested. Worker will close the persistent browser session.");

    try {
      const redis = createRedisConnection();
      await redis.set("browser:shutdown", `manual stop:${id}`, "EX", 60).finally(() => redis.quit());
    } catch {
      // Redis unavailable (Python scraper mode) — job status already updated in MongoDB
    }

    return NextResponse.json({ job });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to stop job" }, { status: 500 });
  }
}
