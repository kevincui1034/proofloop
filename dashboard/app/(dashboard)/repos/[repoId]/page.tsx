import { notFound } from "next/navigation";

import { auth } from "@/auth";
import {
  FailureClassChart,
  PassRateChart,
} from "@/components/OverviewCharts";
import {
  failureClassCounts,
  overviewStats,
  passRateByDay,
} from "@/lib/queries/overview";
import { getRepo } from "@/lib/queries/traces";

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  const toneClass =
    tone === "good"
      ? "text-verdict-green"
      : tone === "bad"
        ? "text-verdict-red"
        : "text-ink";
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-4">
      <div className={`text-2xl font-medium ${toneClass}`}>{value}</div>
      <div className="mt-1 text-xs text-faint">{label}</div>
    </div>
  );
}

export default async function OverviewPage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const session = await auth();
  const { repoId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const [stats, byDay, byClass] = await Promise.all([
    overviewStats(repo.id),
    passRateByDay(repo.id),
    failureClassCounts(repo.id),
  ]);

  if (stats.total === 0) {
    return (
      <p className="text-faint">
        No gate runs synced yet — run a guarded command, or `proofjury sync`.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="gate runs" value={String(stats.total)} />
        <StatTile label="blocked" value={String(stats.blocked)} tone="bad" />
        <StatTile label="allowed" value={String(stats.passed)} tone="good" />
        <StatTile
          label="recall hit rate (of blocks)"
          value={
            stats.recallHitRate === null
              ? "—"
              : `${Math.round(stats.recallHitRate * 100)}%`
          }
        />
        <StatTile
          label="auto-resolved blocks"
          value={
            stats.autoResolveRate === null
              ? "—"
              : `${Math.round(stats.autoResolveRate * 100)}%`
          }
        />
        <StatTile
          label="p95 gate time"
          value={stats.p95DurationMs === null ? "—" : `${stats.p95DurationMs}ms`}
        />
      </div>

      <section className="rounded-lg border border-line bg-surface-2 p-4">
        <h3 className="text-sm font-medium text-ink">Gate runs over time</h3>
        <div className="mt-3">
          <PassRateChart data={byDay} />
        </div>
      </section>

      {byClass.length > 0 && (
        <section className="rounded-lg border border-line bg-surface-2 p-4">
          <h3 className="text-sm font-medium text-ink">Catches by failure class</h3>
          <div className="mt-3">
            <FailureClassChart data={byClass} />
          </div>
        </section>
      )}
    </div>
  );
}
