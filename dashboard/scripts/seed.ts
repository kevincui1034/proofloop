/**
 * Seed the local dashboard from a real .proofjury store, POSTing every
 * record + proof files through the actual /api/v1/ingest route (the
 * production path — not raw inserts).
 *
 * Usage: npm run seed -- <path-to-.proofjury> [--repo-name NAME] [--base URL]
 * Requires: docker compose Postgres up + `npm run dev` running.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

process.env.DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgres://proofjury:proofjury@localhost:54329/proofjury";

async function main() {
  const args = process.argv.slice(2);
  const storeDir = args.find((a) => !a.startsWith("--"));
  if (!storeDir) {
    console.error(
      "usage: npm run seed -- <path-to-.proofjury> [--repo-name NAME] [--base URL]",
    );
    process.exit(64);
  }
  const flag = (name: string) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : undefined;
  };
  const repoName = flag("--repo-name");
  const base = flag("--base") ?? "http://localhost:3000/api/v1";

  // Dev user + device token straight in the DB (the only non-API step).
  const { db } = await import("../db");
  const { users, deviceTokens } = await import("../db/schema");
  const { mintToken } = await import("../lib/tokens");
  const { eq } = await import("drizzle-orm");

  let [user] = await db
    .select()
    .from(users)
    .where(eq(users.email, "dev@localhost"))
    .limit(1);
  if (!user) {
    [user] = await db
      .insert(users)
      .values({ name: "Dev User", email: "dev@localhost", githubLogin: "dev" })
      .returning();
  }
  const { token, tokenHash } = mintToken();
  await db
    .insert(deviceTokens)
    .values({ userId: user.id, tokenHash, name: "seed-script" });

  const jsonl = readFileSync(path.join(storeDir, "memory.jsonl"), "utf8");
  let ok = 0;
  let unchanged = 0;
  let failed = 0;
  for (const line of jsonl.split("\n")) {
    if (!line.trim()) continue;
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line);
    } catch {
      continue;
    }
    const runDir = path.join(storeDir, "runs", String(record.id));
    const proofFiles: Record<string, string> = {};
    try {
      for (const name of readdirSync(runDir)) {
        proofFiles[name] = readFileSync(path.join(runDir, name), "utf8");
      }
    } catch {
      // no proof dir — record still ingests
    }
    const response = await fetch(`${base}/ingest`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        repo_id: repoName ?? record.repo_id,
        record,
        proof_files: proofFiles,
      }),
    });
    if (!response.ok) {
      failed++;
      console.error(`  ${record.id}: ${response.status}`, await response.text());
      continue;
    }
    const body = (await response.json()) as { status: string };
    if (body.status === "unchanged") unchanged++;
    else ok++;
  }
  console.log(
    `seeded ${ok} record(s) (${unchanged} unchanged, ${failed} failed) as dev@localhost`,
  );
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
