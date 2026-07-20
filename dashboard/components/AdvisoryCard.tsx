import type { advisories } from "@/db/schema";

import { DeliveryBadge, EvidenceText, LabelBadge } from "./badges";

type AdvisoryRow = typeof advisories.$inferSelect;

/** The delivery lifecycle, in order; the current state is highlighted. */
const LIFECYCLE = ["held", "staged", "injected", "sent", "suppressed"] as const;

export function AdvisoryCard({
  advisory,
  actions,
}: {
  advisory: AdvisoryRow;
  actions?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-faint">
          {advisory.recordId}#{advisory.idx}
        </span>
        {advisory.kind && (
          <span className="text-xs text-faint">{advisory.kind}</span>
        )}
        {advisory.tier !== null && (
          <span className="text-xs text-faint">tier {advisory.tier}</span>
        )}
        {advisory.confidence !== null && (
          <span className="text-xs text-faint">
            {Math.round(advisory.confidence * 100)}% confident
          </span>
        )}
        <DeliveryBadge delivery={advisory.delivery} />
        <LabelBadge label={advisory.label} />
        {advisory.retraction && (
          <span className="rounded border border-verdict-red/40 px-1.5 py-0.5 text-xs text-verdict-red">
            retraction {advisory.retraction}
          </span>
        )}
      </div>
      <p className="mt-2 text-body">
        <EvidenceText text={advisory.concern} />
      </p>
      {advisory.target && (
        <p className="mt-1 font-mono text-xs text-amber-ink">{advisory.target}</p>
      )}
      <div className="mt-3 flex items-center gap-1 text-xs text-faint">
        {LIFECYCLE.filter(
          (stage) =>
            stage === advisory.delivery ||
            (advisory.delivery === "sent" && stage !== "suppressed"),
        ).map((stage, i, arr) => (
          <span key={stage} className="flex items-center gap-1">
            <span
              className={
                stage === advisory.delivery ? "text-amber-ink" : undefined
              }
            >
              {stage}
            </span>
            {i < arr.length - 1 && <span>→</span>}
          </span>
        ))}
        {advisory.judgeModelId && (
          <span className="ml-auto">{advisory.judgeModelId}</span>
        )}
      </div>
      {actions && <div className="mt-3 border-t border-line pt-3">{actions}</div>}
    </div>
  );
}
