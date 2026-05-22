"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Sidebar } from "./sidebar";
import { BrandFooter } from "@/components/branding";

function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center space-y-3">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading workspace…</p>
      </div>
    </div>
  );
}

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.replace("/login");
      return;
    }

    if (pathname.startsWith("/admin")) {
      try {
        const u = JSON.parse(localStorage.getItem("user") || "{}");
        if (u.role !== "admin") {
          router.replace("/dashboard");
          return;
        }
      } catch {
        router.replace("/dashboard");
        return;
      }
    }

    setReady(true);
  }, [router, pathname]);

  if (!ready) {
    return <AuthLoading />;
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Sidebar />
      <main className="ml-64 min-h-screen flex-1 p-8 pb-16">{children}</main>
      <footer className="ml-64 py-4 border-t border-border">
        <BrandFooter />
      </footer>
    </div>
  );
}
