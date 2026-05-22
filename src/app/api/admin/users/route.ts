import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { connectDB } from "@/lib/db";
import { requireAdmin, forbiddenResponse, authErrorResponse } from "@/lib/auth";
import { logActivity } from "@/lib/activityLog";
import User from "@/models/User";

export async function GET(req: NextRequest) {
  try {
    await requireAdmin(req);
    await connectDB();
    const users = await User.find().select("-passwordHash").sort({ createdAt: -1 });
    return NextResponse.json({ users });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Failed to list users" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const admin = await requireAdmin(req);
    const { name, email, password, role = "user" } = await req.json();
    if (!name || !email || !password) {
      return NextResponse.json({ error: "Name, email, password required" }, { status: 400 });
    }

    await connectDB();
    const existing = await User.findOne({ email: email.toLowerCase() });
    if (existing) {
      return NextResponse.json({ error: "Email exists" }, { status: 409 });
    }

    const user = await User.create({
      name,
      email: email.toLowerCase(),
      passwordHash: await bcrypt.hash(password, 12),
      role: role === "admin" ? "admin" : "user",
      status: "active",
    });

    await logActivity("user_created", `Created ${user.email}`, admin._id);
    return NextResponse.json({
      user: { id: user._id, name: user.name, email: user.email, role: user.role, status: user.status },
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Forbidden") return forbiddenResponse();
    return NextResponse.json({ error: "Failed to create user" }, { status: 500 });
  }
}
