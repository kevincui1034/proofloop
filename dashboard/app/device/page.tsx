import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { resolveUserCode } from "@/lib/device";

async function decide(formData: FormData) {
  "use server";
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const code = String(formData.get("code") ?? "");
  const decision =
    formData.get("decision") === "deny" ? "denied" : "approved";
  const result = await resolveUserCode(code, session.user.id, decision);
  redirect(
    result.ok
      ? `/device?done=${decision}`
      : "/device?error=unknown-or-expired",
  );
}

export default async function DevicePage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string; done?: string; error?: string }>;
}) {
  const session = await auth();
  if (!session?.user) redirect("/login?from=device");
  const { code, done, error } = await searchParams;

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-md rounded-lg border border-line bg-surface-2 p-8">
        <h1 className="font-serif text-2xl text-ink">Connect a machine</h1>
        {done ? (
          <p className="mt-4 text-verdict-green">
            {done === "approved"
              ? "Approved — the CLI will pick up its token within a few seconds. You can close this tab."
              : "Denied. The CLI has been told no."}
          </p>
        ) : (
          <>
            <p className="mt-2 text-sm text-body">
              A machine running <span className="font-mono">proofjury connect</span>{" "}
              printed a code. Enter it here to let that machine sync gate
              records to your dashboard. Sync never blocks a gate; advice you
              give here reaches your agent on its next gate run.
            </p>
            {error && (
              <p className="mt-3 text-sm text-verdict-red">
                That code isn&apos;t pending — it may have expired. Re-run{" "}
                <span className="font-mono">proofjury connect</span>.
              </p>
            )}
            <form action={decide} className="mt-6 flex flex-col gap-4">
              <input
                name="code"
                defaultValue={code ?? ""}
                placeholder="MKGH-P4TN"
                autoComplete="off"
                className="rounded-md border border-line-2 bg-surface-3 px-4 py-2 font-mono text-lg tracking-widest text-ink placeholder:text-faint"
              />
              <div className="flex gap-3">
                <button
                  type="submit"
                  name="decision"
                  value="approve"
                  className="flex-1 rounded-md bg-amber px-4 py-2 font-medium text-surface-3 hover:bg-amber-deep"
                >
                  Approve
                </button>
                <button
                  type="submit"
                  name="decision"
                  value="deny"
                  className="flex-1 rounded-md border border-line-2 px-4 py-2 text-body hover:border-verdict-red hover:text-verdict-red"
                >
                  Deny
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </main>
  );
}
