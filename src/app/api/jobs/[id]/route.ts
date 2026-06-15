import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { clampJobLimits } from "@/lib/limits";
import { normalizeJob } from "@/lib/dashboard";
import ScrapeJob from "@/models/ScrapeJob";

const EDITABLE_STATUSES = [
  "pending",
  "paused",
  "stopped",
  "lead_limit_reached",
  "retry_required",
  "verification_required",
  "failed",
  "completed",
];

export async function PATCH(
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

    if (!EDITABLE_STATUSES.includes(job.status)) {
      return NextResponse.json(
        { error: "Cannot edit job limits while it is actively running" },
        { status: 400 }
      );
    }

    const body = await req.json();
    const limits = clampJobLimits({
      maxGigs: job.maxGigs,
      maxReviewsPerGig: job.maxReviewsPerGig,
      maxTotalLeads:
        body.maxTotalLeads !== undefined
          ? Number(body.maxTotalLeads)
          : job.maxTotalLeads,
      delaySeconds: job.delaySeconds,
    });

    if (limits.maxTotalLeads <= (job.totalLeadsFound ?? 0)) {
      return NextResponse.json(
        {
          error: `maxTotalLeads must be greater than current leads (${job.totalLeadsFound ?? 0})`,
        },
        { status: 400 }
      );
    }

    await ScrapeJob.findByIdAndUpdate(id, { maxTotalLeads: limits.maxTotalLeads });
    const raw = await ScrapeJob.findById(id).lean();
    return NextResponse.json({ job: normalizeJob(raw as Record<string, unknown>) });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to update job" }, { status: 500 });
  }
}

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
