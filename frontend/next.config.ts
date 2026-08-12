import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @ts-ignore
  turbopack: {
    root: process.cwd(),
  },
  webpack: (config) => {
    config.resolve.fallback = {
      ...config.resolve.fallback,
      accounts: false,
      '@base-org/account': false,
      '@coinbase/wallet-sdk': false,
      '@metamask/connect-evm': false,
      'porto/internal': false,
      'porto': false,
      '@x402/evm/upto/client': false,
      '@x402/evm/exact/client': false,
      '@x402/svm/upto/client': false,
      '@x402/svm/exact/client': false,
      '@x402/core/client': false,
      '@x402/evm': false,
      '@x402/svm': false,
      '@x402/core': false,
    };
    return config;
  },
};

export default nextConfig;
