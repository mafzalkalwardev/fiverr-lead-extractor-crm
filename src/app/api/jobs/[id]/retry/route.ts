import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";

/** Manual backup resume after Fiverr verification; keeps saved progress. */
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
    const job = await ScrapeJob.findOne(query);
    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    if (!["verification_required", "blocked", "failed"].includes(job.status)) {
      return NextResponse.json(
        { error: `Cannot retry job in status: ${job.status}` },
        { status: 400 }
      );
    }

    await ScrapeJob.findByIdAndUpdate(id, {
      status: "pending",
      verificationMessage: "",
    });
    await appendJobLog(
      id,
      "Manual retry requested. Worker will continue using the existing persistent browser session."
    );

    await enqueueScrapeJob(id);
    console.log("[POST /api/jobs/retry] re-queued job:", id, "resumeIndex:", job.resumeIndex);

    return NextResponse.json({
      ok: true,
      message: "Job re-queued. Worker will continue from saved progress.",
      resumeIndex: job.resumeIndex,
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Retry failed" }, { status: 500 });
  }
}
