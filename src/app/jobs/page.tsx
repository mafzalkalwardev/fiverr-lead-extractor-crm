"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import type { ScrapeJob } from "@/types";
import { JobStatusBadge } from "@/components/job-status-badge";
import { formatDate } from "@/lib/utils";
import { REVIEW_IMAGE_MODE_LABELS } from "@/lib/extraction-modes";

export default function JobsListPage() {
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);

  useEffect(() => {
    apiFetch<{ jobs: ScrapeJob[] }>("/api/jobs")
      .then((d) => setJobs(d.jobs))
      .catch(console.error);
  }, []);

  return (
    <DashboardLayout>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Live Job Monitor</h1>
        <p className="text-muted-foreground">Select a job to view live progress</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {jobs.map((job) => (
          <Link key={job._id} href={`/jobs/${job._id}`}>
            <Card className="hover:border-primary/50 transition-colors cursor-pointer">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-lg">{job.niche}</CardTitle>
                <JobStatusBadge status={job.status} />
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                <p>
                  {job.totalLeadsFound} leads (US {job.usLeadsFound} · CA {job.canadaLeadsFound})
                </p>
                {job.reviewImageMode && <p>{REVIEW_IMAGE_MODE_LABELS[job.reviewImageMode]}</p>}
                <p>{formatDate(job.createdAt)}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </DashboardLayout>
  );
}
