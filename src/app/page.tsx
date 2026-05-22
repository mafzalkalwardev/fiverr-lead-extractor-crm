"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Home — middleware also redirects; this avoids server `redirect()` manifest bugs. */
export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("token");
    router.replace(token ? "/dashboard" : "/login");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  );
}
