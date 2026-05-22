"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { JobStatusBadge } from "@/components/job-status-badge";
import { apiFetch } from "@/lib/api";
import { formatDate } from "@/lib/utils";

interface JobRow {
  _id: string;
  niche: string;
  status: string;
  totalLeadsFound: number;
  usLeadsFound: number;
  canadaLeadsFound: number;
  gigsScanned: number;
  userId?: { name: string; email: string };
  createdAt: string;
}

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<JobRow[]>([]);

  useEffect(() => {
    apiFetch<{ jobs: JobRow[] }>("/api/admin/jobs")
      .then((d) => setJobs(d.jobs))
      .catch(console.error);
  }, []);

  return (
    <DashboardLayout>
      <h1 className="text-3xl font-bold mb-8">All Jobs</h1>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="p-3 text-left">Niche</th>
              <th className="p-3 text-left">User</th>
              <th className="p-3 text-left">Status</th>
              <th className="p-3 text-left">Leads</th>
              <th className="p-3 text-left">US / CA</th>
              <th className="p-3 text-left">Gigs</th>
              <th className="p-3 text-left">Date</th>
              <th className="p-3 text-left"></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j._id} className="border-b border-border/50">
                <td className="p-3 font-medium">{j.niche}</td>
                <td className="p-3 text-muted-foreground">
                  {j.userId?.email || "—"}
                </td>
                <td className="p-3">
                  <JobStatusBadge status={j.status} />
                </td>
                <td className="p-3">{j.totalLeadsFound}</td>
                <td className="p-3">
                  {j.usLeadsFound} / {j.canadaLeadsFound}
                </td>
                <td className="p-3">{j.gigsScanned}</td>
                <td className="p-3">{formatDate(j.createdAt)}</td>
                <td className="p-3">
                  <Link href={`/jobs/${j._id}`} className="text-primary hover:underline">
                    Monitor
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DashboardLayout>
  );
}
