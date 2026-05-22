import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import ScrapeJob from "@/models/ScrapeJob";
import Lead from "@/models/Lead";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const user = await getAuthUser(req);
    const { id } = await params;
    await connectDB();

    const jobQuery =
      user.role === "admin" ? { _id: id } : { _id: id, userId: user._id };
    const job = await ScrapeJob.findOne(jobQuery);
    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    const leads = await Lead.find({ jobId: id }).sort({ scrapedAt: -1 });
    return NextResponse.json({ leads });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to fetch leads" }, { status: 500 });
  }
}
