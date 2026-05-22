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
import { EXTRACTION_MODE_LABELS } from "@/lib/extraction-modes";

export default function JobMonitorPage() {
  const { id } = useParams<{ id: string }>();
  const { toast } = useToast();
  const [job, setJob] = useState<ScrapeJob | null>(null);

  const fetchJob = useCallback(async () => {
    try {
      const data = await apiFetch<{ job: ScrapeJob }>(`/api/jobs/${id}`);
      setJob(data.job);
    } catch (err) {
      console.error(err);
    }
  }, [id]);

  useEffect(() => {
    fetchJob();
  }, [fetchJob]);

  useEffect(() => {
    const terminal = ["completed", "failed", "stopped", "blocked"];
    const ms = job && terminal.includes(job.status) ? 12000 : 4000;
    const t = setInterval(fetchJob, ms);
    return () => clearInterval(t);
  }, [fetchJob, job?.status]);

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
        description: "Retry is a manual backup; the worker will still use the existing browser session.",
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
        <p className="text-muted-foreground">Loading...</p>
      </DashboardLayout>
    );
  }

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
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Live Job Monitor</h1>
          <p className="text-muted-foreground">
            {job.niche} · {EXTRACTION_MODE_LABELS[job.extractionMode] || job.extractionMode}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {job.status === "pending" && "Waiting in queue for worker"}
            {job.status === "running" && "Scraper active"}
            {job.status === "discovering_gigs" && "Finding Fiverr gig URLs"}
            {job.status === "extracting_reviews" && "Opening gigs and extracting reviews"}
            {job.status === "verification_required" &&
              "Complete Fiverr verification in the opened browser. The app will continue automatically."}
            {job.status === "blocked" && "Blocked by Fiverr"}
            {job.status === "failed" && "Failed — see errors"}
            {job.status === "completed" && "Completed"}
            {job.status === "stopped" && "Stopped"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
              "Complete Fiverr verification in the opened browser. The app will continue automatically."}
          </p>
          <ol className="text-xs text-muted-foreground mt-2 list-decimal list-inside space-y-1">
            <li>Look for the Chrome window opened by FT Solutions (not your normal browser).</li>
            <li>Complete any Fiverr “Press & Hold” or sign-in check there.</li>
            <li>Leave that window open; Retry is only a manual backup.</li>
          </ol>
          <p className="text-xs text-muted-foreground mt-2">
            Progress saved — gig {job.resumeIndex ?? 0} of {job.gigQueue?.length || "?"}.
          </p>
        </div>
      )}

      {(job.discoverySource || (job.activityLog && job.activityLog.length > 0)) && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Activity Log</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {job.discoverySource && (
              <p>
                <span className="text-muted-foreground">Search source: </span>
                <span className="font-medium text-primary">{job.discoverySource}</span>
                {job.urlsDiscovered != null && (
                  <span className="text-muted-foreground"> · {job.urlsDiscovered} URLs discovered</span>
                )}
              </p>
            )}
            <ul className="max-h-40 overflow-y-auto text-xs text-muted-foreground font-mono space-y-1">
              {(job.activityLog || []).slice(-20).map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Progress</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Progress value={job.progressPercent} />
            <div className="grid grid-cols-2 gap-3 text-sm">
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

        <Card>
          <CardHeader>
            <CardTitle>Errors</CardTitle>
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
