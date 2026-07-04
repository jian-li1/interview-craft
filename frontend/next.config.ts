import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone build output for the Cloud Run Dockerfile (deploy/, backend/Dockerfile
  // pattern mirrored here) — bundles only the files needed to run `server.js`.
  output: "standalone",
};

export default nextConfig;
