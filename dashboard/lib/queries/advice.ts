/**
 * Judge advice feed: the chronological answer to "what has the judge told
 * my agent". Deny events (blocked records: diagnosis + fix context, with
 * the later `resolves` linkage = "was the advice followed"), advisory
 * findings with their delivery lifecycle, and retractions as entries of
 * their own.
 */
import { and, desc, eq } from "drizzle-orm";
import { alias } from "drizzle-orm/pg-core";

import { db } from "@/db";
import { advisories, records } from "@/db/schema";

export interface FeedDeny {
  type: "deny";
  recordId: string;
  createdAt: Date;
  diagnosis: string;
  failureClasses: string[];
  recalledFrom: string | null;
  resolvedBy: string | null;
}

export interface FeedAdvisory {
  type: "advisory";
  recordId: string;
  idx: number;
  createdAt: Date;
  concern: string;
  kind: string | null;
  tier: number | null;
  confidence: number | null;
  target: string | null;
  delivery: string;
  label: string | null;
  retraction: string | null;
}

export type FeedEvent = FeedDeny | FeedAdvisory;

export async function adviceFeed(repoPk: string): Promise<FeedEvent[]> {
  const resolver = alias(records, "resolver");
  const denies = await db
    .select({
      recordId: records.recordId,
      createdAt: records.createdAt,
      diagnosis: records.diagnosis,
      failureClasses: records.failureClasses,
      recalledFrom: records.recalledFrom,
      resolvedBy: resolver.recordId,
    })
    .from(records)
    .leftJoin(
      resolver,
      and(eq(resolver.repoPk, repoPk), eq(resolver.resolves, records.recordId)),
    )
    .where(and(eq(records.repoPk, repoPk), eq(records.gatePassed, false)))
    .orderBy(desc(records.createdAt));

  const findings = await db
    .select()
    .from(advisories)
    .where(eq(advisories.repoPk, repoPk))
    .orderBy(desc(advisories.createdAt), advisories.idx);

  const events: FeedEvent[] = [
    ...denies.map(
      (row): FeedDeny => ({
        type: "deny",
        recordId: row.recordId,
        createdAt: row.createdAt,
        diagnosis: row.diagnosis,
        failureClasses: row.failureClasses,
        recalledFrom: row.recalledFrom,
        resolvedBy: row.resolvedBy,
      }),
    ),
    ...findings.map(
      (row): FeedAdvisory => ({
        type: "advisory",
        recordId: row.recordId,
        idx: row.idx,
        createdAt: row.createdAt,
        concern: row.concern,
        kind: row.kind,
        tier: row.tier,
        confidence: row.confidence,
        target: row.target,
        delivery: row.delivery,
        label: row.label,
        retraction: row.retraction,
      }),
    ),
  ];
  return events.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
}
