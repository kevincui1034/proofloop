"use client";

import { useEffect, useRef } from "react";
import type { StageHandle } from "./stage";

/**
 * Client shell for the night world's WebGL atmosphere. The OGL module is
 * code-split behind a dynamic import and initialized off the critical path
 * (idle callback). Reduced motion never mounts it; a failed context leaves
 * the CSS beam fallback visible. Decorative only — aria-hidden, no content.
 */
export default function GLStage() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let stage: StageHandle | null = null;
    let cancelled = false;

    const start = () => {
      import("./stage").then((m) => {
        if (cancelled || !ref.current) return;
        stage = m.createStage(ref.current);
        if (stage) {
          // the shader owns the atmosphere now — retire the CSS beam
          const fallback =
            ref.current.parentElement?.querySelector<HTMLElement>(
              '[data-gl="fallback"]'
            );
          if (fallback) fallback.style.opacity = "0";
        }
      });
    };

    const hasIdle = typeof window.requestIdleCallback === "function";
    const idleId = hasIdle
      ? window.requestIdleCallback(start, { timeout: 2000 })
      : window.setTimeout(start, 300);

    return () => {
      cancelled = true;
      if (hasIdle) window.cancelIdleCallback(idleId);
      else window.clearTimeout(idleId);
      stage?.destroy();
    };
  }, []);

  return <div ref={ref} aria-hidden="true" className="absolute inset-0" />;
}
