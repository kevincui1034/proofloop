/**
 * M0 harness check: migrations applied, core tables queryable.
 */
import { sql } from "drizzle-orm";
import { describe, expect, it } from "vitest";

import { db } from "../db";

describe("schema", () => {
  it("has all domain tables", async () => {
    const result = await db.execute(sql`
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public' ORDER BY table_name
    `);
    const names = result.rows.map((r) => r.table_name);
    for (const expected of [
      "users",
      "accounts",
      "sessions",
      "repos",
      "device_codes",
      "device_tokens",
      "records",
      "advisories",
      "label_events",
      "proof_files",
    ]) {
      expect(names).toContain(expected);
    }
  });

  it("enforces ingest idempotency key", async () => {
    const constraint = await db.execute(sql`
      SELECT indexname FROM pg_indexes
      WHERE tablename = 'records' AND indexname = 'records_repo_record'
    `);
    expect(constraint.rows).toHaveLength(1);
  });
});
