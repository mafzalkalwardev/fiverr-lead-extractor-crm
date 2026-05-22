import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { connectDB } from "@/lib/db";
import { requireAdmin, forbiddenResponse } from "@/lib/auth";
import { logActivity } from "@/lib/activityLog";
import User from "@/models/User";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const admin = await requireAdmin(req);
    const { id } = await params;
    const body = await req.json();
    await connectDB();

    const update: Record<string, unknown> = {};
    if (body.status === "active" || body.status === "inactive") {
      update.status = body.status;
    }
    if (body.name) update.name = body.name;
    if (body.role === "admin" || body.role === "user") update.role = body.role;

    const user = await User.findByIdAndUpdate(id, update, { new: true }).select(
      "-passwordHash"
    );
    if (!user) {
      return NextResponse.json({ error: "User not found" }, { status: 404 });
    }

    if (body.status === "active") {
      await logActivity("user_activated", user.email, admin._id);
    } else if (body.status === "inactive") {
      await logActivity("user_deactivated", user.email, admin._id);
    }

    return NextResponse.json({ user });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Update failed" }, { status: 500 });
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  /** Reset password — POST with { password } */
  try {
    const admin = await requireAdmin(req);
    const { id } = await params;
    const { password } = await req.json();
    if (!password || password.length < 6) {
      return NextResponse.json({ error: "Password min 6 chars" }, { status: 400 });
    }

    await connectDB();
    const user = await User.findByIdAndUpdate(
      id,
      { passwordHash: await bcrypt.hash(password, 12) },
      { new: true }
    ).select("-passwordHash");

    if (!user) {
      return NextResponse.json({ error: "User not found" }, { status: 404 });
    }

    await logActivity("password_reset", `Reset password for ${user.email}`, admin._id);
    return NextResponse.json({ user });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Reset failed" }, { status: 500 });
  }
}
