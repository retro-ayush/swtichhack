import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // /api/* is served by app/api/[...path]/route.ts (server-side proxy that
  // injects TEAMPILOT_API_TOKEN); no rewrite needed.
};

export default nextConfig;
