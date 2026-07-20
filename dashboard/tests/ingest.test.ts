import { and, eq } from "drizzle-orm";
import { beforeEach, describe, expect, it } from "vitest";

import { POST as ingestPost } from "@/app/api/v1/ingest/route";
import { db } from "@/db";
import { advisories, proofFiles, records, repos } from "@/db/schema";

import {
  ingestRequest,
  makeToken,
  makeUser,
  sampleAdvisory,
  sampleRecord,
  truncateAll,
} from "./helpers";

process.env.BLOB_DRIVER = "local";

function payload(overrides: Record<string, unknown> = {}) {
  return {
    repo_id: "demo-app",
    record: sampleRecord(),
    proof_files: {
      "checks.json": "[]",
      "context.json": "{}",
      "diff.patch": "--- a/x\n+++ b/x\n",
    },
    ...overrides,
  };
}

describe("POST /api/v1/ingest", () => {
  let token: string;
  let userId: string;

  beforeEach(async () => {
    await truncateAll();
    userId = await makeUser();
    token = await makeToken(userId);
  });

  it("401s without / with bad / with revoked token", async () => {
    expect((await ingestPost(ingestRequest(null, payload()))).status).toBe(401);
    expect(
      (await ingestPost(ingestRequest("pjt_bogus", payload()))).status,
    ).toBe(401);
    const { deviceTokens } = await import("@/db/schema");
    await db.update(deviceTokens).set({ revokedAt: new Date() });
    expect((await ingestPost(ingestRequest(token, payload()))).status).toBe(401);
  });

  it("creates repo, record, proof files with correct extraction", async () => {
    const response = await ingestPost(ingestRequest(token, payload()));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok", record_id: "chk_001" });

    const [repo] = await db.select().from(repos);
    expect(repo.repoSlug).toBe("demo-app");
    expect(repo.userId).toBe(userId);

    const [record] = await db.select().from(records);
    expect(record.recordId).toBe("chk_001");
    expect(record.gatePassed).toBe(false);
    expect(record.action).toBe("deploy");
    // failure_classes: FAILED checks only — the passing `tests` check's
    // null class must not appear.
    expect(record.failureClasses).toEqual(["missing_env_var"]);
    expect(record.diagnosis).toContain("STRIPE_API_KEY");

    const files = await db.select().from(proofFiles);
    expect(files.map((f) => f.name).sort()).toEqual([
      "checks.json",
      "context.json",
      "diff.patch",
    ]);
    expect(files.every((f) => f.blobKey.startsWith(`${userId}/demo-app/chk_001/`))).toBe(
      true,
    );
  });

  it("exact replay is unchanged and adds no rows", async () => {
    await ingestPost(ingestRequest(token, payload()));
    const replay = await ingestPost(ingestRequest(token, payload()));
    expect(await replay.json()).toEqual({
      status: "unchanged",
      record_id: "chk_001",
    });
    expect(await db.$count(records)).toBe(1);
    expect(await db.$count(repos)).toBe(1);
  });

  it("modified replay updates extraction and JSONB", async () => {
    await ingestPost(ingestRequest(token, payload()));
    const relabeled = sampleRecord({
      resolution: { status: "false_positive", at: "2026-07-18T13:00:00Z" },
    });
    const response = await ingestPost(
      ingestRequest(token, payload({ record: relabeled })),
    );
    expect((await response.json()).status).toBe("ok");
    const [record] = await db.select().from(records);
    expect(record.resolutionStatus).toBe("false_positive");
    expect(
      (record.data as { resolution: { status: string } }).resolution.status,
    ).toBe("false_positive");
    expect(await db.$count(records)).toBe(1);
  });

  it("extracts advisories rows with signatures, replacing on re-ingest", async () => {
    const withAdvisory = sampleRecord({
      advisories: [sampleAdvisory()],
    });
    await ingestPost(ingestRequest(token, payload({ record: withAdvisory })));
    let rows = await db.select().from(advisories);
    expect(rows).toHaveLength(1);
    expect(rows[0].idx).toBe(0);
    expect(rows[0].delivery).toBe("injected");
    expect(rows[0].signature).toBe(
      "payments.py|call error external handling",
    );

    const relabeled = sampleRecord({
      advisories: [sampleAdvisory({ label: "confirmed" })],
    });
    await ingestPost(ingestRequest(token, payload({ record: relabeled })));
    rows = await db.select().from(advisories);
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("confirmed");
  });

  it("accepts unknown extra record keys (additive schema)", async () => {
    const future = sampleRecord({ some_future_field: { nested: true } });
    const response = await ingestPost(
      ingestRequest(token, payload({ record: future })),
    );
    expect(response.status).toBe(200);
    const [record] = await db.select().from(records);
    expect(
      (record.data as Record<string, unknown>).some_future_field,
    ).toEqual({ nested: true });
  });

  it("rejects malformed records with 400 and detail", async () => {
    const bad = sampleRecord({ gate_passed: "yes" });
    const response = await ingestPost(
      ingestRequest(token, payload({ record: bad })),
    );
    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.error).toBe("invalid_record");
    expect(body.detail).toContain("gate_passed");
  });

  it("ignores proof files with unexpected names", async () => {
    const response = await ingestPost(
      ingestRequest(
        token,
        payload({
          proof_files: { "checks.json": "[]", "../../evil.sh": "rm -rf" },
        }),
      ),
    );
    expect(response.status).toBe(200);
    const files = await db.select().from(proofFiles);
    expect(files.map((f) => f.name)).toEqual(["checks.json"]);
  });

  it("scopes repos per user — same slug, different users, no merge", async () => {
    await ingestPost(ingestRequest(token, payload()));
    const otherUser = await makeUser("other");
    const otherToken = await makeToken(otherUser);
    await ingestPost(ingestRequest(otherToken, payload()));
    const repoRows = await db.select().from(repos);
    expect(repoRows).toHaveLength(2);
    expect(
      await db.$count(
        records,
        and(eq(records.recordId, "chk_001")),
      ),
    ).toBe(2);
  });
});
