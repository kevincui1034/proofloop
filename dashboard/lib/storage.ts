/**
 * Proof-file storage. Proof files are scrubbed but still private code
 * context: the browser reads them ONLY through the authed proxy route
 * (app/api/proof/...), never a direct storage URL.
 *
 * Drivers: LocalDirStorage under dashboard/.data/blob/ (dev + tests);
 * R2Storage (Cloudflare R2, S3-compatible) in production. R2 buckets are
 * private by default — put() returns url:null and the proxy streams via
 * get(), so no object is ever publicly reachable.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export interface ProofStorage {
  /** Store `body` at `key`; returns a fetchable URL only if the driver
   *  exposes one (R2/local do not — they're read back through get()). */
  put(key: string, body: string): Promise<{ url: string | null }>;
  /** Read back by key; null when missing. */
  get(key: string): Promise<string | null>;
}

/** Reject path traversal — keys are {userId}/{repoSlug}/{recordId}/{name}. */
function safeKey(key: string): string {
  const normalized = path.posix.normalize(key);
  if (normalized.startsWith("..") || path.posix.isAbsolute(normalized)) {
    throw new Error(`unsafe storage key: ${key}`);
  }
  return normalized;
}

export class LocalDirStorage implements ProofStorage {
  constructor(
    private baseDir: string = path.join(process.cwd(), ".data", "blob"),
  ) {}

  async put(key: string, body: string): Promise<{ url: string | null }> {
    const rel = safeKey(key);
    const file = path.join(this.baseDir, rel);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, body, "utf8");
    return { url: null };
  }

  async get(key: string): Promise<string | null> {
    try {
      return await readFile(path.join(this.baseDir, safeKey(key)), "utf8");
    } catch {
      return null;
    }
  }
}

/**
 * Cloudflare R2 via the S3 API. The SDK is dynamic-imported so the local
 * driver (dev/tests) never loads it. `forcePathStyle` defaults on so the
 * same adapter works against R2 and against MinIO in tests.
 */
export class R2Storage implements ProofStorage {
  private clientPromise?: Promise<
    import("@aws-sdk/client-s3").S3Client
  >;

  constructor(private bucket: string = process.env.R2_BUCKET ?? "") {
    if (!this.bucket) throw new Error("R2_BUCKET is not set");
  }

  private client() {
    if (!this.clientPromise) {
      this.clientPromise = import("@aws-sdk/client-s3").then(
        ({ S3Client }) =>
          new S3Client({
            region: process.env.R2_REGION ?? "auto",
            endpoint: process.env.R2_ENDPOINT,
            forcePathStyle: process.env.R2_FORCE_PATH_STYLE !== "false",
            credentials: {
              accessKeyId: process.env.R2_ACCESS_KEY_ID ?? "",
              secretAccessKey: process.env.R2_SECRET_ACCESS_KEY ?? "",
            },
          }),
      );
    }
    return this.clientPromise;
  }

  async put(key: string, body: string): Promise<{ url: string | null }> {
    const { PutObjectCommand } = await import("@aws-sdk/client-s3");
    const client = await this.client();
    await client.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: safeKey(key),
        Body: body,
        ContentType: "text/plain; charset=utf-8",
      }),
    );
    // Private bucket by design — served only via the authed proxy.
    return { url: null };
  }

  async get(key: string): Promise<string | null> {
    const { GetObjectCommand } = await import("@aws-sdk/client-s3");
    const client = await this.client();
    try {
      const result = await client.send(
        new GetObjectCommand({ Bucket: this.bucket, Key: safeKey(key) }),
      );
      const body = result.Body as
        | { transformToString?: () => Promise<string> }
        | undefined;
      return body?.transformToString ? await body.transformToString() : null;
    } catch {
      // Missing object or read failure → treated as not found (the proxy
      // route then returns 404). Never leak the storage error to callers.
      return null;
    }
  }
}

export function getStorage(): ProofStorage {
  if (process.env.BLOB_DRIVER === "local") return new LocalDirStorage();
  // R2 in production (endpoint + bucket configured); local otherwise.
  if (process.env.R2_ENDPOINT && process.env.R2_BUCKET) {
    return new R2Storage();
  }
  return new LocalDirStorage();
}
