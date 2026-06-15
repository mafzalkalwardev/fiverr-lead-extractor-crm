"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Image as ImageIcon, ImageOff, History } from "lucide-react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/providers/toast-provider";
import { DEFAULT_TARGET_COUNTRIES, TARGET_COUNTRY_OPTIONS } from "@/lib/constants";
import {
  CLIENT_EXTRACTION_MODES,
  EXTRACTION_MODE_LABELS,
  REVIEW_IMAGE_MODE_LABELS,
  type ExtractionMode,
  type ReviewImageMode,
} from "@/lib/extraction-modes";
import type { ScrapeJob } from "@/types";
import { WorkerStatusBanner } from "@/components/worker-status-banner";
import { cn } from "@/lib/utils";

interface ContinuableJob {
  _id: string;
  niche: string;
  status: string;
  createdAt: string;
  totalInQueue: number;
  processedCount: number;
  remainingCount: number;
  totalLeadsFound: number;
}

export default function NewJobPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<ExtractionMode>("live");
  const [reviewImageMode, setReviewImageMode] = useState<ReviewImageMode>("with_image");
  const [niche, setNiche] = useState("Web Development");
  const [manualUrls, setManualUrls] = useState("");
  const [htmlFiles, setHtmlFiles] = useState<FileList | null>(null);
  const [countries, setCountries] = useState<string[]>([...DEFAULT_TARGET_COUNTRIES]);
  const [form, setForm] = useState({
    maxGigs: 0,
    maxReviewsPerGig: 0,
    maxTotalLeads: 500,
    delaySeconds: 1,
  });
  const [continuePrevious, setContinuePrevious] = useState(false);
  const [continueFromJobId, setContinueFromJobId] = useState("");
  const [discoverNewGigsAfterQueue, setDiscoverNewGigsAfterQueue] = useState(true);
  const [continuableJobs, setContinuableJobs] = useState<ContinuableJob[]>([]);
  const [loadingContinuable, setLoadingContinuable] = useState(false);

  const fetchContinuable = useCallback(async () => {
    if (mode !== "live" || niche.trim().length < 2) {
      setContinuableJobs([]);
      return;
    }
    setLoadingContinuable(true);
    try {
      const data = await apiFetch<{ jobs: ContinuableJob[] }>(
        `/api/jobs/continuation?niche=${encodeURIComponent(niche.trim())}`
      );
      setContinuableJobs(data.jobs || []);
      if (data.jobs?.length === 1) {
        setContinueFromJobId(data.jobs[0]._id);
      }
    } catch {
      setContinuableJobs([]);
    } finally {
      setLoadingContinuable(false);
    }
  }, [mode, niche]);

  useEffect(() => {
    const t = setTimeout(fetchContinuable, 400);
    return () => clearTimeout(t);
  }, [fetchContinuable]);

  const toggleCountry = (c: string) => {
    setCountries((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!niche.trim()) {
      toast({ title: "Enter a niche / service label" });
      return;
    }
    if (countries.length === 0) {
      toast({ title: "Select at least one country" });
      return;
    }
    if (mode === "manual_urls" && !manualUrls.trim()) {
      toast({ title: "Paste at least one Fiverr gig URL" });
      return;
    }
    if (mode === "html_import" && (!htmlFiles || htmlFiles.length === 0)) {
      toast({ title: "Select HTML file(s) to upload" });
      return;
    }
    if (continuePrevious && mode === "live") {
      if (!continueFromJobId) {
        toast({ title: "Select a previous job to continue from" });
        return;
      }
    }

    setLoading(true);
    try {
      let data: { job: ScrapeJob; jobId?: string };

      if (mode === "html_import" && htmlFiles) {
        const fd = new FormData();
        fd.append("niche", niche.trim());
        fd.append("extractionMode", mode);
        fd.append("targetCountries", JSON.stringify(countries));
        fd.append("maxGigs", String(htmlFiles.length));
        fd.append("maxReviewsPerGig", String(form.maxReviewsPerGig));
        fd.append("maxTotalLeads", String(form.maxTotalLeads));
        fd.append("delaySeconds", String(form.delaySeconds));
        fd.append("reviewImageMode", reviewImageMode);
        for (let i = 0; i < htmlFiles.length; i++) {
          fd.append("htmlFiles", htmlFiles[i]);
        }
        const token = localStorage.getItem("token");
        const res = await fetch("/api/jobs/start", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || "Failed to start job");
        data = json;
      } else {
        data = await apiFetch<{ job: ScrapeJob; jobId?: string }>("/api/jobs/start", {
          method: "POST",
          body: JSON.stringify({
            niche: niche.trim(),
            extractionMode: mode,
            targetCountries: countries,
            manualGigUrls: mode === "manual_urls" ? manualUrls : undefined,
            reviewImageMode,
            ...form,
            maxGigs: mode === "manual_urls" ? Math.min(form.maxGigs, manualUrls.split(/\n/).length) : form.maxGigs,
            ...(continuePrevious && mode === "live"
              ? {
                  continueFromJobId,
                  discoverNewGigsAfterQueue,
                }
              : {}),
          }),
        });
      }

      const id = data.job?._id || data.jobId;
      if (!id) throw new Error("No job id returned");

      toast({
        title: "Job queued",
        description: `${EXTRACTION_MODE_LABELS[mode]} · ${REVIEW_IMAGE_MODE_LABELS[reviewImageMode]}`,
      });
      router.push(`/jobs/${id}`);
    } catch (err) {
      toast({
        title: "Job creation failed",
        description: err instanceof Error ? err.message : "Error",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Create Scraping Job</h1>
        <p className="text-muted-foreground">
          Choose extraction mode — no CAPTCHA bypass; public review data only
        </p>
      </div>

      <WorkerStatusBanner />

      <div className="mb-4 rounded-md border border-primary/30 bg-primary/10 px-4 py-3 text-sm">
        <p className="font-medium">Automatic Search (recommended)</p>
        <p className="text-muted-foreground mt-1 text-xs">
          Walks Fiverr search pages, skips gigs already used for the same niche, then opens each gig
          and saves US/Canada reviews using the review image option selected below. If Fiverr asks
          for verification, complete it in the scraper browser and the job will resume.
        </p>
      </div>

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Extraction Mode</CardTitle>
          <CardDescription>Select how leads are collected</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="grid gap-2 sm:grid-cols-2">
              {CLIENT_EXTRACTION_MODES.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    "rounded-lg border p-3 text-left text-sm transition-colors",
                    mode === m
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:border-primary/40"
                  )}
                >
                  {EXTRACTION_MODE_LABELS[m]}
                </button>
              ))}
            </div>

            <div className="space-y-2">
              <Label htmlFor="niche">Service / Niche label</Label>
              <Input
                id="niche"
                placeholder="Web Development"
                value={niche}
                onChange={(e) => setNiche(e.target.value)}
                required
              />
            </div>

            {mode === "live" && (
              <div className="space-y-3 rounded-lg border border-border/80 bg-muted/20 p-4">
                <div className="flex items-start gap-3">
                  <History className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="flex-1 space-y-3">
                    <div>
                      <p className="font-medium text-sm">Continue from previous job</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Pick up unprocessed gigs from an earlier run (e.g. after a month). Already-saved
                        leads are skipped automatically; then optionally search Fiverr for new gigs.
                      </p>
                    </div>
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={continuePrevious}
                        onChange={(e) => {
                          setContinuePrevious(e.target.checked);
                          if (!e.target.checked) setContinueFromJobId("");
                        }}
                        className="rounded border-input"
                      />
                      Continue unprocessed gigs from a previous job
                    </label>
                    {continuePrevious && (
                      <>
                        <div className="space-y-2">
                          <Label htmlFor="continueJob">Previous job</Label>
                          <select
                            id="continueJob"
                            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                            value={continueFromJobId}
                            onChange={(e) => setContinueFromJobId(e.target.value)}
                            disabled={loadingContinuable}
                          >
                            <option value="">
                              {loadingContinuable
                                ? "Loading…"
                                : continuableJobs.length
                                  ? "Select a job…"
                                  : "No jobs with remaining gigs for this niche"}
                            </option>
                            {continuableJobs.map((j) => (
                              <option key={j._id} value={j._id}>
                                {j.remainingCount} gigs left · {j.processedCount}/{j.totalInQueue}{" "}
                                processed · {j.totalLeadsFound} leads ·{" "}
                                {new Date(j.createdAt).toLocaleDateString()}
                              </option>
                            ))}
                          </select>
                        </div>
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            checked={discoverNewGigsAfterQueue}
                            onChange={(e) => setDiscoverNewGigsAfterQueue(e.target.checked)}
                            className="rounded border-input"
                          />
                          After queue finishes, search Fiverr for new gigs
                        </label>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div className="space-y-2">
              <Label>Review Image Option</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setReviewImageMode("with_image")}
                  className={cn(
                    "flex min-h-20 items-start gap-3 rounded-lg border p-3 text-left text-sm transition-colors",
                    reviewImageMode === "with_image"
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:border-primary/40"
                  )}
                >
                  <ImageIcon className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    <span className="block font-medium">With review image link</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      Save only US/Canada reviews where a buyer delivery/review image is found.
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setReviewImageMode("without_image")}
                  className={cn(
                    "flex min-h-20 items-start gap-3 rounded-lg border p-3 text-left text-sm transition-colors",
                    reviewImageMode === "without_image"
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:border-primary/40"
                  )}
                >
                  <ImageOff className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    <span className="block font-medium">Without review image link</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      Faster mode: save US/Canada reviews and leave the review image link empty.
                    </span>
                  </span>
                </button>
              </div>
            </div>

            {mode === "manual_urls" && (
              <div className="space-y-2">
                <Label>Paste Fiverr gig URLs (one per line)</Label>
                <textarea
                  className="flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  placeholder="https://www.fiverr.com/seller/gig-slug"
                  value={manualUrls}
                  onChange={(e) => setManualUrls(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  On Fiverr.com, open any gig → copy the address bar link → paste one URL per line.
                  No technical skills needed.
                </p>
              </div>
            )}

            {mode === "html_import" && (
              <div className="space-y-2">
                <Label>Upload saved Fiverr gig HTML files</Label>
                <Input
                  type="file"
                  accept=".html,.htm"
                  multiple
                  onChange={(e) => setHtmlFiles(e.target.files)}
                />
                <p className="text-xs text-muted-foreground">
                  Save page from browser (Ctrl+S), upload here. No automation to Fiverr servers.
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label>Target Countries</Label>
              <div className="flex flex-wrap gap-2">
                {TARGET_COUNTRY_OPTIONS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => toggleCountry(c)}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm",
                      countries.includes(c)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground"
                    )}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            {mode !== "html_import" && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Max Gigs</Label>
                  <Input
                    type="number"
                    min={0}
                    max={99999}
                    value={form.maxGigs}
                    onChange={(e) => setForm({ ...form, maxGigs: Number(e.target.value) })}
                  />
                  <p className="text-xs text-muted-foreground">
                    Use 0 to scrape every gig from every search page (no gig limit).
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Max Reviews / Gig</Label>
                  <Input
                    type="number"
                    min={0}
                    max={500}
                    value={form.maxReviewsPerGig}
                    onChange={(e) =>
                      setForm({ ...form, maxReviewsPerGig: Number(e.target.value) })
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Use 0 to extract every matching US/Canada review on each gig before moving on.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Max Total Leads</Label>
                  <Input
                    type="number"
                    min={1}
                    max={500}
                    value={form.maxTotalLeads}
                    onChange={(e) =>
                      setForm({ ...form, maxTotalLeads: Number(e.target.value) })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label>Delay (seconds)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={30}
                    value={form.delaySeconds}
                    onChange={(e) =>
                      setForm({ ...form, delaySeconds: Number(e.target.value) })
                    }
                  />
                </div>
              </div>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Starting..." : "Start Lead Extraction"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </DashboardLayout>
  );
}
