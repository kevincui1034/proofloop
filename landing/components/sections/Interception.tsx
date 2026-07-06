"use client";

import { motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";
import Terminal from "@/components/Terminal";
import RogueBot from "@/components/characters/RogueBot";
import { gateStoryScript } from "@/lib/terminal-scripts";
import {
  EASE,
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

const FOUR_THINGS = [
  {
    name: "Checks that decide",
    detail: "deterministic and reproducible — no model in the verdict",
  },
  {
    name: "An explanation",
    detail: "the LLM only explains why, written for your agent to act on",
  },
  {
    name: "A proof record",
    detail: "file:line and command output, replayable any time",
  },
  {
    name: "A memory",
    detail: "every diagnosed failure, recalled the moment it recurs",
  },
];

/** A small rushing bot bumps into the gate bar and freezes — intercepted. */
function GateBump() {
  // Hydration-safe: false during SSR + first client render, real value after mount.
  const rm = useReducedMotionSafe();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.6 });
  const [bumped, setBumped] = useState(false);

  useEffect(() => {
    if (!inView || rm) return;
    const t = setTimeout(() => setBumped(true), 1000);
    return () => clearTimeout(t);
  }, [inView, rm]);

  const arrived = rm || inView;
  const isCaught = rm || bumped;

  return (
    <div ref={ref} aria-hidden="true" className="relative mt-5 h-[92px] overflow-hidden">
      {/* ground */}
      <div className="absolute inset-x-0 bottom-2 h-px bg-line" />
      {/* gate bar */}
      <div
        className="absolute bottom-2 right-[16%] h-[76px] w-2.5 rounded-sm"
        style={{
          background:
            "repeating-linear-gradient(45deg, var(--amber) 0 7px, #171006 7px 14px)",
        }}
      />
      <motion.div
        className="absolute bottom-1 right-[calc(16%+22px)] w-[68px]"
        initial={{ x: "-600%", opacity: 0 }}
        animate={arrived ? { x: "0%", opacity: 1 } : undefined}
        transition={rm ? { duration: 0 } : { duration: 1.0, ease: EASE }}
      >
        <RogueBot variant="violet" mood={isCaught ? "caught" : "rushing"} />
      </motion.div>
      <p className="absolute bottom-0 left-0 font-mono text-[11px] text-faint">
        intercepted before execution
      </p>
    </div>
  );
}

export default function Interception() {
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
    <section className="border-t border-line/70">
      <div className="mx-auto grid max-w-6xl items-start gap-12 px-5 py-24 sm:py-32 lg:grid-cols-[5fr_7fr] lg:gap-14">
        <motion.div {...motionProps}>
          <motion.h2
            variants={itemV}
            className="max-w-[18ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
          >
            The gate that cannot be talked past.
          </motion.h2>
          <motion.p variants={itemV} className="mt-5 text-pretty leading-relaxed sm:text-lg">
            <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[0.9em] text-amber">
              proofloop guard deploy
            </code>{" "}
            intercepts the command itself. Deterministic checks decide — env
            vars set, tests actually ran, build passes, no hardcoded secrets,
            config sanity. The LLM never votes. It only explains why.
          </motion.p>

          <motion.dl variants={itemV} className="mt-8 space-y-4 border-l border-line pl-5">
            {FOUR_THINGS.map((t) => (
              <div key={t.name}>
                <dt className="font-semibold text-ink">{t.name}</dt>
                <dd className="text-sm leading-relaxed text-faint">{t.detail}</dd>
              </div>
            ))}
          </motion.dl>

          <motion.p variants={itemV} className="mt-8 text-pretty leading-relaxed sm:text-lg">
            <strong className="font-semibold text-ink">
              Blocks the deploy — then tells your agent exactly how to fix it.
            </strong>{" "}
            A denial isn&apos;t a dead stop; it&apos;s structured feedback your
            agent uses to fix and re-run.
          </motion.p>
        </motion.div>

        <div>
          <Terminal
            script={gateStoryScript}
            ariaLabel="Terminal transcript: proofloop blocks a deploy over missing env vars, skipped tests and a localhost config, the agent applies the fixes, re-runs, and the gate passes — deploy allowed."
          />
          <GateBump />
        </div>
      </div>
    </section>
  );
}
