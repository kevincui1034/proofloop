"use client";

import { useRef } from "react";
import { COMMAND, JOURNEY } from "@/lib/content";
import { gsap, MQ, useGSAP } from "@/components/experience/gsap-setup";
import { uniforms } from "@/components/experience/uniform-store";

const FRAGMENT_STYLES = {
  big: "text-4xl sm:text-6xl md:text-7xl font-semibold tracking-[-0.02em] text-ink",
  small: "font-mono text-base sm:text-xl text-faint",
  thesis:
    "text-4xl sm:text-6xl md:text-7xl font-semibold tracking-[-0.02em] text-amber-ink",
} as const;

/**
 * S2 — the deploy journey. The command chip travels a dotted path while the
 * problem statement scrolls through the beam, fragment by fragment, ending
 * on the thesis — the one allowed exclusivity claim, held longest in the
 * light. Desktop pins and scrubs the track through the viewport; the beam
 * brightens whatever passes its center. Mobile keeps the natural stack with
 * per-line reveals; the static document is the same stack, fully visible.
 */
export default function S2Journey() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;
      const frags = Array.from(
        root.querySelectorAll<HTMLElement>('[data-s2="fragment"]')
      );

      const mm = gsap.matchMedia();

      // ——— desktop: the pinned journey ———
      mm.add(MQ.full, () => {
        const frame = q('[data-s2="frame"]');
        const track = q('[data-s2="track"]');
        const chipline = q('[data-s2="chipline"]');
        const chip = q('[data-s2="chip"]');
        const comets = root.querySelectorAll<HTMLElement>('[data-s2="comet"]');
        const thesis = frags[frags.length - 1];

        gsap.set(frame, {
          height: "100svh",
          paddingTop: 0,
          paddingBottom: 0,
          justifyContent: "center",
          overflow: "clip",
        });
        gsap.set(chipline, { display: "block" });
        gsap.set(frags, { autoAlpha: 0.13 });

        const centerY = (el: HTMLElement) =>
          frame.clientHeight / 2 - (el.offsetTop + el.offsetHeight / 2);

        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: root,
            start: "top top",
            end: "+=150%",
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
            onUpdate() {
              // beam-exact emphasis: brightness from real distance to center
              const mid = frame.clientHeight / 2;
              for (const f of frags) {
                const r = f.getBoundingClientRect();
                const d = Math.abs(r.top + r.height / 2 - mid);
                const a = Math.max(
                  0.13,
                  1 - Math.pow(d / (frame.clientHeight * 0.3), 1.6)
                );
                gsap.set(f, { autoAlpha: a });
              }
            },
          },
        });

        tl.fromTo(
          track,
          { y: () => centerY(frags[0]) },
          { y: () => centerY(thesis), duration: 100 },
          0
        )
          // the thesis takes the bench: a slight rise as it settles center
          .fromTo(
            thesis,
            { scale: 0.985 },
            { scale: 1.05, duration: 14, ease: "power1.out" },
            86
          )
          // the command crosses the whole scene, left to right — travel is
          // measured inside the max-w container, not the full-bleed overlay
          .fromTo(
            chip,
            { x: 0 },
            {
              x: () =>
                chip.parentElement!.clientWidth - chip.clientWidth - 40,
              duration: 100,
            },
            0
          )
          // the beam leans after the traveling command
          .fromTo(uniforms, { beamX: 0.3 }, { beamX: 0.72, duration: 100 }, 0);

        // rogue comets race past the command at intervals
        comets.forEach((comet, i) => {
          tl.fromTo(
            comet,
            { x: "-10vw", autoAlpha: 0 },
            {
              keyframes: [
                { x: "30vw", autoAlpha: 1, duration: 8 },
                { x: "112vw", autoAlpha: 1, duration: 16 },
                { autoAlpha: 0, duration: 0.5 },
              ],
              ease: "none",
            },
            8 + i * 26
          );
        });

        return () => {
          gsap.set(frags, { clearProps: "all" });
        };
      });

      // ——— mobile: natural stack, per-line reveals ———
      mm.add(MQ.compact, () => {
        for (const f of frags) {
          gsap.fromTo(
            f,
            { autoAlpha: 0.13, y: 22 },
            {
              autoAlpha: 1,
              y: 0,
              ease: "none",
              scrollTrigger: {
                trigger: f,
                start: "top 82%",
                end: "top 45%",
                scrub: true,
              },
            }
          );
        }
      });

    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s2" className="relative z-10">
      {/* traveling command chip + dotted path (decorative, desktop only) */}
      <div
        data-s2="chipline"
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-1/2 z-20 hidden"
      >
        <div className="relative mx-auto max-w-6xl px-5">
          <div className="absolute inset-x-5 top-1/2 border-t border-dashed border-line-2/60" />
          <span
            data-s2="chip"
            className="relative inline-block rounded-md border border-amber/50 bg-surface-2 px-3 py-1.5 font-mono text-xs text-amber-ink shadow-[0_0_24px_-6px_var(--amber)]"
          >
            $ {COMMAND}
          </span>
          {/* rogue-agent comets — all frantic motion belongs to them */}
          <span data-s2="comet" className="absolute -top-7 left-0 text-xl text-bot-teal">
            ◇
          </span>
          <span data-s2="comet" className="absolute top-9 left-0 text-xl text-bot-violet">
            △
          </span>
          <span data-s2="comet" className="absolute top-1.5 left-0 text-lg text-bot-rose">
            ○
          </span>
        </div>
      </div>

      <div
        data-s2="frame"
        className="mx-auto flex max-w-5xl flex-col px-5 py-28 sm:py-36"
      >
        <div data-s2="track" className="flex flex-col gap-14 text-center sm:gap-24">
          {JOURNEY.map((f) => (
            <p
              key={f.text}
              data-s2="fragment"
              data-kind={f.kind}
              className={FRAGMENT_STYLES[f.kind]}
            >
              {f.text}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}
