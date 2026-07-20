/**
 * Device tokens: minted once (plaintext `pjt_<base64url>` shown to the CLI
 * a single time), stored only as sha256. Bearer auth for /api/v1/*.
 */
import { createHash, randomBytes } from "node:crypto";

import { and, eq, isNull } from "drizzle-orm";

import { db } from "@/db";
import { deviceTokens, users } from "@/db/schema";

export function mintToken(): { token: string; tokenHash: string } {
  const token = `pjt_${randomBytes(32).toString("base64url")}`;
  return { token, tokenHash: hashToken(token) };
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export interface AuthedDevice {
  userId: string;
  tokenId: string;
  userLogin: string | null;
}

/** Resolve a Bearer token to its user, touching last_used_at. Null on any failure. */
export async function authenticateBearer(
  request: Request,
): Promise<AuthedDevice | null> {
  const header = request.headers.get("authorization") ?? "";
  const match = /^Bearer\s+(pjt_[A-Za-z0-9_-]+)$/.exec(header);
  if (!match) return null;
  const tokenHash = hashToken(match[1]);
  const rows = await db
    .select({
      tokenId: deviceTokens.id,
      userId: deviceTokens.userId,
      userLogin: users.githubLogin,
    })
    .from(deviceTokens)
    .innerJoin(users, eq(users.id, deviceTokens.userId))
    .where(
      and(eq(deviceTokens.tokenHash, tokenHash), isNull(deviceTokens.revokedAt)),
    )
    .limit(1);
  if (rows.length === 0) return null;
  // Best-effort freshness marker; never fail auth over it.
  db.update(deviceTokens)
    .set({ lastUsedAt: new Date() })
    .where(eq(deviceTokens.id, rows[0].tokenId))
    .catch(() => {});
  return rows[0];
}
