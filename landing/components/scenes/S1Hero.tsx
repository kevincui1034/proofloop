"use client";

import { useRef } from "react";
import { COMMAND, HERO } from "@/lib/content";
import { GITHUB_URL, GitHubIcon } from "@/components/ui/brand";
import { gsap, MQ, SplitText, useGSAP } from "@/components/experience/gsap-setup";
import { uniforms } from "@/components/experience/uniform-store";

/**
 * S1 — "Night Court". The opening frame: the command that is about to run,
 * and the page's only h1. A time-based entrance plays on load; the pinned
 * scrub then dissolves the frame while the command detaches and travels
 * right — the protagonist the next scenes follow.
 */
export default function S1Hero() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;

      const mm = gsap.matchMedia();
      mm.add({ full: MQ.full, compact: MQ.compact }, (ctx) => {
        const compact = !!ctx.conditions?.compact;
        const title = q('[data-s1="title"]');
        const cmd = q('[data-s1="cmd"]');
        const cmdText = q('[data-s1="cmdtext"]');
        const sub = q('[data-s1="sub"]');
        const ctas = q('[data-s1="ctas"]');
        const hint = q('[data-s1="hint"]');

        // text-wrap: balance re-flows mid-split; disable before splitting
        gsap.set(title, { textWrap: "wrap" });
        const split = SplitText.create(title, { type: "chars,words" });
        const typed = SplitText.create(cmdText, { type: "chars" });

        gsap.set(split.chars, { yPercent: 60, autoAlpha: 0 });
        gsap.set(typed.chars, { autoAlpha: 0 });
        gsap.set([sub, ctas], { autoAlpha: 0, y: 18 });
        gsap.set(hint, { autoAlpha: 0 });

        // the pin exists from the first frame; its tweens are added after
        // the entrance so scrub start-values capture the settled states
        const scrub = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: root,
            start: "top top",
            end: compact ? "+=80%" : "+=100%",
            pin: true,
            scrub: 0.6,
            invalidateOnRefresh: true,
          },
        });

        gsap
          .timeline({
            delay: 0.15,
            onComplete: () => {
              split.revert();
              typed.revert();
              scrub
                .to(hint, { autoAlpha: 0, duration: 8 }, 0)
                .to(sub, { autoAlpha: 0, y: -24, duration: 22 }, 0)
                .to(ctas, { autoAlpha: 0, y: -24, duration: 22 }, 5)
                .to(title, { yPercent: -22, autoAlpha: 0.2, duration: 70 }, 8)
                // the command detaches and begins its journey right
                .to(
                  cmd,
                  {
                    x: compact ? "16vw" : "24vw",
                    autoAlpha: 0,
                    duration: 55,
                    ease: "power1.in",
                  },
                  30
                )
                // the light shaft leans after it
                .to(uniforms, { beamX: 0.66, duration: 70 }, 20)
                .to({}, { duration: 30 }, 70); // settle room before S2
            },
          })
          .to(typed.chars, {
            autoAlpha: 1,
            duration: 0.02,
            stagger: 0.018,
            ease: "none",
          })
          .to(
            split.chars,
            {
              yPercent: 0,
              autoAlpha: 1,
              duration: 0.9,
              stagger: 0.013,
              ease: "power3.out",
            },
            0.35
          )
          .to(sub, { autoAlpha: 1, y: 0, duration: 0.6, ease: "power2.out" }, 1.1)
          .to(ctas, { autoAlpha: 1, y: 0, duration: 0.6, ease: "power2.out" }, 1.25)
          .to(hint, { autoAlpha: 1, duration: 0.5 }, 1.6);
      });
    },
    { scope: ref }
  );

  return (
    <section
      ref={ref}
      data-scene="s1"
      className="relative z-10 flex min-h-svh flex-col items-center justify-center px-5 pt-[52px] text-center"
    >
      <p data-s1="cmd" className="font-mono text-sm text-amber-ink sm:text-base">
        <span aria-hidden="true" className="text-faint">
          ${" "}
        </span>
        <span data-s1="cmdtext">{COMMAND}</span>
        <span aria-hidden="true" className="cursor-blink ml-0.5">
          ▍
        </span>
      </p>

      <h1
        data-s1="title"
        className="mt-7 max-w-[13ch] text-balance text-[13vw] font-semibold leading-[1.02] tracking-[-0.03em] text-ink sm:text-7xl md:text-8xl"
      >
        {HERO.title}
      </h1>

      <p
        data-s1="sub"
        className="mt-7 max-w-[52ch] text-pretty leading-relaxed sm:text-lg"
      >
        {HERO.sub}
      </p>

      <div
        data-s1="ctas"
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
        <a
          href="#early-access"
          className="rounded-md border border-line-2 px-6 py-3 text-sm font-medium text-ink transition-colors hover:border-amber-ink/60 hover:text-amber-ink"
        >
          Get early access
        </a>
      </div>

      {/* GSAP fades the outer p; the inner span owns the CSS bob so the two
          transform/opacity systems never fight over one element */}
      <p
        data-s1="hint"
        className="absolute bottom-7 left-1/2 -translate-x-1/2 font-mono text-xs text-faint"
      >
        <span className="hint-drop inline-block">{HERO.hint}</span>
      </p>
    </section>
  );
}
