import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import ScrapeJob from "@/models/ScrapeJob";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const job = await ScrapeJob.findOneAndUpdate(
      { _id: id, userId: user._id, status: "running" },
      { status: "paused" },
      { new: true }
    );

    if (!job) {
      return NextResponse.json({ error: "Job not found or not running" }, { status: 400 });
    }

    return NextResponse.json({ job });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") {
      return authErrorResponse();
    }
    return NextResponse.json({ error: "Failed to pause job" }, { status: 500 });
  }
}
