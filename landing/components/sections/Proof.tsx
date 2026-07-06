"use client";

import { motion } from "motion/react";
import EvidenceReceipt from "@/components/EvidenceReceipt";
import {
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

export default function Proof() {
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
    <section className="mx-auto grid max-w-6xl items-center gap-14 px-5 py-24 sm:py-32 lg:grid-cols-2">
      <div className="order-2 lg:order-1">
        <EvidenceReceipt />
      </div>
      <motion.div {...motionProps} className="order-1 lg:order-2">
        <motion.h2
          variants={itemV}
          className="max-w-[18ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
        >
          Every deploy ships with a proof record.
        </motion.h2>
        <motion.p variants={itemV} className="mt-5 max-w-[52ch] text-pretty leading-relaxed sm:text-lg">
          Proof, not vibes — which check failed, the file:line, the command
          output that shows it. Reproducible, not a regenerated opinion.
        </motion.p>
        <motion.p variants={itemV} className="mt-4 max-w-[52ch] text-pretty leading-relaxed text-faint">
          Each interception is persisted to{" "}
          <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[0.9em] text-body">
            .proofloop/runs/
          </code>{" "}
          — the trace, the env scan, the build log. Run it again with the same
          inputs and you get the same verdict.
        </motion.p>
      </motion.div>
    </section>
  );
}
