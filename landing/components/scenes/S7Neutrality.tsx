"use client";

import { useRef } from "react";
import { gsap, SplitText, useGSAP } from "@/components/experience/gsap-setup";

const MOTION_OK = "(prefers-reduced-motion: no-preference)";

/**
 * S7 — the neutral bench. Three agent glyphs travel their lanes into the
 * court seal (scrubbed), then the disambiguation line is entered into the
 * record, line by masked line.
 */
export default function S7Neutrality() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;
      const lanes = Array.from(
        root.querySelectorAll<SVGGeometryElement>('[data-s7="lane"]')
      );
      const glyphs = Array.from(
        root.querySelectorAll<SVGTextElement>('[data-s7="glyph"]')
      );

      const mm = gsap.matchMedia();
      mm.add(MOTION_OK, () => {
        const viz = q('[data-s7="viz"]');
        const seal = root.querySelector<SVGGElement>('[data-s7="seal"]')!;

        gsap.set(lanes, { autoAlpha: 0.25 });
        gsap.set(seal, {
          autoAlpha: 0,
          scale: 0.92,
          transformOrigin: "50% 50%",
        });

        // the glyphs converge along their lanes as the reader scrolls
        const progress = { t: 0 };
        const starts = glyphs.map((g) => ({
          x: Number(g.getAttribute("x")),
          y: Number(g.getAttribute("y")),
        }));
        gsap.to(progress, {
          t: 1,
          ease: "none",
          scrollTrigger: {
            trigger: viz,
            start: "top 80%",
            end: "top 28%",
            scrub: 0.6,
          },
          onUpdate() {
            glyphs.forEach((g, i) => {
              const path = lanes[i];
              const pt = path.getPointAtLength(
                progress.t * path.getTotalLength()
              );
              gsap.set(g, { x: pt.x - starts[i].x, y: pt.y - starts[i].y + 5 });
            });
            gsap.set(lanes, { autoAlpha: 0.25 + progress.t * 0.55 });
          },
        });

        // the seal presses once the glyphs arrive
        gsap.to(seal, {
          autoAlpha: 1,
          scale: 1,
          duration: 0.5,
          ease: "power3.out",
          scrollTrigger: { trigger: viz, start: "top 34%" },
        });

        // the pull-quote is entered into the record
        const quote = q('[data-s7="quotetext"]');
        gsap.set(quote, { textWrap: "wrap" });
        const split = SplitText.create(quote, { type: "lines", mask: "lines" });
        gsap.from(split.lines, {
          yPercent: 115,
          duration: 0.85,
          stagger: 0.13,
          ease: "power4.out",
          scrollTrigger: { trigger: q('[data-s7="quote"]'), start: "top 72%" },
          onComplete: () => split.revert(),
        });
      });
    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s7" className="relative z-10 px-5 py-28 sm:py-36">
      <div className="mx-auto max-w-6xl">
        <h2 className="max-w-[18ch] text-balance font-serif text-5xl leading-[1.05] text-ink sm:text-6xl">
          It doesn&apos;t care which agent wrote it.
        </h2>
        <p className="mt-6 max-w-[56ch] leading-relaxed">
          Same gate, same checks, same memory — whether the code came from
          Claude Code, Codex, or Cursor. A neutral judge is something no agent
          vendor can be.
        </p>

        {/* converging lanes → the seal */}
        <div data-s7="viz" className="mx-auto mt-16 max-w-2xl">
          <svg viewBox="0 0 600 220" fill="none" aria-hidden="true" className="block w-full">
            <defs>
              <path
                id="seal-arc"
                d="M470 110 m-33 0 a33 33 0 1 1 66 0 a33 33 0 1 1 -66 0"
              />
            </defs>
            <path
              data-s7="lane"
              d="M40 40 C 220 40, 320 96, 416 106"
              stroke="var(--bot-teal)"
              strokeWidth="1.5"
              strokeDasharray="3 6"
            />
            <path
              data-s7="lane"
              d="M40 110 H 416"
              stroke="var(--bot-violet)"
              strokeWidth="1.5"
              strokeDasharray="3 6"
            />
            <path
              data-s7="lane"
              d="M40 180 C 220 180, 320 124, 416 114"
              stroke="var(--bot-rose)"
              strokeWidth="1.5"
              strokeDasharray="3 6"
            />
            <text data-s7="glyph" x="28" y="45" fill="var(--bot-teal)" fontSize="18" textAnchor="middle">◇</text>
            <text data-s7="glyph" x="28" y="116" fill="var(--bot-violet)" fontSize="18" textAnchor="middle">△</text>
            <text data-s7="glyph" x="28" y="186" fill="var(--bot-rose)" fontSize="16" textAnchor="middle">○</text>

            {/* the embossed seal */}
            <g data-s7="seal">
              <circle cx="470" cy="110" r="52" stroke="var(--ink)" strokeWidth="2" />
              <circle cx="470" cy="110" r="46" stroke="var(--ink)" strokeWidth="0.75" />
              <text
                fontSize="8.5"
                letterSpacing="2.6"
                fill="var(--faint)"
                fontFamily="var(--font-geist-mono)"
              >
                <textPath href="#seal-arc" startOffset="2">
                  PROOFLOOP · NEUTRAL BENCH · EST. 2026 ·
                </textPath>
              </text>
              {/* gate glyph, centered */}
              <g transform="translate(454 96) scale(1.6)" fill="var(--amber-deep)">
                <rect x="2" y="3" width="16" height="2.4" rx="1.2" />
                <rect x="3.6" y="7.4" width="2.8" height="9.6" rx="1.4" />
                <rect x="13.6" y="7.4" width="2.8" height="9.6" rx="1.4" />
                <circle cx="10" cy="10.6" r="2" />
              </g>
            </g>
          </svg>
          <p className="mt-2 text-center font-mono text-xs uppercase tracking-[0.24em] text-faint">
            Claude Code · Codex · Cursor — same bench
          </p>
        </div>

        {/* the record's pull-quote */}
        <figure
          data-s7="quote"
          className="mx-auto mt-24 max-w-4xl border-y-[6px] border-double border-ink/60 py-12 sm:py-16"
        >
          <blockquote
            data-s7="quotetext"
            className="text-balance text-center font-serif text-3xl italic leading-[1.25] text-ink sm:text-5xl"
          >
            “Your guardrails stop the{" "}
            <span className="underline decoration-verdict-red decoration-[3px] underline-offset-[6px]">
              dangerous
            </span>{" "}
            command. Proofloop stops the{" "}
            <span className="underline decoration-amber-deep decoration-[3px] underline-offset-[6px]">
              broken
            </span>{" "}
            one.”
          </blockquote>
        </figure>
      </div>
    </section>
  );
}
