"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Sidebar } from "./sidebar";
import { BrandFooter } from "@/components/branding";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.replace("/login");
      return;
    }
    if (pathname.startsWith("/admin")) {
      try {
        const u = JSON.parse(localStorage.getItem("user") || "{}");
        if (u.role !== "admin") router.replace("/dashboard");
      } catch {
        router.replace("/dashboard");
      }
    }
  }, [router, pathname]);

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
