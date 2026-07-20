/**
 * Server-side proof-file reads. Blob URLs never reach the client — pages
 * read content here (server components) or via the authed proxy route.
 */
import { and, eq } from "drizzle-orm";

import { db } from "@/db";
import { proofFiles } from "@/db/schema";
import { getStorage } from "@/lib/storage";

export async function getProofFile(
  recordPk: string,
  name: string,
): Promise<string | null> {
  const [row] = await db
    .select()
    .from(proofFiles)
    .where(and(eq(proofFiles.recordPk, recordPk), eq(proofFiles.name, name)))
    .limit(1);
  if (!row) return null;
  if (row.blobUrl) {
    try {
      const response = await fetch(row.blobUrl);
      if (!response.ok) return null;
      return await response.text();
    } catch {
      return null;
    }
  }
  return getStorage().get(row.blobKey);
}
