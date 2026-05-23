"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Download } from "lucide-react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { DataTable } from "@/components/data-table";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { ScrapeJob, Lead } from "@/types";
import { useToast } from "@/components/providers/toast-provider";

const ALL_LEADS = "__all__";

function UrlCell({ url }: { url: string }) {
  if (!url) return <span className="text-muted-foreground">—</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary text-xs break-all hover:underline max-w-[280px] inline-block"
      title={url}
    >
      {url}
    </a>
  );
}

function ReviewImageCell({ url }: { url: string }) {
  if (!url) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex items-center gap-2 max-w-[200px]">
      <img
        src={url}
        alt=""
        className="h-10 w-10 rounded object-cover border border-border shrink-0"
        loading="lazy"
      />
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary text-xs break-all hover:underline line-clamp-2"
        title={url}
      >
        Open
      </a>
    </div>
  );
}

function LeadsContent() {
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);
  const [jobId, setJobId] = useState(searchParams?.get("jobId") ?? ALL_LEADS);
  const [leads, setLeads] = useState<Lead[]>([]);

  useEffect(() => {
    apiFetch<{ jobs: ScrapeJob[] }>("/api/jobs")
      .then((d) => setJobs(d.jobs))
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const url = jobId === ALL_LEADS ? "/api/leads" : `/api/jobs/${jobId}/leads`;
    apiFetch<{ leads: Lead[] }>(url)
      .then((d) => setLeads(d.leads))
      .catch(console.error);
  }, [jobId]);

  const exportLeads = async () => {
    const token = localStorage.getItem("token");
    const url = jobId === ALL_LEADS ? "/api/leads/export" : `/api/jobs/${jobId}/export`;
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      toast({ title: "Export failed" });
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = jobId === ALL_LEADS ? "fiverr-leads-all.xlsx" : "fiverr-leads-export.xlsx";
    a.click();
    toast({ title: "Leads exported" });
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="space-y-2 min-w-[200px]">
          <Label>Job</Label>
          <Select value={jobId} onChange={(e) => setJobId(e.target.value)}>
            <option value={ALL_LEADS}>All leads</option>
            {jobs.map((j) => (
              <option key={j._id} value={j._id}>
                {j.niche} — {j.status} ({j.totalLeadsFound} leads)
              </option>
            ))}
          </Select>
        </div>
        <Button onClick={exportLeads} className="gap-2" disabled={!jobId}>
          <Download className="h-4 w-4" /> Export Leads
        </Button>
      </div>

      <DataTable
        data={leads as unknown as Record<string, unknown>[]}
        columns={[
          { key: "sellerName", header: "Seller Name" },
          { key: "sellerUsername", header: "Seller Username" },
          {
            key: "gigLink",
            header: "Gig Link",
            render: (r) => <UrlCell url={String(r.gigLink || "")} />,
          },
          { key: "gigTitle", header: "Gig Title" },
          { key: "reviewerName", header: "Reviewer Username" },
          { key: "country", header: "Country" },
          {
            key: "review",
            header: "Review",
            render: (r) => (
              <span className="max-w-[180px] truncate block" title={String(r.review)}>
                {String(r.review)}
              </span>
            ),
          },
          { key: "reviewRating", header: "Review Rating" },
          {
            key: "reviewedImageLink",
            header: "Reviewed Image Link",
            render: (r) => <ReviewImageCell url={String(r.reviewedImageLink || "")} />,
          },
          { key: "serviceNiche", header: "Service/Niche" },
        ]}
        emptyMessage="No leads yet — run a job with US/Canada filter"
      />
    </>
  );
}

export default function LeadsPage() {
  return (
    <DashboardLayout>
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Extracted Leads</h1>
        <p className="text-muted-foreground">US & Canada reviews only · deduplicated</p>
      </div>
      <Suspense fallback={<p>Loading...</p>}>
        <LeadsContent />
      </Suspense>
    </DashboardLayout>
  );
}
