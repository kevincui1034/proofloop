import { pollDeviceCode } from "@/lib/device";

export async function POST(request: Request) {
  let deviceCode: unknown;
  try {
    ({ device_code: deviceCode } = await request.json());
  } catch {
    return Response.json({ error: "invalid" }, { status: 400 });
  }
  if (typeof deviceCode !== "string" || !/^[0-9a-f]{64}$/.test(deviceCode)) {
    return Response.json({ error: "invalid" }, { status: 400 });
  }
  const result = await pollDeviceCode(deviceCode);
  switch (result.status) {
    case "pending":
      return Response.json({ status: "pending" }, { status: 202 });
    case "slow_down":
      return Response.json({ error: "slow_down" }, { status: 429 });
    case "ok":
      return Response.json({
        token: result.token,
        token_id: result.tokenId,
        user_login: result.userLogin,
      });
    default:
      return Response.json({ error: result.status }, { status: 400 });
  }
}
