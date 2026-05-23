"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { apiFetch } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { ActivityLogEntry } from "@/types";

export default function UserActivityPage() {
  const [logs, setLogs] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ logs: ActivityLogEntry[] }>("/api/auth/activity")
      .then((data) => {
        setLogs(data.logs);
      })
      .catch((err) => {
        setError(err.message || "Failed to load activity.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="page-title">Activity Logs</h1>
          <p className="page-subtitle">View your recent actions and system events.</p>
        </div>

        <div className="overflow-hidden rounded-2xl border border-border bg-card/80 shadow-sm">
          {loading ? (
            <div className="p-8 text-center text-sm text-muted-foreground">Loading your activity...</div>
          ) : error ? (
            <div className="p-8 text-center text-sm text-red-300">{error}</div>
          ) : logs.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">No recent activity found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="p-3 text-left">Time</th>
                    <th className="p-3 text-left">Action</th>
                    <th className="p-3 text-left">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log._id} className="border-b border-border/50">
                      <td className="p-3 whitespace-nowrap">{formatDate(log.createdAt)}</td>
                      <td className="p-3 font-mono text-xs text-primary">{log.action}</td>
                      <td className="p-3 text-muted-foreground">{log.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </DashboardLayout>
  );
}
