"use client";

import { useRef } from "react";
import { MEMORY_RECORDS, RECALL_QUOTE } from "@/lib/content";
import { gsap, MQ, useGSAP } from "@/components/experience/gsap-setup";

// Deterministic card tilts — index cards filed by hand, never randomized.
const TILTS = [-1.5, 1, -0.5, 1.25, -1];

const DOT = {
  red: "bg-verdict-red",
  green: "bg-verdict-green",
  amber: "bg-amber",
} as const;

/**
 * S6 — memory. Records file onto the shelf one by one; the amber thread
 * arcs from the recurrence (chk_003) back to the original diagnosis
 * (chk_001); the verdict lands as a stat. Desktop pins the shelf while the
 * filing happens; mobile reveals in flow.
 */
export default function S6Memory() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;
      const cards = Array.from(
        root.querySelectorAll<HTMLElement>('[data-s6="card"]')
      );
      const thread = root.querySelector<SVGGeometryElement>(
        '[data-s6="thread"]'
      )!;

      const setup = () => {
        gsap.set(cards, {
          autoAlpha: 0,
          y: 64,
          rotate: (i) => TILTS[i] * 4,
        });
        // pathLength=1 on the SVG normalizes dash math — a stretched
        // (preserveAspectRatio-less) viewBox would otherwise render the
        // draw as broken segments
        gsap.set(thread, { strokeDasharray: 1, strokeDashoffset: 1 });
        gsap.set([q('[data-s6="recall-label"]'), q('[data-s6="thread-tip"]')], {
          autoAlpha: 0,
        });
        gsap.set(q('[data-s6="stat"]'), { autoAlpha: 0, scale: 0.94 });
        gsap.set(q('[data-s6="quote"]'), { autoAlpha: 0 });
      };

      const file = (tl: gsap.core.Timeline, snap: boolean) => {
        // d = duration scale: pinned-scrub timelines use big unitless beats,
        // in-flow timelines use seconds
        const d = snap ? 1 : 6;
        cards.forEach((card, i) => {
          tl.to(
            card,
            {
              autoAlpha: 1,
              y: 0,
              rotate: TILTS[i],
              duration: 0.55 * d,
              ease: "power3.out",
            },
            0.2 * d * i + (snap ? 0 : 4)
          );
        });
        // the thread waits for the last card to finish filing
        const after =
          (snap ? 0 : 4) + 0.2 * d * (cards.length - 1) + 0.55 * d;
        tl.to(q('[data-s6="recall-label"]'), { autoAlpha: 1, duration: 0.3 * d }, after)
          .to(
            thread,
            { strokeDashoffset: 0, duration: 0.9 * d, ease: "power1.inOut" },
            after + 0.1 * d
          )
          .to(q('[data-s6="thread-tip"]'), { autoAlpha: 1, duration: 0.2 * d }, after + d)
          .to(
            q('[data-s6="stat"]'),
            { autoAlpha: 1, scale: 1, duration: 0.4 * d, ease: "power3.out" },
            after + 1.1 * d
          )
          .to(q('[data-s6="quote"]'), { autoAlpha: 1, duration: 0.4 * d }, after + 1.4 * d);
      };

      const mm = gsap.matchMedia();

      mm.add(MQ.full, () => {
        setup();
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: root,
            start: "top top",
            end: "+=125%",
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        });
        file(tl, false);
      });

      mm.add(MQ.compact, () => {
        setup();
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: q('[data-s6="shelf"]'),
            start: "top 75%",
          },
        });
        file(tl, true);
      });
    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s6" className="relative z-10">
      <div className="mx-auto flex min-h-svh max-w-6xl flex-col justify-center px-5 py-28 sm:py-36">
        <h2 className="max-w-[14ch] text-balance font-serif text-5xl leading-[1.05] text-ink sm:text-6xl">
          The gate remembers.
        </h2>
        <p className="mt-6 max-w-[56ch] leading-relaxed">
          Every diagnosed failure is filed — the failure class, the evidence,
          the judgment. When the same mistake comes back, there is no
          re-deliberation and no model call.
        </p>

        {/* the shelf */}
        <div data-s6="shelf" className="relative mx-auto mt-20 w-full max-w-3xl">
          <p
            data-s6="recall-label"
            className="mb-1 text-center font-mono text-[11px] text-amber-ink"
          >
            recalled_from → chk_001
          </p>
          <div className="relative mx-[9%] h-10" aria-hidden="true">
            {/* near-real aspect + uniform-ish stretch; no non-scaling-stroke —
                it forces screen-space dashes and breaks the pathLength draw */}
            <svg
              viewBox="0 0 640 40"
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full overflow-visible"
            >
              <path
                data-s6="thread"
                d="M627 39 C 512 4, 128 4, 13 36"
                pathLength={1}
                fill="none"
                stroke="var(--amber-ink)"
                strokeWidth="1.5"
                opacity="0.9"
              />
            </svg>
            <span
              data-s6="thread-tip"
              className="absolute -bottom-1 left-0 -translate-x-1/2 text-[13px] leading-none text-amber-ink"
            >
              ▾
            </span>
          </div>

          <div className="flex items-stretch gap-2 sm:gap-3">
            {MEMORY_RECORDS.map((r, i) => (
              <div
                key={r.id}
                data-s6="card"
                style={{ rotate: `${TILTS[i]}deg` }}
                className={`min-w-0 flex-1 rounded-md border px-2 py-2.5 sm:px-3 ${
                  r.newest
                    ? "border-amber-deep/70 bg-amber/10 shadow-[0_10px_24px_-14px_rgba(138,98,16,0.6)]"
                    : "border-line-2 bg-surface-2 shadow-[0_10px_24px_-16px_rgba(29,35,46,0.5)]"
                } ${i === 2 || i === 3 ? "hidden min-[480px]:block" : ""}`}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[r.tone]}`}
                  />
                  <span
                    className={`truncate font-mono text-[11px] font-semibold ${
                      r.newest ? "text-amber-ink" : "text-ink"
                    }`}
                  >
                    {r.id}
                  </span>
                </div>
                <p className="mt-1 truncate font-mono text-[10px] text-faint">
                  {r.cls}
                </p>
                <p
                  className={`mt-0.5 truncate font-mono text-[9px] uppercase tracking-wider ${
                    r.tone === "green" ? "text-verdict-green" : "text-faint"
                  }`}
                >
                  {r.status}
                </p>
              </div>
            ))}
          </div>
          {/* shelf edge */}
          <div className="mt-1.5 h-2 rounded-sm border-t border-line-2 bg-surface-3 shadow-[0_10px_24px_-14px_rgba(29,35,46,0.45)]" />
        </div>

        <p
          data-s6="stat"
          className="mt-20 text-center font-serif text-4xl leading-[1.1] text-ink sm:text-6xl"
        >
          Blocked in <span className="italic text-amber-ink">64&nbsp;ms</span>.
        </p>
        <p
          data-s6="quote"
          className="mx-auto mt-4 max-w-[52ch] text-center font-mono text-xs leading-relaxed text-faint sm:text-sm"
        >
          “{RECALL_QUOTE}”
        </p>
      </div>
    </section>
  );
}
