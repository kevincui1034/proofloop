"use client";

import {
  motion,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "motion/react";
import { useRef, useState } from "react";
import RogueBot from "@/components/characters/RogueBot";
import JudgeCharacter from "@/components/characters/JudgeCharacter";
import GateStructure from "@/components/GateStructure";
import StampBlocked from "@/components/StampBlocked";
import { GITHUB_URL, GitHubIcon } from "@/components/Nav";
import { EASE, skidStop, useReducedMotionSafe } from "@/components/characters/motion-presets";

export default function Hero() {
  // Hydration-safe: false during SSR + first client render, real value after mount.
  const rm = useReducedMotionSafe();
  const outerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: outerRef,
    offset: ["start start", "end end"],
  });

  const [caught, setCaught] = useState(false);
  const [raised, setRaised] = useState(false);
  const [stamped, setStamped] = useState(false);

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    setRaised(v >= 0.52);
    setCaught(v >= 0.55);
    setStamped(v >= 0.75);
  });

  // Three bots race in from the left, queueing up before the gate.
  const bot1X = useTransform(scrollYProgress, [0.02, 0.5], ["-75vw", "0vw"]);
  const bot2X = useTransform(scrollYProgress, [0.08, 0.55], ["-85vw", "0vw"]);
  const bot3X = useTransform(scrollYProgress, [0.14, 0.6], ["-95vw", "0vw"]);
  const bot1Y = useTransform(scrollYProgress, [0.05, 0.15, 0.25, 0.35, 0.45, 0.5], [0, -9, 4, -7, 3, 0]);
  const bot2Y = useTransform(scrollYProgress, [0.1, 0.2, 0.3, 0.4, 0.5, 0.55], [0, -7, 5, -8, 2, 0]);
  const bot3Y = useTransform(scrollYProgress, [0.15, 0.25, 0.35, 0.45, 0.55, 0.6], [0, -8, 3, -6, 4, 0]);
  const hintOpacity = useTransform(scrollYProgress, [0, 0.06], [1, 0]);

  const showCaught = rm ? true : caught;
  const showRaised = rm ? true : raised;
  const showStamped = rm ? true : stamped;
  const mood = showCaught ? "caught" : "rushing";

  // Constant DOM/props shape (safe for hydration); only the transition is
  // rm-aware. The mount animation starts before rm can flip to true, and its
  // target is the final state, so reduced-motion users still end fully visible.
  const entrance = (delay: number) => ({
    initial: { opacity: 0, y: 26 },
    animate: { opacity: 1, y: 0 },
    transition: rm ? { duration: 0 } : { duration: 0.8, ease: EASE, delay },
  });

  // With rm, freeze the skid-stop so the post-mount flip to "caught" doesn't
  // replay the overshoot keyframes.
  const skid = rm ? { ...skidStop, caught: { x: 0, rotate: 0 } } : skidStop;

  return (
    <div
      ref={outerRef}
      className="relative"
      style={{ height: rm ? "auto" : "220vh" }}
    >
      <section
        aria-label="Proofloop — the correctness gate for AI-written code"
        className={`${rm ? "relative" : "sticky top-0"} flex h-svh min-h-[560px] flex-col overflow-hidden`}
      >
        {/* headline */}
        <div className="relative z-30 mx-auto w-full max-w-6xl px-5 pt-[max(84px,12svh)] sm:pt-[15svh]">
          <motion.p {...entrance(0)} className="mb-5 font-mono text-xs text-amber sm:text-[13px]">
            $ proofloop guard deploy -- ./deploy.sh
          </motion.p>
          <motion.h1
            {...entrance(0.08)}
            className="max-w-[13ch] text-balance text-[clamp(2.4rem,7vw,4.9rem)] font-semibold leading-[1.04] tracking-[-0.03em] text-ink"
          >
            The last command before production.
          </motion.h1>
          <motion.p {...entrance(0.18)} className="mt-5 max-w-[52ch] text-pretty text-base leading-relaxed text-body sm:text-lg">
            Proofloop is the correctness gate for AI-written code — it catches
            what your agent got wrong before it ships, proves why, and
            remembers.
          </motion.p>
          <motion.div {...entrance(0.28)} className="mt-8 flex flex-wrap items-center gap-3">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-md bg-amber px-5 py-2.5 text-sm font-semibold text-[#171006] transition-[filter] hover:brightness-110"
            >
              <GitHubIcon className="h-4 w-4" />
              Star on GitHub
            </a>
            <a
              href="#early-access"
              className="rounded-md border border-line-strong px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:border-amber/60 hover:text-amber"
            >
              Get early access
            </a>
          </motion.div>
        </div>

        {/* the scene: three rogue bots race toward the gate where the Judge waits */}
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[30svh] max-h-[400px] min-h-[210px] sm:h-[40svh]"
          animate={
            showStamped && !rm
              ? { x: [0, -7, 6, -4, 2, 0], transition: { duration: 0.5, delay: 0.05 } }
              : { x: 0 }
          }
        >
          {/* fade so the scene never fights the headline */}
          <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-bg via-bg/70 to-transparent" />
          {/* ground */}
          <div className="absolute inset-x-0 bottom-[26px] h-px bg-line-strong" />
          <div className="absolute inset-x-0 bottom-0 h-[26px] bg-inset/60" />

          {/* gate + judge */}
          <div className="absolute bottom-[25px] right-[2%] w-[clamp(110px,16vw,170px)] sm:right-[6%]">
            <GateStructure className="w-full" />
          </div>
          <div className="absolute bottom-[25px] right-[calc(2%+8px)] w-[clamp(88px,13vw,136px)] sm:right-[calc(6%+14px)]">
            <JudgeCharacter raised={showRaised} />
          </div>

          {/* bots */}
          {(
            [
              { x: bot1X, y: bot1Y, variant: "teal", pos: "right-[23%]", w: "w-[clamp(64px,10.5vw,108px)]" },
              { x: bot2X, y: bot2Y, variant: "violet", pos: "right-[39%]", w: "w-[clamp(56px,9.5vw,96px)]" },
              { x: bot3X, y: bot3Y, variant: "rose", pos: "right-[53%]", w: "w-[clamp(50px,8.5vw,88px)]" },
            ] as const
          ).map((b) => (
            <motion.div
              key={b.variant}
              style={{ x: rm ? 0 : b.x, y: rm ? 0 : b.y }}
              className={`absolute bottom-[22px] ${b.pos} ${b.w} aspect-square`}
            >
              <motion.div variants={skid} initial={false} animate={mood}>
                <RogueBot variant={b.variant} mood={mood} />
              </motion.div>
            </motion.div>
          ))}

          {/* the verdict slams over the scene */}
          <div className="absolute left-1/2 top-[18%] z-30 -translate-x-1/2">
            <StampBlocked verdict="blocked" show={showStamped} size="lg" />
          </div>
        </motion.div>

        {/* scroll hint */}
        {!rm && (
          <motion.div
            style={{ opacity: hintOpacity }}
            className="absolute bottom-2 left-1/2 z-30 -translate-x-1/2"
            aria-hidden="true"
          >
            <svg viewBox="0 0 24 24" className="hint-drop h-6 w-6" fill="none" stroke="var(--faint)" strokeWidth="2" strokeLinecap="round">
              <path d="M5 9l7 7 7-7" />
            </svg>
          </motion.div>
        )}
      </section>
    </div>
  );
}
