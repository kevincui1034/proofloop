/**
 * Ingest: one JSON request per gate record — the record verbatim plus its
 * proof files inlined as text. Idempotent on (repo, record_id); a replay
 * with identical content is a no-op ("unchanged"), a replay with changed
 * content (relabeled locally) updates extracted columns + JSONB. This is
 * how CLI-side labels flow up.
 *
 * The CLI record schema is additive and pinned CLI-side — validation
 * requires the core keys and PASSES THROUGH unknown keys untouched.
 */
import { and, eq } from "drizzle-orm";
import { z } from "zod";

import { db } from "@/db";
import { advisories, proofFiles, records, repos } from "@/db/schema";
import { advisorySignature } from "@/lib/signature";
import type { ProofStorage } from "@/lib/storage";

const checkEntry = z
  .object({
    name: z.string(),
    type: z.string(),
    passed: z.boolean(),
    failure_class: z.string().nullable(),
    evidence: z.string(),
  })
  .passthrough();

const advisoryEntry = z
  .object({
    id: z.string(),
    concern: z.string(),
    kind: z.string().nullable().optional(),
    tier: z.number().nullable().optional(),
    confidence: z.number().nullable().optional(),
    grounded_in: z.array(z.string()).optional(),
    target: z.string().nullable().optional(),
    judge_model_id: z.string().nullable().optional(),
    delivery: z.string(),
    label: z.string().nullable().optional(),
    retraction: z.string().nullable().optional(),
  })
  .passthrough();

export const recordSchema = z
  .object({
    id: z.string().min(1),
    repo_id: z.string().min(1),
    created_at: z.string().min(1),
    action_intercepted: z.string().min(1),
    agent_source: z.string(),
    checks: z.array(checkEntry),
    gate_passed: z.boolean(),
    diagnosis: z.string(),
    proof_refs: z.array(z.string()),
    recalled_from: z.string().nullable(),
    resolution: z.record(z.unknown()).nullable(),
    resolves: z.string().nullable().optional(),
    advisories: z.array(advisoryEntry).optional().default([]),
    gate_duration_ms: z.number().optional().default(0),
    inputs_hash: z.string().optional().default(""),
    judge_model_id: z.string().optional().default(""),
    cli_version: z.string().optional().default(""),
    schema_version: z.string().optional().default(""),
    task_ref: z.string().nullable().optional(),
  })
  .passthrough();

export const ingestSchema = z.object({
  repo_id: z.string().min(1),
  record: recordSchema,
  proof_files: z.record(z.string()).optional().default({}),
  truncated_files: z.array(z.string()).optional().default([]),
});

export type IngestPayload = z.infer<typeof ingestSchema>;

/** Stable serialization for change detection across JSONB round-trips. */
export function stableStringify(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((k) => [k, sortKeys((value as Record<string, unknown>)[k])]),
    );
  }
  return value;
}

const PROOF_FILE_NAMES = new Set([
  "checks.json",
  "context.json",
  "diff.patch",
  "impact.json",
]);

export type IngestResult =
  | { status: "ok" | "unchanged"; recordId: string }
  | { status: "invalid"; detail: string };

export async function ingestRecord(
  userId: string,
  payload: unknown,
  storage: ProofStorage,
): Promise<IngestResult> {
  const parsed = ingestSchema.safeParse(payload);
  if (!parsed.success) {
    return {
      status: "invalid",
      detail: parsed.error.issues
        .slice(0, 5)
        .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
        .join("; "),
    };
  }
  const { repo_id: repoSlug, record, proof_files, truncated_files } = parsed.data;

  // Upsert the repo under this user.
  await db
    .insert(repos)
    .values({ userId, repoSlug })
    .onConflictDoNothing({ target: [repos.userId, repos.repoSlug] });
  const [repo] = await db
    .select({ id: repos.id })
    .from(repos)
    .where(and(eq(repos.userId, userId), eq(repos.repoSlug, repoSlug)))
    .limit(1);

  // Unchanged replay → no-op (idempotency).
  const [existing] = await db
    .select({ pk: records.pk, data: records.data })
    .from(records)
    .where(and(eq(records.repoPk, repo.id), eq(records.recordId, record.id)))
    .limit(1);
  if (existing && stableStringify(existing.data) === stableStringify(record)) {
    return { status: "unchanged", recordId: record.id };
  }

  const createdAt = new Date(record.created_at);
  if (Number.isNaN(createdAt.getTime())) {
    return { status: "invalid", detail: "created_at: not a parseable timestamp" };
  }

  // Extracted columns.
  const failureClasses = Array.from(
    new Set(
      record.checks
        .filter((c) => !c.passed && c.failure_class)
        .map((c) => c.failure_class as string),
    ),
  );
  const resolution = (record.resolution ?? {}) as Record<string, unknown>;

  // Blob-put proof files before the tx (storage is not transactional).
  const storedFiles: {
    name: string;
    blobKey: string;
    blobUrl: string | null;
    sizeBytes: number;
    truncated: boolean;
  }[] = [];
  for (const [name, content] of Object.entries(proof_files)) {
    if (!PROOF_FILE_NAMES.has(name)) continue; // never store arbitrary names
    const blobKey = `${userId}/${repoSlug}/${record.id}/${name}`;
    const { url } = await storage.put(blobKey, content);
    storedFiles.push({
      name,
      blobKey,
      blobUrl: url,
      sizeBytes: Buffer.byteLength(content, "utf8"),
      truncated: truncated_files.includes(name),
    });
  }

  await db.transaction(async (tx) => {
    const extracted = {
      createdAt,
      action: record.action_intercepted,
      agentSource: record.agent_source,
      gatePassed: record.gate_passed,
      failureClasses,
      diagnosis: record.diagnosis,
      recalledFrom: record.recalled_from,
      resolves: record.resolves ?? null,
      resolutionStatus: (resolution.status as string) ?? null,
      resolutionOutcome: (resolution.outcome as string) ?? null,
      inputsHash: record.inputs_hash,
      gateDurationMs: Math.round(record.gate_duration_ms),
      judgeModelId: record.judge_model_id,
      cliVersion: record.cli_version,
      schemaVersion: record.schema_version,
      data: record,
      updatedAt: new Date(),
    };
    const [row] = await tx
      .insert(records)
      .values({ repoPk: repo.id, recordId: record.id, ...extracted })
      .onConflictDoUpdate({
        target: [records.repoPk, records.recordId],
        set: extracted,
      })
      .returning({ pk: records.pk });

    // Advisories: delete + reinsert (labels/delivery may have changed).
    await tx.delete(advisories).where(eq(advisories.recordPk, row.pk));
    if (record.advisories.length > 0) {
      await tx.insert(advisories).values(
        record.advisories.map((entry, idx) => ({
          recordPk: row.pk,
          repoPk: repo.id,
          recordId: record.id,
          idx,
          concern: entry.concern,
          kind: entry.kind ?? null,
          tier: entry.tier ?? null,
          confidence: entry.confidence ?? null,
          target: entry.target ?? null,
          judgeModelId: entry.judge_model_id ?? null,
          delivery: entry.delivery,
          label: entry.label ?? null,
          retraction: entry.retraction ?? null,
          signature: advisorySignature(entry.concern, entry.target ?? null),
          createdAt,
        })),
      );
    }

    for (const file of storedFiles) {
      await tx
        .insert(proofFiles)
        .values({ recordPk: row.pk, ...file })
        .onConflictDoUpdate({
          target: [proofFiles.recordPk, proofFiles.name],
          set: {
            blobKey: file.blobKey,
            blobUrl: file.blobUrl,
            sizeBytes: file.sizeBytes,
            truncated: file.truncated,
          },
        });
    }
  });

  return { status: "ok", recordId: record.id };
}
