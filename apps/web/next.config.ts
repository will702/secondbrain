import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export served by the FastAPI backend (packaged app + prod mode).
  // `pnpm dev` is unaffected; `pnpm start` no longer applies.
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
