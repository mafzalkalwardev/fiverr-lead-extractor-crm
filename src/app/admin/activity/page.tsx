"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { apiFetch } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { ActivityLogEntry } from "@/types";

export default function AdminActivityPage() {
  const [logs, setLogs] = useState<ActivityLogEntry[]>([]);

  useEffect(() => {
    apiFetch<{ logs: ActivityLogEntry[] }>("/api/admin/activity")
      .then((d) => setLogs(d.logs))
      .catch(console.error);
  }, []);

  return (
    <DashboardLayout>
      <h1 className="text-3xl font-bold mb-8">Activity Logs</h1>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="p-3 text-left">Time</th>
              <th className="p-3 text-left">User</th>
              <th className="p-3 text-left">Action</th>
              <th className="p-3 text-left">Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l._id} className="border-b border-border/50">
                <td className="p-3 whitespace-nowrap">{formatDate(l.createdAt)}</td>
                <td className="p-3">
                  {typeof l.userId === "object" && l.userId
                    ? (l.userId as { email: string }).email
                    : "—"}
                </td>
                <td className="p-3 font-mono text-xs">{l.action}</td>
                <td className="p-3 text-muted-foreground">{l.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </DashboardLayout>
  );
}
