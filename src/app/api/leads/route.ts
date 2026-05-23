import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import Lead from "@/models/Lead";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    await connectDB();

    const query: Record<string, unknown> = {};
    if (user.role !== "admin") {
      query.userId = user._id;
    }

    const leads = await Lead.find(query).sort({ scrapedAt: -1 }).limit(5000);
    return NextResponse.json({ leads });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    return NextResponse.json({ error: "Failed to fetch leads" }, { status: 500 });
  }
}
