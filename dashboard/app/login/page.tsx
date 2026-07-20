import { redirect } from "next/navigation";

import { auth, devLoginEnabled, signIn } from "@/auth";

export default async function LoginPage() {
  const session = await auth();
  if (session?.user) redirect("/repos");
  const githubEnabled = Boolean(process.env.AUTH_GITHUB_ID);

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-sm rounded-lg border border-line bg-surface-2 p-8">
        <h1 className="font-serif text-3xl text-ink">Proofjury</h1>
        <p className="mt-2 text-sm text-body">
          Every gate run as a trace — the verdict, the evidence, and what the
          judge told your coding agent.
        </p>
        <div className="mt-8 flex flex-col gap-3">
          {githubEnabled && (
            <form
              action={async () => {
                "use server";
                await signIn("github", { redirectTo: "/repos" });
              }}
            >
              <button
                type="submit"
                className="w-full rounded-md bg-amber px-4 py-2 font-medium text-surface-3 hover:bg-amber-deep"
              >
                Sign in with GitHub
              </button>
            </form>
          )}
          {devLoginEnabled && (
            <form
              action={async () => {
                "use server";
                await signIn("dev", { redirectTo: "/repos" });
              }}
            >
              <button
                type="submit"
                className="w-full rounded-md border border-line-2 px-4 py-2 text-body hover:border-amber hover:text-ink"
              >
                Dev login (local only)
              </button>
            </form>
          )}
          {!githubEnabled && !devLoginEnabled && (
            <p className="text-sm text-faint">
              No sign-in method configured — set AUTH_GITHUB_ID/SECRET (or
              AUTH_DEV_LOGIN=1 locally).
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
