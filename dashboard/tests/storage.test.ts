import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LocalDirStorage, R2Storage, getStorage } from "@/lib/storage";

describe("getStorage selection", () => {
  const saved = { ...process.env };
  afterEach(() => {
    process.env = { ...saved };
  });

  it("uses local when BLOB_DRIVER=local", () => {
    process.env.BLOB_DRIVER = "local";
    process.env.R2_ENDPOINT = "https://acct.r2.cloudflarestorage.com";
    process.env.R2_BUCKET = "proofs";
    expect(getStorage()).toBeInstanceOf(LocalDirStorage);
  });

  it("uses R2 when endpoint+bucket set and driver not local", () => {
    delete process.env.BLOB_DRIVER;
    process.env.R2_ENDPOINT = "https://acct.r2.cloudflarestorage.com";
    process.env.R2_BUCKET = "proofs";
    expect(getStorage()).toBeInstanceOf(R2Storage);
  });

  it("falls back to local when R2 is not configured", () => {
    delete process.env.BLOB_DRIVER;
    delete process.env.R2_ENDPOINT;
    delete process.env.R2_BUCKET;
    expect(getStorage()).toBeInstanceOf(LocalDirStorage);
  });
});

describe("LocalDirStorage", () => {
  it("round-trips and rejects traversal keys", async () => {
    const dir = `/tmp/proofjury-storage-test-${process.pid}`;
    const storage = new LocalDirStorage(dir);
    await storage.put("u1/repo/chk_001/checks.json", "[1,2,3]");
    expect(await storage.get("u1/repo/chk_001/checks.json")).toBe("[1,2,3]");
    expect(await storage.get("u1/repo/missing/x.json")).toBeNull();
    await expect(storage.put("../escape", "x")).rejects.toThrow("unsafe");
  });
});

/**
 * Real S3-API round-trip — runs only when R2/MinIO creds are present
 * (kept out of the default suite so CI stays hermetic). Self-provisions
 * its bucket, so it works against a fresh MinIO or a real R2 account:
 *
 *   R2_ENDPOINT=http://localhost:9000 R2_BUCKET=proofs \
 *   R2_ACCESS_KEY_ID=minioadmin R2_SECRET_ACCESS_KEY=minioadmin \
 *   npx vitest run tests/storage.test.ts
 */
describe.skipIf(!process.env.R2_ENDPOINT)("R2Storage (S3 API)", () => {
  beforeEach(async () => {
    const { S3Client, CreateBucketCommand } = await import(
      "@aws-sdk/client-s3"
    );
    const client = new S3Client({
      region: "auto",
      endpoint: process.env.R2_ENDPOINT,
      forcePathStyle: true,
      credentials: {
        accessKeyId: process.env.R2_ACCESS_KEY_ID ?? "",
        secretAccessKey: process.env.R2_SECRET_ACCESS_KEY ?? "",
      },
    });
    try {
      await client.send(
        new CreateBucketCommand({ Bucket: process.env.R2_BUCKET }),
      );
    } catch {
      // already exists — fine
    }
  });

  it("round-trips a proof file", async () => {
    const storage = new R2Storage();
    const key = `u1/repo/chk_${Date.now()}/impact.json`;
    const result = await storage.put(key, '{"depth":2}');
    expect(result.url).toBeNull(); // private bucket
    expect(await storage.get(key)).toBe('{"depth":2}');
    expect(await storage.get("u1/repo/nope/x.json")).toBeNull();
  });
});
