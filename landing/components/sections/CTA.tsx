"use client";

import { motion } from "motion/react";
import StampBlocked from "@/components/StampBlocked";
import { GITHUB_URL, GitHubIcon, GateGlyph } from "@/components/Nav";
import {
  fadeUp,
  fadeUpInstant,
  staggerParent,
  staggerParentInstant,
  useReducedMotionSafe,
  VIEWPORT,
} from "@/components/characters/motion-presets";

const MAILTO =
  "mailto:kevincui1034@gmail.com?subject=Proofloop%20early%20access";

export default function CTA() {
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
    <section id="early-access" className="border-t border-line/70">
      <motion.div {...motionProps} className="mx-auto max-w-6xl px-5 pb-10 pt-24 text-center sm:pt-32">
        <motion.div variants={itemV} className="mb-8">
          <StampBlocked verdict="allowed" size="lg" />
        </motion.div>
        <motion.h2
          variants={itemV}
          className="mx-auto max-w-[16ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-[2.6rem] sm:leading-[1.12]"
        >
          Stop shipping broken deploys.
        </motion.h2>
        <motion.p
          variants={itemV}
          className="mx-auto mt-4 max-w-[46ch] text-pretty leading-relaxed sm:text-lg"
        >
          One command between your agent and production. Open source, and it
          gets smarter with every catch.
        </motion.p>
        <motion.div
          variants={itemV}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md bg-amber px-6 py-3 text-sm font-semibold text-[#171006] transition-[filter] hover:brightness-110"
          >
            <GitHubIcon className="h-4 w-4" />
            Star on GitHub
          </a>
          <a
            href={MAILTO}
            className="rounded-md border border-line-strong px-6 py-3 text-sm font-medium text-ink transition-colors hover:border-amber/60 hover:text-amber"
          >
            Get early access
          </a>
        </motion.div>

        <footer className="mt-24 flex flex-col items-center justify-between gap-3 border-t border-line py-7 text-xs text-faint sm:flex-row">
          <span className="flex items-center gap-1.5 font-mono text-[13px] text-body">
            <GateGlyph className="h-3.5 w-3.5" />
            proofloop
          </span>
          <span>Apache-2.0 · correctness, not security · © 2026 Proofloop</span>
        </footer>
      </motion.div>
    </section>
  );
}
