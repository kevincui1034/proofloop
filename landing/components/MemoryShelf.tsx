"use client";

import { motion, type Variants } from "motion/react";
import { EASE, useReducedMotionSafe } from "./characters/motion-presets";

type Tone = "red" | "green" | "amber";

type Record_ = {
  id: string;
  cls: string;
  status: string;
  tone: Tone;
  newest?: boolean;
  hideOnXs?: boolean;
};

// The first three story cards mirror the acceptance demo verbatim
// (see lib/terminal-scripts.ts): chk_001 is diagnosed, chk_002 is the
// gate-PASSED record resolving it, and chk_003 is the recurrence recalled
// from chk_001. chk_014 / chk_027 are illustrative records from later runs.
const RECORDS: Record_[] = [
  { id: "chk_001", cls: "missing_env_var", status: "diagnosed", tone: "red" },
  { id: "chk_002", cls: "gate_passed", status: "resolves chk_001", tone: "green" },
  { id: "chk_014", cls: "config_mismatch", status: "diagnosed", tone: "red", hideOnXs: true },
  { id: "chk_027", cls: "hardcoded_secret", status: "diagnosed", tone: "red", hideOnXs: true },
  { id: "chk_003", cls: "missing_env_var", status: "recalled · 64 ms", tone: "amber", newest: true },
];

const DOT: Record<Tone, string> = {
  red: "bg-verdict-red/70",
  green: "bg-verdict-green/70",
  amber: "bg-amber",
};

/**
 * Proof records sliding onto a shelf; the newest card (chk_003) is
 * highlighted and linked back to chk_001 with an amber recall arc.
 */
export default function MemoryShelf({ className = "" }: { className?: string }) {
  // Hydration-safe: false during SSR + first client render, real value after mount.
  const rm = useReducedMotionSafe();

  // Hidden targets are constant regardless of rm (identical SSR markup);
  // reduced motion only zeroes transitions, so reveals snap on scroll.
  const parent: Variants = {
    hidden: {},
    visible: { transition: { staggerChildren: rm ? 0 : 0.13 } },
  };
  const card: Variants = {
    hidden: { opacity: 0, x: 46 },
    visible: { opacity: 1, x: 0, transition: rm ? { duration: 0 } : { duration: 0.55, ease: EASE } },
  };

  return (
    <motion.div
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.4 }}
      variants={parent}
      className={`relative ${className}`}
    >
      {/* recall label + arc — from the newest card (chk_003) back to chk_001 */}
      <motion.p
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={rm ? { duration: 0 } : { delay: 1.05, duration: 0.4 }}
        className="mb-1 text-center font-mono text-[11px] text-amber"
      >
        recalled_from → chk_001
      </motion.p>
      <div className="relative mx-[9%] h-9" aria-hidden="true">
        <svg viewBox="0 0 100 34" preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible">
          {/* NOTE: framer's pathLength animation rewrites stroke-dasharray,
              so dashed strokes fade in via opacity instead */}
          <motion.path
            d="M98 33 C 80 2, 20 2, 2 30"
            fill="none"
            stroke="var(--amber)"
            strokeWidth="1.5"
            strokeDasharray="4 4"
            vectorEffect="non-scaling-stroke"
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, amount: 0.6 }}
            transition={rm ? { duration: 0 } : { duration: 0.7, delay: 0.9 }}
          />
        </svg>
        <motion.span
          className="absolute -bottom-1 left-0 -translate-x-1/2 text-[13px] leading-none text-amber"
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, amount: 0.6 }}
          transition={rm ? { duration: 0 } : { delay: 1.6, duration: 0.3 }}
        >
          ▾
        </motion.span>
      </div>

      {/* record cards */}
      <div className="flex items-stretch gap-2 sm:gap-3">
        {RECORDS.map((r) => (
          <motion.div
            key={r.id}
            variants={card}
            className={`min-w-0 flex-1 rounded-lg border px-2 py-2.5 sm:px-3 ${
              r.newest
                ? "border-amber/70 bg-[rgba(245,184,61,0.07)] shadow-[0_0_24px_-6px_rgba(245,184,61,0.35)]"
                : "border-line bg-raised"
            } ${r.hideOnXs ? "hidden min-[480px]:block" : ""}`}
          >
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[r.tone]}`} />
              <span className={`truncate font-mono text-[11px] font-semibold ${r.newest ? "text-amber" : "text-ink"}`}>
                {r.id}
              </span>
            </div>
            <p className="mt-1 truncate font-mono text-[10px] text-faint">{r.cls}</p>
            <p
              className={`mt-0.5 truncate font-mono text-[9px] uppercase tracking-wider ${
                r.tone === "green" ? "text-verdict-green/80" : "text-faint/70"
              }`}
            >
              {r.status}
            </p>
          </motion.div>
        ))}
      </div>

      {/* the shelf */}
      <div className="mt-1.5 h-2 rounded-sm border-t border-line-strong bg-[#101724] shadow-[0_10px_24px_-12px_rgba(0,0,0,0.9)]" />
    </motion.div>
  );
}
