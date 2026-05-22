import ActivityLog, { type ActivityAction } from "@/models/ActivityLog";
import type { Types } from "mongoose";

export async function logActivity(
  action: ActivityAction,
  details: string,
  userId?: Types.ObjectId | string
) {
  await ActivityLog.create({
    userId: userId || undefined,
    action,
    details,
    createdAt: new Date(),
  });
}
