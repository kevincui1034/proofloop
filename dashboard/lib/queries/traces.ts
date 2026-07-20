/**
 * Repo + trace queries. All queries are user-scoped at the repo boundary:
 * pages resolve the repo through requireRepo(userId, repoId) and every
 * record query is keyed by repoPk.
 */
import {
  and,
  arrayContains,
  count,
  desc,
  eq,
  ilike,
  lt,
  max,
  or,
  sql,
} from "drizzle-orm";

import { db } from "@/db";
import { advisories, records, repos } from "@/db/schema";

export async function listRepos(userId: string) {
  return db
    .select({
      id: repos.id,
      repoSlug: repos.repoSlug,
      displayName: repos.displayName,
      recordCount: count(records.pk),
      lastActivity: max(records.createdAt),
      passRate: sql<number | null>`
        avg(case when ${records.gatePassed} then 1.0 else 0.0 end)`,
    })
    .from(repos)
    .leftJoin(records, eq(records.repoPk, repos.id))
    .where(eq(repos.userId, userId))
    .groupBy(repos.id)
    .orderBy(desc(max(records.createdAt)));
}

export async function getRepo(userId: string, repoId: string) {
  const [repo] = await db
    .select()
    .from(repos)
    .where(and(eq(repos.id, repoId), eq(repos.userId, userId)))
    .limit(1);
  return repo ?? null;
}

export interface TraceFilters {
  verdict?: "passed" | "blocked";
  action?: string;
  failureClass?: string;
  agent?: string;
  q?: string;
  /** keyset cursor: "<createdAt ISO>|<pk>" from the previous page's tail */
  before?: string;
}

export const TRACES_PAGE_SIZE = 50;

export async function listTraces(repoPk: string, filters: TraceFilters) {
  const conditions = [eq(records.repoPk, repoPk)];
  if (filters.verdict) {
    conditions.push(eq(records.gatePassed, filters.verdict === "passed"));
  }
  if (filters.action) conditions.push(eq(records.action, filters.action));
  if (filters.failureClass) {
    conditions.push(arrayContains(records.failureClasses, [filters.failureClass]));
  }
  if (filters.agent) conditions.push(eq(records.agentSource, filters.agent));
  if (filters.q) {
    const needle = `%${filters.q}%`;
    conditions.push(
      or(ilike(records.diagnosis, needle), ilike(records.recordId, needle))!,
    );
  }
  if (filters.before) {
    const [ts, pk] = filters.before.split("|");
    const beforeDate = new Date(ts);
    if (!Number.isNaN(beforeDate.getTime()) && pk) {
      conditions.push(
        or(
          lt(records.createdAt, beforeDate),
          and(eq(records.createdAt, beforeDate), lt(records.pk, pk)),
        )!,
      );
    }
  }
  const advisoryCount = db
    .select({ n: count() })
    .from(advisories)
    .where(eq(advisories.recordPk, records.pk));
  return db
    .select({
      pk: records.pk,
      recordId: records.recordId,
      createdAt: records.createdAt,
      action: records.action,
      agentSource: records.agentSource,
      gatePassed: records.gatePassed,
      failureClasses: records.failureClasses,
      recalledFrom: records.recalledFrom,
      resolutionStatus: records.resolutionStatus,
      advisoryCount: sql<number>`(${advisoryCount})`,
    })
    .from(records)
    .where(and(...conditions))
    .orderBy(desc(records.createdAt), desc(records.pk))
    .limit(TRACES_PAGE_SIZE);
}

/** Distinct filter values actually present in this repo (for the filter bar). */
export async function traceFacets(repoPk: string) {
  const [actions, agents, classes] = await Promise.all([
    db
      .selectDistinct({ value: records.action })
      .from(records)
      .where(eq(records.repoPk, repoPk)),
    db
      .selectDistinct({ value: records.agentSource })
      .from(records)
      .where(eq(records.repoPk, repoPk)),
    db.execute(sql`
      SELECT DISTINCT unnest(failure_classes) AS value
      FROM records WHERE repo_pk = ${repoPk} ORDER BY value
    `),
  ]);
  return {
    actions: actions.map((r) => r.value).sort(),
    agents: agents.map((r) => r.value).sort(),
    failureClasses: (classes.rows as { value: string }[]).map((r) => r.value),
  };
}

export async function getTrace(repoPk: string, recordId: string) {
  const [record] = await db
    .select()
    .from(records)
    .where(and(eq(records.repoPk, repoPk), eq(records.recordId, recordId)))
    .limit(1);
  if (!record) return null;
  const advisoryRows = await db
    .select()
    .from(advisories)
    .where(eq(advisories.recordPk, record.pk))
    .orderBy(advisories.idx);
  // "was the advice followed": the later record whose `resolves` points here.
  const [resolvedBy] = await db
    .select({ recordId: records.recordId })
    .from(records)
    .where(and(eq(records.repoPk, repoPk), eq(records.resolves, recordId)))
    .limit(1);
  return { record, advisories: advisoryRows, resolvedBy: resolvedBy ?? null };
}
