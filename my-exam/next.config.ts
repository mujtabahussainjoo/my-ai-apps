import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    serverActions: {
      // Server actions default to a 1MB body, which silently fails any upload
      // above ~1MB even though the form advertises 15MB per file. Folder
      // uploads multiply that, so the cap is raised to cover a realistic
      // training pack; the form enforces a matching client-side total.
      bodySizeLimit: "64mb",
    },
  },
};

export default nextConfig;
