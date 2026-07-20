import { beforeEach, describe, expect, it } from "vitest";

import { POST as ingestPost } from "@/app/api/v1/ingest/route";
import { db } from "@/db";
import { repos } from "@/db/schema";
import {
  GRADUATION_MIN_CONFIRMED,
  graduationBoard,
} from "@/lib/queries/graduation";
import { classReliability, recallStats } from "@/lib/queries/memory";
import { listTraces } from "@/lib/queries/traces";

import {
  ingestRequest,
  makeToken,
  makeUser,
  sampleAdvisory,
  sampleRecord,
  truncateAll,
} from "./helpers";

process.env.BLOB_DRIVER = "local";

describe("E2/E3 queries", () => {
  let token: string;
  let repoPk: string;

  beforeEach(async () => {
    await truncateAll();
    const userId = await makeUser();
    token = await makeToken(userId);
  });

  async function ingest(record: Record<string, unknown>) {
    const response = await ingestPost(
      ingestRequest(token, { repo_id: "demo-app", record }),
    );
    expect(response.status).toBe(200);
    const [repo] = await db.select({ id: repos.id }).from(repos);
    repoPk = repo.id;
  }

  it("graduation requires >= GRADUATION_MIN_CONFIRMED same-signature confirms", async () => {
    // Same concern+target → same signature, across three records; a
    // fourth confirmed advisory has a different signature (warming).
    for (let i = 1; i <= 3; i++) {
      await ingest(
        sampleRecord({
          id: `chk_00${i}`,
          advisories: [
            sampleAdvisory({
              id: `chk_00${i}#0`,
              label: "confirmed",
              concern: "External call has no error handling",
              target: `payments.py:${10 + i}`, // line shifts — same file part
            }),
          ],
        }),
      );
    }
    await ingest(
      sampleRecord({
        id: "chk_004",
        advisories: [
          sampleAdvisory({
            id: "chk_004#0",
            label: "confirmed",
            concern: "Different concern entirely here",
            target: "orders.py:5",
          }),
        ],
      }),
    );
    const board = await graduationBoard(repoPk);
    expect(GRADUATION_MIN_CONFIRMED).toBe(3);
    expect(board.candidates).toHaveLength(1);
    expect(board.candidates[0].confirmed).toBe(3);
    expect(board.candidates[0].refs).toEqual([
      "chk_001#0",
      "chk_002#0",
      "chk_003#0",
    ]);
    expect(board.warming).toHaveLength(1);
    // unlabeled/rejected findings never count
    await ingest(
      sampleRecord({
        id: "chk_005",
        advisories: [
          sampleAdvisory({
            id: "chk_005#0",
            label: "rejected",
            concern: "Different concern entirely here",
            target: "orders.py:5",
          }),
        ],
      }),
    );
    const after = await graduationBoard(repoPk);
    expect(after.warming[0].confirmed).toBe(1); // still 1 — reject didn't add
  });

  it("class reliability implements the noisy rule exactly", async () => {
    // missing_env_var: 2 false positives vs 1 accepted → noisy.
    // tests_not_run: 1 fp, 2 accepted → reliable.
    const mk = (id: string, cls: string, status: string) =>
      sampleRecord({
        id,
        checks: [
          {
            name: "x",
            type: "deterministic",
            passed: false,
            failure_class: cls,
            evidence: "e",
          },
        ],
        resolution: { status, at: "2026-07-18T00:00:00Z" },
      });
    await ingest(mk("chk_001", "missing_env_var", "false_positive"));
    await ingest(mk("chk_002", "missing_env_var", "false_positive"));
    await ingest(mk("chk_003", "missing_env_var", "accepted"));
    await ingest(mk("chk_004", "tests_not_run", "false_positive"));
    await ingest(mk("chk_005", "tests_not_run", "accepted"));
    await ingest(mk("chk_006", "tests_not_run", "accepted"));
    const rows = await classReliability(repoPk);
    const byClass = Object.fromEntries(rows.map((r) => [r.failureClass, r]));
    expect(byClass.missing_env_var.noisy).toBe(true);
    expect(byClass.tests_not_run.noisy).toBe(false);
  });

  it("recall stats count cross-repo hits by the colon marker", async () => {
    await ingest(sampleRecord({ id: "chk_001" }));
    await ingest(sampleRecord({ id: "chk_002", recalled_from: "chk_001" }));
    await ingest(sampleRecord({ id: "chk_003", recalled_from: "app:chk_009" }));
    const stats = await recallStats(repoPk);
    expect(stats.recalled).toBe(2);
    expect(stats.crossRepoHits).toBe(1);
  });

  it("trace filters compose (verdict + class + search)", async () => {
    await ingest(sampleRecord({ id: "chk_001" })); // blocked, missing_env_var
    await ingest(
      sampleRecord({
        id: "chk_002",
        gate_passed: true,
        checks: [],
        diagnosis: "all clear",
      }),
    );
    const blocked = await listTraces(repoPk, { verdict: "blocked" });
    expect(blocked.map((r) => r.recordId)).toEqual(["chk_001"]);
    const byClass = await listTraces(repoPk, {
      failureClass: "missing_env_var",
    });
    expect(byClass).toHaveLength(1);
    const search = await listTraces(repoPk, { q: "STRIPE" });
    expect(search.map((r) => r.recordId)).toEqual(["chk_001"]);
    const none = await listTraces(repoPk, {
      verdict: "passed",
      failureClass: "missing_env_var",
    });
    expect(none).toHaveLength(0);
  });
});
