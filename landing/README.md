# Proofloop landing page

Marketing site for the [Proofloop CLI](../cli) — a correctness gate for
AI-written code that blocks unready deploys at the deploy moment. The
page's job: convert visitors to GitHub stars and early-access emails.

## Stack

- Next.js 16 (App Router) with `output: "export"` — the site is a **fully
  static export**. There are no API routes, server actions, or middleware
  at runtime; anything dynamic must run in the browser.
- **GSAP + ScrollTrigger + SplitText** for the scroll-driven scenes,
  **Lenis** for smooth scrolling (driven from GSAP's ticker — one rAF for
  the whole site), and **OGL** (code-split, idle-initialized) for the
  night world's WebGL light shaft. See
  [components/experience/](components/experience/) for the spine.
- The page is two worlds under one scroll: scenes S1–S4 are the dark
  "night court", S5–S8 the light "proof record" paper world. Semantic
  color tokens are scoped by `data-world` attributes in
  [app/globals.css](app/globals.css); S4's flood flips the root attribute
  behind full cover.
- Reduced motion renders a plain top-to-bottom document: no pins, no
  Lenis, no canvas (`gsap.matchMedia()` contexts in each scene).
- Tailwind CSS 4.

> Heads-up for agents: this Next.js version may differ from your training
> data — see [AGENTS.md](AGENTS.md) and `node_modules/next/dist/docs/`.

## Commands

```bash
npm install
npm run dev     # local dev server
npm run build   # static export → out/
```

## Early-access email capture

The "Get early access" form in
[components/ui/EarlyAccessForm.tsx](components/ui/EarlyAccessForm.tsx) POSTs directly
to Formspree from the browser (static export = no server to proxy
through). The form id lives in the `FORMSPREE_FORM_ID` constant at the top
of that file — create a form at formspree.io and paste its id there. The
`<form action=... method="POST">` attributes are kept so the no-JS path
still submits; the fetch path sends `Accept: application/json` so
Formspree responds inline instead of redirecting to its hosted page. A
`mailto:` link remains only as the error-state fallback.

## Deploy

Deployed on Vercel; `npm run build` emits `out/`. Build artifacts
(`out/`, `.next/`, `.vercel/`, `*.tsbuildinfo`) are gitignored — don't
commit them.

## Copy constraints

All user-facing copy must follow the positioning rules in
[PRODUCT.md](PRODUCT.md): certain competitor-owned phrases are banned, the
only exclusivity claim allowed is about the **deploy moment**, and
positioning statements are paired with "correctness, not security".
