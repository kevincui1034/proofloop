/**
 * E3 — memory / recall explorer. Mirrors `proofjury memory stats`
 * (cli memory/export.py): which priors fire, recall hit rate, cross-repo
 * hits, class reliability (recall.py noisy rule), advisory breakdowns,
 * and the rejected-signature suppression list.
 */
import { sql } from "drizzle-orm";

import { db } from "@/db";

export interface CitedPrior {
  citedId: string; // "chk_012" or cross-repo "repo:chk_012"
  hits: number;
  crossRepo: boolean;
}

export async function mostCitedPriors(repoPk: string): Promise<CitedPrior[]> {
  const result = await db.execute(sql`
    SELECT recalled_from AS cited, count(*)::int AS hits
    FROM records
    WHERE repo_pk = ${repoPk} AND recalled_from IS NOT NULL
    GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 20
  `);
  return (result.rows as { cited: string; hits: number }[]).map((row) => ({
    citedId: row.cited,
    hits: row.hits,
    crossRepo: row.cited.includes(":"),
  }));
}

export interface RecallStats {
  blocked: number;
  recalled: number;
  crossRepoHits: number;
}

export async function recallStats(repoPk: string): Promise<RecallStats> {
  const result = await db.execute(sql`
    SELECT count(*) FILTER (WHERE NOT gate_passed)::int AS blocked,
           count(*) FILTER (WHERE recalled_from IS NOT NULL)::int AS recalled,
           count(*) FILTER (WHERE recalled_from LIKE '%:%')::int AS cross_repo
    FROM records WHERE repo_pk = ${repoPk}
  `);
  const row = result.rows[0] as {
    blocked: number;
    recalled: number;
    cross_repo: number;
  };
  return {
    blocked: row.blocked,
    recalled: row.recalled,
    crossRepoHits: row.cross_repo,
  };
}

export interface ClassReliability {
  failureClass: string;
  accepted: number;
  falsePositive: number;
  noisy: boolean;
}

/** recall.py: a class is noisy when false_positive >= 2 AND > accepted —
 * its priors demote (never exclude) in recall. */
export async function classReliability(
  repoPk: string,
): Promise<ClassReliability[]> {
  const result = await db.execute(sql`
    SELECT cls AS failure_class,
           count(*) FILTER (WHERE resolution_status = 'accepted')::int AS accepted,
           count(*) FILTER (WHERE resolution_status = 'false_positive')::int AS false_positive
    FROM records, unnest(failure_classes) AS cls
    WHERE repo_pk = ${repoPk}
      AND NOT gate_passed
      AND resolution_status IN ('accepted', 'false_positive')
    GROUP BY 1 ORDER BY 1
  `);
  return (
    result.rows as {
      failure_class: string;
      accepted: number;
      false_positive: number;
    }[]
  ).map((row) => ({
    failureClass: row.failure_class,
    accepted: row.accepted,
    falsePositive: row.false_positive,
    noisy: row.false_positive >= 2 && row.false_positive > row.accepted,
  }));
}

export interface AdvisoryBreakdown {
  byDelivery: { delivery: string; count: number }[];
  byLabel: { label: string; count: number }[];
  rejectedSignatures: { signature: string; concern: string }[];
}

export async function advisoryBreakdown(
  repoPk: string,
): Promise<AdvisoryBreakdown> {
  const [byDelivery, byLabel, rejected] = await Promise.all([
    db.execute(sql`
      SELECT delivery, count(*)::int AS count FROM advisories
      WHERE repo_pk = ${repoPk} GROUP BY 1 ORDER BY 2 DESC
    `),
    db.execute(sql`
      SELECT label, count(*)::int AS count FROM advisories
      WHERE repo_pk = ${repoPk} AND label IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
    `),
    db.execute(sql`
      SELECT DISTINCT ON (signature) signature, concern FROM advisories
      WHERE repo_pk = ${repoPk} AND label = 'rejected'
      ORDER BY signature, created_at DESC
    `),
  ]);
  return {
    byDelivery: byDelivery.rows as { delivery: string; count: number }[],
    byLabel: byLabel.rows as { label: string; count: number }[],
    rejectedSignatures: rejected.rows as { signature: string; concern: string }[],
  };
}
