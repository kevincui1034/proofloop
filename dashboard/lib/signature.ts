/**
 * Port of the CLI's `advisory_signature` (cli/src/proofjury/memory/recall.py).
 *
 * MUST stay byte-identical to the Python implementation — E2 graduation
 * groups by this signature and the CLI suppresses rejected signatures.
 * Parity is pinned by the shared fixture file
 * cli/tests/fixtures/advisory_signatures.json, asserted from both sides.
 */
const TOKEN_RE = /[a-z0-9_]{4,}/g;

export function advisorySignature(
  concern: string | null | undefined,
  target: string | null | undefined,
): string {
  // Python: (target or "").split(":", 1)[0].strip().lower()
  const filePart = (target ?? "").split(":")[0].trim().toLowerCase();
  // Python: sorted(set(re.findall(r"[a-z0-9_]{4,}", (concern or "").lower())))
  // ASCII-only token charset → JS lexicographic sort == Python sort.
  const tokens = Array.from(
    new Set((concern ?? "").toLowerCase().match(TOKEN_RE) ?? []),
  ).sort();
  return filePart + "|" + tokens.join(" ");
}
