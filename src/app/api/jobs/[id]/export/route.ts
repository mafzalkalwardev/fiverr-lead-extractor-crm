import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { buildLeadsExcel } from "@/lib/exportLeads";
import { logActivity } from "@/lib/activityLog";
import ScrapeJob from "@/models/ScrapeJob";

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

    const buffer = await buildLeadsExcel({ jobId: job._id });
    await logActivity("export_downloaded", `Job ${id} leads export`, user._id);

    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="fiverr-leads-${job.niche.replace(/\s+/g, "-")}.xlsx"`,
      },
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Export failed" }, { status: 500 });
  }
}
