# Product

## Register

brand

## Users

Solo developers (and soon teams) who let coding agents — Claude Code, Codex, Cursor — write and ship code no human reviews. They arrive skeptical of AI-tool marketing, fluent in terminals, allergic to vibes. Context: reading this at night, probably in dark mode, deciding whether to `npm i` one more tool.

## Product Purpose

Proofloop is the correctness gate for AI-written code. It intercepts the deploy command itself, decides with deterministic checks (env vars, tests ran, build passes, no hardcoded secrets, config sanity), uses an LLM only to explain why, emits a reproducible proof record, and remembers every diagnosed failure so recurrence is caught instantly. Neutral across all agents. The landing page's job: make the deploy-moment gap visceral, show the block→fix→allow story, and convert to GitHub stars + early-access emails.

## Brand Personality

Dignified, deterministic, a little theatrical. A calm judge in a room full of rushing robots. Voice: courtroom confidence — verdicts, proof, records — never security-vendor fear, never SaaS cheer. Emotional goal: relief ("finally, someone checks").

## Anti-references

- Security-guardrail vendor sites (Galileo, Straiker): fear-based, enterprise-gray. We do correctness, not security.
- Generic AI-SaaS dark landing: purple gradients, glass cards, gradient text, metric heroes.
- Banned phrases (competitors own them): "verification layer", "self-improving loop", "closing the feedback loop", "quality gates". Never claim "nobody guards correctness" — only "no one guards correctness at the deploy moment".

## Design Principles

1. **Verdicts, not vibes** — every claim on the page is staged as evidence: terminal transcripts, proof receipts, record ids. Show the block happening.
2. **The judge is calm; the bots are frantic** — motion energy belongs to the rogue bots; the gate and typography stay still and heavy. Contrast is the drama.
3. **Color is a verdict** — amber = the judge/brand, red = BLOCKED, green = ALLOWED, bot colors are vendor-neutral. No decorative color.
4. **Deterministic craft** — the page itself must feel checked: no broken states, reduced-motion complete, keyboard-visible focus, single h1.
5. **Neutral bench** — never favor an agent vendor visually; bots are equals before the gate.

## Accessibility & Inclusion

prefers-reduced-motion renders final states everywhere (no typing, no spins, no pins beyond static). Characters aria-hidden; terminals carry aria-labels describing the outcome. Body text ≥ 4.5:1 on the near-black surface. Responsive to 375px.
