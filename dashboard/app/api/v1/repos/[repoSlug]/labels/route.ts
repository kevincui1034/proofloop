import { and, asc, eq, gt } from "drizzle-orm";

import { db } from "@/db";
import { labelEvents, repos } from "@/db/schema";
import { authenticateBearer } from "@/lib/tokens";

const PAGE_CAP = 200;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ repoSlug: string }> },
) {
  const device = await authenticateBearer(request);
  if (!device) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const { repoSlug } = await params;
  const cursor = Number(new URL(request.url).searchParams.get("cursor") ?? 0);
  if (!Number.isFinite(cursor) || cursor < 0) {
    return Response.json({ error: "bad_cursor" }, { status: 400 });
  }
  const [repo] = await db
    .select({ id: repos.id })
    .from(repos)
    .where(
      and(eq(repos.userId, device.userId), eq(repos.repoSlug, repoSlug)),
    )
    .limit(1);
  if (!repo) {
    // Unknown repo for this user — nothing to pull, cursor unchanged.
    return Response.json({ events: [], cursor });
  }
  const rows = await db
    .select({
      seq: labelEvents.id,
      recordId: labelEvents.recordId,
      kind: labelEvents.kind,
      idx: labelEvents.idx,
      payload: labelEvents.payload,
      createdAt: labelEvents.createdAt,
    })
    .from(labelEvents)
    .where(and(eq(labelEvents.repoPk, repo.id), gt(labelEvents.id, cursor)))
    .orderBy(asc(labelEvents.id))
    .limit(PAGE_CAP);
  return Response.json({
    events: rows.map((row) => ({
      seq: row.seq,
      record_id: row.recordId,
      kind: row.kind,
      index: row.idx,
      payload: row.payload,
      created_at: row.createdAt.toISOString(),
    })),
    cursor: rows.length > 0 ? rows[rows.length - 1].seq : cursor,
  });
}
