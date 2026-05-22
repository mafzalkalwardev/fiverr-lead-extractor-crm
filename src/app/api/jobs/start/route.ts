import { NextRequest, NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { connectDB, isDbConnectionError } from "@/lib/db";
import { getAuthUser, authErrorResponse } from "@/lib/auth";
import { clampJobLimits } from "@/lib/limits";
import { logActivity } from "@/lib/activityLog";
import { DEFAULT_TARGET_COUNTRIES } from "@/lib/constants";
import { getScraperMode } from "@/lib/scraper-mode";
import {
  EXTRACTION_MODES,
  parseGigUrlsFromText,
  type ExtractionMode,
} from "@/lib/extraction-modes";
import { isRedisConnectionError } from "@/queue/connection";
import { enqueueScrapeJob } from "@/queue/scrapeQueue";
import { normalizeFiverrUrl } from "@/scraper/fiverr/urls";
import ScrapeJob from "@/models/ScrapeJob";

async function saveHtmlFiles(
  jobId: string,
  files: { name: string; content: string; gigUrl: string }[]
) {
  const dir = path.join(process.cwd(), "data", "uploads", jobId);
  await fs.mkdir(dir, { recursive: true });
  const saved: { filename: string; gigUrl: string; storedPath: string }[] = [];
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const safeName = f.name.replace(/[^a-zA-Z0-9._-]/g, "_");
    const storedPath = path.join(dir, `${i}-${safeName}`);
    await fs.writeFile(storedPath, f.content, "utf-8");
    saved.push({
      filename: f.name,
      gigUrl: normalizeFiverrUrl(f.gigUrl) || "",
      storedPath,
    });
  }
  return saved;
}

export async function POST(req: NextRequest) {
  try {
    const user = await getAuthUser(req);
    const contentType = req.headers.get("content-type") || "";

    let body: Record<string, unknown> = {};
    const htmlFiles: { name: string; content: string; gigUrl: string }[] = [];

    if (contentType.includes("multipart/form-data")) {
      const form = await req.formData();
      body = {
        niche: form.get("niche"),
        extractionMode: form.get("extractionMode"),
        targetCountries: form.get("targetCountries"),
        maxGigs: form.get("maxGigs"),
        maxReviewsPerGig: form.get("maxReviewsPerGig"),
        maxTotalLeads: form.get("maxTotalLeads"),
        delaySeconds: form.get("delaySeconds"),
        manualGigUrls: form.get("manualGigUrls"),
      };
      const uploads = form.getAll("htmlFiles");
      for (const entry of uploads) {
        if (entry instanceof File) {
          const content = await entry.text();
          const gigUrl = (form.get(`gigUrl_${entry.name}`) as string) || "";
          htmlFiles.push({ name: entry.name, content, gigUrl });
        }
      }
    } else {
      body = await req.json();
    }

    console.log("[POST /api/jobs/start] body:", JSON.stringify({ ...body, htmlFiles: htmlFiles.length }));

    const niche = String(body.niche || "").trim();
    if (!niche || niche.length < 2) {
      return NextResponse.json({ error: "niche is required" }, { status: 400 });
    }

    const extractionMode = (String(body.extractionMode || "live") as ExtractionMode);
    if (!EXTRACTION_MODES.includes(extractionMode)) {
      return NextResponse.json({ error: "Invalid extraction mode" }, { status: 400 });
    }

    const limits = clampJobLimits({
      maxGigs: Number(body.maxGigs) || 10,
      maxReviewsPerGig: Number(body.maxReviewsPerGig ?? 0),
      maxTotalLeads: Number(body.maxTotalLeads) || 500,
      delaySeconds: Number(body.delaySeconds) || 1,
    });

    let targetCountries = DEFAULT_TARGET_COUNTRIES;
    if (body.targetCountries) {
      try {
        const parsed =
          typeof body.targetCountries === "string"
            ? JSON.parse(body.targetCountries)
            : body.targetCountries;
        if (Array.isArray(parsed) && parsed.length) targetCountries = parsed as string[];
      } catch {
        /* keep default */
      }
    }

    let manualGigUrls: string[] = [];
    if (extractionMode === "manual_urls") {
      const raw = String(body.manualGigUrls || "");
      manualGigUrls = parseGigUrlsFromText(raw).flatMap((u) => {
        const normalized = normalizeFiverrUrl(u);
        return normalized ? [normalized] : [];
      });
      if (manualGigUrls.length === 0) {
        return NextResponse.json(
          { error: "Paste at least one valid Fiverr gig URL" },
          { status: 400 }
        );
      }
    }

    if (extractionMode === "html_import" && htmlFiles.length === 0 && !contentType.includes("multipart")) {
      return NextResponse.json(
        { error: "Upload at least one HTML file for HTML Import mode" },
        { status: 400 }
      );
    }

    await connectDB();

    const job = await ScrapeJob.create({
      userId: user._id,
      niche,
      extractionMode,
      targetCountries,
      ...limits,
      status: "pending",
      manualGigUrls,
      gigQueue: manualGigUrls,
      errorLog: [],
    });

    const jobId = job._id.toString();

    if (extractionMode === "html_import" && htmlFiles.length > 0) {
      const saved = await saveHtmlFiles(jobId, htmlFiles);
      await ScrapeJob.findByIdAndUpdate(jobId, { htmlFiles: saved, maxGigs: saved.length });
    }

    console.log("[POST /api/jobs/start] created job:", jobId, extractionMode);

    try {
      await enqueueScrapeJob(jobId);
      console.log("[POST /api/jobs/start] queue ok:", jobId);
    } catch (queueErr) {
      console.log(
        "[POST /api/jobs/start] BullMQ skipped — Python scraper polls MongoDB:",
        queueErr instanceof Error ? queueErr.message : queueErr
      );
    }

    await logActivity(
      "job_started",
      `${extractionMode} · ${niche} · ${getScraperMode()}`,
      user._id
    );

    return NextResponse.json({
      job: { ...job.toObject(), _id: jobId },
      jobId,
    });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthorized") return authErrorResponse();
    if (isDbConnectionError(err)) {
      return NextResponse.json({ error: "Database unavailable" }, { status: 503 });
    }
    if (isRedisConnectionError(err)) {
      return NextResponse.json(
        { error: "Redis unavailable (optional). Start Python scraper: npm run scraper:py" },
        { status: 503 }
      );
    }
    console.error("[POST /api/jobs/start]", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to start job" },
      { status: 500 }
    );
  }
}
