import { NextRequest, NextResponse } from "next/server";
import { connectDB, isDbConnectionError } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { getDashboardStats, normalizeJob } from "@/lib/dashboard";
import { getScraperMode } from "@/lib/scraper-mode";
import ScrapeJob from "@/models/ScrapeJob";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    await connectDB();

    const baseQuery = user.role === "admin" ? {} : { userId: user._id };

    const rawJobs = await ScrapeJob.find(baseQuery).sort({ createdAt: -1 }).lean();
    const jobs = rawJobs.map((j) => normalizeJob(j as Record<string, unknown>));
    const stats = await getDashboardStats(user._id, user.role === "admin");

    return NextResponse.json({ jobs, stats, scraperMode: getScraperMode() });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    if (isDbConnectionError(err)) {
      return NextResponse.json({ error: "Database unavailable" }, { status: 503 });
    }
    console.error("[GET /api/jobs]", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to fetch jobs" },
      { status: 500 }
    );
  }
}
