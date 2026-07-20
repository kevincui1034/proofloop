import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { EvidenceText } from "@/components/badges";
import {
  GRADUATION_MIN_CONFIRMED,
  graduationBoard,
  type Candidate,
} from "@/lib/queries/graduation";
import { getRepo } from "@/lib/queries/traces";

function CandidateCard({
  candidate,
  repoId,
  graduated,
}: {
  candidate: Candidate;
  repoId: string;
  graduated: boolean;
}) {
  const snippet = `# ${candidate.concern}\n# candidate from ${candidate.confirmed} confirmed advisory finding(s)\n[advisory]\n# review: consider a deterministic check for this pattern${candidate.target ? `\n# seen at: ${candidate.target}` : ""}`;
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={
            graduated
              ? "rounded border border-verdict-green/40 px-2 py-0.5 text-xs font-medium text-verdict-green"
              : "rounded border border-line-2 px-2 py-0.5 text-xs text-faint"
          }
        >
          {candidate.confirmed}× confirmed
        </span>
        {candidate.kind && (
          <span className="text-xs text-faint">{candidate.kind}</span>
        )}
        {candidate.target && (
          <span className="font-mono text-xs text-amber-ink">
            {candidate.target}
          </span>
        )}
      </div>
      <p className="mt-2 text-body">
        <EvidenceText text={candidate.concern} />
      </p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {candidate.refs.map((ref) => (
          <Link
            key={ref}
            href={`/repos/${repoId}/traces/${ref.split("#")[0]}`}
            className="font-mono text-faint hover:text-amber-ink"
          >
            {ref}
          </Link>
        ))}
      </div>
      {graduated && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-faint hover:text-body">
            .proofjury.toml starting point
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-surface-3 p-3 font-mono text-xs text-body">
            {snippet}
          </pre>
        </details>
      )}
    </div>
  );
}

export default async function GraduationPage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const session = await auth();
  const { repoId } = await params;
  const repo = await getRepo(session!.user.id, repoId);
  if (!repo) notFound();
  const { candidates, warming } = await graduationBoard(repo.id);

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-faint">
        An advisory finding confirmed {GRADUATION_MIN_CONFIRMED}+ times with
        the same signature is a candidate to become a deterministic check —
        judgment graduating into rules.
      </p>
      <section>
        <h3 className="text-sm font-medium text-ink">
          Candidates ({candidates.length})
        </h3>
        {candidates.length === 0 ? (
          <p className="mt-2 text-sm text-faint">
            None yet — confirm recurring findings (here or with{" "}
            <span className="font-mono">proofjury advisory confirm</span>) to
            move them along.
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {candidates.map((candidate) => (
              <CandidateCard
                key={candidate.signature}
                candidate={candidate}
                repoId={repoId}
                graduated
              />
            ))}
          </div>
        )}
      </section>
      {warming.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-ink">
            Warming up ({warming.length})
          </h3>
          <div className="mt-3 flex flex-col gap-3">
            {warming.map((candidate) => (
              <CandidateCard
                key={candidate.signature}
                candidate={candidate}
                repoId={repoId}
                graduated={false}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
