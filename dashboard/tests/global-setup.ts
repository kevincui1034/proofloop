/**
 * Vitest global setup: apply Drizzle migrations to the TEST database.
 *
 * Tests TRUNCATE between files, so they must never share a database with
 * `next dev` — locally they get their own `proofjury_test` DB (created
 * here if missing) in the same docker Postgres. CI sets DATABASE_URL
 * explicitly and skips the create.
 */
import { execSync } from "node:child_process";

import { Client } from "pg";

const LOCAL_ADMIN_URL = "postgres://proofjury:proofjury@localhost:54329/proofjury";
const LOCAL_TEST_URL = "postgres://proofjury:proofjury@localhost:54329/proofjury_test";

export default async function setup() {
  if (!process.env.DATABASE_URL) {
    const admin = new Client({ connectionString: LOCAL_ADMIN_URL });
    await admin.connect();
    const exists = await admin.query(
      "SELECT 1 FROM pg_database WHERE datname = 'proofjury_test'",
    );
    if (exists.rowCount === 0) {
      await admin.query("CREATE DATABASE proofjury_test");
    }
    await admin.end();
    process.env.DATABASE_URL = LOCAL_TEST_URL;
  }
  execSync("npx drizzle-kit migrate", {
    stdio: "inherit",
    env: process.env,
  });
}
