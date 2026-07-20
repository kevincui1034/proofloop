import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { EvidenceText } from "@/components/badges";
import {
  advisoryBreakdown,
  classReliability,
  mostCitedPriors,
  recallStats,
} from "@/lib/queries/memory";
import { getRepo } from "@/lib/queries/traces";

export default async function MemoryPage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const session = await auth();
  const { repoId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const [cited, stats, reliability, advisory] = await Promise.all([
    mostCitedPriors(repo.id),
    recallStats(repo.id),
    classReliability(repo.id),
    advisoryBreakdown(repo.id),
  ]);
  const hitRate =
    stats.blocked > 0 ? Math.round((stats.recalled / stats.blocked) * 100) : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-line bg-surface-2 p-4">
          <div className="text-2xl font-medium text-ink">
            {hitRate === null ? "—" : `${hitRate}%`}
          </div>
          <div className="mt-1 text-xs text-faint">
            of blocks recalled a prior
          </div>
        </div>
        <div className="rounded-lg border border-line bg-surface-2 p-4">
          <div className="text-2xl font-medium text-ink">{stats.recalled}</div>
          <div className="mt-1 text-xs text-faint">recall hits</div>
        </div>
        <div className="rounded-lg border border-line bg-surface-2 p-4">
          <div className="text-2xl font-medium text-amber-ink">
            {stats.crossRepoHits}
          </div>
          <div className="mt-1 text-xs text-faint">
            cross-repo recalls (priors from your other repos)
          </div>
        </div>
      </div>

      <section className="rounded-lg border border-line bg-surface-2">
        <h3 className="border-b border-line px-4 py-2 text-sm font-medium text-ink">
          Most-cited priors
        </h3>
        {cited.length === 0 ? (
          <p className="px-4 py-3 text-sm text-faint">
            No recalls yet — they appear when a failure repeats.
          </p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {cited.map((prior) => (
                <tr
                  key={prior.citedId}
                  className="border-b border-line/50 last:border-0"
                >
                  <td className="px-4 py-2 font-mono">
                    {prior.crossRepo ? (
                      <span className="text-amber-ink">{prior.citedId}</span>
                    ) : (
                      <Link
                        href={`/repos/${repoId}/traces/${prior.citedId}`}
                        className="text-body hover:text-amber-ink"
                      >
                        {prior.citedId}
                      </Link>
                    )}
                  </td>
                  <td className="px-4 py-2 text-faint">
                    cited {prior.hits}×{prior.crossRepo && " · cross-repo"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="rounded-lg border border-line bg-surface-2">
        <h3 className="border-b border-line px-4 py-2 text-sm font-medium text-ink">
          Class reliability{" "}
          <span className="font-normal text-faint">
            — noisy classes demote in recall, never exclude
          </span>
        </h3>
        {reliability.length === 0 ? (
          <p className="px-4 py-3 text-sm text-faint">
            No labeled blocks yet — resolve blocks as accepted/false_positive
            to build this signal.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-faint">
                <th className="px-4 py-2 font-normal">class</th>
                <th className="px-4 py-2 font-normal">accepted</th>
                <th className="px-4 py-2 font-normal">false positive</th>
                <th className="px-4 py-2 font-normal">status</th>
              </tr>
            </thead>
            <tbody>
              {reliability.map((row) => (
                <tr
                  key={row.failureClass}
                  className="border-b border-line/50 last:border-0"
                >
                  <td className="px-4 py-2 font-mono text-body">
                    {row.failureClass}
                  </td>
                  <td className="px-4 py-2 text-verdict-green">{row.accepted}</td>
                  <td className="px-4 py-2 text-verdict-red">
                    {row.falsePositive}
                  </td>
                  <td className="px-4 py-2">
                    {row.noisy ? (
                      <span className="text-verdict-red">noisy — demoted</span>
                    ) : (
                      <span className="text-faint">reliable</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="grid gap-6 sm:grid-cols-2">
        <section className="rounded-lg border border-line bg-surface-2 p-4">
          <h3 className="text-sm font-medium text-ink">Advisory delivery</h3>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {advisory.byDelivery.length === 0 && (
              <li className="text-faint">none yet</li>
            )}
            {advisory.byDelivery.map((row) => (
              <li key={row.delivery} className="flex justify-between">
                <span className="text-body">{row.delivery}</span>
                <span className="text-faint">{row.count}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-lg border border-line bg-surface-2 p-4">
          <h3 className="text-sm font-medium text-ink">Advisory labels</h3>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {advisory.byLabel.length === 0 && (
              <li className="text-faint">none yet</li>
            )}
            {advisory.byLabel.map((row) => (
              <li key={row.label} className="flex justify-between">
                <span className="text-body">{row.label}</span>
                <span className="text-faint">{row.count}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {advisory.rejectedSignatures.length > 0 && (
        <section className="rounded-lg border border-line bg-surface-2">
          <h3 className="border-b border-line px-4 py-2 text-sm font-medium text-ink">
            Rejected — will not re-fire
          </h3>
          <ul className="divide-y divide-line/50">
            {advisory.rejectedSignatures.map((row) => (
              <li key={row.signature} className="px-4 py-2 text-sm text-body">
                <EvidenceText text={row.concern} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
