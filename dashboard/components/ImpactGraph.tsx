"use client";

/**
 * Blast-radius node-link view from impact.json — hand-rolled SVG.
 * impact.json is depth ≤ 2 and ≤ 50 dependents by construction (CLI
 * IMPACT_DEFAULTS), so a tiered column layout is deterministic and needs
 * no graph library. Amber marks the changed files (the cause); dependents
 * stay neutral — color is semantic, not decorative.
 */
import { useMemo, useState } from "react";

interface Dependent {
  file: string;
  edge: string;
  depth: number;
}

interface ImpactDoc {
  depth: number;
  truncated: boolean;
  changed: { file: string; dependents: Dependent[] }[];
}

interface Node {
  id: string;
  label: string;
  column: number;
  row: number;
  changed: boolean;
}

interface Edge {
  from: string;
  to: string;
  label: string;
}

const COLUMN_WIDTH = 260;
const ROW_HEIGHT = 44;
const NODE_WIDTH = 220;
const NODE_HEIGHT = 30;
const PADDING = 16;

function layout(doc: ImpactDoc): { nodes: Node[]; edges: Edge[] } {
  const nodes = new Map<string, Node>();
  const edges: Edge[] = [];
  const rows = [0, 0, 0];

  const addNode = (file: string, column: number, changed: boolean): Node => {
    const existing = nodes.get(file);
    if (existing) return existing;
    const node: Node = {
      id: file,
      label: file,
      column,
      row: rows[column]++,
      changed,
    };
    nodes.set(file, node);
    return node;
  };

  for (const entry of doc.changed) {
    addNode(entry.file, 0, true);
    for (const dep of entry.dependents) {
      const column = Math.min(dep.depth, 2);
      addNode(dep.file, column, false);
      // Edge points from the dependent's import source: depth-1 edges come
      // from the changed file; depth-2 from the depth-1 layer (nearest
      // known importer chain isn't in the doc, so anchor to the entry).
      const source =
        dep.depth === 1
          ? entry.file
          : (entry.dependents.find((d) => d.depth === dep.depth - 1)?.file ??
            entry.file);
      edges.push({ from: source, to: dep.file, label: dep.edge });
    }
  }
  return { nodes: Array.from(nodes.values()), edges };
}

function nodeX(node: Node): number {
  return PADDING + node.column * COLUMN_WIDTH;
}
function nodeY(node: Node): number {
  return PADDING + node.row * ROW_HEIGHT;
}

export function ImpactGraph({ impactJson }: { impactJson: string }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const doc = useMemo<ImpactDoc | null>(() => {
    try {
      return JSON.parse(impactJson) as ImpactDoc;
    } catch {
      return null;
    }
  }, [impactJson]);
  const graph = useMemo(() => (doc ? layout(doc) : null), [doc]);
  if (!doc || !graph) return null;
  const { nodes, edges } = graph;
  if (nodes.length === 0) return null;

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const height =
    PADDING * 2 + Math.max(...nodes.map((n) => n.row + 1)) * ROW_HEIGHT;
  const width = PADDING * 2 + 3 * COLUMN_WIDTH;
  const isDim = (id: string) =>
    hovered !== null &&
    hovered !== id &&
    !edges.some(
      (e) =>
        (e.from === hovered && e.to === id) ||
        (e.to === hovered && e.from === id),
    );

  return (
    <div className="mt-3 overflow-x-auto">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label="Reverse-import blast radius graph"
      >
        {edges.map((edge, i) => {
          const from = byId.get(edge.from);
          const to = byId.get(edge.to);
          if (!from || !to) return null;
          const x1 = nodeX(from) + NODE_WIDTH;
          const y1 = nodeY(from) + NODE_HEIGHT / 2;
          const x2 = nodeX(to);
          const y2 = nodeY(to) + NODE_HEIGHT / 2;
          const mx = (x1 + x2) / 2;
          const active = hovered === edge.from || hovered === edge.to;
          return (
            <g key={i}>
              <path
                d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                fill="none"
                stroke={active ? "var(--amber)" : "var(--line-2)"}
                strokeWidth={active ? 2 : 1.5}
                opacity={hovered && !active ? 0.25 : 1}
              />
              {active && (
                <text
                  x={mx}
                  y={(y1 + y2) / 2 - 6}
                  textAnchor="middle"
                  fill="var(--faint)"
                  fontSize="10"
                  fontFamily="var(--font-geist-mono)"
                >
                  {edge.label}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${nodeX(node)}, ${nodeY(node)})`}
            onMouseEnter={() => setHovered(node.id)}
            onMouseLeave={() => setHovered(null)}
            opacity={isDim(node.id) ? 0.35 : 1}
            style={{ cursor: "default" }}
          >
            <rect
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={4}
              fill={node.changed ? "var(--surface-3)" : "var(--surface-2)"}
              stroke={node.changed ? "var(--amber)" : "var(--line-2)"}
              strokeWidth={node.changed ? 1.5 : 1}
            />
            <text
              x={10}
              y={NODE_HEIGHT / 2 + 4}
              fill={node.changed ? "var(--amber-ink)" : "var(--body)"}
              fontSize="12"
              fontFamily="var(--font-geist-mono)"
            >
              {node.label.length > 30
                ? `…${node.label.slice(-29)}`
                : node.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="mt-1 flex gap-4 text-xs text-faint">
        <span>
          <span className="text-amber-ink">▛</span> changed
        </span>
        <span>columns → import depth</span>
        {doc.truncated && <span>(truncated at the CLI&apos;s max_files cap)</span>}
      </div>
    </div>
  );
}
