import { NextRequest, NextResponse } from "next/server";
import { connectDB } from "@/lib/db";
import { getAuthUser, signToken } from "@/lib/auth";
import User from "@/models/User";

export async function GET(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    return NextResponse.json({
      user: {
        id: user._id,
        name: user.name,
        email: user.email,
        role: user.role,
        status: user.status,
      },
    });
  } catch {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const authUser = await getAuthUser(req);
    const body = await req.json();
    const name = typeof body.name === "string" ? body.name.trim() : undefined;
    const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : undefined;

    if (!name && !email) {
      return NextResponse.json({ error: "Nothing to update" }, { status: 400 });
    }

    await connectDB();

    if (email && email !== authUser.email) {
      const existing = await User.findOne({ email });
      if (existing) {
        return NextResponse.json({ error: "Email already in use" }, { status: 409 });
      }
      authUser.email = email;
    }

    if (name) {
      authUser.name = name;
    }

    await authUser.save();

    const token = signToken({
      userId: authUser._id.toString(),
      email: authUser.email,
      role: authUser.role,
    });

    return NextResponse.json({
      user: {
        id: authUser._id,
        name: authUser.name,
        email: authUser.email,
        role: authUser.role,
        status: authUser.status,
      },
      token,
    });
  } catch {
    return NextResponse.json({ error: "Update failed" }, { status: 500 });
  }
}
