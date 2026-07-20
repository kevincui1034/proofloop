import { and, eq } from "drizzle-orm";

import { auth } from "@/auth";
import { db } from "@/db";
import { records, repos } from "@/db/schema";
import { getProofFile } from "@/lib/proofs";

/**
 * Authed proxy for proof files — the ONLY way a browser reads them.
 * Session + ownership checked; blob URLs never reach the client.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ recordPk: string; name: string }> },
) {
  const session = await auth();
  if (!session?.user?.id) {
    return new Response("unauthorized", { status: 401 });
  }
  const { recordPk, name } = await params;
  const [owned] = await db
    .select({ pk: records.pk })
    .from(records)
    .innerJoin(repos, eq(repos.id, records.repoPk))
    .where(and(eq(records.pk, recordPk), eq(repos.userId, session.user.id)))
    .limit(1);
  if (!owned) return new Response("not found", { status: 404 });
  const content = await getProofFile(recordPk, name);
  if (content === null) return new Response("not found", { status: 404 });
  return new Response(content, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "private, max-age=3600",
    },
  });
}
