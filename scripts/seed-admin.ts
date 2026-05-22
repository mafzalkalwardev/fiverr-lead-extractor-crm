/**
 * Seed default admin user. Run: npm run seed:admin
 */
import { config } from "dotenv";
import { resolve } from "path";
import bcrypt from "bcryptjs";
import mongoose from "mongoose";

config({ path: resolve(__dirname, "..", ".env") });

const MONGODB_URI =
  process.env.MONGODB_URI || "mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm";

const ADMIN_EMAIL = process.env.ADMIN_EMAIL || "admin@ftsolutions.local";
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "Admin@FT2024";
const ADMIN_NAME = process.env.ADMIN_NAME || "FT Solutions Admin";

async function main() {
  console.log("MongoDB:", MONGODB_URI);
  await mongoose.connect(MONGODB_URI);

  const User =
    mongoose.models.User ||
    mongoose.model(
      "User",
      new mongoose.Schema(
        {
          name: String,
          email: { type: String, unique: true },
          passwordHash: String,
          role: { type: String, enum: ["admin", "user"] },
          status: { type: String, enum: ["active", "inactive"] },
          lastLogin: Date,
        },
        { timestamps: true }
      )
    );

  const hash = await bcrypt.hash(ADMIN_PASSWORD, 12);
  const user = await User.findOneAndUpdate(
    { email: ADMIN_EMAIL.toLowerCase() },
    {
      name: ADMIN_NAME,
      email: ADMIN_EMAIL.toLowerCase(),
      passwordHash: hash,
      role: "admin",
      status: "active",
    },
    { upsert: true, new: true }
  );

  console.log("");
  console.log("=== Admin login ready ===");
  console.log("Email:   ", user.email);
  console.log("Password:", ADMIN_PASSWORD);
  console.log("Database:", MONGODB_URI);
  console.log("");
  await mongoose.disconnect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
