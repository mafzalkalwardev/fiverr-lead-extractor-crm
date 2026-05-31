import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";

const RESUMABLE_STATUSES = ["paused", "retry_required"];

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const query =
      user.role === "admin"
        ? { _id: id, status: { $in: RESUMABLE_STATUSES } }
        : { _id: id, userId: user._id, status: { $in: RESUMABLE_STATUSES } };

    const job = await ScrapeJob.findOneAndUpdate(
      query,
      { status: "pending", verificationMessage: "" },
      { new: true }
    );

    if (!job) {
      return NextResponse.json(
        { error: "Job not found or not in a resumable state (paused/retry_required)" },
        { status: 400 }
      );
    }

    await appendJobLog(id, `User resumed job from gig ${job.resumeIndex ?? 0}/${job.gigQueue?.length ?? 0}. Continuing from last checkpoint.`);

    await enqueueScrapeJob(job._id.toString());

    return NextResponse.json({ job });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") {
      return authErrorResponse();
    }
    return NextResponse.json({ error: "Failed to resume job" }, { status: 500 });
  }
}
