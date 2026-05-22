import path from "path";
import type { NextConfig } from "next";

/** Pin workspace root (avoids wrong root when parent folder has package-lock.json). */
const projectRoot = __dirname;

const nextConfig: NextConfig = {
  outputFileTracingRoot: projectRoot,
  serverExternalPackages: ["mongoose", "playwright", "exceljs", "bullmq"],
  poweredByHeader: false,
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts"],
  },
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
