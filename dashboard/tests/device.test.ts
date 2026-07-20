import { eq } from "drizzle-orm";
import { beforeEach, describe, expect, it } from "vitest";

import { POST as codePost } from "@/app/api/v1/device/code/route";
import { POST as tokenPost } from "@/app/api/v1/device/token/route";
import { POST as ingestPost } from "@/app/api/v1/ingest/route";
import { db } from "@/db";
import { deviceCodes } from "@/db/schema";
import { resolveUserCode } from "@/lib/device";

import {
  ingestRequest,
  jsonRequest,
  makeUser,
  sampleRecord,
  truncateAll,
} from "./helpers";

async function mint(): Promise<{ deviceCode: string; userCode: string }> {
  const response = await codePost(
    jsonRequest("http://test.local/api/v1/device/code", {
      hostname: "test-host",
      cli_version: "0.1.0",
    }),
  );
  const body = await response.json();
  return { deviceCode: body.device_code, userCode: body.user_code };
}

function poll(deviceCode: string): Promise<Response> {
  return tokenPost(
    jsonRequest("http://test.local/api/v1/device/token", {
      device_code: deviceCode,
    }),
  );
}

/** Clear the interval throttle so sequential polls in tests aren't 429ed. */
async function resetPollThrottle(): Promise<void> {
  await db.update(deviceCodes).set({ lastPolledAt: null });
}

describe("device-code flow", () => {
  beforeEach(async () => {
    await truncateAll();
  });

  it("mints a well-formed code pair", async () => {
    const response = await codePost(
      jsonRequest("http://test.local/api/v1/device/code", {}),
    );
    const body = await response.json();
    expect(body.device_code).toMatch(/^[0-9a-f]{64}$/);
    expect(body.user_code).toMatch(/^[BCDFGHJKLMNPQRSTVWXZ2-9]{4}-[BCDFGHJKLMNPQRSTVWXZ2-9]{4}$/);
    expect(body.verification_uri).toContain("/device");
    expect(body.interval).toBe(5);
  });

  it("pending until approved, then delivers the token exactly once", async () => {
    const { deviceCode, userCode } = await mint();
    expect((await poll(deviceCode)).status).toBe(202);

    const userId = await makeUser();
    const approval = await resolveUserCode(userCode, userId, "approved");
    expect(approval).toEqual({ ok: true, hostname: "test-host" });

    await resetPollThrottle();
    const success = await poll(deviceCode);
    expect(success.status).toBe(200);
    const body = await success.json();
    expect(body.token).toMatch(/^pjt_/);
    expect(body.user_login).toBe("dev");

    // The token works for ingest.
    const ingest = await ingestPost(
      ingestRequest(body.token, { repo_id: "demo", record: sampleRecord() }),
    );
    expect(ingest.status).toBe(200);

    // Second exchange of a consumed code → invalid, no second token.
    await resetPollThrottle();
    const replay = await poll(deviceCode);
    expect(replay.status).toBe(400);
    expect((await replay.json()).error).toBe("invalid");
  });

  it("denied and expired codes report their state", async () => {
    const denied = await mint();
    const userId = await makeUser("denier");
    await resolveUserCode(denied.userCode, userId, "denied");
    await resetPollThrottle();
    expect((await (await poll(denied.deviceCode)).json()).error).toBe("denied");

    const expired = await mint();
    await db
      .update(deviceCodes)
      .set({ expiresAt: new Date(Date.now() - 1000) })
      .where(eq(deviceCodes.status, "pending"));
    await resetPollThrottle();
    expect((await (await poll(expired.deviceCode)).json()).error).toBe("expired");
    // An expired code can no longer be approved.
    const late = await resolveUserCode(expired.userCode, userId, "approved");
    expect(late.ok).toBe(false);
  });

  it("enforces the poll interval with 429 slow_down", async () => {
    const { deviceCode } = await mint();
    expect((await poll(deviceCode)).status).toBe(202);
    expect((await poll(deviceCode)).status).toBe(429); // immediate re-poll
  });

  it("rejects malformed device codes", async () => {
    expect((await poll("not-hex")).status).toBe(400);
    expect(
      (await poll("a".repeat(64))).status, // valid shape, unknown code
    ).toBe(400);
  });
});
