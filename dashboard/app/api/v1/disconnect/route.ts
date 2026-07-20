import { eq } from "drizzle-orm";

import { db } from "@/db";
import { deviceTokens } from "@/db/schema";
import { authenticateBearer } from "@/lib/tokens";

/** Revoke the calling token itself. Best-effort from the CLI's side. */
export async function POST(request: Request) {
  const device = await authenticateBearer(request);
  if (!device) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  await db
    .update(deviceTokens)
    .set({ revokedAt: new Date() })
    .where(eq(deviceTokens.id, device.tokenId));
  return Response.json({ status: "revoked" });
}
