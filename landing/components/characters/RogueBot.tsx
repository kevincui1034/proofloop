"use client";

import { motion, type Variants } from "motion/react";
import { useId, useMemo } from "react";
import { seedFromId, useReducedMotionSafe } from "./motion-presets";

export type BotVariant = "teal" | "violet" | "rose";
export type BotMood = "rushing" | "caught" | "idle";

type RogueBotProps = {
  variant: BotVariant;
  mood: BotMood;
  /** Fixed pixel size; omit to fill the parent (width/height 100%). */
  size?: number;
};

const ACCENT: Record<BotVariant, string> = {
  teal: "var(--bot-teal)",
  violet: "var(--bot-violet)",
  rose: "var(--bot-rose)",
};

/* per-variant character accessories: antenna shape, eye size + spacing */
const FACE: Record<BotVariant, { eyeR: number; eyeLX: number; eyeRX: number }> = {
  teal: { eyeR: 4, eyeLX: 50, eyeRX: 70 },
  violet: { eyeR: 3.2, eyeLX: 46.5, eyeRX: 73.5 },
  rose: { eyeR: 5, eyeLX: 51, eyeRX: 69 },
};

const BODY = "#131a25";
const BODY_DARK = "#0d131c";
const OUTLINE = "#2b3544";

export default function RogueBot({ variant, mood, size }: RogueBotProps) {
  // Hydration-safe: false during SSR + first client render, real value after
  // mount. When it flips, the rm-gated variants below re-resolve and stop the
  // infinite wheel/blink/antenna loops.
  const rm = useReducedMotionSafe();
  const accent = ACCENT[variant];
  const face = FACE[variant];

  // Randomized blink cadence, stable per instance (derived from useId so the
  // render stays pure and SSR matches the client).
  const id = useId();
  const blink = useMemo(() => {
    const seed = seedFromId(id);
    return {
      repeatDelay: 2 + seed * 3,
      delay: 0.4 + ((seed * 7.31) % 1) * 1.6,
    };
  }, [id]);

  const v = useMemo(() => {
    const root: Variants = {
      rushing: { rotate: 5, y: 0, x: 0 },
      caught: rm
        ? { rotate: 0, y: 0, x: 0 }
        : {
            rotate: 0,
            y: 0,
            x: [0, -2.5, 2.5, -1.5, 1.5, 0],
            transition: { duration: 0.5, ease: "easeOut" },
          },
      idle: rm
        ? { rotate: 0, x: 0, y: 0 }
        : {
            rotate: 0,
            x: 0,
            y: [0, -4, 0],
            transition: { duration: 3.4, repeat: Infinity, ease: "easeInOut" },
          },
    };

    const wheel: Variants = {
      rushing: rm
        ? { rotate: 0 }
        : { rotate: 360, transition: { repeat: Infinity, ease: "linear", duration: 0.55 } },
      caught: { rotate: 0, transition: { duration: 0.3 } },
      idle: { rotate: 0 },
    };

    const speedlines: Variants = {
      rushing: rm
        ? { opacity: 0.35 }
        : { opacity: [0.45, 0.08, 0.45], transition: { repeat: Infinity, duration: 0.6 } },
      caught: { opacity: 0, transition: { duration: 0.15 } },
      idle: { opacity: 0 },
    };

    const armSpring = rm
      ? { duration: 0 }
      : { type: "spring" as const, stiffness: 300, damping: 15 };
    const armL: Variants = {
      rushing: { rotate: 38 },
      caught: { rotate: 150, transition: armSpring },
      idle: { rotate: 6 },
    };
    const armR: Variants = {
      rushing: { rotate: 46 },
      caught: { rotate: -150, transition: armSpring },
      idle: { rotate: -6 },
    };

    // wide-eyed on caught
    const eyeScale: Variants = {
      rushing: { scale: 1 },
      caught: {
        scale: 1.35,
        transition: rm ? { duration: 0 } : { type: "spring", stiffness: 400, damping: 16 },
      },
      idle: { scale: 1 },
    };

    const eyeBlink: Variants = {
      rushing: rm
        ? { scaleY: 1 }
        : {
            scaleY: [1, 0.1, 1],
            transition: { duration: 0.22, repeat: Infinity, ...blink },
          },
      caught: { scaleY: 1 },
      idle: rm
        ? { scaleY: 1 }
        : {
            scaleY: [1, 0.1, 1],
            transition: { duration: 0.22, repeat: Infinity, ...blink },
          },
    };

    const antennaTip: Variants = {
      rushing: rm
        ? { y: 0 }
        : { y: [0, -2.5, 0], transition: { duration: 0.5, repeat: Infinity, ease: "easeInOut" } },
      caught: { y: -1.5 },
      idle: rm
        ? { y: 0 }
        : { y: [0, -2, 0], transition: { duration: 1.6, repeat: Infinity, ease: "easeInOut" } },
    };

    const mouthFlat: Variants = {
      rushing: { opacity: 1 },
      caught: { opacity: 0 },
      idle: { opacity: 1 },
    };
    const mouthO: Variants = {
      rushing: { opacity: 0 },
      caught: { opacity: 1 },
      idle: { opacity: 0 },
    };

    return { root, wheel, speedlines, armL, armR, eyeScale, eyeBlink, antennaTip, mouthFlat, mouthO };
  }, [rm, blink]);

  return (
    <motion.svg
      viewBox="0 0 120 120"
      width={size ?? "100%"}
      height={size ?? "100%"}
      aria-hidden="true"
      focusable="false"
      initial={false}
      animate={mood}
      variants={v.root}
      style={{ display: "block", overflow: "visible" }}
    >
      {/* ground shadow */}
      <ellipse cx="60" cy="111" rx="32" ry="4" fill="#000" opacity="0.35" />

      {/* speed lines (rushing only) */}
      <motion.g
        variants={v.speedlines}
        stroke={accent}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="7 7"
      >
        <line x1="2" y1="62" x2="26" y2="62" />
        <line x1="-6" y1="78" x2="24" y2="78" />
        <line x1="4" y1="94" x2="22" y2="94" />
      </motion.g>

      {/* arms (behind torso) — drawn pointing down, rotated at the shoulder */}
      <g transform="translate(32 64)">
        <motion.g variants={v.armL}>
          <rect x="-4" y="-2" width="8" height="24" rx="4" fill={BODY} stroke={OUTLINE} strokeWidth="1.5" />
          <circle cx="0" cy="23" r="4.5" fill={BODY_DARK} stroke={accent} strokeWidth="1.5" />
        </motion.g>
      </g>
      <g transform="translate(88 64)">
        <motion.g variants={v.armR}>
          <rect x="-4" y="-2" width="8" height="24" rx="4" fill={BODY} stroke={OUTLINE} strokeWidth="1.5" />
          <circle cx="0" cy="23" r="4.5" fill={BODY_DARK} stroke={accent} strokeWidth="1.5" />
        </motion.g>
      </g>

      {/* wheels — spokes spin only while rushing */}
      {[44, 76].map((cx) => (
        <g key={cx} transform={`translate(${cx} 101)`}>
          <motion.g variants={v.wheel}>
            <circle r="8.5" fill={BODY_DARK} stroke={OUTLINE} strokeWidth="2" />
            <line x1="-5.5" y1="0" x2="5.5" y2="0" stroke={OUTLINE} strokeWidth="1.8" />
            <line x1="0" y1="-5.5" x2="0" y2="5.5" stroke={OUTLINE} strokeWidth="1.8" />
          </motion.g>
          <circle r="2.4" fill={accent} />
        </g>
      ))}

      {/* torso */}
      <rect x="32" y="56" width="56" height="40" rx="14" fill={BODY} stroke={OUTLINE} strokeWidth="2" />
      <rect x="44" y="68" width="32" height="16" rx="5" fill={BODY_DARK} />
      <circle cx="52" cy="76" r="2.4" fill={accent} />
      <circle cx="60" cy="76" r="2.4" fill={accent} opacity="0.55" />
      <circle cx="68" cy="76" r="2.4" fill={accent} opacity="0.3" />

      {/* head dome */}
      <path
        d="M36 50 v-6 c0 -14 10.5 -23 24 -23 s24 9 24 23 v6 z"
        fill={BODY}
        stroke={OUTLINE}
        strokeWidth="2"
      />

      {/* antenna — shape varies per bot */}
      {variant === "teal" && (
        <g>
          <line x1="60" y1="21" x2="60" y2="12" stroke={OUTLINE} strokeWidth="2" />
          <motion.g variants={v.antennaTip}>
            <circle cx="60" cy="10" r="3" fill={accent} />
          </motion.g>
        </g>
      )}
      {variant === "violet" && (
        <g>
          <polyline
            points="60,21 63.5,15.5 57.5,11"
            fill="none"
            stroke={OUTLINE}
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <motion.g variants={v.antennaTip}>
            <path d="M57.5 5.2 l3.2 3.3 -3.2 3.3 -3.2 -3.3 z" fill={accent} />
          </motion.g>
        </g>
      )}
      {variant === "rose" && (
        <g>
          <path d="M60 21 q7 -5 1.5 -11" fill="none" stroke={OUTLINE} strokeWidth="2" />
          <motion.g variants={v.antennaTip}>
            <circle cx="61" cy="7.5" r="3" fill="none" stroke={accent} strokeWidth="2" />
          </motion.g>
        </g>
      )}

      {/* eyes — outer group scales when caught, inner group blinks */}
      {[face.eyeLX, face.eyeRX].map((x, i) => (
        <g key={i} transform={`translate(${x} 38)`}>
          <motion.g variants={v.eyeScale}>
            <motion.g variants={v.eyeBlink}>
              <circle r={face.eyeR} fill={accent} />
              <circle r={face.eyeR * 0.4} cx={face.eyeR * 0.25} cy={-face.eyeR * 0.25} fill="#eafffa" opacity="0.85" />
            </motion.g>
          </motion.g>
        </g>
      ))}

      {/* mouth — flat when rushing/idle, small "o" when caught */}
      <motion.line
        variants={v.mouthFlat}
        x1="55"
        y1="47"
        x2="65"
        y2="47"
        stroke={OUTLINE}
        strokeWidth="2"
        strokeLinecap="round"
      />
      <motion.circle variants={v.mouthO} cx="60" cy="47" r="2.6" fill={BODY_DARK} stroke={OUTLINE} strokeWidth="1.5" />
    </motion.svg>
  );
}
