"use client";

import { motion } from "motion/react";
import MemoryShelf from "@/components/MemoryShelf";
import Terminal from "@/components/Terminal";
import { recurrenceScript } from "@/lib/terminal-scripts";
import {
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

export default function Memory() {
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
    <section className="border-t border-line/70 bg-[#0c1119]">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:py-32">
        <motion.div {...motionProps} className="max-w-2xl">
          <motion.h2
            variants={itemV}
            className="max-w-[18ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
          >
            Every catch makes it smarter.
          </motion.h2>
          <motion.p variants={itemV} className="mt-5 text-pretty leading-relaxed sm:text-lg">
            Every diagnosed failure is stored in training-ready form — the
            failure class, the evidence, the judgment. When the same mistake
            comes back, the gate doesn&apos;t re-deliberate. It recognizes.
          </motion.p>
        </motion.div>

        <MemoryShelf className="mt-14" />

        <div className="mt-14 grid items-center gap-10 lg:grid-cols-[7fr_5fr]">
          <Terminal
            script={recurrenceScript}
            ariaLabel="Terminal transcript: a recurring missing env var is blocked instantly — recalled from prior record chk_001, no LLM call needed."
          />
          <motion.p
            initial="hidden"
            whileInView="visible"
            viewport={VIEWPORT}
            variants={itemV}
            className="text-pretty leading-relaxed sm:text-lg"
          >
            The second time your agent forgets a key, there&apos;s no
            re-deliberation and no model call — the block lands in{" "}
            <span className="font-mono text-sm text-amber">64&nbsp;ms</span>, and it
            arrives{" "}
            <strong className="font-semibold text-ink">
              with the receipts
            </strong>
            : the prior record, the prior diagnosis, the recurrence linked as{" "}
            <span className="font-mono text-sm text-amber">recalled_from</span>.
          </motion.p>
        </div>
      </div>
    </section>
  );
}
