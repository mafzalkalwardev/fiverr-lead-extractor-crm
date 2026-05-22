import mongoose, { Schema, Document, Model, Types } from "mongoose";

export type ActivityAction =
  | "user_login"
  | "job_started"
  | "job_stopped"
  | "job_blocked"
  | "export_downloaded"
  | "records_extracted"
  | "user_created"
  | "user_activated"
  | "user_deactivated"
  | "password_reset"
  | "records_deleted";

export interface IActivityLog extends Document {
  userId?: Types.ObjectId;
  action: ActivityAction;
  details: string;
  createdAt: Date;
}

const ActivityLogSchema = new Schema<IActivityLog>(
  {
    userId: { type: Schema.Types.ObjectId, ref: "User", index: true },
    action: { type: String, required: true, index: true },
    details: { type: String, default: "" },
    createdAt: { type: Date, default: Date.now, index: true },
  },
  { timestamps: false }
);

const ActivityLog: Model<IActivityLog> =
  mongoose.models.ActivityLog ||
  mongoose.model<IActivityLog>("ActivityLog", ActivityLogSchema);

export default ActivityLog;
