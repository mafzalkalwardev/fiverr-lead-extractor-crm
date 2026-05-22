import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  serverExternalPackages: ["mongoose", "playwright", "exceljs", "bullmq"],
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
