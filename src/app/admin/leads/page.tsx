"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { DataTable } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import { useToast } from "@/components/providers/toast-provider";
import type { Lead } from "@/types";

export default function AdminLeadsPage() {
  const { toast } = useToast();
  const [leads, setLeads] = useState<Lead[]>([]);

  const load = () =>
    apiFetch<{ leads: Lead[] }>("/api/admin/leads").then((d) => setLeads(d.leads));

  useEffect(() => {
    load().catch(console.error);
  }, []);

  const removeDuplicates = async () => {
    try {
      const r = await apiFetch<{ deleted: number }>("/api/admin/leads", {
        method: "DELETE",
        body: JSON.stringify({ removeDuplicates: true }),
      });
      toast({ title: `Removed ${r.deleted} duplicates` });
      load();
    } catch (err) {
      toast({ title: "Error", description: err instanceof Error ? err.message : "" });
    }
  };

  return (
    <DashboardLayout>
      <div className="mb-8 flex justify-between items-center">
        <h1 className="text-3xl font-bold">All Leads</h1>
        <Button variant="outline" onClick={removeDuplicates}>
          Remove Duplicates
        </Button>
      </div>
      <DataTable
        data={leads as unknown as Record<string, unknown>[]}
        columns={[
          { key: "sellerName", header: "Seller" },
          { key: "reviewerName", header: "Reviewer" },
          { key: "country", header: "Country" },
          { key: "serviceNiche", header: "Niche" },
          {
            key: "review",
            header: "Review",
            render: (r) => (
              <span className="max-w-[200px] truncate block">{String(r.review)}</span>
            ),
          },
        ]}
        emptyMessage="No leads in database"
      />
    </DashboardLayout>
  );
}
