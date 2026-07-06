"use client";

import { useSyncExternalStore } from "react";
import { useReducedMotion, type Transition, type Variants } from "motion/react";

/** Shared easing — fast start, long settle. */
export const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

const subscribeNoop = () => () => {};
/** false for the server/hydration render, true once mounted on the client. */
const useMounted = () =>
  useSyncExternalStore(
    subscribeNoop,
    () => true,
    () => false
  );

/**
 * Hydration-safe reduced-motion flag. motion's useReducedMotion() returns
 * null during SSR but the real preference on the first client render, so
 * branching server-visible markup on it directly gives prefers-reduced-motion
 * users a hydration mismatch. This stays false for the hydration render
 * (matching the server HTML), then reports the real preference. Components
 * may briefly render their animated initial state pre-mount; once this flips
 * to true they must settle into final states and stop infinite animations.
 */
export function useReducedMotionSafe(): boolean {
  const prefersRm = useReducedMotion();
  return useMounted() ? (prefersRm ?? false) : false;
}

/**
 * Deterministic per-instance pseudo-random in [0, 1) from a React useId
 * value — keeps character blink cadences varied without impure render calls.
 */
export function seedFromId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 9973;
  return h / 9973;
}

/** Heavy, physical spring — used by stamps landing. */
export const HEAVY_SPRING: Transition = {
  type: "spring",
  stiffness: 380,
  damping: 24,
  mass: 1.1,
};

/** Snappy spring for the Judge's arm. */
export const ARM_SPRING: Transition = {
  type: "spring",
  stiffness: 260,
  damping: 17,
};

/** Enter from offscreen-left with a slight vertical wobble. */
export const rushIn: Variants = {
  hidden: { x: "-60vw", opacity: 0 },
  visible: {
    x: 0,
    y: [0, -6, 3, -4, 0],
    opacity: 1,
    transition: { duration: 0.9, ease: EASE },
  },
};

/** Overshoot + settle when a rushing character halts at the gate. */
export const skidStop: Variants = {
  rushing: { x: 0, rotate: 0 },
  caught: {
    x: [0, 14, -3, 0],
    rotate: [-8, 3, 0],
    transition: { duration: 0.55, ease: EASE },
  },
};

/** Rubber-stamp slam: big → settled, always tilted. */
export const stamp: Variants = {
  hidden: { scale: 3, opacity: 0, rotate: -12 },
  visible: {
    scale: 1,
    opacity: 1,
    rotate: -12,
    transition: HEAVY_SPRING,
  },
};

/** Gentle idle float. */
export const float: Variants = {
  animate: {
    y: [0, -4, 0],
    transition: { duration: 3.2, ease: "easeInOut", repeat: Infinity },
  },
};

/** Standard section entrance. */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
};

/**
 * Reduced-motion twin of fadeUp: identical targets (so a post-mount rm flip
 * never re-resolves values and triggers a spurious animation), instant reveal.
 */
export const fadeUpInstant: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0 } },
};

/** Container that staggers fadeUp children. */
export const staggerParent: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
};

/** Reduced-motion twin of staggerParent — children reveal together. */
export const staggerParentInstant: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0 } },
};

/** Default whileInView viewport settings for sections. */
export const VIEWPORT = { once: true, amount: 0.4 } as const;
export const VIEWPORT_TALL = { once: true, amount: 0.2 } as const;
