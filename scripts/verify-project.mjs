/**
 * End-to-end verification script for Fiverr Review Intelligence.
 * Run: node scripts/verify-project.mjs
 */
import { readFileSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

// Load .env manually
const envPath = resolve(root, ".env");
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, "utf8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i > 0) process.env[t.slice(0, i)] = t.slice(i + 1);
  }
}

const BASE = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
const results = [];

function pass(name, detail = "") {
  results.push({ name, ok: true, detail });
  console.log(`✓ ${name}${detail ? `: ${detail}` : ""}`);
}
function fail(name, detail = "") {
  results.push({ name, ok: false, detail });
  console.error(`✗ ${name}${detail ? `: ${detail}` : ""}`);
}

async function fetchJson(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text.slice(0, 200) };
  }
  return { res, data };
}

// 1. Package scripts
console.log("\n=== 1. package.json scripts ===");
const pkg = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
for (const s of ["dev", "build", "start", "lint", "worker", "dev:all"]) {
  pkg.scripts[s] ? pass(`script: ${s}`) : fail(`script: ${s}`, "missing");
}

// 2. Env
console.log("\n=== 2. Environment ===");
const required = ["MONGODB_URI", "REDIS_URL", "JWT_SECRET"];
for (const k of required) {
  process.env[k] ? pass(`env ${k}`) : fail(`env ${k}`, "not set in .env");
}
pass("SCRAPER_MODE", process.env.SCRAPER_MODE || "demo");

// 3. MongoDB
console.log("\n=== 3. MongoDB ===");
try {
  const mongoose = (await import("mongoose")).default;
  await mongoose.connect(process.env.MONGODB_URI, { serverSelectionTimeoutMS: 5000 });
  pass("MongoDB connect", process.env.MONGODB_URI);
  await mongoose.disconnect();
} catch (e) {
  fail("MongoDB connect", e.message);
}

// 4. Redis
console.log("\n=== 4. Redis ===");
try {
  const IORedis = (await import("ioredis")).default;
  const redis = new IORedis(process.env.REDIS_URL, { maxRetriesPerRequest: 1, connectTimeout: 5000 });
  await redis.ping();
  pass("Redis ping", process.env.REDIS_URL);
  await redis.quit();
} catch (e) {
  fail("Redis ping", e.message);
}

// 5-8. HTTP (requires dev server on :3000)
console.log("\n=== 5-8. HTTP API (needs npm run dev + npm run worker) ===");
let token = "";
const testEmail = `test_${Date.now()}@example.com`;
const testPassword = "TestPass123!";

try {
  const reg = await fetchJson("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "Test User", email: testEmail, password: testPassword }),
  });
  if (reg.res.ok && reg.data.token) {
    token = reg.data.token;
    pass("Auth register");
  } else {
    fail("Auth register", reg.data.error || reg.res.status);
  }
} catch (e) {
  fail("Auth register", `Server not reachable: ${e.message}`);
}

if (token) {
  try {
    const login = await fetchJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: testEmail, password: testPassword }),
    });
    login.res.ok && login.data.token ? pass("Auth login") : fail("Auth login", login.data.error);
  } catch (e) {
    fail("Auth login", e.message);
  }

  const auth = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  try {
    const start = await fetchJson("/api/jobs/start", {
      method: "POST",
      headers: auth,
      body: JSON.stringify({
        keyword: "logo design",
        category: "graphics-design",
        maxPages: 1,
        maxGigs: 3,
        maxReviewsPerGig: 2,
        delaySeconds: 1,
      }),
    });
    if (start.res.ok && start.data.job?._id) {
      pass("Demo job start", start.data.job._id);
      const jobId = start.data.job._id;

      // Wait for worker
      console.log("  Waiting 15s for worker to process...");
      await new Promise((r) => setTimeout(r, 15000));

      const job = await fetchJson(`/api/jobs/${jobId}`, { headers: auth });
      if (job.res.ok) {
        const j = job.data.job;
        pass("Job monitor", `status=${j.status} gigs=${j.totalGigsFound} reviews=${j.totalReviewsExtracted} progress=${j.progressPercent}%`);
        if (j.status === "pending" || j.status === "running") {
          fail("Job completion", "Worker may not be running — start: npm run worker");
        }
      } else {
        fail("Job monitor", job.data.error);
      }

      const exp = await fetch(`${BASE}/api/jobs/${jobId}/export`, { headers: auth });
      const buf = await exp.arrayBuffer();
      if (exp.ok && buf.byteLength > 1000) {
        pass("Excel export", `${buf.byteLength} bytes`);
      } else {
        fail("Excel export", `status=${exp.status} size=${buf.byteLength}`);
      }
    } else {
      fail("Demo job start", start.data.error || start.res.status);
    }
  } catch (e) {
    fail("Demo job flow", e.message);
  }
}

console.log("\n=== Summary ===");
const ok = results.filter((r) => r.ok).length;
const total = results.length;
console.log(`${ok}/${total} checks passed`);
if (ok < total) process.exit(1);
