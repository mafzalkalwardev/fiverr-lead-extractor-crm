"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  PlusCircle,
  Activity,
  Users,
  Download,
  LogOut,
  Shield,
  ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/branding";

const userNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs/new", label: "Create Job", icon: PlusCircle },
  { href: "/jobs", label: "Live Monitor", icon: Activity },
  { href: "/leads", label: "Leads", icon: Users },
];

const adminNav = [
  { href: "/admin", label: "Admin CRM", icon: Shield },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/jobs", label: "All Jobs", icon: Activity },
  { href: "/admin/leads", label: "All Leads", icon: Download },
  { href: "/admin/activity", label: "Activity Logs", icon: ScrollText },
];

export function Sidebar() {
  const pathname = usePathname();
  const [role, setRole] = useState<string>("user");

  useEffect(() => {
    try {
      const u = JSON.parse(localStorage.getItem("user") || "{}");
      setRole(u.role || "user");
    } catch {
      setRole("user");
    }
  }, []);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/login";
  };

  const items = role === "admin" ? [...userNav, ...adminNav] : userNav;

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-64 flex-col border-r border-border bg-gradient-to-b from-card to-background shadow-xl">
      <div className="border-b border-border px-6 py-4">
        <BrandLogo />
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto p-4">
        {items.map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border p-4">
        <Button variant="ghost" className="w-full justify-start gap-2" onClick={logout}>
          <LogOut className="h-4 w-4" />
          Logout
        </Button>
      </div>
    </aside>
  );
}
