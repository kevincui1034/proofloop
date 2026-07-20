import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { ClassChip, VerdictBadge, timeAgo } from "@/components/badges";
import {
  TRACES_PAGE_SIZE,
  getRepo,
  listTraces,
  traceFacets,
  type TraceFilters,
} from "@/lib/queries/traces";

function FilterLink({
  repoId,
  params,
  patch,
  label,
  active,
}: {
  repoId: string;
  params: Record<string, string | undefined>;
  patch: Record<string, string | undefined>;
  label: string;
  active: boolean;
}) {
  // Filter changes reset pagination; a patch that sets `before` (the
  // "older →" link) wins over the reset.
  const next = { ...params, before: undefined, ...patch };
  const query = Object.entries(next)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(v!)}`)
    .join("&");
  return (
    <Link
      href={`/repos/${repoId}/traces${query ? `?${query}` : ""}`}
      className={
        active
          ? "rounded border border-amber/60 px-2 py-0.5 text-xs text-amber-ink"
          : "rounded border border-line px-2 py-0.5 text-xs text-faint hover:text-body"
      }
    >
      {label}
    </Link>
  );
}

export default async function TracesPage({
  params,
  searchParams,
}: {
  params: Promise<{ repoId: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const session = await auth();
  const { repoId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const sp = await searchParams;
  const filters: TraceFilters = {
    verdict: sp.verdict as TraceFilters["verdict"],
    action: sp.action,
    failureClass: sp.class,
    agent: sp.agent,
    q: sp.q,
    before: sp.before,
  };
  const [rows, facets] = await Promise.all([
    listTraces(repo.id, filters),
    traceFacets(repo.id),
  ]);
  const tail = rows[rows.length - 1];
  const nextCursor =
    rows.length === TRACES_PAGE_SIZE && tail
      ? `${tail.createdAt.toISOString()}|${tail.pk}`
      : null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLink repoId={repoId} params={sp} patch={{ verdict: undefined }} label="all" active={!sp.verdict} />
        <FilterLink repoId={repoId} params={sp} patch={{ verdict: "blocked" }} label="blocked" active={sp.verdict === "blocked"} />
        <FilterLink repoId={repoId} params={sp} patch={{ verdict: "passed" }} label="allowed" active={sp.verdict === "passed"} />
        <span className="mx-2 text-line-2">·</span>
        {facets.actions.map((action) => (
          <FilterLink
            key={action}
            repoId={repoId}
            params={sp}
            patch={{ action: sp.action === action ? undefined : action }}
            label={action}
            active={sp.action === action}
          />
        ))}
        {facets.failureClasses.length > 0 && (
          <span className="mx-2 text-line-2">·</span>
        )}
        {facets.failureClasses.map((cls) => (
          <FilterLink
            key={cls}
            repoId={repoId}
            params={sp}
            patch={{ class: sp.class === cls ? undefined : cls }}
            label={cls}
            active={sp.class === cls}
          />
        ))}
        <form className="ml-auto" action={`/repos/${repoId}/traces`}>
          <input
            name="q"
            defaultValue={sp.q ?? ""}
            placeholder="search diagnosis…"
            className="rounded-md border border-line bg-surface-3 px-3 py-1 text-sm text-ink placeholder:text-faint"
          />
        </form>
      </div>

      {rows.length === 0 ? (
        <p className="mt-8 text-faint">No traces match.</p>
      ) : (
        <ul className="mt-4 divide-y divide-line rounded-lg border border-line bg-surface-2">
          {rows.map((row) => (
            <li key={row.pk}>
              <Link
                href={`/repos/${repoId}/traces/${row.recordId}`}
                className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-surface-3/50"
              >
                <VerdictBadge passed={row.gatePassed} />
                <span className="font-mono text-sm text-ink">{row.recordId}</span>
                <span className="text-xs text-faint">{row.action}</span>
                <span className="text-xs text-faint">{row.agentSource}</span>
                <span className="flex flex-wrap gap-1">
                  {row.failureClasses.map((cls) => (
                    <ClassChip key={cls} name={cls} />
                  ))}
                </span>
                {row.recalledFrom && (
                  <span className="text-xs text-amber-ink" title={`recalled from ${row.recalledFrom}`}>
                    ↩ recall
                  </span>
                )}
                {row.advisoryCount > 0 && (
                  <span className="text-xs text-faint">
                    {row.advisoryCount} advisor{row.advisoryCount === 1 ? "y" : "ies"}
                  </span>
                )}
                <span className="ml-auto text-xs text-faint">
                  {timeAgo(row.createdAt)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {nextCursor && (
        <div className="mt-4 text-center">
          <FilterLink
            repoId={repoId}
            params={sp}
            patch={{ before: nextCursor }}
            label="older →"
            active={false}
          />
        </div>
      )}
    </div>
  );
}
