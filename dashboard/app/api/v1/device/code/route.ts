import { createDeviceCode } from "@/lib/device";

export async function POST(request: Request) {
  let body: { hostname?: string; cli_version?: string } = {};
  try {
    body = await request.json();
  } catch {
    // empty body is fine — hostname/cli_version are optional metadata
  }
  const { deviceCode, userCode, expiresIn, interval } = await createDeviceCode({
    hostname: typeof body.hostname === "string" ? body.hostname.slice(0, 100) : undefined,
    cliVersion:
      typeof body.cli_version === "string" ? body.cli_version.slice(0, 40) : undefined,
  });
  const appUrl = process.env.APP_URL ?? "http://localhost:3000";
  return Response.json({
    device_code: deviceCode,
    user_code: userCode,
    verification_uri: `${appUrl}/device`,
    expires_in: expiresIn,
    interval,
  });
}
