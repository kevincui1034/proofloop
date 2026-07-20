/**
 * Shared test utilities: seeded users/tokens, a realistic CLI record
 * fixture (mirrors cli/src/proofjury/memory/schema.py FIELD_ORDER), and
 * table truncation between test files.
 */
import { sql } from "drizzle-orm";

import { db } from "@/db";
import { deviceTokens, users } from "@/db/schema";
import { mintToken } from "@/lib/tokens";

export async function truncateAll(): Promise<void> {
  await db.execute(sql`
    TRUNCATE TABLE label_events, proof_files, advisories, records, repos,
      device_tokens, device_codes, sessions, accounts, users
    RESTART IDENTITY CASCADE
  `);
}

export async function makeUser(login = "dev"): Promise<string> {
  const [row] = await db
    .insert(users)
    .values({ name: login, email: `${login}@test.local`, githubLogin: login })
    .returning({ id: users.id });
  return row.id;
}

export async function makeToken(userId: string): Promise<string> {
  const { token, tokenHash } = mintToken();
  await db.insert(deviceTokens).values({ userId, tokenHash, name: "test" });
  return token;
}

/** A realistic gate record, shaped like MemoryRecord.to_dict(). */
export function sampleRecord(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: "chk_001",
    repo_id: "demo-app",
    created_at: "2026-07-18T12:00:00Z",
    action_intercepted: "deploy",
    agent_source: "claude-code",
    context_ref: ".proofjury/runs/chk_001/",
    checks: [
      {
        name: "env_vars",
        type: "deterministic",
        passed: false,
        failure_class: "missing_env_var",
        evidence: "STRIPE_API_KEY (payments.py:14) unset",
      },
      {
        name: "tests",
        type: "deterministic",
        passed: true,
        failure_class: null,
        evidence: "",
      },
    ],
    gate_passed: false,
    diagnosis: "STRIPE_API_KEY is read at payments.py:14 but unset",
    judge_input: "judge input text",
    judge_output: '{"diagnosis": "d", "fix_steps": []}',
    proof_refs: ["checks.json", "context.json", "diff.patch"],
    recalled_from: null,
    judge_model_id: "deterministic/proofjury-v1",
    resolution: null,
    schema_version: "1",
    cli_version: "0.1.0",
    gate_duration_ms: 120,
    inputs_hash: "abc123",
    env_fingerprint: ["HOME", "PATH"],
    resolves: null,
    advisories: [],
    advisory_input: "",
    advisory_output: "",
    task_ref: null,
    ...overrides,
  };
}

export function sampleAdvisory(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: "chk_001#0",
    concern: "External call has no error handling",
    kind: "discovery",
    tier: 4,
    confidence: 0.9,
    grounded_in: [],
    target: "payments.py:14",
    judge_model_id: "mock/judge",
    delivery: "injected",
    label: null,
    retraction: null,
    ...overrides,
  };
}

export function ingestRequest(
  token: string | null,
  body: unknown,
): Request {
  return new Request("http://test.local/api/v1/ingest", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
}

export function jsonRequest(url: string, body: unknown): Request {
  return new Request(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
