"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Download, Square, RefreshCw, ExternalLink } from "lucide-react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { apiFetch } from "@/lib/api";
import type { ScrapeJob } from "@/types";
import { JobStatusBadge } from "@/components/job-status-badge";
import { WorkerStatusBanner } from "@/components/worker-status-banner";
import { useToast } from "@/components/providers/toast-provider";
import { EXTRACTION_MODE_LABELS, REVIEW_IMAGE_MODE_LABELS } from "@/lib/extraction-modes";

export default function JobMonitorPage() {
  const params = useParams() as { id?: string } | null;
  const id = params?.id ?? "";
  const { toast } = useToast();
  const [job, setJob] = useState<ScrapeJob | null>(null);

  const fetchJob = useCallback(async () => {
    if (!id) return;
    try {
      const data = await apiFetch<{ job: ScrapeJob }>(`/api/jobs/${id}`);
      setJob(data.job);
    } catch (err) {
      console.error(err);
    }
  }, [id]);

  useEffect(() => {
    if (!id) return;
    fetchJob();
  }, [fetchJob, id]);

  useEffect(() => {
    if (!id) return;
    const terminal = ["completed", "failed", "stopped", "blocked"];
    const ms = job && terminal.includes(job.status) ? 12000 : 4000;
    const t = setInterval(fetchJob, ms);
    return () => clearInterval(t);
  }, [fetchJob, job?.status, id]);

  const stopJob = async () => {
    try {
      await apiFetch(`/api/jobs/${id}/stop`, { method: "POST" });
      toast({ title: "Job stopped" });
      fetchJob();
    } catch (err) {
      toast({ title: "Error", description: err instanceof Error ? err.message : "" });
    }
  };

  const retryJob = async () => {
    try {
      await apiFetch(`/api/jobs/${id}/retry`, { method: "POST" });
      toast({
        title: "Retry queued",
        description: "The scraper will resume from the saved gig index.",
      });
      fetchJob();
    } catch (err) {
      toast({ title: "Retry failed", description: err instanceof Error ? err.message : "" });
    }
  };

  const openBrowser = () => {
    if (job?.currentGigLink) {
      window.open(job.currentGigLink, "_blank", "noopener,noreferrer");
    } else {
      toast({ title: "No gig URL yet", description: "Wait for worker to set current gig link." });
    }
  };

  const exportLeads = async () => {
    const token = localStorage.getItem("token");
    const res = await fetch(`/api/jobs/${id}/export`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      toast({ title: "Export failed" });
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fiverr-leads-${job?.niche || id}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    toast({ title: "Export downloaded" });
  };

  if (!job) {
    return (
      <DashboardLayout>
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          Loading job…
        </div>
      </DashboardLayout>
    );
  }

  const statusHint: Record<string, string> = {
    pending: "Queued — Python scraper will pick this up",
    running: "Python scraper active",
    discovering_gigs: job.currentSearchPage
      ? `Searching Fiverr — search page ${job.currentSearchPage}${
          job.discoveryPageLimit ? ` of ${job.discoveryPageLimit}` : ""
        }`
      : "Searching Fiverr for gig URLs",
    extracting_reviews: "Finishing all reviews on current gig, then next gig",
    verification_required: "Verification paused - solve it once in the scraper browser",
    blocked: "Blocked by Fiverr",
    failed: "Failed — see errors below",
    completed: "Completed successfully",
    stopped: "Stopped by user",
  };

  const errors = job.errors || job.jobErrors || [];
  const isVerification = job.status === "verification_required";
  const browserClosedError = errors.some((e) =>
    /browser.*closed|Target page, context or browser/i.test(e)
  );
  const canRetry =
    isVerification ||
    (job.status === "failed" && browserClosedError);

  return (
    <DashboardLayout>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="page-title">Job Monitor</h1>
          <p className="text-muted-foreground">
            {job.niche} · {EXTRACTION_MODE_LABELS[job.extractionMode] || job.extractionMode}
            {job.reviewImageMode ? ` · ${REVIEW_IMAGE_MODE_LABELS[job.reviewImageMode]}` : ""}
          </p>
          <p className="text-sm text-muted-foreground/90">
            {statusHint[job.status] || job.status}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <JobStatusBadge status={job.status} />
          <Button variant="outline" size="sm" onClick={exportLeads} className="gap-1">
            <Download className="h-4 w-4" /> Export
          </Button>
          {canRetry && (
            <>
              <Button variant="outline" size="sm" onClick={openBrowser} className="gap-1">
                <ExternalLink className="h-4 w-4" /> Open Gig Link
              </Button>
              <Button size="sm" onClick={retryJob} className="gap-1">
                <RefreshCw className="h-4 w-4" /> Retry
              </Button>
            </>
          )}
          {["running", "pending", "verification_required"].includes(job.status) && (
            <Button variant="destructive" size="sm" onClick={stopJob} className="gap-1">
              <Square className="h-4 w-4" /> Stop
            </Button>
          )}
        </div>
      </div>

      <WorkerStatusBanner />

      {canRetry && (
        <div className="mb-4 rounded-md border border-amber-500/50 bg-amber-500/15 px-4 py-4 text-sm">
          <p className="font-medium text-amber-200">
            {job.verificationMessage ||
              "Complete Fiverr verification in the opened browser. The app will continue automatically without refreshing the challenge."}
          </p>
          <ol className="text-xs text-muted-foreground mt-2 list-decimal list-inside space-y-1">
            <li>Look for the Chrome window opened by FT Solutions (not your normal browser).</li>
            <li>Complete any Fiverr Press &amp; Hold or sign-in check there.</li>
            <li>Leave that window open; the worker will resume from the saved gig automatically.</li>
          </ol>
          <p className="text-xs text-muted-foreground mt-2">
            Progress saved - gig {job.resumeIndex ?? 0} of {job.gigQueue?.length || "?"}.
          </p>
        </div>
      )}

      <Card className="mb-6 border-border/80 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold">Activity log</CardTitle>
          {(job.discoverySource || job.status === "discovering_gigs") && (
            <p className="text-sm text-muted-foreground">
              {job.status === "discovering_gigs" && job.currentSearchPage ? (
                <>
                  Search page{" "}
                  <span className="text-primary font-medium">{job.currentSearchPage}</span>
                  {job.discoveryPageLimit
                    ? ` / ${job.discoveryPageLimit}`
                    : " (all pages until last)"}
                </>
              ) : null}
              {job.discoverySource && (
                <>
                  {job.status === "discovering_gigs" && job.currentSearchPage ? " · " : null}
                  Discovery:{" "}
                  <span className="text-primary font-medium">{job.discoverySource}</span>
                </>
              )}
              {job.urlsDiscovered != null && ` · ${job.urlsDiscovered} gigs`}
              {(job.skippedExistingGigs ?? 0) > 0 && ` · skipped ${job.skippedExistingGigs} already used`}
              {job.discoveryPagesScanned != null && job.discoveryPagesScanned > 0
                ? ` · ${job.discoveryPagesScanned} pages scanned`
                : ""}
            </p>
          )}
        </CardHeader>
        <CardContent>
          <ul className="max-h-56 overflow-y-auto rounded-md border border-border/60 bg-muted/10 p-3 text-xs font-mono space-y-1.5">
            {(job.activityLog || []).length === 0 ? (
              <li className="text-muted-foreground">No activity yet</li>
            ) : (
              (job.activityLog || []).slice(-40).map((line, i) => (
                <li key={i} className="text-muted-foreground leading-relaxed">
                  {line}
                </li>
              ))
            )}
          </ul>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-border/80 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Progress</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Progress value={job.progressPercent} />
            <div className="grid grid-cols-2 gap-3 text-sm">
              {job.status === "discovering_gigs" && (job.currentSearchPage ?? 0) > 0 && (
                <div className="col-span-2">
                  <p className="text-muted-foreground">Search page</p>
                  <p className="text-xl font-bold text-primary">
                    Page {job.currentSearchPage}
                    {job.discoveryPageLimit
                      ? ` / ${job.discoveryPageLimit}`
                      : " — scraping all pages"}
                  </p>
                </div>
              )}
              <div>
                <p className="text-muted-foreground">Current gig</p>
                <p className="text-xl font-bold">
                  {job.currentGigNumber || job.resumeIndex || 0}
                  {job.totalGigs || job.gigQueue?.length ? ` / ${job.totalGigs || job.gigQueue?.length}` : ""}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Review page</p>
                <p className="text-xl font-bold">{job.currentReviewPage || 0}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Reviews parsed</p>
                <p className="text-xl font-bold">{job.totalReviewsParsed ?? job.reviewsChecked}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Gigs scanned</p>
                <p className="text-xl font-bold">{job.gigsScanned}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Reviews checked</p>
                <p className="text-xl font-bold">{job.reviewsChecked}</p>
              </div>
              <div>
                <p className="text-muted-foreground">US leads</p>
                <p className="text-xl font-bold text-emerald-400">{job.usLeadsFound}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Canada leads</p>
                <p className="text-xl font-bold text-emerald-400">{job.canadaLeadsFound}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Total leads</p>
                <p className="text-xl font-bold">{job.totalLeadsFound}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Failed gigs</p>
                <p className="text-xl font-bold text-red-400">{job.failedGigs}</p>
              </div>
            </div>
            {job.currentSeller && (
              <p className="text-sm">
                <span className="text-muted-foreground">Current seller: </span>
                {job.currentSeller}
              </p>
            )}
            {job.currentSellerUsername && (
              <p className="text-sm">
                <span className="text-muted-foreground">Seller username: </span>
                {job.currentSellerUsername}
              </p>
            )}
            {job.currentGigLink && (
              <a
                href={job.currentGigLink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-primary break-all hover:underline block"
              >
                {job.currentGigLink}
              </a>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/80 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">Errors</CardTitle>
          </CardHeader>
          <CardContent>
            {errors.length ? (
              <ul className="text-sm text-red-400 space-y-2 max-h-48 overflow-y-auto">
                {errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No errors</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Link href={`/leads?jobId=${id}`}>
          <Button variant="outline">View Extracted Leads →</Button>
        </Link>
      </div>
    </DashboardLayout>
  );
}
