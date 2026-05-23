import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { connectDB, isDbConnectionError } from "@/lib/db";
import { signToken } from "@/lib/auth";
import User from "@/models/User";

/** Public registration disabled — admins create users */
export async function POST(req: NextRequest) {
  try {
    // Public registration enabled for any user

    const { name, email, password } = await req.json();
    if (!name || !email || !password) {
      return NextResponse.json({ error: "All fields required" }, { status: 400 });
    }

    await connectDB();
    const existing = await User.findOne({ email: email.toLowerCase() });
    if (existing) {
      return NextResponse.json({ error: "Email already registered" }, { status: 409 });
    }

    const passwordHash = await bcrypt.hash(password, 12);
    const user = await User.create({
      name,
      email: email.toLowerCase(),
      passwordHash,
      role: "user",
      status: "active",
    });

    const token = signToken({
      userId: user._id.toString(),
      email: user.email,
      role: user.role,
    });

    return NextResponse.json({
      token,
      user: { id: user._id, name: user.name, email: user.email, role: user.role, status: user.status },
    });
  } catch (err) {
    if (isDbConnectionError(err)) {
      return NextResponse.json({ error: "Database unavailable" }, { status: 503 });
    }
    return NextResponse.json({ error: "Registration failed" }, { status: 500 });
  }
}
