import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { ClassChip, EvidenceText, VerdictBadge } from "@/components/badges";
import { AdvisoryActions } from "@/components/AdvisoryActions";
import { AdvisoryCard } from "@/components/AdvisoryCard";
import { DiffView } from "@/components/DiffView";
import { ImpactGraph } from "@/components/ImpactGraph";
import { getRepo, getTrace } from "@/lib/queries/traces";
import { getProofFile } from "@/lib/proofs";

interface CheckEntry {
  name: string;
  type: string;
  passed: boolean;
  failure_class: string | null;
  evidence: string;
}

interface RecordData {
  checks: CheckEntry[];
  diagnosis: string;
  judge_input?: string;
  judge_output?: string;
  advisory_input?: string;
  advisory_output?: string;
  task_ref?: string | null;
  resolution?: { status?: string; note?: string } | null;
  cli_version?: string;
  gate_duration_ms?: number;
  env_fingerprint?: string[];
}

function Transcript({ title, text }: { title: string; text: string }) {
  if (!text) return null;
  return (
    <details className="rounded-md border border-line bg-surface-3">
      <summary className="cursor-pointer px-4 py-2 text-sm text-faint hover:text-body">
        {title}
      </summary>
      <pre className="overflow-x-auto whitespace-pre-wrap px-4 pb-4 font-mono text-xs text-body">
        {text}
      </pre>
    </details>
  );
}

export default async function TracePage({
  params,
}: {
  params: Promise<{ repoId: string; recordId: string }>;
}) {
  const session = await auth();
  const { repoId, recordId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const trace = await getTrace(repo.id, recordId);
  if (!trace) notFound();
  const data = trace.record.data as unknown as RecordData;
  const [diffText, impactText] = await Promise.all([
    getProofFile(trace.record.pk, "diff.patch"),
    getProofFile(trace.record.pk, "impact.json"),
  ]);

  return (
    <div className="flex flex-col gap-6">
      {/* header */}
      <div className="flex flex-wrap items-center gap-3">
        <VerdictBadge passed={trace.record.gatePassed} />
        <h2 className="font-mono text-xl text-ink">{trace.record.recordId}</h2>
        <span className="text-sm text-faint">{trace.record.action}</span>
        <span className="text-sm text-faint">{trace.record.agentSource}</span>
        <span className="text-sm text-faint">
          {trace.record.createdAt.toLocaleString()}
        </span>
        {typeof data.gate_duration_ms === "number" && (
          <span className="text-sm text-faint">{data.gate_duration_ms}ms</span>
        )}
      </div>

      {/* recall + resolution linkage */}
      <div className="flex flex-wrap gap-3 text-sm">
        {trace.record.recalledFrom && (
          <RecallChip repoId={repoId} cited={trace.record.recalledFrom} />
        )}
        {trace.record.resolves && (
          <span className="rounded border border-line px-2 py-1 text-body">
            resolves{" "}
            <Link
              href={`/repos/${repoId}/traces/${trace.record.resolves}`}
              className="font-mono text-amber-ink hover:underline"
            >
              {trace.record.resolves}
            </Link>
          </span>
        )}
        {trace.resolvedBy && (
          <span className="rounded border border-verdict-green/40 px-2 py-1 text-verdict-green">
            resolved by{" "}
            <Link
              href={`/repos/${repoId}/traces/${trace.resolvedBy.recordId}`}
              className="font-mono hover:underline"
            >
              {trace.resolvedBy.recordId}
            </Link>
          </span>
        )}
        {trace.record.resolutionStatus && (
          <span className="rounded border border-line px-2 py-1 text-faint">
            resolution: {trace.record.resolutionStatus}
          </span>
        )}
        {data.task_ref && (
          <span className="rounded border border-line px-2 py-1 text-faint">
            task: {data.task_ref}
          </span>
        )}
      </div>

      {/* checks */}
      <section className="rounded-lg border border-line bg-surface-2">
        <h3 className="border-b border-line px-4 py-2 text-sm font-medium text-ink">
          Checks
        </h3>
        <table className="w-full text-sm">
          <tbody>
            {data.checks.map((check) => (
              <tr key={check.name} className="border-b border-line/50 last:border-0">
                <td className="px-4 py-2 font-mono text-body">{check.name}</td>
                <td className="px-4 py-2">
                  {check.passed ? (
                    <span className="text-verdict-green">passed</span>
                  ) : (
                    <span className="text-verdict-red">FAILED</span>
                  )}
                </td>
                <td className="px-4 py-2">
                  {check.failure_class && <ClassChip name={check.failure_class} />}
                </td>
                <td className="px-4 py-2 text-body">
                  <EvidenceText text={check.evidence} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* judge */}
      <section className="rounded-lg border border-line bg-surface-2 p-4">
        <h3 className="text-sm font-medium text-ink">Judge</h3>
        <p className="mt-2 text-body">
          <EvidenceText text={data.diagnosis} />
        </p>
        <p className="mt-2 text-xs text-faint">
          {trace.record.judgeModelId}
        </p>
        <div className="mt-3 flex flex-col gap-2">
          <Transcript title="judge input" text={data.judge_input ?? ""} />
          <Transcript title="judge output" text={data.judge_output ?? ""} />
          <Transcript title="advisory input" text={data.advisory_input ?? ""} />
          <Transcript title="advisory output" text={data.advisory_output ?? ""} />
        </div>
      </section>

      {/* blast radius */}
      {impactText && (
        <section className="rounded-lg border border-line bg-surface-2 p-4">
          <h3 className="text-sm font-medium text-ink">Blast radius</h3>
          <p className="mt-1 text-xs text-faint">
            Deterministic reverse-import graph — changed files and what
            depends on them.
          </p>
          <ImpactGraph impactJson={impactText} />
        </section>
      )}

      {/* advisories */}
      {trace.advisories.length > 0 && (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-ink">
            Advisory findings{" "}
            <span className="font-normal text-faint">
              (model judgment — never part of the verdict)
            </span>
          </h3>
          {trace.advisories.map((advisory) => (
            <AdvisoryCard
              key={advisory.pk}
              advisory={advisory}
              actions={
                <AdvisoryActions
                  advisoryPk={advisory.pk}
                  delivery={advisory.delivery}
                  label={advisory.label}
                  path={`/repos/${repoId}/traces/${recordId}`}
                />
              }
            />
          ))}
        </section>
      )}

      {/* diff */}
      {diffText && (
        <section className="rounded-lg border border-line bg-surface-2 p-4">
          <h3 className="text-sm font-medium text-ink">Diff (scrubbed)</h3>
          <DiffView patch={diffText} />
        </section>
      )}
    </div>
  );
}

function RecallChip({ repoId, cited }: { repoId: string; cited: string }) {
  // Cross-repo citations look like "repo:chk_NNN"; local ones are bare ids.
  const crossRepo = cited.includes(":");
  if (crossRepo) {
    return (
      <span
        className="rounded border border-amber/40 px-2 py-1 text-amber-ink"
        title="Recalled from another of your repos"
      >
        ↩ recalled from <span className="font-mono">{cited}</span> (cross-repo)
      </span>
    );
  }
  return (
    <span className="rounded border border-amber/40 px-2 py-1 text-amber-ink">
      ↩ recalled from{" "}
      <Link
        href={`/repos/${repoId}/traces/${cited}`}
        className="font-mono hover:underline"
      >
        {cited}
      </Link>
    </span>
  );
}
