"use client";

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, ExternalLink, Play, RefreshCw } from "lucide-react";
import { APP_NAME } from "@/lib/constants";

type Status = {
  mongo: boolean;
  worker: boolean;
  message: string;
};

function StatusRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
      {ok ? (
        <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
      ) : (
        <XCircle className="h-5 w-5 text-destructive shrink-0" />
      )}
      <span className="text-sm">{label}</span>
    </div>
  );
}

export default function SetupPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [appUrl, setAppUrl] = useState("http://localhost:3000");

  const load = () => {
    fetch("/api/system/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus(null));
    if (typeof window !== "undefined") {
      setAppUrl(window.location.origin);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const ready = status?.mongo && status?.worker;

  return (
    <DashboardLayout>
      <div className="mb-8 max-w-3xl">
        <h1 className="page-title">System Setup</h1>
        <p className="page-subtitle">
          {APP_NAME} — check services before creating jobs
        </p>
      </div>

      <div className="grid gap-6 max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Service health</CardTitle>
            <CardDescription>Both must be green for jobs to run automatically</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatusRow ok={!!status?.mongo} label="Database (MongoDB)" />
            <StatusRow
              ok={!!status?.worker}
              label="Scraper service (Python — processes jobs automatically)"
            />
            {status?.message && (
              <p className="text-xs text-muted-foreground pt-1">{status.message}</p>
            )}
            <Button variant="outline" size="sm" className="gap-2" onClick={load}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Play className="h-5 w-5 text-primary" />
              How to start (for non-technical users)
            </CardTitle>
            <CardDescription>
              Double-click the desktop shortcut — do not open terminals manually
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <ol className="list-decimal list-inside space-y-2">
              <li>
                Use <strong className="text-foreground">Start Fiverr Lead CRM.bat</strong> in the
                project folder (installer places it on the Desktop).
              </li>
              <li>Wait until this page shows both services green.</li>
              <li>Sign in, create a job, and monitor progress under Live Monitor.</li>
            </ol>
            <p>
              This is a <strong className="text-foreground">local application</strong>, not a public
              website link. It runs on your computer at{" "}
              <code className="text-xs bg-muted px-1 rounded">{appUrl}</code>.
            </p>
            {ready && (
              <Button asChild className="gap-2">
                <a href="/dashboard">
                  <ExternalLink className="h-4 w-4" />
                  Open Dashboard
                </a>
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}
