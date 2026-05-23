"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { CLIENT_MODE } from "@/lib/constants";

interface SystemStatus {
  worker: boolean;
  redis: boolean;
  mongo: boolean;
  message: string;
  scraperEngine?: string;
  configuredEngine?: string;
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
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  if (!status) return null;

  const wrongEngine =
    status.configuredEngine === "python" && status.scraperEngine === "node";
  const pythonOk = status.worker && status.scraperEngine === "python";

  if (wrongEngine) {
    return (
      <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Wrong scraper is running</p>
          <p className="text-xs mt-1 opacity-90">
            The old Node worker is processing jobs (0 reviews). Stop any{" "}
            <code className="bg-black/30 px-1 rounded">npm run worker</code> terminal. Only run{" "}
            <code className="bg-black/30 px-1 rounded">npm run client:start</code> or{" "}
            <code className="bg-black/30 px-1 rounded">npm run scraper:py</code>.
          </p>
        </div>
      </div>
    );
  }

  if (pythonOk) {
    return (
      <div className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-400">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        Python scraper active - jobs pause for Fiverr verification and resume automatically
      </div>
    );
  }

  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div>
        <p className="font-medium">Scraper service offline</p>
        <p className="text-xs mt-1 opacity-90">
          Jobs stay <strong>pending</strong> until the Python scraper starts.
        </p>
        {!CLIENT_MODE && (
          <code className="mt-2 block text-xs bg-black/30 rounded px-2 py-1">
            npm run client:start
          </code>
        )}
        {CLIENT_MODE && (
          <p className="text-xs mt-2 flex items-center gap-1 opacity-80">
            <Info className="h-3 w-3" />
            Run the desktop shortcut provided with your install package.
          </p>
        )}
      </div>
    </div>
  );
}
