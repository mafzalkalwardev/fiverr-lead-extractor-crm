import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { findContinuableJobs } from "@/lib/job-continuation";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    const niche = req.nextUrl.searchParams.get("niche")?.trim() || "";

    if (niche.length < 2) {
      return NextResponse.json({ jobs: [] });
    }

    await connectDB();
    const jobs = await findContinuableJobs(
      user._id,
      niche,
      user.role === "admin"
    );

    return NextResponse.json({ jobs });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to load continuation jobs" },
      { status: 500 }
    );
  }
}
