"use client";

import { useRef } from "react";
import {
  FIX_TRANSCRIPT,
  RECEIPT_ROWS,
  RECORD_LINE,
  type TranscriptLine,
} from "@/lib/content";
import Stamp from "@/components/ui/Stamp";
import { gsap, useGSAP } from "@/components/experience/gsap-setup";

const RECEIPT_TEETH = Array.from(
  { length: 24 },
  (_, i) => `${i * 14},0 ${i * 14 + 7},9 ${i * 14 + 14},0`
).join(" ");

const MOTION_OK = "(prefers-reduced-motion: no-preference)";

/** The chk_001 proof record, pulled out of the printer by scroll. */
function Receipt() {
  return (
    <div className="relative mx-auto w-full max-w-[350px]">
      {/* printer slot */}
      <div className="relative z-10 mx-auto flex h-4 w-[94%] items-center justify-end rounded-full bg-ink px-2.5 shadow-[0_6px_16px_-8px_rgba(29,35,46,0.7)]">
        <span className="h-1.5 w-1.5 rounded-full bg-amber" />
      </div>
      {/* the sleeve never moves; the paper translates down out of it */}
      <div data-s5="sleeve" className="-mt-2 overflow-hidden px-2 pb-2">
        <div data-s5="paper">
          <div className="bg-surface-2 px-5 pb-4 pt-6 font-mono text-[11px] leading-relaxed text-ink shadow-[0_28px_60px_-30px_rgba(29,35,46,0.55)]">
            <div className="flex items-baseline justify-between">
              <span className="text-[13px] font-bold tracking-[0.22em]">
                PROOF RECORD
              </span>
              <span className="rounded-sm bg-ink px-1.5 py-0.5 text-[10px] font-bold text-surface-2">
                chk_001
              </span>
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-faint">
              <span>gate: deploy</span>
              <span>2026-07-04T21:14:09Z</span>
            </div>
            <div className="mt-2 border-b border-dashed border-line-2" />
            {RECEIPT_ROWS.map((r, i) => (
              <div
                key={i}
                className="border-b border-dashed border-line py-1.5 last:border-0"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-bold">{r.name}</span>
                  <span
                    className={
                      r.fail
                        ? "font-semibold text-verdict-red"
                        : "font-semibold text-verdict-green"
                    }
                  >
                    {r.verdict}
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-2 text-[10px] text-faint">
                  <span>{r.loc}</span>
                  <span className="truncate text-right">{r.detail}</span>
                </div>
              </div>
            ))}
            <div className="mt-1 border-t border-dashed border-line-2 pt-2 text-[10px]">
              <div className="flex justify-between gap-2">
                <span className="font-bold">inputs_hash</span>
                <span className="truncate">sha256:9f3c41a8…de21</span>
              </div>
              <div className="mt-1 flex justify-between text-faint">
                <span>reproducible · same inputs, same verdict</span>
                <span>exit 2</span>
              </div>
            </div>
          </div>
          {/* perforated bottom edge */}
          <svg
            viewBox="0 0 336 10"
            preserveAspectRatio="none"
            className="block h-2.5 w-full"
            aria-hidden="true"
          >
            <polygon points={RECEIPT_TEETH} fill="var(--surface-2)" />
          </svg>
        </div>
      </div>
    </div>
  );
}

function TranscriptRow({ line }: { line: TranscriptLine }) {
  const tone =
    line.tone === "green"
      ? "text-verdict-green"
      : line.tone === "amber"
        ? "text-amber-ink"
        : line.tone === "red"
          ? "text-verdict-red"
          : "text-body";
  return (
    <li data-s5="fixline" className={`py-1 ${tone}`}>
      {line.kind === "cmd" && <span className="text-faint">$ </span>}
      {line.text}
    </li>
  );
}

/**
 * S5 — the proof record. The paper world opens: "Let the record show —",
 * the receipt is physically pulled from the printer by scrolling, and the
 * deny payload becomes the fix. No pins here: the paper world breathes at
 * document rhythm to contrast the night world's grip.
 */
export default function S5ProofRecord() {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const root = ref.current!;
      const q = (sel: string) => root.querySelector<HTMLElement>(sel)!;

      const mm = gsap.matchMedia();
      mm.add(MOTION_OK, () => {
        // the first words on paper ink in
        gsap
          .timeline({
            scrollTrigger: { trigger: root, start: "top 72%" },
          })
          .from(q('[data-s5="show"]'), {
            autoAlpha: 0,
            y: 26,
            duration: 0.9,
            ease: "power3.out",
          })
          .from(
            q('[data-s5="recordline"]'),
            { autoAlpha: 0, duration: 0.5 },
            0.5
          )
          .from(
            q('[data-s5="blocked-stamp"]'),
            { autoAlpha: 0, scale: 1.9, rotation: 6, duration: 0.3, ease: "power4.in" },
            0.7
          )
          .from(
            q('[data-s5="rule"]'),
            { scaleX: 0, transformOrigin: "0 50%", duration: 0.8, ease: "power2.inOut" },
            0.4
          );

        // the reader pulls the receipt out of the printer
        gsap.fromTo(
          q('[data-s5="paper"]'),
          { yPercent: -101 },
          {
            yPercent: 0,
            ease: "none",
            scrollTrigger: {
              trigger: q('[data-s5="sleeve"]'),
              start: "top 78%",
              end: "+=52%",
              scrub: 0.5,
            },
          }
        );

        // the fix transcript types itself into the record
        const fixlines = root.querySelectorAll<HTMLElement>(
          '[data-s5="fixline"]'
        );
        gsap
          .timeline({
            scrollTrigger: { trigger: fixlines[0], start: "top 78%" },
          })
          .from(fixlines, {
            autoAlpha: 0,
            y: 8,
            duration: 0.35,
            stagger: 0.14,
            ease: "power2.out",
          })
          .from(
            q('[data-s5="allowed"]'),
            {
              autoAlpha: 0,
              scale: 1.8,
              rotation: 10,
              duration: 0.3,
              ease: "power4.in",
            },
            ">-0.1"
          );
      });
    },
    { scope: ref }
  );

  return (
    <section ref={ref} data-scene="s5" className="relative z-10 px-5 pt-28 sm:pt-36">
      <div className="mx-auto max-w-6xl">
        {/* the first words on paper */}
        <p
          data-s5="show"
          className="font-serif text-5xl italic leading-[1.05] text-ink sm:text-7xl"
        >
          Let the record show&nbsp;—
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
          <p data-s5="recordline" className="font-mono text-xs text-faint sm:text-sm">
            {RECORD_LINE}
          </p>
          <span data-s5="blocked-stamp" className="inline-block">
            <Stamp verdict="blocked" size="sm" className="-rotate-6" />
          </span>
        </div>
        <div data-s5="rule" className="mt-10 border-b-2 border-ink/70" />

        <div className="mt-16 grid items-start gap-14 md:grid-cols-2 md:gap-10">
          <div>
            <h2 className="max-w-[16ch] text-balance font-serif text-4xl leading-[1.08] text-ink sm:text-5xl">
              Every verdict ships with a proof record.
            </h2>
            <p className="mt-6 max-w-[52ch] leading-relaxed">
              Which check failed. The file and line. The command output that
              shows it. Reproducible — run it again with the same inputs and
              you get the same verdict, not a regenerated opinion.
            </p>
            <p className="mt-4 max-w-[52ch] leading-relaxed">
              Each interception is persisted to{" "}
              <code className="font-mono text-sm text-ink">
                .proofjury/runs/
              </code>{" "}
              — the trace, the env scan, the build log.
            </p>
          </div>
          <Receipt />
        </div>

        {/* the denial is structured feedback */}
        <div className="mt-24 grid items-start gap-10 border-t border-line pt-16 sm:mt-32 md:grid-cols-2">
          <div>
            <h2 className="max-w-[16ch] text-balance font-serif text-4xl leading-[1.08] text-ink sm:text-5xl">
              A denial is not a dead stop.
            </h2>
            <p className="mt-6 max-w-[52ch] leading-relaxed">
              The block tells your agent exactly how to fix it — structured
              feedback it applies, then re-runs. Same gate, new verdict.
            </p>
          </div>
          <div className="relative">
            <ul className="rounded-lg border border-line bg-surface-2 p-5 font-mono text-xs leading-relaxed sm:text-[13px]">
              {FIX_TRANSCRIPT.map((line, i) => (
                <TranscriptRow key={i} line={line} />
              ))}
            </ul>
            <div data-s5="allowed" className="absolute -right-3 -top-5">
              <Stamp verdict="allowed" size="sm" className="rotate-3" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
