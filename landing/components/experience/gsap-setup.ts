import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useGSAP } from "@gsap/react";

// Register once, browser-only. Scene modules import from here so every
// consumer shares one configured GSAP instance. Client components still
// execute their module scope during prerender, hence the window guard.
if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger, SplitText, useGSAP);
  // Mobile URL-bar show/hide fires resize; re-measuring mid-scroll causes
  // pin jumps. Dimension-changing rotations still refresh.
  ScrollTrigger.config({ ignoreMobileResize: true });
}

/**
 * The three motion contexts. SSR markup is always the final state; `full`
 * and `compact` set initial states pre-paint inside useGSAP, and `static`
 * (reduced motion) creates nothing — the document reads top-to-bottom.
 */
export const MQ = {
  full: "(min-width: 800px) and (prefers-reduced-motion: no-preference)",
  compact: "(max-width: 799.98px) and (prefers-reduced-motion: no-preference)",
  static: "(prefers-reduced-motion: reduce)",
} as const;

export { gsap, ScrollTrigger, SplitText, useGSAP };
