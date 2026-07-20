/** Repo overview aggregates — mirrors `proofjury status` / `memory stats`. */
import { sql } from "drizzle-orm";

import { db } from "@/db";

export interface DayPoint {
  day: string; // YYYY-MM-DD
  passed: number;
  blocked: number;
}

export async function passRateByDay(repoPk: string): Promise<DayPoint[]> {
  const result = await db.execute(sql`
    SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day,
           count(*) FILTER (WHERE gate_passed)     AS passed,
           count(*) FILTER (WHERE NOT gate_passed) AS blocked
    FROM records WHERE repo_pk = ${repoPk}
    GROUP BY 1 ORDER BY 1
  `);
  return (result.rows as { day: string; passed: string; blocked: string }[]).map(
    (row) => ({
      day: row.day,
      passed: Number(row.passed),
      blocked: Number(row.blocked),
    }),
  );
}

export async function failureClassCounts(
  repoPk: string,
): Promise<{ name: string; count: number }[]> {
  const result = await db.execute(sql`
    SELECT unnest(failure_classes) AS name, count(*) AS count
    FROM records WHERE repo_pk = ${repoPk}
    GROUP BY 1 ORDER BY 2 DESC, 1
  `);
  return (result.rows as { name: string; count: string }[]).map((row) => ({
    name: row.name,
    count: Number(row.count),
  }));
}

export interface OverviewStats {
  total: number;
  blocked: number;
  passed: number;
  recallHitRate: number | null; // recalled / blocked
  autoResolveRate: number | null;
  p95DurationMs: number | null;
  advisories: number;
}

export async function overviewStats(repoPk: string): Promise<OverviewStats> {
  const result = await db.execute(sql`
    SELECT count(*)::int                                     AS total,
           count(*) FILTER (WHERE NOT gate_passed)::int      AS blocked,
           count(*) FILTER (WHERE gate_passed)::int          AS passed,
           count(*) FILTER (WHERE recalled_from IS NOT NULL)::int AS recalled,
           count(*) FILTER (WHERE resolution_status = 'auto_resolved')::int AS auto_resolved,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY gate_duration_ms) AS p95,
           (SELECT count(*)::int FROM advisories a WHERE a.repo_pk = ${repoPk}) AS advisory_count
    FROM records WHERE repo_pk = ${repoPk}
  `);
  const row = result.rows[0] as {
    total: number;
    blocked: number;
    passed: number;
    recalled: number;
    auto_resolved: number;
    p95: number | null;
    advisory_count: number;
  };
  return {
    total: row.total,
    blocked: row.blocked,
    passed: row.passed,
    recallHitRate: row.blocked > 0 ? row.recalled / row.blocked : null,
    autoResolveRate: row.blocked > 0 ? row.auto_resolved / row.blocked : null,
    p95DurationMs: row.p95 === null ? null : Math.round(Number(row.p95)),
    advisories: row.advisory_count,
  };
}
