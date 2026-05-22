import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { requireAdmin, forbiddenResponse, authErrorResponse } from "@/lib/auth";
import ScrapeJob from "@/models/ScrapeJob";

export async function GET(req: NextRequest) {
  try {
    await requireAdmin(req);
    await connectDB();
    const jobs = await ScrapeJob.find()
      .populate("userId", "name email")
      .sort({ createdAt: -1 });
    return NextResponse.json({ jobs });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to fetch jobs" }, { status: 500 });
  }
}
