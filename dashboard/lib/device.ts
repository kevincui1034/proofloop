/**
 * Device-code flow: the CLI mints a (device_code, user_code) pair, the
 * user approves the user_code in the browser while logged in, the CLI's
 * poll exchanges the device_code for a bearer token — exactly once.
 * Everything secret is stored hashed.
 */
import { createHash, randomBytes, randomInt } from "node:crypto";

import { and, eq, gt, sql } from "drizzle-orm";

import { db } from "@/db";
import { deviceCodes, deviceTokens, users } from "@/db/schema";
import { mintToken } from "@/lib/tokens";

export const DEVICE_CODE_TTL_SECONDS = 900;
export const POLL_INTERVAL_SECONDS = 5;
/** Ambiguity-free: no vowels (no accidental words), no 0/O/1/I. */
const USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ23456789";

function generateUserCode(): string {
  const chars = Array.from(
    { length: 8 },
    () => USER_CODE_ALPHABET[randomInt(USER_CODE_ALPHABET.length)],
  );
  return `${chars.slice(0, 4).join("")}-${chars.slice(4).join("")}`;
}

function hashDeviceCode(deviceCode: string): string {
  return createHash("sha256").update(deviceCode, "utf8").digest("hex");
}

export async function createDeviceCode(meta: {
  hostname?: string;
  cliVersion?: string;
}): Promise<{ deviceCode: string; userCode: string; expiresIn: number; interval: number }> {
  const deviceCode = randomBytes(32).toString("hex");
  // Retry on the (astronomically rare) active user_code collision.
  for (let attempt = 0; attempt < 3; attempt++) {
    const userCode = generateUserCode();
    try {
      await db.insert(deviceCodes).values({
        deviceCodeHash: hashDeviceCode(deviceCode),
        userCode,
        hostname: meta.hostname ?? null,
        cliVersion: meta.cliVersion ?? null,
        expiresAt: new Date(Date.now() + DEVICE_CODE_TTL_SECONDS * 1000),
      });
      return {
        deviceCode,
        userCode,
        expiresIn: DEVICE_CODE_TTL_SECONDS,
        interval: POLL_INTERVAL_SECONDS,
      };
    } catch (error) {
      if (attempt === 2) throw error;
    }
  }
  throw new Error("unreachable");
}

export type PollResult =
  | { status: "pending" }
  | { status: "slow_down" }
  | { status: "ok"; token: string; tokenId: string; userLogin: string | null }
  | { status: "expired" | "denied" | "invalid" };

export async function pollDeviceCode(deviceCode: string): Promise<PollResult> {
  const [row] = await db
    .select()
    .from(deviceCodes)
    .where(eq(deviceCodes.deviceCodeHash, hashDeviceCode(deviceCode)))
    .limit(1);
  if (!row) return { status: "invalid" };
  if (row.status === "consumed" || row.status === "denied") {
    return row.status === "denied" ? { status: "denied" } : { status: "invalid" };
  }
  if (row.expiresAt.getTime() < Date.now()) {
    await db
      .update(deviceCodes)
      .set({ status: "expired" })
      .where(eq(deviceCodes.id, row.id));
    return { status: "expired" };
  }
  // Enforce the poll interval (grace of 1s for clock skew).
  if (
    row.lastPolledAt &&
    Date.now() - row.lastPolledAt.getTime() < (POLL_INTERVAL_SECONDS - 1) * 1000
  ) {
    return { status: "slow_down" };
  }
  await db
    .update(deviceCodes)
    .set({ lastPolledAt: new Date() })
    .where(eq(deviceCodes.id, row.id));

  if (row.status === "pending") return { status: "pending" };

  // approved → mint the token exactly once: the consume is guarded by a
  // conditional UPDATE so a concurrent double-poll can't double-mint.
  const consumed = await db
    .update(deviceCodes)
    .set({ status: "consumed" })
    .where(and(eq(deviceCodes.id, row.id), eq(deviceCodes.status, "approved")))
    .returning({ userId: deviceCodes.userId });
  if (consumed.length === 0 || !consumed[0].userId) return { status: "invalid" };

  const { token, tokenHash } = mintToken();
  const [tokenRow] = await db
    .insert(deviceTokens)
    .values({
      userId: consumed[0].userId,
      tokenHash,
      name: row.hostname,
    })
    .returning({ id: deviceTokens.id });
  const [user] = await db
    .select({ githubLogin: users.githubLogin, name: users.name })
    .from(users)
    .where(eq(users.id, consumed[0].userId))
    .limit(1);
  return {
    status: "ok",
    token,
    tokenId: tokenRow.id,
    userLogin: user?.githubLogin ?? user?.name ?? null,
  };
}

/** Approve or deny a pending user_code on behalf of the logged-in user. */
export async function resolveUserCode(
  userCode: string,
  userId: string,
  decision: "approved" | "denied",
): Promise<{ ok: boolean; hostname?: string | null }> {
  const rows = await db
    .update(deviceCodes)
    .set({ status: decision, userId: decision === "approved" ? userId : null })
    .where(
      and(
        eq(deviceCodes.userCode, userCode.trim().toUpperCase()),
        eq(deviceCodes.status, "pending"),
        gt(deviceCodes.expiresAt, sql`now()`),
      ),
    )
    .returning({ hostname: deviceCodes.hostname });
  if (rows.length === 0) return { ok: false };
  return { ok: true, hostname: rows[0].hostname };
}
