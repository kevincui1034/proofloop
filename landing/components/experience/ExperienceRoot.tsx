"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import { gsap, ScrollTrigger } from "./gsap-setup";
import { uniforms } from "./uniform-store";

/**
 * The scroll spine. Renders nothing — it wires Lenis into GSAP's ticker
 * (one rAF for the whole site) and keeps ScrollTrigger in sync. Reduced
 * motion never instantiates Lenis: native scrolling, native anchor jumps.
 */
export default function ExperienceRoot() {
  useEffect(() => {
    const mm = gsap.matchMedia();

    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const lenis = new Lenis({
        autoRaf: false,
        // in-page links (#early-access, #top) scroll through Lenis
        anchors: true,
      });
      const raf = (time: number) => lenis.raf(time * 1000);
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add(raf);
      gsap.ticker.lagSmoothing(0);

      const onPointer = (e: PointerEvent) => {
        uniforms.pointerX = e.clientX / window.innerWidth;
        uniforms.pointerY = e.clientY / window.innerHeight;
      };
      window.addEventListener("pointermove", onPointer, { passive: true });

      return () => {
        window.removeEventListener("pointermove", onPointer);
        gsap.ticker.remove(raf);
        lenis.destroy();
      };
    });

    // Web-font swap after hydration changes trigger positions; re-measure.
    document.fonts?.ready.then(() => ScrollTrigger.refresh());

    return () => mm.revert();
  }, []);

  return null;
}
