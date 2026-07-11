"use client";

import { useRef } from "react";
import { EXHIBITS } from "@/lib/content";
import { gsap, MQ, useGSAP } from "@/components/experience/gsap-setup";
import { uniforms } from "@/components/experience/uniform-store";

// where the spotlight points for each exhibit column (0..1 viewport x)
const BEAM_STOPS = [0.24, 0.5, 0.76];

/**
 * S3 — the exhibits. Three confident little mistakes, presented one at a
 * time under the narrowing spotlight, each punched with a red ✗ that snaps
 * regardless of scroll speed. Mobile reveals cards in flow; the static
 * document shows all three, marked.
 */
export default function S3Mistakes() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;
      const cards = Array.from(
        root.querySelectorAll<HTMLElement>('[data-s3="card"]')
      );
      const crosses = Array.from(
        root.querySelectorAll<HTMLElement>('[data-s3="cross"]')
      );

      const mm = gsap.matchMedia();

      // ——— desktop: pinned, one exhibit per third of the scrub ———
      mm.add(MQ.full, () => {
        const kicker = q('[data-s3="kicker"]');
        const title = q('[data-s3="title"]');

        gsap.set([kicker, title], { autoAlpha: 0, y: 18 });
        gsap.set(cards, { autoAlpha: 0, y: 56, rotate: (i) => -2 + i * 1.6 });
        gsap.set(crosses, { autoAlpha: 0, scale: 2.6 });

        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: root,
            start: "top top",
            end: "+=150%",
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        });

        tl.to(kicker, { autoAlpha: 1, y: 0, duration: 5 }, 0).to(
          title,
          { autoAlpha: 1, y: 0, duration: 6 },
          2
        );

        cards.forEach((card, i) => {
          const at = 14 + i * 26;
          tl.to(
            card,
            { autoAlpha: 1, y: 0, rotate: 0, duration: 7, ease: "power3.out" },
            at
          )
            // the ✗ punches in — short window, near-snap under scrub
            .to(
              crosses[i],
              {
                autoAlpha: 1,
                scale: 1,
                duration: 2,
                ease: "power4.in",
              },
              at + 8
            )
            // the spotlight swings to the exhibit on the table
            .to(uniforms, { beamX: BEAM_STOPS[i], duration: 6 }, at)
            .to(uniforms, { beam: 0.85, duration: 2 }, at + 8)
            .to(uniforms, { beam: 0.6, duration: 4 }, at + 11);
        });
        // hold the full tableau for the last stretch of the pin
        tl.to({}, { duration: 22 }, 78);

        return () => {
          gsap.set([...cards, ...crosses, kicker, title], { clearProps: "all" });
        };
      });

      // ——— mobile: in-flow reveals, one press per card ———
      mm.add(MQ.compact, () => {
        cards.forEach((card, i) => {
          const press = gsap
            .timeline({
              scrollTrigger: {
                trigger: card,
                start: "top 78%",
                toggleActions: "play none none none",
              },
            })
            .fromTo(
              card,
              { autoAlpha: 0, y: 36 },
              { autoAlpha: 1, y: 0, duration: 0.55, ease: "power3.out" }
            )
            .fromTo(
              crosses[i],
              { autoAlpha: 0, scale: 2.4 },
              { autoAlpha: 1, scale: 1, duration: 0.3, ease: "power4.in" },
              0.35
            );
          return press;
        });
      });
    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s3" className="relative z-10">
      <div className="mx-auto flex min-h-svh max-w-6xl flex-col justify-center px-5 py-28 sm:py-36">
        <p
          data-s3="kicker"
          className="font-mono text-xs uppercase tracking-[0.28em] text-faint sm:text-sm"
        >
          The failures aren&apos;t malicious.
        </p>
        <h2
          data-s3="title"
          className="mt-4 max-w-[22ch] text-balance text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-5xl"
        >
          Confident little mistakes, shipped at full speed.
        </h2>

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {EXHIBITS.map((e) => (
            <article
              key={e.tag}
              data-s3="card"
              className="relative rounded-lg border border-line bg-surface-2 p-6"
            >
              <span
                data-s3="cross"
                aria-hidden="true"
                className="absolute right-4 top-4 font-sans text-4xl font-extrabold leading-none text-verdict-red-deep"
                style={{ rotate: "-8deg" }}
              >
                ✗
              </span>
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-faint">
                {e.tag}
              </p>
              <h3 className="mt-3 text-xl font-semibold text-ink">{e.title}</h3>
              <p className="mt-2 text-sm leading-relaxed">{e.body}</p>
              <p className="mt-5 border-t border-dashed border-line-2 pt-3 font-mono text-xs text-verdict-red">
                {e.evidence}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
