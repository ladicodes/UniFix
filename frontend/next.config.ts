import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets phones and other machines on the LAN load the dev server, e.g. http://192.168.x.x:3000.
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "*.local"],
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
};

export default nextConfig;
