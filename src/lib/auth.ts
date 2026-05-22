import jwt from "jsonwebtoken";
import { NextRequest } from "next/server";
import { connectDB } from "./db";
import User, { type IUser } from "@/models/User";

const JWT_SECRET = process.env.JWT_SECRET || "dev-secret-change-me";
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || "7d";

export interface JwtPayload {
  userId: string;
  email: string;
  role: string;
}

export function signToken(payload: JwtPayload): string {
  return jwt.sign(payload, JWT_SECRET, {
    expiresIn: JWT_EXPIRES_IN as jwt.SignOptions["expiresIn"],
  });
}

export function verifyToken(token: string): JwtPayload {
  return jwt.verify(token, JWT_SECRET) as JwtPayload;
}

export function getTokenFromRequest(req: NextRequest): string | null {
  const auth = req.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) return auth.slice(7);
  return req.cookies.get("token")?.value ?? null;
}

/** Resolve authenticated active user */
export async function getAuthUser(req: NextRequest): Promise<IUser> {
  const token = getTokenFromRequest(req);
  if (!token) throw new Error("Unauthorized");

  const payload = verifyToken(token);
  await connectDB();
  const user = await User.findById(payload.userId).select("-passwordHash");
  if (!user) throw new Error("Unauthorized");
  if (user.status === "inactive") throw new Error("Account inactive");
  return user;
}

export async function requireAdmin(req: NextRequest): Promise<IUser> {
  const user = await getAuthUser(req);
  if (user.role !== "admin") throw new Error("Forbidden");
  return user;
}

export function authErrorResponse(message = "Unauthorized") {
  return Response.json({ error: message }, { status: 401 });
}

export function forbiddenResponse(message = "Forbidden") {
  return Response.json({ error: message }, { status: 403 });
}
