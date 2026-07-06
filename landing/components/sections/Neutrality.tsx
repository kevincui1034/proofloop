"use client";

import { motion } from "motion/react";
import RogueBot, { type BotVariant } from "@/components/characters/RogueBot";
import JudgeCharacter from "@/components/characters/JudgeCharacter";
import GateStructure from "@/components/GateStructure";
import {
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

// Deliberately vendor-neutral glyphs — no agent logos.
const LANES: { variant: BotVariant; glyph: string; top: string; pathY: number }[] = [
  { variant: "teal", glyph: "◇", top: "top-[2%]", pathY: 15 },
  { variant: "violet", glyph: "△", top: "top-[36%]", pathY: 50 },
  { variant: "rose", glyph: "○", top: "top-[70%]", pathY: 85 },
];

const LANE_COLORS: Record<BotVariant, string> = {
  teal: "var(--bot-teal)",
  violet: "var(--bot-violet)",
  rose: "var(--bot-rose)",
};

export default function Neutrality() {
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
      <div className="mx-auto max-w-6xl px-5 py-24 text-center sm:py-32">
        <motion.div {...motionProps}>
          <motion.h2
            variants={itemV}
            className="mx-auto max-w-[20ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
          >
            Doesn&apos;t care which agent wrote it.
          </motion.h2>
          <motion.p
            variants={itemV}
            className="mx-auto mt-5 max-w-[56ch] text-pretty leading-relaxed sm:text-lg"
          >
            Same gate, same checks, same memory — whether the code came from
            Claude Code, Codex, or Cursor. A neutral judge is something no
            agent vendor can be.
          </motion.p>
        </motion.div>

        {/* three agents, one gate */}
        <div className="relative mx-auto mt-14 h-[260px] max-w-2xl sm:h-[300px]" aria-hidden="true">
          {/* converging lanes */}
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-y-0 left-[13%] right-[24%] h-full w-[63%]"
          >
            {/* dashed lanes fade in (pathLength would rewrite the dasharray) */}
            {LANES.map((l, i) => (
              <motion.path
                key={l.variant}
                d={`M0 ${l.pathY} C 55 ${l.pathY}, 60 50, 100 50`}
                fill="none"
                stroke={LANE_COLORS[l.variant]}
                strokeWidth="1.5"
                strokeDasharray="5 5"
                vectorEffect="non-scaling-stroke"
                initial={{ opacity: 0 }}
                whileInView={{ opacity: 0.5 }}
                viewport={{ once: true, amount: 0.5 }}
                transition={rm ? { duration: 0 } : { duration: 0.7, delay: 0.25 + i * 0.18 }}
              />
            ))}
          </svg>

          {/* the three bots, idling in their lanes */}
          {LANES.map((l) => (
            <div key={l.variant} className={`absolute left-0 ${l.top} w-[15%] max-w-[74px]`}>
              <RogueBot variant={l.variant} mood="idle" />
              <p className="mt-1 text-center font-mono text-xs text-faint">{l.glyph}</p>
            </div>
          ))}

          {/* one gate, one judge */}
          <div className="absolute right-0 top-1/2 w-[24%] max-w-[130px] -translate-y-1/2">
            <GateStructure className="w-full" />
          </div>
          <div className="absolute right-[3%] top-1/2 w-[19%] max-w-[104px] -translate-y-[42%]">
            <JudgeCharacter raised={false} />
          </div>
        </div>

        {/* the disambiguation line */}
        <motion.blockquote
          initial="hidden"
          whileInView="visible"
          viewport={VIEWPORT}
          variants={itemV}
          className="mx-auto mt-16 max-w-3xl border-y border-line py-8"
        >
          <p className="text-balance text-xl font-medium leading-snug text-ink sm:text-2xl">
            Your guardrails stop the{" "}
            <span className="text-verdict-red">dangerous</span> command.
            <br className="hidden sm:block" /> Proofloop stops the{" "}
            <span className="text-amber">broken</span> one.
          </p>
        </motion.blockquote>
      </div>
    </section>
  );
}
