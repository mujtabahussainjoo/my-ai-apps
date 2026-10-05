import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Remote dev through a Cloudflare quick tunnel reaches the dev server under a
  // random `*.trycloudflare.com` hostname, which the dev server otherwise blocks
  // as a cross-origin source (no assets, no HMR). The hostname changes on every
  // tunnel restart, so match the whole zone rather than one host.
  allowedDevOrigins: ["*.trycloudflare.com"],
  // pdfjs loads its worker with `import(GlobalWorkerOptions.workerSrc)`, where the
  // default resolves to a sibling of pdfjs' own module. Turbopack rewrites that
  // dynamic import into its own module graph, so the worker path ends up inside
  // `.next/.../chunks/ssr/` and every PDF parse dies with
  // "Cannot find module .../pdf.worker.mjs". Keeping these packages external lets
  // Node's own ESM loader resolve the worker from node_modules instead.
  serverExternalPackages: ["pdf-parse", "pdfjs-dist"],
  experimental: {
    serverActions: {
      // Server actions default to a 1MB body, which silently fails any upload
      // above ~1MB even though the form advertises 15MB per file. Folder
      // uploads multiply that, so the cap is raised to cover a realistic
      // training pack; the form enforces a matching client-side total.
      bodySizeLimit: "64mb",
      // Server Actions run their own origin check, so the tunnel hostname has
      // to be allowed here as well or every mutation from the tunnel is
      // rejected as a cross-site request.
      allowedOrigins: ["*.trycloudflare.com"],
    },
  },
};

export default nextConfig;
