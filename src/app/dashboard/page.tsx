"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Users, Flag, CheckCircle, Activity, Briefcase } from "lucide-react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { StatsCard } from "@/components/stats-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { DashboardStats, ScrapeJob } from "@/types";
import { JobStatusBadge } from "@/components/job-status-badge";
import { formatDate } from "@/lib/utils";
import { CLIENT_MODE } from "@/lib/constants";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);

  useEffect(() => {
    apiFetch<{ stats: DashboardStats; jobs: ScrapeJob[] }>("/api/jobs")
      .then((d) => {
        setStats(d.stats);
        setJobs(d.jobs.slice(0, 5));
      })
      .catch(console.error);
  }, []);

  return (
    <DashboardLayout>
      <div className="mb-8">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Overview of jobs and qualified US/Canada leads</p>
      </div>

      {!CLIENT_MODE && (
        <div className="mb-6 rounded-lg border border-border/80 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
          For reliable runs when Fiverr shows verification, use{" "}
          <Link href="/jobs/new" className="font-medium text-primary hover:underline">
            Manual URL
          </Link>{" "}
          or{" "}
          <Link href="/jobs/new" className="font-medium text-primary hover:underline">
            HTML Import
          </Link>{" "}
          on the Create Job screen.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 mb-8">
        <StatsCard title="Total Jobs" value={stats?.totalJobs ?? 0} icon={Briefcase} />
        <StatsCard title="Total Leads" value={stats?.totalLeads ?? 0} icon={Users} />
        <StatsCard title="US Leads" value={stats?.usLeads ?? 0} icon={Flag} />
        <StatsCard title="Canada Leads" value={stats?.canadaLeads ?? 0} icon={Flag} />
        <StatsCard title="Running" value={stats?.runningJobs ?? 0} icon={Activity} />
        <StatsCard title="Completed" value={stats?.completedJobs ?? 0} icon={CheckCircle} />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent Jobs</CardTitle>
          <Link href="/jobs/new">
            <Button size="sm">Create Job</Button>
          </Link>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No jobs yet.</p>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <Link
                  key={job._id}
                  href={`/jobs/${job._id}`}
                  className="flex items-center justify-between rounded-md border border-border p-4 hover:bg-muted/30"
                >
                  <div>
                    <p className="font-medium">{job.niche}</p>
                    <p className="text-xs text-muted-foreground">
                      {job.totalLeadsFound} leads · {job.extractionMode || "live"} ·{" "}
                      {formatDate(job.createdAt)}
                    </p>
                  </div>
                  <JobStatusBadge status={job.status} />
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </DashboardLayout>
  );
}
