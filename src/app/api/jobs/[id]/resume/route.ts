import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import ScrapeJob from "@/models/ScrapeJob";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const job = await ScrapeJob.findOneAndUpdate(
      { _id: id, userId: user._id, status: "paused" },
      { status: "running" },
      { new: true }
    );

    if (!job) {
      return NextResponse.json({ error: "Job not found or not paused" }, { status: 400 });
    }

    await enqueueScrapeJob(job._id.toString());

    return NextResponse.json({ job });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") {
      return authErrorResponse();
    }
    return NextResponse.json({ error: "Failed to resume job" }, { status: 500 });
  }
}
