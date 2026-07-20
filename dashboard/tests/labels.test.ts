import { beforeEach, describe, expect, it } from "vitest";

import { GET as labelsGet } from "@/app/api/v1/repos/[repoSlug]/labels/route";
import { POST as ingestPost } from "@/app/api/v1/ingest/route";
import { db } from "@/db";
import { advisories, labelEvents, records } from "@/db/schema";
import {
  approveAdvisory,
  confirmAdvisory,
  LabelError,
  rejectAdvisory,
} from "@/lib/labels";

import {
  ingestRequest,
  makeToken,
  makeUser,
  sampleAdvisory,
  sampleRecord,
  truncateAll,
} from "./helpers";

process.env.BLOB_DRIVER = "local";

async function seedAdvisory(
  token: string,
  advisoryOverrides: Record<string, unknown>,
) {
  const record = sampleRecord({
    advisories: [sampleAdvisory(advisoryOverrides)],
  });
  const response = await ingestPost(
    ingestRequest(token, { repo_id: "demo-app", record }),
  );
  expect(response.status).toBe(200);
  const [row] = await db.select().from(advisories);
  return row;
}

function pullLabels(token: string, cursor = 0) {
  return labelsGet(
    new Request(
      `http://test.local/api/v1/repos/demo-app/labels?cursor=${cursor}`,
      { headers: { authorization: `Bearer ${token}` } },
    ),
    { params: Promise.resolve({ repoSlug: "demo-app" }) },
  );
}

describe("E1 label actions", () => {
  let userId: string;
  let token: string;

  beforeEach(async () => {
    await truncateAll();
    userId = await makeUser();
    token = await makeToken(userId);
  });

  it("approve requires held", async () => {
    const injected = await seedAdvisory(token, { delivery: "injected" });
    await expect(
      approveAdvisory({ advisoryPk: injected.pk, userId }),
    ).rejects.toThrow(LabelError);
    expect(await db.$count(labelEvents)).toBe(0);
  });

  it("approve stages a held finding and emits one event", async () => {
    const held = await seedAdvisory(token, { delivery: "held" });
    await approveAdvisory({ advisoryPk: held.pk, userId });
    const [row] = await db.select().from(advisories);
    expect(row.delivery).toBe("staged");
    const [record] = await db.select().from(records);
    const data = record.data as { advisories: { delivery: string }[] };
    expect(data.advisories[0].delivery).toBe("staged"); // JSONB converged
    const events = await db.select().from(labelEvents);
    expect(events).toHaveLength(1);
    expect(events[0].payload).toEqual({ delivery: "staged" });
    expect(events[0].kind).toBe("advisory_label");
  });

  it("reject after injection stages a retraction; held reject does not", async () => {
    const injected = await seedAdvisory(token, { delivery: "injected" });
    await rejectAdvisory({ advisoryPk: injected.pk, userId });
    let [row] = await db.select().from(advisories);
    expect(row.label).toBe("rejected");
    expect(row.retraction).toBe("staged");
    let events = await db.select().from(labelEvents);
    expect(events[0].payload).toEqual({
      label: "rejected",
      retraction: "staged",
    });

    await truncateAll();
    userId = await makeUser();
    token = await makeToken(userId);
    const held = await seedAdvisory(token, { delivery: "held" });
    await rejectAdvisory({ advisoryPk: held.pk, userId });
    [row] = await db.select().from(advisories);
    expect(row.label).toBe("rejected");
    expect(row.retraction).toBeNull();
    events = await db.select().from(labelEvents);
    expect(events[0].payload).toEqual({ label: "rejected" });
  });

  it("confirm labels and emits", async () => {
    const injected = await seedAdvisory(token, { delivery: "injected" });
    await confirmAdvisory({ advisoryPk: injected.pk, userId });
    const [row] = await db.select().from(advisories);
    expect(row.label).toBe("confirmed");
    const events = await db.select().from(labelEvents);
    expect(events[0].payload).toEqual({ label: "confirmed" });
  });

  it("another user's advisory is invisible", async () => {
    const held = await seedAdvisory(token, { delivery: "held" });
    const stranger = await makeUser("stranger");
    await expect(
      approveAdvisory({ advisoryPk: held.pk, userId: stranger }),
    ).rejects.toThrow("not found");
  });

  it("GET labels pages by cursor, ascending, only newer events", async () => {
    const held = await seedAdvisory(token, { delivery: "held" });
    await approveAdvisory({ advisoryPk: held.pk, userId });
    await confirmAdvisory({ advisoryPk: held.pk, userId });

    let response = await pullLabels(token, 0);
    let body = await response.json();
    expect(body.events).toHaveLength(2);
    expect(body.events[0].seq).toBeLessThan(body.events[1].seq);
    expect(body.events[0].payload).toEqual({ delivery: "staged" });
    expect(body.events[0].index).toBe(0);
    const cursor = body.cursor;

    response = await pullLabels(token, cursor);
    body = await response.json();
    expect(body.events).toHaveLength(0);
    expect(body.cursor).toBe(cursor);
  });

  it("re-ingest of a CLI-relabeled record replaces advisory rows (up-sync)", async () => {
    const held = await seedAdvisory(token, { delivery: "held" });
    await approveAdvisory({ advisoryPk: held.pk, userId });
    // CLI applied the event, gate delivered it, drain re-pushes with sent:
    const record = sampleRecord({
      advisories: [sampleAdvisory({ delivery: "sent" })],
    });
    const response = await ingestPost(
      ingestRequest(token, { repo_id: "demo-app", record }),
    );
    expect((await response.json()).status).toBe("ok");
    const [row] = await db.select().from(advisories);
    expect(row.delivery).toBe("sent");
  });
});
