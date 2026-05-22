"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

interface SystemStatus {
  worker: boolean;
  redis: boolean;
  mongo: boolean;
  message: string;
}

export function WorkerStatusBanner() {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    const load = () => {
      fetch("/api/system/status")
        .then((r) => r.json())
        .then(setStatus)
        .catch(() => setStatus(null));
    };
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  if (!status) return null;

  if (status.worker) {
    return (
      <div className="mb-4 flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-400">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        Worker is running — jobs will move from pending to running automatically.
      </div>
    );
  }

  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div>
        <p className="font-medium">Worker not running</p>
        <p className="text-xs mt-1 opacity-90">
          Jobs stay <strong>pending</strong> until you start the worker in a separate terminal:
        </p>
        <code className="mt-2 block text-xs bg-black/30 rounded px-2 py-1">
          npm run worker
        </code>
        {!status.redis && (
          <p className="text-xs mt-2">Redis is not reachable — run scripts\start-redis5.ps1 first.</p>
        )}
      </div>
    </div>
  );
}
