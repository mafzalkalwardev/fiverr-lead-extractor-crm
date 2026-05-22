"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { StatsCard } from "@/components/stats-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { DashboardStats } from "@/types";
import { Users, Briefcase, Flag, Shield } from "lucide-react";
import { COMPANY_NAME, COMPANY_PHONE } from "@/lib/constants";

export default function AdminPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);

  useEffect(() => {
    apiFetch<{ stats: DashboardStats }>("/api/jobs")
      .then((d) => setStats(d.stats))
      .catch(console.error);
  }, []);

  return (
    <DashboardLayout>
      <div className="mb-8">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Shield className="h-8 w-8 text-primary" />
          Admin CRM
        </h1>
        <p className="text-muted-foreground">
          {COMPANY_NAME} · {COMPANY_PHONE}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4 mb-8">
        <StatsCard title="All Jobs" value={stats?.totalJobs ?? 0} icon={Briefcase} />
        <StatsCard title="All Leads" value={stats?.totalLeads ?? 0} icon={Users} />
        <StatsCard title="US Leads" value={stats?.usLeads ?? 0} icon={Flag} />
        <StatsCard title="Canada Leads" value={stats?.canadaLeads ?? 0} icon={Flag} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[
          { href: "/admin/users", label: "Manage Users" },
          { href: "/admin/jobs", label: "All Jobs" },
          { href: "/admin/leads", label: "All Leads" },
          { href: "/admin/activity", label: "Activity Logs" },
        ].map((l) => (
          <Card key={l.href}>
            <CardHeader>
              <CardTitle className="text-lg">{l.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <Link href={l.href}>
                <Button variant="outline" className="w-full">
                  Open
                </Button>
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </DashboardLayout>
  );
}
