import type { NextConfig } from "next";

// Server runtime required (Auth.js, Postgres, Blob) — deliberately NOT
// `output: "export"` (the landing app's static-export config must not be
// copied here).
const nextConfig: NextConfig = {};

export default nextConfig;
