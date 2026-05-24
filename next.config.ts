import type { NextConfig } from "next";
import path from "path";

const BACKEND_URL =
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.VITE_API_BASE_URL ||
  "https://hive-production-7343.up.railway.app";

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(__dirname),
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || BACKEND_URL,
    VITE_API_BASE_URL: process.env.VITE_API_BASE_URL || BACKEND_URL,
  },
  async rewrites() {
    return [
      { source: "/health", destination: `${BACKEND_URL}/health` },
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
