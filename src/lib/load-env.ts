import { config } from "dotenv";
import { resolve } from "path";

/** Load .env from project root (required for worker/scripts outside Next.js). */
config({ path: resolve(process.cwd(), ".env") });
