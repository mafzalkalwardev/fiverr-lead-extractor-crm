import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { requireAdmin, forbiddenResponse } from "@/lib/auth";
import { logActivity } from "@/lib/activityLog";
import Lead from "@/models/Lead";

export async function GET(req: NextRequest) {
  try {
    await requireAdmin(req);
    await connectDB();
    const { searchParams } = new URL(req.url);
    const jobId = searchParams.get("jobId");
    const userId = searchParams.get("userId");

    const query: Record<string, string> = {};
    if (jobId) query.jobId = jobId;
    if (userId) query.userId = userId;

    const leads = await Lead.find(query).sort({ scrapedAt: -1 }).limit(5000);
    return NextResponse.json({ leads });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Failed to fetch leads" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const admin = await requireAdmin(req);
    const { leadIds, removeDuplicates } = await req.json();
    await connectDB();

    if (removeDuplicates) {
      const all = await Lead.find().lean();
      const seen = new Set<string>();
      const dupIds: string[] = [];
      for (const l of all) {
        const key = [l.gigLink, l.reviewerName, l.review]
          .map((value) => String(value || "").trim().toLowerCase())
          .join("|||");
        const dedupeKey = key || l.dedupeKey;
        if (seen.has(dedupeKey)) dupIds.push(l._id.toString());
        else seen.add(dedupeKey);
      }
      if (dupIds.length) await Lead.deleteMany({ _id: { $in: dupIds } });
      await logActivity("records_deleted", `Removed ${dupIds.length} duplicates`, admin._id);
      return NextResponse.json({ deleted: dupIds.length });
    }

    if (Array.isArray(leadIds) && leadIds.length) {
      const r = await Lead.deleteMany({ _id: { $in: leadIds } });
      await logActivity("records_deleted", `Deleted ${r.deletedCount} leads`, admin._id);
      return NextResponse.json({ deleted: r.deletedCount });
    }

    return NextResponse.json({ error: "No leads specified" }, { status: 400 });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Delete failed" }, { status: 500 });
  }
}
