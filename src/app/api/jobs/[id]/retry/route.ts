import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";

const RETRYABLE_STATUSES = [
  "verification_required",
  "blocked",
  "failed",
  "retry_required",
  "stopped",
];

/** Manual retry — keeps all saved progress (gigQueue, resumeIndex, GigProgress records). */
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
        ? { _id: id, status: { $in: RETRYABLE_STATUSES } }
        : { _id: id, userId: user._id, status: { $in: RETRYABLE_STATUSES } };

    const job = await ScrapeJob.findOne(query);
    if (!job) {
      return NextResponse.json(
        { error: `Cannot retry job — not found or not in a retryable status (${RETRYABLE_STATUSES.join(", ")})` },
        { status: 400 }
      );
    }

    await ScrapeJob.findByIdAndUpdate(id, {
      status: "pending",
      verificationMessage: "",
      lastError: "",
      $inc: { retryCount: 1 },
    });

    await appendJobLog(
      id,
      `Retry #${(job.retryCount ?? 0) + 1} queued — will continue from gig ${job.resumeIndex ?? 0}/${job.gigQueue?.length ?? 0}.`
    );

    await enqueueScrapeJob(id);

    return NextResponse.json({
      ok: true,
      message: "Job re-queued. Worker will continue from saved progress.",
      resumeIndex: job.resumeIndex,
      retryCount: (job.retryCount ?? 0) + 1,
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Retry failed" }, { status: 500 });
  }
}
