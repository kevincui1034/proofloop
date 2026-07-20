import Link from "next/link";

import { auth } from "@/auth";
import { listRepos } from "@/lib/queries/traces";

function PassRate({ rate }: { rate: number | null }) {
  if (rate === null) return <span className="text-faint">—</span>;
  const pct = Math.round(rate * 100);
  return (
    <span className={pct >= 50 ? "text-verdict-green" : "text-verdict-red"}>
      {pct}% pass
    </span>
  );
}

export default async function ReposPage() {
  const session = await auth();
  const repos = await listRepos(session!.user.id);

  return (
    <div>
      <h1 className="font-serif text-3xl text-ink">Connected repos</h1>
      {repos.length === 0 ? (
        <div className="mt-8 rounded-lg border border-line bg-surface-2 p-8">
          <p className="text-body">
            No repos yet. On a machine with Proofjury installed:
          </p>
          <pre className="mt-4 rounded-md bg-surface-3 p-4 font-mono text-sm text-amber-ink">
            {"$ proofjury connect\n$ proofjury sync"}
          </pre>
          <p className="mt-4 text-sm text-faint">
            After that, every gate run syncs automatically — sync never
            blocks, slows, or fails the gate.
          </p>
        </div>
      ) : (
        <ul className="mt-8 grid gap-4 sm:grid-cols-2">
          {repos.map((repo) => (
            <li key={repo.id}>
              <Link
                href={`/repos/${repo.id}`}
                className="block rounded-lg border border-line bg-surface-2 p-6 hover:border-amber"
              >
                <div className="flex items-baseline justify-between">
                  <span className="font-mono text-lg text-ink">
                    {repo.displayName ?? repo.repoSlug}
                  </span>
                  <PassRate rate={repo.passRate === null ? null : Number(repo.passRate)} />
                </div>
                <div className="mt-2 flex gap-4 text-sm text-faint">
                  <span>{repo.recordCount} gate runs</span>
                  {repo.lastActivity && (
                    <span>
                      last {new Date(repo.lastActivity).toLocaleString()}
                    </span>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
