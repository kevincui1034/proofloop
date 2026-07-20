/**
 * Hand-rolled unified-diff renderer — no dependency. Verdict colors at low
 * alpha carry add/remove; identity stays in the text itself.
 */

interface DiffLine {
  kind: "file" | "hunk" | "add" | "del" | "ctx";
  text: string;
}

function parse(patch: string): DiffLine[] {
  return patch.split("\n").map((line): DiffLine => {
    if (
      line.startsWith("diff ") ||
      line.startsWith("index ") ||
      line.startsWith("--- ") ||
      line.startsWith("+++ ")
    ) {
      return { kind: "file", text: line };
    }
    if (line.startsWith("@@")) return { kind: "hunk", text: line };
    if (line.startsWith("+")) return { kind: "add", text: line };
    if (line.startsWith("-")) return { kind: "del", text: line };
    return { kind: "ctx", text: line };
  });
}

const LINE_STYLES: Record<DiffLine["kind"], string> = {
  file: "text-ink bg-surface-3",
  hunk: "text-amber-ink",
  add: "text-verdict-green bg-verdict-green/10",
  del: "text-verdict-red bg-verdict-red/10",
  ctx: "text-body",
};

export function DiffView({ patch }: { patch: string }) {
  const lines = parse(patch);
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-line bg-surface-3">
      <pre className="min-w-max p-3 font-mono text-xs leading-5">
        {lines.map((line, i) => (
          <div key={i} className={LINE_STYLES[line.kind]}>
            {line.text || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
