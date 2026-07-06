"use client";

import { motion } from "motion/react";
import { useId, useMemo } from "react";
import { ARM_SPRING, seedFromId, useReducedMotionSafe } from "./motion-presets";

type JudgeProps = {
  raised: boolean;
  /** Fixed pixel width; omit to fill the parent. Height follows the 140:160 aspect. */
  size?: number;
};

const ROBE = "#18202c";
const ROBE_DARK = "#10161f";
const OUTLINE = "#2b3544";
const AMBER = "var(--amber)";
const AMBER_DEEP = "var(--amber-deep)";

/**
 * The Proofloop Judge — a calm, robed gatekeeper. One arm spring-rotates
 * to an open stop-palm when `raised` is true.
 */
export default function JudgeCharacter({ raised, size }: JudgeProps) {
  // Hydration-safe: false during SSR + first client render, real value after
  // mount. When it flips, the blink loop stops and the arm snaps instantly.
  const rm = useReducedMotionSafe();

  const id = useId();
  const blinkTiming = useMemo(() => {
    const seed = seedFromId(id);
    return { repeatDelay: 4 + seed * 2, delay: 1 + ((seed * 5.17) % 1) };
  }, [id]);

  return (
    <motion.svg
      viewBox="0 0 140 160"
      width={size ?? "100%"}
      height={size ? (size * 160) / 140 : "100%"}
      aria-hidden="true"
      focusable="false"
      initial={false}
      style={{ display: "block", overflow: "visible" }}
    >
      {/* ground shadow */}
      <ellipse cx="70" cy="152" rx="34" ry="4.5" fill="#000" opacity="0.35" />

      {/* right arm (viewer's right) — resting */}
      <g transform="translate(94 78)">
        <g transform="rotate(-8)">
          <rect x="-4.5" y="-2" width="9" height="26" rx="4.5" fill={ROBE} stroke={OUTLINE} strokeWidth="1.5" />
          <circle cx="0" cy="26" r="5" fill={ROBE_DARK} stroke={OUTLINE} strokeWidth="1.5" />
        </g>
      </g>

      {/* robe */}
      <path
        d="M70 64 C 52 64 46 77 44 96 C 42 118 40 137 37 150 L103 150 C100 137 98 118 96 96 C94 77 88 64 70 64 Z"
        fill={ROBE}
        stroke={OUTLINE}
        strokeWidth="2"
      />
      {/* amber stole trim */}
      <path d="M61.5 68 C 60.5 95 59.5 122 58.5 147" fill="none" stroke={AMBER} strokeWidth="3" opacity="0.9" />
      <path d="M78.5 68 C 79.5 95 80.5 122 81.5 147" fill="none" stroke={AMBER} strokeWidth="3" opacity="0.9" />
      {/* hem band */}
      <line x1="39" y1="145" x2="101" y2="145" stroke={AMBER_DEEP} strokeWidth="2.5" opacity="0.65" />
      {/* collar */}
      <path d="M59 66 L70 76 L81 66" fill="none" stroke={OUTLINE} strokeWidth="2" strokeLinejoin="round" />

      {/* scales-of-justice badge */}
      <g transform="translate(70 100)" stroke={AMBER} strokeWidth="1.6" strokeLinecap="round" fill="none">
        <line x1="0" y1="-7" x2="0" y2="6" />
        <line x1="-6.5" y1="-4.5" x2="6.5" y2="-4.5" />
        <path d="M-9.5 -2.5 a3 3 0 0 0 6 0" />
        <path d="M3.5 -2.5 a3 3 0 0 0 6 0" />
        <line x1="-3" y1="6" x2="3" y2="6" />
        <circle cx="0" cy="-7.5" r="1.2" fill={AMBER} stroke="none" />
      </g>

      {/* head */}
      <circle cx="70" cy="44" r="16" fill={ROBE} stroke={OUTLINE} strokeWidth="2" />
      {/* magistrate cap */}
      <rect x="53" y="25" width="34" height="7" rx="3.5" fill={ROBE_DARK} stroke={OUTLINE} strokeWidth="1.5" />
      <line x1="56" y1="32.5" x2="84" y2="32.5" stroke={AMBER_DEEP} strokeWidth="1.5" opacity="0.8" />

      {/* calm eyes with slow blink */}
      {[-6.5, 6.5].map((dx) => (
        <g key={dx} transform={`translate(${70 + dx} 44)`}>
          <motion.g
            initial={false}
            animate={
              rm
                ? { scaleY: 1 }
                : { scaleY: [1, 0.1, 1] }
            }
            transition={
              rm
                ? { duration: 0 }
                : { duration: 0.28, repeat: Infinity, ...blinkTiming }
            }
          >
            <circle r="2.1" fill="#dbe4ee" />
          </motion.g>
        </g>
      ))}
      {/* composed mouth */}
      <line x1="66" y1="52.5" x2="74" y2="52.5" stroke="#4a5666" strokeWidth="1.8" strokeLinecap="round" />

      {/* left arm (viewer's left) — the stop arm */}
      <g transform="translate(46 78)">
        <motion.g
          initial={false}
          animate={{ rotate: raised ? 168 : 10 }}
          transition={rm ? { duration: 0 } : ARM_SPRING}
        >
          <rect x="-4.5" y="-2" width="9" height="28" rx="4.5" fill={ROBE} stroke={OUTLINE} strokeWidth="1.5" />
          {/* amber cuff so the sleeve reads against the robe */}
          <line x1="-4" y1="23.5" x2="4" y2="23.5" stroke={AMBER_DEEP} strokeWidth="2" />
          {/* open stop-palm */}
          <g transform="translate(0 28)">
            <rect x="-6" y="-1" width="12" height="13" rx="5" fill={ROBE_DARK} stroke={OUTLINE} strokeWidth="1.5" />
            <line x1="-3.2" y1="6" x2="-3.2" y2="10.5" stroke={OUTLINE} strokeWidth="1.4" strokeLinecap="round" />
            <line x1="0" y1="6.5" x2="0" y2="11.2" stroke={OUTLINE} strokeWidth="1.4" strokeLinecap="round" />
            <line x1="3.2" y1="6" x2="3.2" y2="10.5" stroke={OUTLINE} strokeWidth="1.4" strokeLinecap="round" />
            <circle cx="0" cy="3" r="1.8" fill={AMBER} opacity="0.9" />
          </g>
        </motion.g>
      </g>
    </motion.svg>
  );
}
