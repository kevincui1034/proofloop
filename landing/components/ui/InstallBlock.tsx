"use client";

import { useState } from "react";
import { INSTALL } from "@/lib/content";

/**
 * The copyable install command — the conversion action for an open-source
 * CLI. Clipboard access needs JS; the <pre> stays selectable without it.
 */
export default function InstallBlock() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(INSTALL.lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (permissions, http) — the text is selectable.
    }
  }

  return (
    <div className="mx-auto mt-10 w-full max-w-2xl text-left">
      <div className="rounded-lg border border-line-2 bg-surface-2 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium uppercase tracking-wide text-faint">
            {INSTALL.heading}
          </span>
          <button
            type="button"
            onClick={copy}
            aria-label="Copy install commands"
            className="rounded border border-line-2 px-2.5 py-1 text-xs text-body transition-colors hover:border-amber-ink/60 hover:text-amber-ink"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="mt-3 overflow-x-auto font-mono text-[13px] leading-relaxed text-ink">
          {INSTALL.lines.map((line) => (
            <span key={line} className="block">
              <span className="select-none text-faint">$ </span>
              {line}
            </span>
          ))}
        </pre>
        <p className="mt-2 text-xs text-faint">{INSTALL.note}</p>
      </div>
    </div>
  );
}
