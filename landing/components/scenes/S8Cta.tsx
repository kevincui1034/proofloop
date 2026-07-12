"use client";

import { useRef } from "react";
import { GITHUB_URL, GitHubIcon, GateGlyph } from "@/components/ui/brand";
import EarlyAccessForm from "@/components/ui/EarlyAccessForm";
import Stamp from "@/components/ui/Stamp";
import { gsap, useGSAP } from "@/components/experience/gsap-setup";

const MOTION_OK = "(prefers-reduced-motion: no-preference)";

/**
 * S8 — the verdict you want. The ALLOWED stamp presses once, then
 * conversion. The case closes with the footer's one-line docket.
 */
export default function S8Cta() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;

      const mm = gsap.matchMedia();
      mm.add(MOTION_OK, () => {
        gsap
          .timeline({
            scrollTrigger: { trigger: root, start: "top 68%" },
          })
          .from(q('[data-s8="stamp"]'), {
            autoAlpha: 0,
            scale: 2.1,
            rotation: 8,
            duration: 0.35,
            ease: "power4.in",
          })
          .from(
            [q('[data-s8="title"]'), q('[data-s8="sub"]'), q('[data-s8="actions"]')],
            {
              autoAlpha: 0,
              y: 26,
              duration: 0.7,
              stagger: 0.12,
              ease: "power3.out",
            },
            0.4
          );
      });
    },
    { scope: ref }
  );

  return (
    <section
      ref={ref}
      data-scene="s8"
      id="early-access"
      className="relative z-10 px-5 pt-28 sm:pt-36"
    >
      <div className="mx-auto max-w-6xl text-center">
        <div data-s8="stamp" className="inline-block">
          <Stamp verdict="allowed" size="lg" className="-rotate-3" />
        </div>
        <h2
          data-s8="title"
          className="mx-auto mt-9 max-w-[14ch] text-balance font-serif text-5xl leading-[1.05] text-ink sm:text-7xl"
        >
          Stop shipping broken deploys.
        </h2>
        <p
          data-s8="sub"
          className="mx-auto mt-6 max-w-[46ch] text-pretty leading-relaxed sm:text-lg"
        >
          One command between your agent and production. Open source — and it
          gets smarter with every catch.
        </p>
        <div
          data-s8="actions"
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
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
          <EarlyAccessForm />
        </div>

        <footer className="mt-28 flex flex-col items-center justify-between gap-3 border-t border-line py-7 text-xs text-faint sm:flex-row">
          <span className="flex items-center gap-1.5 font-mono text-[13px] text-body">
            <GateGlyph className="h-3.5 w-3.5" />
            proofjury
          </span>
          <span>Apache-2.0 · correctness, not security · © 2026 Proofjury</span>
        </footer>
      </div>
    </section>
  );
}
