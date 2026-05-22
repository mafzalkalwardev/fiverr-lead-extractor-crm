"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
  type ExtractionMode,
} from "@/lib/extraction-modes";
import type { ScrapeJob } from "@/types";
import { WorkerStatusBanner } from "@/components/worker-status-banner";
import { cn } from "@/lib/utils";

export default function NewJobPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<ExtractionMode>("live");
  const [niche, setNiche] = useState("Web Development");
  const [manualUrls, setManualUrls] = useState("");
  const [htmlFiles, setHtmlFiles] = useState<FileList | null>(null);
  const [countries, setCountries] = useState<string[]>([...DEFAULT_TARGET_COUNTRIES]);
  const [form, setForm] = useState({
    maxGigs: 5,
    maxReviewsPerGig: 10,
    maxTotalLeads: 50,
    delaySeconds: 2,
  });

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
            ...form,
            maxGigs: mode === "manual_urls" ? Math.min(form.maxGigs, manualUrls.split(/\n/).length) : form.maxGigs,
          }),
        });
      }

      const id = data.job?._id || data.jobId;
      if (!id) throw new Error("No job id returned");

      toast({ title: "Job queued", description: `${EXTRACTION_MODE_LABELS[mode]}` });
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
        <p className="font-medium">First time setup</p>
        <p className="text-muted-foreground mt-1 text-xs">
          A Chrome window opens automatically when you start a job. If Fiverr asks for
          verification, complete it in that window, click <strong>Retry</strong> on the job page,
          and do not close Chrome while extraction runs.
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
                    min={1}
                    max={50}
                    value={form.maxGigs}
                    onChange={(e) => setForm({ ...form, maxGigs: Number(e.target.value) })}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Reviews / Gig</Label>
                  <Input
                    type="number"
                    min={1}
                    max={50}
                    value={form.maxReviewsPerGig}
                    onChange={(e) =>
                      setForm({ ...form, maxReviewsPerGig: Number(e.target.value) })
                    }
                  />
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
                    min={2}
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
