import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin();

const nextConfig: NextConfig = {
  // туннель для разработки: dev-сервер отдаёт свои файлы только localhost
  allowedDevOrigins: process.env.DEV_TUNNEL_HOST ? [process.env.DEV_TUNNEL_HOST] : [],
  // для Docker: сервер и только нужные ему модули в .next/standalone
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  // «Входящие» переименованы в «Журнал»: старый адрес мог остаться в закладках
  async redirects() {
    return [{ source: "/inbox", destination: "/journal", permanent: true }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default withNextIntl(nextConfig);
