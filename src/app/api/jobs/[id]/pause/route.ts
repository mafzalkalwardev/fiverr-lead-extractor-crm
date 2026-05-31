import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { appendJobLog } from "@/lib/jobLog";
import ScrapeJob from "@/models/ScrapeJob";

const PAUSABLE_STATUSES = [
  "running",
  "discovering_gigs",
  "extracting_reviews",
  "verification_required",
];

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
        ? { _id: id, status: { $in: PAUSABLE_STATUSES } }
        : { _id: id, userId: user._id, status: { $in: PAUSABLE_STATUSES } };

    const job = await ScrapeJob.findOneAndUpdate(
      query,
      { status: "paused" },
      { new: true }
    );

    if (!job) {
      return NextResponse.json(
        { error: "Job not found or cannot be paused in current status" },
        { status: 400 }
      );
    }

    await appendJobLog(id, "User paused the job. Worker will stop after current safe checkpoint.");

    return NextResponse.json({ job });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") {
      return authErrorResponse();
    }
    return NextResponse.json({ error: "Failed to pause job" }, { status: 500 });
  }
}
