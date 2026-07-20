/**
 * E2 — graduation board. Mirrors the CLI's candidate computation
 * (memory/export.py): >= GRADUATION_MIN_CONFIRMED confirmed advisories
 * sharing a signature become a candidate deterministic check; the latest
 * concern wording wins. 1–2 confirmations = "warming up".
 */
import { sql } from "drizzle-orm";

import { db } from "@/db";

/** Mirror of cli/src/proofjury/memory/export.py GRADUATION_MIN_CONFIRMED. */
export const GRADUATION_MIN_CONFIRMED = 3;

export interface Candidate {
  signature: string;
  confirmed: number;
  concern: string;
  kind: string | null;
  target: string | null;
  refs: string[]; // "chk_012#0"
}

export async function graduationBoard(repoPk: string): Promise<{
  candidates: Candidate[];
  warming: Candidate[];
}> {
  const result = await db.execute(sql`
    SELECT signature,
           count(*)::int AS confirmed,
           (array_agg(concern ORDER BY created_at DESC))[1] AS concern,
           (array_agg(kind    ORDER BY created_at DESC))[1] AS kind,
           (array_agg(target  ORDER BY created_at DESC))[1] AS target,
           array_agg(record_id || '#' || idx ORDER BY created_at) AS refs
    FROM advisories
    WHERE repo_pk = ${repoPk} AND label = 'confirmed'
    GROUP BY signature
    ORDER BY confirmed DESC, concern
  `);
  const rows = result.rows as unknown as Candidate[];
  return {
    candidates: rows.filter((r) => r.confirmed >= GRADUATION_MIN_CONFIRMED),
    warming: rows.filter((r) => r.confirmed < GRADUATION_MIN_CONFIRMED),
  };
}
