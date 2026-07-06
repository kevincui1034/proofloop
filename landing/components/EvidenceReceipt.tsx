"use client";

import { motion, type Variants } from "motion/react";
import { EASE, useReducedMotionSafe } from "./characters/motion-presets";

type Row = {
  name: string;
  verdict: string;
  fail: boolean;
  loc: string;
  detail: string;
};

// Mirrors the real chk_001 record from the acceptance demo (see lib/terminal-scripts.ts).
const ROWS: Row[] = [
  { name: "env_vars", verdict: "✗ missing_env_var", fail: true, loc: "db.py:3", detail: "DATABASE_URL unset" },
  { name: "env_vars", verdict: "✗ missing_env_var", fail: true, loc: "payments.py:14", detail: "STRIPE_API_KEY unset" },
  { name: "tests", verdict: "✗ tests_not_run", fail: true, loc: "session.json", detail: "no run for this worktree" },
  { name: "config", verdict: "✗ config_mismatch", fail: true, loc: "config.py:3", detail: "API_BASE_URL → localhost" },
  { name: "config", verdict: "✗ config_mismatch", fail: true, loc: "config.py:4", detail: "DEBUG = True" },
  { name: "secrets", verdict: "✓ clean", fail: false, loc: "—", detail: "passed · 0 findings" },
];

const TEETH = Array.from(
  { length: 24 },
  (_, i) => `${i * 14},0 ${i * 14 + 7},9 ${i * 14 + 14},0`
).join(" ");

/**
 * A proof-record receipt that "prints" downward out of a slot when scrolled
 * into view — clip-path reveal, perforated bottom edge, staggered mono rows.
 */
export default function EvidenceReceipt({ className = "" }: { className?: string }) {
  // Hydration-safe: false during SSR + first client render, real value after mount.
  const rm = useReducedMotionSafe();

  // The paper slides down out of an overflow-hidden sleeve — a transform-only
  // "print" reveal (clip-path inset() proved unreliable to interpolate).
  // Hidden targets are constant regardless of rm (identical SSR markup);
  // reduced motion only zeroes the reveal transition.
  const reveal: Variants = {
    hidden: { y: "-101%" },
    visible: {
      y: "0%",
      transition: rm
        ? { duration: 0 }
        : { duration: 1.4, ease: EASE, staggerChildren: 0.13, delayChildren: 0.15 },
    },
  };

  const row: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: rm ? 0 : 0.35 } },
  };

  return (
    <div className={`relative mx-auto w-full max-w-[350px] ${className}`}>
      {/* printer slot */}
      <div className="relative z-10 mx-auto flex h-4 w-[94%] items-center justify-end rounded-full border border-line-strong bg-inset px-2.5 shadow-[0_6px_16px_-6px_rgba(0,0,0,0.8)]">
        <span className="h-1.5 w-1.5 rounded-full bg-amber shadow-[0_0_6px_var(--amber)]" />
      </div>

      {/* the sleeve (which never moves) is the in-view trigger — the paper
          starts fully outside it, so observing the paper itself would report
          zero intersection and never fire */}
      <motion.div
        className="-mt-2 overflow-hidden px-2 pb-2"
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, amount: 0.2 }}
      >
        <motion.div variants={reveal}>
          <div className="bg-[var(--paper)] px-5 pb-4 pt-6 font-mono text-[11px] leading-relaxed text-[var(--paper-ink)] shadow-[0_28px_60px_-28px_rgba(0,0,0,0.85)]">
          {/* header */}
          <motion.div variants={row}>
            <div className="flex items-baseline justify-between">
              <span className="text-[13px] font-bold tracking-[0.22em]">PROOF RECORD</span>
              <span className="rounded-sm bg-[var(--paper-ink)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--paper)]">
                chk_001
              </span>
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-[var(--paper-faint)]">
              <span>gate: deploy</span>
              <span>2026-07-04T21:14:09Z</span>
            </div>
            <div className="mt-2 border-b border-dashed border-[#c9c2ac]" />
          </motion.div>

          {/* check rows */}
          {ROWS.map((r, i) => (
            <motion.div
              key={i}
              variants={row}
              className="border-b border-dashed border-[#ddd6c2] py-1.5 last:border-0"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-bold">{r.name}</span>
                <span className={r.fail ? "text-[var(--paper-red)] font-semibold" : "text-[var(--paper-green)] font-semibold"}>
                  {r.verdict}
                </span>
              </div>
              <div className="flex items-baseline justify-between gap-2 text-[10px] text-[var(--paper-faint)]">
                <span>{r.loc}</span>
                <span className="truncate text-right">{r.detail}</span>
              </div>
            </motion.div>
          ))}

          {/* footer */}
          <motion.div variants={row}>
            <div className="mt-1 border-t border-dashed border-[#c9c2ac] pt-2 text-[10px]">
              <div className="flex justify-between gap-2">
                <span className="font-bold">inputs_hash</span>
                <span className="truncate">sha256:9f3c41a8…de21</span>
              </div>
              <div className="mt-1 flex justify-between text-[var(--paper-faint)]">
                <span>reproducible · same inputs, same verdict</span>
                <span>exit 2</span>
              </div>
            </div>
          </motion.div>
          </div>

          {/* perforated bottom edge */}
          <svg viewBox="0 0 336 10" preserveAspectRatio="none" className="block h-2.5 w-full" aria-hidden="true">
            <polygon points={TEETH} fill="var(--paper)" />
          </svg>
        </motion.div>
      </motion.div>
    </div>
  );
}
