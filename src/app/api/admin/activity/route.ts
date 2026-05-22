import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { requireAdmin, forbiddenResponse } from "@/lib/auth";
import ActivityLog from "@/models/ActivityLog";

export async function GET(req: NextRequest) {
  try {
    await requireAdmin(req);
    await connectDB();
    const logs = await ActivityLog.find()
      .populate("userId", "name email")
      .sort({ createdAt: -1 })
      .limit(200);
    return NextResponse.json({ logs });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Failed to fetch logs" }, { status: 500 });
  }
}
