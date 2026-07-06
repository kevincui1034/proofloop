"use client";

import { motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { TerminalLine } from "@/lib/terminal-scripts";
import { useReducedMotionSafe } from "@/components/characters/motion-presets";

type TerminalProps = {
  script: TerminalLine[];
  playOnInView?: boolean;
  className?: string;
  /** Describes the transcript outcome for assistive tech. */
  ariaLabel?: string;
};

const TONE_CLASS: Record<NonNullable<TerminalLine["tone"]> | "default", string> = {
  red: "text-verdict-red",
  green: "text-verdict-green",
  dim: "text-faint",
  amber: "text-amber",
  default: "text-body",
};

const TYPE_MS = 24;

function gapBefore(line: TerminalLine | undefined): number {
  if (!line) return 0;
  const base = line.type === "cmd" ? 320 : line.type === "status" ? 380 : 110;
  return base + (line.delayMs ?? 0);
}

function LineView({
  line,
  text,
  animate,
  showCursor,
}: {
  line: TerminalLine;
  text: string;
  animate: boolean;
  showCursor: boolean;
}) {
  const tone = TONE_CLASS[line.tone ?? "default"];
  const cursor = showCursor ? (
    <span className="cursor-blink ml-px inline-block h-[1.05em] w-[7px] translate-y-[0.18em] bg-body/80" />
  ) : null;

  if (line.type === "cmd") {
    return (
      <div className="whitespace-pre-wrap break-words text-ink">
        <span className="select-none text-faint">$ </span>
        {text}
        {cursor}
      </div>
    );
  }

  if (line.type === "status") {
    const inner = (
      <span className={`inline-block font-semibold ${tone}`}>{text}</span>
    );
    return (
      <div className="whitespace-pre-wrap break-words py-0.5">
        {animate ? (
          <motion.span
            className="inline-block"
            initial={{ scale: 0.4, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 420, damping: 20 }}
          >
            {inner}
          </motion.span>
        ) : (
          inner
        )}
        {cursor}
      </div>
    );
  }

  const out = (
    <div className={`whitespace-pre-wrap break-words ${tone}`}>
      {text}
      {cursor}
    </div>
  );
  return animate ? (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.25 }}>
      {out}
    </motion.div>
  ) : (
    out
  );
}

export default function Terminal({
  script,
  playOnInView = true,
  className = "",
  ariaLabel,
}: TerminalProps) {
  // Hydration-safe: false during SSR + first client render, real value after
  // mount — the transcript may render its first (empty) frame before flipping
  // to the instant full-transcript view for reduced-motion users.
  const rm = useReducedMotionSafe();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const started = playOnInView ? inView : true;

  // pos.line = index of the line currently printing; pos.char = typed chars of it
  const [pos, setPos] = useState({ line: 0, char: 0 });
  const done = pos.line >= script.length;

  useEffect(() => {
    if (!started || rm) return;
    let line = 0;
    let char = 0;
    let cancelled = false;
    let t: ReturnType<typeof setTimeout>;

    const advance = () => {
      if (cancelled) return;
      const cur = script[line];
      if (!cur) return;
      if (cur.type === "cmd" && char < cur.text.length) {
        char += 1;
        setPos({ line, char });
        t = setTimeout(advance, TYPE_MS);
        return;
      }
      // current line complete → pause for the NEXT line's authored gap
      // BEFORE revealing it (so e.g. a delayMs on a status line reads as a
      // dramatic pause preceding the verdict, not one trailing it)
      line += 1;
      char = 0;
      if (line >= script.length) {
        setPos({ line, char });
        return;
      }
      t = setTimeout(() => {
        if (cancelled) return;
        setPos({ line, char });
        advance();
      }, gapBefore(script[line]));
    };

    t = setTimeout(advance, gapBefore(script[0]) + 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [started, rm, script]);

  const instant = rm;

  return (
    <figure
      ref={ref}
      role="img"
      aria-label={ariaLabel ?? "Terminal transcript"}
      className={`overflow-hidden rounded-xl border border-line bg-raised shadow-[0_24px_64px_-32px_rgba(0,0,0,0.9)] ${className}`}
    >
      {/* window chrome */}
      <div className="relative flex items-center gap-1.5 border-b border-line bg-inset/60 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57] opacity-80" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e] opacity-80" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840] opacity-80" />
        <span className="absolute inset-x-0 text-center font-mono text-[11px] tracking-wide text-faint">
          proofloop
        </span>
      </div>

      {/* body — a hidden ghost of the full script reserves the final height
          so the page never reflows while lines print */}
      <div aria-hidden="true" className="relative p-4 font-mono text-[12px] leading-[1.65] sm:p-5 sm:text-[13px]">
        <div className="invisible space-y-0.5">
          {script.map((l, i) => (
            <LineView key={i} line={l} text={l.text} animate={false} showCursor={false} />
          ))}
        </div>
        <div className="absolute inset-0 space-y-0.5 p-4 sm:p-5">
          {instant
            ? script.map((l, i) => (
                <LineView
                  key={i}
                  line={l}
                  text={l.text}
                  animate={false}
                  showCursor={i === script.length - 1}
                />
              ))
            : script.map((l, i) => {
                if (i > pos.line) return null;
                const active = i === pos.line;
                const text = active && l.type === "cmd" ? l.text.slice(0, pos.char) : l.text;
                const cursorHere = started && (active || (done && i === script.length - 1));
                return (
                  <LineView key={i} line={l} text={text} animate={!active || l.type !== "cmd"} showCursor={cursorHere} />
                );
              })}
        </div>
      </div>
    </figure>
  );
}
