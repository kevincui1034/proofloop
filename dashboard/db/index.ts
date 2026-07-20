import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "./schema";

// One pool per process; Next dev hot-reload reuses it via globalThis.
const globalForDb = globalThis as unknown as { pgPool?: Pool };

/**
 * Managed Postgres (Supabase, etc.) requires TLS; local docker does not.
 * `DATABASE_SSL=disable` forces it off. `rejectUnauthorized: false` keeps
 * the connection encrypted without pinning the provider CA — set
 * DATABASE_SSL_CA to a PEM to verify strictly.
 */
function sslConfig(url: string | undefined) {
  if (process.env.DATABASE_SSL === "disable") return false;
  if (!url || /@(localhost|127\.0\.0\.1|postgres)[:/]/.test(url)) return false;
  const ca = process.env.DATABASE_SSL_CA;
  return ca ? { ca } : { rejectUnauthorized: false };
}

const pool =
  globalForDb.pgPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 10,
    ssl: sslConfig(process.env.DATABASE_URL),
  });
if (process.env.NODE_ENV !== "production") globalForDb.pgPool = pool;

export const db = drizzle(pool, { schema });
export type Db = typeof db;
