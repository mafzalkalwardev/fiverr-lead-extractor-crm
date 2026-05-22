import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { normalizeJob } from "@/lib/dashboard";
import ScrapeJob from "@/models/ScrapeJob";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const query =
      user.role === "admin" ? { _id: id } : { _id: id, userId: user._id };
    const raw = await ScrapeJob.findOne(query).lean();
    if (!raw) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    return NextResponse.json({
      job: normalizeJob(raw as Record<string, unknown>),
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to fetch job" }, { status: 500 });
  }
}
