import { ingestRecord } from "@/lib/ingest";
import { getStorage } from "@/lib/storage";
import { authenticateBearer } from "@/lib/tokens";

/** Vercel's function body limit is ~4.5 MB; reject earlier with a clear 413. */
const MAX_BODY_BYTES = 4_000_000;

export async function POST(request: Request) {
  const device = await authenticateBearer(request);
  if (!device) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (contentLength > MAX_BODY_BYTES) {
    return Response.json({ error: "payload_too_large" }, { status: 413 });
  }
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json(
      { error: "invalid_record", detail: "body is not JSON" },
      { status: 400 },
    );
  }
  const result = await ingestRecord(device.userId, payload, getStorage());
  if (result.status === "invalid") {
    return Response.json(
      { error: "invalid_record", detail: result.detail },
      { status: 400 },
    );
  }
  return Response.json({ status: result.status, record_id: result.recordId });
}
