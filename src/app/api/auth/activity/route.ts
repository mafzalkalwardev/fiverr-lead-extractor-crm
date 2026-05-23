import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser } from "@/lib/auth";
import ActivityLog from "@/models/ActivityLog";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    await connectDB();
    const logs = await ActivityLog.find({ userId: user._id })
      .sort({ createdAt: -1 })
      .limit(50)
      .lean();
    return NextResponse.json({ logs });
  } catch {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
}
