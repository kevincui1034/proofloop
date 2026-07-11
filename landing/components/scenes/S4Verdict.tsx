"use client";

import { useRef } from "react";
import { COMMAND, GATE_CHECKS } from "@/lib/content";
import Stamp from "@/components/ui/Stamp";
import { gsap, MQ, useGSAP } from "@/components/experience/gsap-setup";
import { uniforms } from "@/components/experience/uniform-store";

/**
 * S4 — the gate and the verdict inversion. The centerpiece: the command
 * decelerates before the gate, four checks clack in, the BLOCKED stamp
 * slams (time-based, so it snaps at any scroll speed), and a paper flood
 * swallows the viewport — flipping the world's tokens behind full cover.
 * The static document renders the same story as a flat composition.
 */
export default function S4Verdict() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;
      const qa = (sel: string) => root.querySelectorAll<HTMLElement>(sel);

      const mm = gsap.matchMedia();
      mm.add(
        { full: MQ.full, compact: MQ.compact },
        (ctx) => {
          const compact = !!ctx.conditions?.compact;
          const stage = q('[data-s4="stage"]');
          const shake = q('[data-s4="shake"]');
          const chip = q('[data-s4="chip"]');
          const comets = qa('[data-s4="comet"]');
          const ledger = q('[data-s4="ledger"]');
          const checks = qa('[data-s4="check"]');
          const stampWrap = q('[data-s4="stampwrap"]');
          const stamp = stampWrap.firstElementChild as HTMLElement;
          const shock = q('[data-s4="shockwave"]');
          const flood = q('[data-s4="flood"]');
          const gatePaths = root.querySelectorAll<SVGGeometryElement>(
            '[data-s4="gatepath"]'
          );

          // ——— initial states (pre-paint; SSR markup is the final state) ———
          gatePaths.forEach((p) => {
            const len = p.getTotalLength();
            gsap.set(p, { strokeDasharray: len, strokeDashoffset: len });
          });
          gsap.set(q('[data-s4="title"]'), { autoAlpha: 0, y: 14 });
          // xPercent owns the CSS -translate-x-1/2 centering so the x tween
          // can't clobber it; same pattern for the centered overlays below
          gsap.set(chip, { xPercent: -50, x: compact ? "-44vw" : "-58vw" });
          gsap.set(q('[data-s4="intercept"]'), { xPercent: -50, x: 0 });
          gsap.set(shock, { xPercent: -50, yPercent: -50 });
          gsap.set(flood, { xPercent: -50, yPercent: -50 });
          gsap.set(comets, { x: (i) => `${-66 - i * 10}vw` });
          gsap.set([q('[data-s4="intercept"]'), q('[data-s4="decide"]')], {
            autoAlpha: 0,
          });
          let slammed = false;
          let isPaper = false;
          gsap.set(ledger, { autoAlpha: 0, y: 28 });
          gsap.set(checks, { autoAlpha: 0, y: 10 });
          // restage the stamp as a viewport overlay, hidden until the slam
          gsap.set(stampWrap, {
            position: "absolute",
            inset: 0,
            margin: 0,
            display: "grid",
            placeItems: "center",
            zIndex: 20,
            autoAlpha: 0,
          });

          // ——— the slam: time-based so it hits hard at any scroll speed ———
          const amp = compact ? 4 : 8;
          // NB: no .set()/immediateRender in this paused timeline — zero-
          // duration renders would leak the slam's start states to page load
          const slam = gsap
            .timeline({ paused: true })
            .to(stampWrap, { autoAlpha: 1, duration: 0.02 }, 0)
            .fromTo(
              stamp,
              { scale: 4, rotation: 4, autoAlpha: 0 },
              {
                scale: 1,
                rotation: -6,
                autoAlpha: 1,
                duration: 0.45,
                ease: "power4.in",
                immediateRender: false,
              },
              0
            )
            .fromTo(
              shock,
              { scale: 0.4, autoAlpha: 0.9 },
              {
                scale: 2.6,
                autoAlpha: 0,
                duration: 0.65,
                ease: "power2.out",
                immediateRender: false,
              },
              0.45
            )
            .to(
              shake,
              {
                keyframes: [
                  { x: -amp, y: amp * 0.5, duration: 0.07 },
                  { x: amp * 0.75, y: -amp * 0.6, duration: 0.09 },
                  { x: -amp * 0.4, y: amp * 0.25, duration: 0.11 },
                  { x: 0, y: 0, duration: 0.13 },
                ],
              },
              0.45
            )
            .to(uniforms, { die: 1, duration: 0.35, ease: "power2.in" }, 0.4);

          // ——— the scrubbed master timeline ———
          const tl = gsap.timeline({
            defaults: { ease: "none" },
            scrollTrigger: {
              trigger: stage,
              start: "top top",
              end: compact ? "+=180%" : "+=250%",
              pin: true,
              scrub: 0.7,
              anticipatePin: 1,
              invalidateOnRefresh: true,
              onUpdate(self) {
                const p = self.progress;
                // discrete threshold crossings — robust against scrub jumps,
                // refreshes, and loading mid-page
                if (!slammed && p >= 0.55) {
                  slammed = true;
                  slam.play();
                } else if (slammed && p < 0.55) {
                  slammed = false;
                  slam.reverse();
                }
                const paper = p >= 0.88;
                if (paper !== isPaper) {
                  isPaper = paper;
                  document.documentElement.dataset.world = paper
                    ? "paper"
                    : "night";
                }
                // interrogation spotlight narrows as the checks land
                if (!slammed) uniforms.beam = 0.9 - p * 0.45;
              },
            },
          });

          // 0–18 — approach: the command decelerates before the gate
          tl.to(q('[data-s4="title"]'), { autoAlpha: 1, y: 0, duration: 6 }, 0)
            .to(gatePaths, { strokeDashoffset: 0, duration: 18, stagger: 1.5 }, 0)
            .to(chip, { x: 0, duration: 16, ease: "power3.out" }, 1)
            .to(
              comets,
              { x: 0, duration: 14, ease: "back.out(1.3)", stagger: 1.6 },
              3
            )
            .to(q('[data-s4="intercept"]'), { autoAlpha: 1, duration: 3 }, 15)
            // 18–45 — the checks clack in, one verdict at a time
            .to(ledger, { autoAlpha: 1, y: 0, duration: 4 }, 17);
          checks.forEach((check, i) => {
            tl.to(
              check,
              { autoAlpha: 1, y: 0, duration: 1.6, ease: "power4.out" },
              22 + i * 6
            );
          });
          tl.to(q('[data-s4="decide"]'), { autoAlpha: 1, duration: 4 }, 42);

          // 45–55 — the held breath: a deliberate dead zone. Nothing maps
          // to scroll; dust settles. (The slam fires at 0.55 via onUpdate.)

          // 58–82 — the flood: the reader drives the inversion
          tl.fromTo(
            flood,
            { scale: 0 },
            { scale: 1.15, duration: 24, ease: "power1.in" },
            58
          )
            // the night dims inside the flood
            .to(shake, { autoAlpha: 0, duration: 12 }, 70)
            // pad to duration 100 so timeline positions equal raw-progress
            // percent — the 0.55 slam and 0.88 flip thresholds in onUpdate
            // depend on this alignment (flood must be full BEFORE the flip)
            .to({}, { duration: 18 }, 82);
          // 88 — world flip (onUpdate threshold, behind full cover)
          // 88–100 — a quiet beat of blank paper before the record opens.

          return () => {
            // leaving this context (resize into `static`) must never strand
            // the site in the wrong world
            document.documentElement.dataset.world = "night";
            uniforms.die = 0;
            uniforms.beam = 0.9;
          };
        }
      );
    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s4" className="relative z-10">
      <div data-s4="stage" className="relative min-h-svh overflow-clip">
        <div
          data-s4="shake"
          className="relative flex min-h-svh w-full flex-col items-center justify-center px-5 py-28"
        >
          <h2
            data-s4="title"
            className="text-balance text-center font-mono text-sm uppercase tracking-[0.34em] text-amber-ink sm:text-base"
          >
            The gate cannot be talked past.
          </h2>

          {/* the gate — thin amber strokes, line-drawn on scrub */}
          <div className="relative mt-10 w-full max-w-xl">
            <svg
              data-s4="gate"
              viewBox="0 0 400 260"
              fill="none"
              stroke="var(--amber)"
              strokeWidth="3"
              strokeLinecap="round"
              aria-hidden="true"
              className="mx-auto block w-full max-w-[400px]"
            >
              <path data-s4="gatepath" d="M24 48 H376" />
              <path data-s4="gatepath" d="M64 48 V244" />
              <path data-s4="gatepath" d="M336 48 V244" />
              <path data-s4="gatepath" d="M64 168 H336" />
              {/* scales badge on the lintel */}
              <circle data-s4="gatepath" cx="200" cy="100" r="26" />
              <path
                data-s4="gatepath"
                d="M200 84 V112 M186 92 H214 M186 92 l-7 12 h14 z M214 92 l-7 12 h14 z"
                strokeWidth="2.2"
              />
            </svg>

            {/* the command, stopped at the barrier */}
            <div
              data-s4="chip"
              className="absolute left-1/2 top-[62%] -translate-x-1/2 rounded-md border border-amber/50 bg-surface-2 px-3 py-1.5 font-mono text-[11px] text-amber-ink shadow-[0_0_24px_-6px_var(--amber)] sm:text-xs"
            >
              $ {COMMAND}
            </div>
            <p
              data-s4="intercept"
              className="absolute left-1/2 top-[80%] -translate-x-1/2 font-mono text-[10px] uppercase tracking-[0.24em] text-faint"
            >
              intercepted before execution
            </p>

            {/* rogue-agent comets, skidding to a halt behind the command */}
            <span
              data-s4="comet"
              aria-hidden="true"
              className="absolute left-[8%] top-[58%] text-xl text-bot-teal"
            >
              ◇
            </span>
            <span
              data-s4="comet"
              aria-hidden="true"
              className="absolute left-[16%] top-[70%] text-xl text-bot-violet"
            >
              △
            </span>
            <span
              data-s4="comet"
              aria-hidden="true"
              className="absolute left-[4%] top-[68%] text-lg text-bot-rose"
            >
              ○
            </span>
          </div>

          {/* the check ledger — deterministic checks decide */}
          <ul
            data-s4="ledger"
            className="mt-12 w-full max-w-md rounded-lg border border-line bg-surface-2/80 p-5 font-mono text-xs sm:text-sm"
          >
            {GATE_CHECKS.map((c) => (
              <li
                key={c.name}
                data-s4="check"
                className="flex items-baseline justify-between gap-3 border-b border-dashed border-line-2 py-2 last:border-0"
              >
                <span className="text-body">{c.name}</span>
                <span
                  className={
                    c.pass
                      ? "font-semibold text-verdict-green"
                      : "font-semibold text-verdict-red"
                  }
                >
                  {c.pass ? "✓" : "✗"} {c.verdict}
                </span>
              </li>
            ))}
          </ul>
          <p
            data-s4="decide"
            className="mt-5 max-w-[44ch] text-center text-sm leading-relaxed"
          >
            Deterministic checks decide. The model never votes — it only
            explains.
          </p>

          {/* the slam — full motion re-stages this as a viewport overlay */}
          <div data-s4="stampwrap" className="mt-12">
            <Stamp
              verdict="blocked"
              text="Deploy blocked"
              size="xl"
              className="-rotate-6"
            />
          </div>

          {/* shockwave ring (full motion only; centered via GSAP xPercent) */}
          <div
            data-s4="shockwave"
            aria-hidden="true"
            className="pointer-events-none absolute left-1/2 top-1/2 h-40 w-40 rounded-full border-2 border-verdict-red-deep opacity-0"
          />
        </div>

        {/* THE FLOOD — the paper world arriving. Literal paper color: it must
            match [data-world="paper"] --surface exactly so the seam vanishes. */}
        <div
          data-s4="flood"
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 top-1/2 z-30 h-[160vmax] w-[160vmax] scale-0 rounded-full bg-[#f2edde]"
        />
      </div>
    </section>
  );
}
