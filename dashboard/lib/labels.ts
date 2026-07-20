/**
 * E1 — advisory review from the web. Each action reproduces the CLI
 * semantics EXACTLY (cli/src/proofjury/cli.py advisory approve/reject/
 * confirm), in one transaction: update the advisories row, patch the
 * record's JSONB copy, and append a label_event — the down-sync feed the
 * CLI pulls (its id is the cursor).
 *
 * Delivery to the agent happens CLI-side: the next `proofjury sync` (or
 * post-gate auto-sync) applies the event via store.label_advisory, and
 * the gate's own drain machinery hands staged notes/retractions to the
 * agent on the next gate event.
 */
import { and, eq, sql } from "drizzle-orm";

import { db } from "@/db";
import { advisories, labelEvents, records, repos } from "@/db/schema";

export class LabelError extends Error {}

interface AdvisoryRef {
  advisoryPk: string;
  userId: string;
}

async function loadOwned({ advisoryPk, userId }: AdvisoryRef) {
  const [row] = await db
    .select({
      advisory: advisories,
      repoPk: repos.id,
      recordPk: records.pk,
    })
    .from(advisories)
    .innerJoin(records, eq(records.pk, advisories.recordPk))
    .innerJoin(repos, eq(repos.id, advisories.repoPk))
    .where(and(eq(advisories.pk, advisoryPk), eq(repos.userId, userId)))
    .limit(1);
  if (!row) throw new LabelError("advisory not found");
  return row;
}

type Patch = Partial<{
  label: string;
  delivery: string;
  retraction: string;
}>;

async function applyPatch(ref: AdvisoryRef, patch: Patch): Promise<void> {
  const { advisory, repoPk, recordPk } = await loadOwned(ref);
  await db.transaction(async (tx) => {
    await tx
      .update(advisories)
      .set(patch)
      .where(eq(advisories.pk, advisory.pk));
    // Patch the same fields inside the record's JSONB advisories entry so
    // a CLI re-push comparison sees converged content.
    let expr = sql`${records.data}`;
    for (const [key, value] of Object.entries(patch)) {
      expr = sql`jsonb_set(${expr}, ${`{advisories,${advisory.idx},${key}}`}::text[], ${JSON.stringify(value)}::jsonb)`;
    }
    await tx
      .update(records)
      .set({ data: expr, updatedAt: new Date() })
      .where(eq(records.pk, recordPk));
    await tx.insert(labelEvents).values({
      repoPk,
      recordId: advisory.recordId,
      kind: "advisory_label",
      idx: advisory.idx,
      payload: patch,
      source: "web",
    });
  });
}

/** Approve a HELD finding — it reaches the agent on the next gate event. */
export async function approveAdvisory(ref: AdvisoryRef): Promise<void> {
  const { advisory } = await loadOwned(ref);
  if (advisory.delivery !== "held") {
    throw new LabelError(
      `advisory is not held (delivery: ${advisory.delivery}) — only held findings await approval`,
    );
  }
  await applyPatch(ref, { delivery: "staged" });
}

/** Reject: label + never re-fires (signature suppression is CLI-side) +
 * retraction if the agent already saw it. */
export async function rejectAdvisory(ref: AdvisoryRef): Promise<void> {
  const { advisory } = await loadOwned(ref);
  const delivered =
    advisory.delivery === "injected" || advisory.delivery === "sent";
  await applyPatch(
    ref,
    delivered
      ? { label: "rejected", retraction: "staged" }
      : { label: "rejected" },
  );
}

/** Confirm: repeat confirmations graduate toward a deterministic check. */
export async function confirmAdvisory(ref: AdvisoryRef): Promise<void> {
  await loadOwned(ref); // ownership check
  await applyPatch(ref, { label: "confirmed" });
}
