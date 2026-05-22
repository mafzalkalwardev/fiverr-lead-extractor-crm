"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { CLIENT_MODE } from "@/lib/constants";

interface SystemStatus {
  worker: boolean;
  redis: boolean;
  mongo: boolean;
  message: string;
  scraperEngine?: string;
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
        Python scraper is running — jobs move from pending to running automatically.
      </div>
    );
  }

  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
      <div>
        <p className="font-medium">Scraper service is offline</p>
        <p className="text-xs mt-1 opacity-90">
          New jobs stay <strong>pending</strong> until the background scraper is started.
        </p>
        {!CLIENT_MODE && (
          <>
            <code className="mt-2 block text-xs bg-black/30 rounded px-2 py-1">
              npm run scraper:py
            </code>
            <p className="text-xs mt-2 opacity-80">
              Or run everything:{" "}
              <code className="bg-black/30 px-1 rounded">npm run dev:all</code>
            </p>
          </>
        )}
        {CLIENT_MODE && (
          <p className="text-xs mt-2 opacity-80">
            Start the application using the shortcut provided with your install package, or contact
            your administrator.
          </p>
        )}
      </div>
    </div>
  );
}
