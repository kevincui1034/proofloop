/** Small shared display atoms. Color is a verdict, never decoration. */

export function VerdictBadge({ passed }: { passed: boolean }) {
  return passed ? (
    <span className="rounded border border-verdict-green/40 px-2 py-0.5 text-xs font-medium text-verdict-green">
      ALLOWED
    </span>
  ) : (
    <span className="rounded border border-verdict-red/40 px-2 py-0.5 text-xs font-medium text-verdict-red">
      BLOCKED
    </span>
  );
}

export function ClassChip({ name }: { name: string }) {
  return (
    <span className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-xs text-body">
      {name}
    </span>
  );
}

export function DeliveryBadge({ delivery }: { delivery: string }) {
  const styles: Record<string, string> = {
    injected: "text-amber-ink border-amber/40",
    held: "text-body border-line-2",
    staged: "text-amber-ink border-amber/40",
    sent: "text-verdict-green border-verdict-green/40",
    suppressed: "text-faint border-line",
  };
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-xs ${styles[delivery] ?? "text-faint border-line"}`}
    >
      {delivery}
    </span>
  );
}

export function LabelBadge({ label }: { label: string | null }) {
  if (!label) return null;
  return label === "confirmed" ? (
    <span className="rounded border border-verdict-green/40 px-1.5 py-0.5 text-xs text-verdict-green">
      confirmed
    </span>
  ) : (
    <span className="rounded border border-verdict-red/40 px-1.5 py-0.5 text-xs text-verdict-red">
      rejected
    </span>
  );
}

/** Emphasize file:line references inside evidence text. */
export function EvidenceText({ text }: { text: string }) {
  const parts = text.split(/([A-Za-z0-9_./\\-]+:\d+)/g);
  return (
    <span>
      {parts.map((part, i) =>
        /^[A-Za-z0-9_./\\-]+:\d+$/.test(part) ? (
          <span key={i} className="font-mono text-amber-ink">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  );
}

export function timeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}
