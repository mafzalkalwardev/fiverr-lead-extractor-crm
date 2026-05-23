import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { buildLeadsExcel } from "@/lib/exportLeads";
import { logActivity } from "@/lib/activityLog";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    await connectDB();

    const buffer = await buildLeadsExcel(
      user.role === "admin" ? {} : { userId: user._id }
    );
    await logActivity("export_downloaded", "All leads export", user._id);

    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": 'attachment; filename="fiverr-leads-all.xlsx"',
      },
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Export failed" }, { status: 500 });
  }
}
