import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  devIndicators: false,
  experimental: {
    // Keep production page-data generation serial on the development laptop.
    cpus: 1,
    useTypeScriptCli: true,
  },
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  transpilePackages: ["@trading212/api-contracts", "@trading212/ui"],
};

export default nextConfig;
