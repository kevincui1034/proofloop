"use client";

import { useState } from "react";

// Create the form at formspree.io and paste its id here. The site is a
// static export (no API routes), so the form POSTs straight to Formspree
// from the browser; the action/method attributes keep a no-JS fallback.
const FORMSPREE_FORM_ID = "YOUR_FORM_ID";
const FORMSPREE_ACTION = `https://formspree.io/f/${FORMSPREE_FORM_ID}`;

// Kept only as the error-state fallback link.
const MAILTO =
  "mailto:kevincui1034@gmail.com?subject=Proofjury%20early%20access";

type FormState = "idle" | "submitting" | "success" | "error";

export default function EarlyAccessForm() {
  const [state, setState] = useState<FormState>("idle");

  if (state === "success") {
    return (
      <p className="rounded-md border border-line-2 px-6 py-3 text-sm font-medium text-amber-ink">
        You&apos;re on the list — watch your inbox.
      </p>
    );
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setState("submitting");
    try {
      const response = await fetch(FORMSPREE_ACTION, {
        method: "POST",
        body: new FormData(form),
        // Without this header Formspree redirects to its hosted thank-you page.
        headers: { Accept: "application/json" },
      });
      setState(response.ok ? "success" : "error");
    } catch {
      setState("error");
    }
  }

  return (
    <form
      action={FORMSPREE_ACTION}
      method="POST"
      onSubmit={handleSubmit}
      className="flex flex-wrap items-center justify-center gap-3"
    >
      <input
        type="email"
        name="email"
        required
        placeholder="you@example.com"
        aria-label="Email for early access"
        className="w-64 rounded-md border border-line-2 bg-transparent px-4 py-3 text-sm text-ink placeholder:text-faint focus:border-amber-ink/60 focus:outline-none"
      />
      {/* Honeypot — bots fill it, Formspree drops the submission. */}
      <input
        type="text"
        name="_gotcha"
        style={{ display: "none" }}
        tabIndex={-1}
        autoComplete="off"
      />
      <button
        type="submit"
        disabled={state === "submitting"}
        className="rounded-md border border-line-2 px-6 py-3 text-sm font-medium text-ink transition-colors hover:border-amber-ink/60 hover:text-amber-ink disabled:opacity-60"
      >
        {state === "submitting" ? "Sending…" : "Get early access"}
      </button>
      {state === "error" && (
        <p className="w-full text-xs text-faint">
          That didn&apos;t go through — try again, or{" "}
          <a href={MAILTO} className="underline hover:text-amber-ink">
            email us directly
          </a>
          .
        </p>
      )}
    </form>
  );
}
