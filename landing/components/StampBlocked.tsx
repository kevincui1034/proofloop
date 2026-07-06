"use client";

import { motion, type Variants } from "motion/react";
import { HEAVY_SPRING, VIEWPORT, useReducedMotionSafe } from "./characters/motion-presets";

type StampProps = {
  verdict?: "blocked" | "allowed";
  /** Controlled visibility. Omit to trigger once on scroll into view. */
  show?: boolean;
  size?: "md" | "lg";
  className?: string;
};

/**
 * Rubber-stamp verdict burst — red BLOCKED by default, green ALLOWED variant.
 * Heavy spring from scale 3 → 1, always tilted -12°.
 */
export default function StampBlocked({
  verdict = "blocked",
  show,
  size = "md",
  className = "",
}: StampProps) {
  // Hydration-safe: false during SSR + first client render, real value after mount.
  const rm = useReducedMotionSafe();
  const label = verdict === "blocked" ? "BLOCKED" : "ALLOWED";
  const color = verdict === "blocked" ? "text-verdict-red" : "text-verdict-green";
  const glow =
    verdict === "blocked"
      ? "drop-shadow(0 0 22px rgba(229,72,77,0.4))"
      : "drop-shadow(0 0 22px rgba(74,222,128,0.35))";
  const text =
    size === "lg"
      ? "text-4xl sm:text-6xl px-6 py-2 sm:px-9 sm:py-3"
      : "text-2xl sm:text-3xl px-4 py-1.5 sm:px-6 sm:py-2";

  // Hidden target is constant regardless of rm (identical SSR markup);
  // reduced motion snaps straight to the settled stamp instead of springing.
  const stampV: Variants = {
    hidden: { scale: 3, opacity: 0, rotate: -12 },
    visible: {
      scale: 1,
      opacity: 1,
      rotate: -12,
      transition: rm ? { duration: 0 } : HEAVY_SPRING,
    },
  };

  const ringV: Variants = {
    hidden: { opacity: 0, scale: 0.85 },
    visible: rm
      ? { opacity: 0 }
      : {
          opacity: [0, 0.5, 0],
          scale: [0.85, 1.25, 1.45],
          transition: { duration: 0.55, delay: 0.06 },
        },
  };

  const trigger =
    show === undefined
      ? { whileInView: "visible" as const, viewport: VIEWPORT }
      : { animate: show ? ("visible" as const) : ("hidden" as const) };

  return (
    <motion.span
      initial="hidden"
      {...trigger}
      className={`pointer-events-none relative inline-block select-none ${className}`}
    >
      <motion.span variants={ringV} className={`absolute -inset-3 rounded-2xl border-2 ${color} border-current`} />
      <motion.span
        variants={stampV}
        className={`block rounded-[10px] border-[3px] border-current p-[5px] ${color}`}
        style={{ filter: glow, backgroundColor: "rgba(10,14,20,0.55)" }}
      >
        <span
          className={`block rotate-[0.8deg] rounded-[6px] border-2 border-current font-black uppercase leading-none tracking-[0.16em] ${text}`}
        >
          {label}
        </span>
      </motion.span>
    </motion.span>
  );
}
