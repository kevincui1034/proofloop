"use client";

import { motion } from "motion/react";
import RogueBot, { type BotVariant } from "@/components/characters/RogueBot";
import {
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

const MISTAKES: {
  variant: BotVariant;
  title: string;
  line: string;
  evidence: string;
}[] = [
  {
    variant: "teal",
    title: "The missing key",
    line: "Referenced in the code, set nowhere. The first request crashes.",
    evidence: "payments.py:14 · STRIPE_API_KEY unset",
  },
  {
    variant: "violet",
    title: "The localhost config",
    line: "Works on the agent's machine. Ships to yours.",
    evidence: "config.py:3 · API_BASE_URL=localhost:8000",
  },
  {
    variant: "rose",
    title: "The skipped tests",
    line: "Marked done. Never proven.",
    evidence: "pytest · 0 runs this session",
  },
];

export default function Problem() {
  // Hydration-safe rm: props keep a constant shape (identical SSR markup);
  // reduced motion swaps in instant-reveal variants with identical targets.
  const rm = useReducedMotionSafe();
  const itemV = rm ? fadeUpInstant : fadeUp;
  const motionProps = {
    initial: "hidden" as const,
    whileInView: "visible" as const,
    viewport: VIEWPORT,
    variants: rm ? staggerParentInstant : staggerParent,
  };

  return (
    <section className="mx-auto max-w-6xl px-5 py-24 sm:py-32">
      <motion.div {...motionProps}>
        <motion.h2
          variants={itemV}
          className="max-w-[24ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
        >
          Your agent wrote it, reviewed it, and is about to ship it.
        </motion.h2>
        <motion.p
          variants={itemV}
          className="mt-5 max-w-[58ch] text-pretty leading-relaxed sm:text-lg"
        >
          Coding agents ship a growing share of production code — changes land
          every day that no engineer has read. The failures aren&apos;t
          malicious. They&apos;re confident little mistakes, shipped at full
          speed.
        </motion.p>
        <motion.p
          variants={itemV}
          className="mt-4 max-w-[58ch] text-pretty leading-relaxed sm:text-lg"
        >
          Guardrails watch for dangerous commands. Test suites check whatever
          got run. But{" "}
          <strong className="font-semibold text-ink">
            no one guards correctness at the deploy moment
          </strong>{" "}
          — the second the code leaves the repo.
        </motion.p>

        <div className="mt-14 grid gap-4 sm:grid-cols-3 sm:gap-5">
          {MISTAKES.map((m) => (
            <motion.article
              key={m.title}
              variants={itemV}
              className="rounded-xl border border-line bg-raised p-5"
            >
              <div className="grid place-items-center rounded-lg bg-inset py-4">
                <div className="w-[86px]">
                  <RogueBot variant={m.variant} mood="caught" />
                </div>
              </div>
              <h3 className="mt-4 font-semibold text-ink">{m.title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-body">{m.line}</p>
              <p className="mt-3 font-mono text-xs text-faint">
                <span className="text-verdict-red">✗ </span>
                {m.evidence}
              </p>
            </motion.article>
          ))}
        </div>
      </motion.div>
    </section>
  );
}
