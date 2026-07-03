import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @ts-ignore
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
