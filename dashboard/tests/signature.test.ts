/**
 * PINNED: TS advisorySignature parity with the CLI's Python
 * advisory_signature, via the shared fixture file (generated from the
 * Python side — the source of truth). Drift breaks this side's CI.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { advisorySignature } from "@/lib/signature";

const FIXTURES = path.resolve(
  __dirname,
  "../../cli/tests/fixtures/advisory_signatures.json",
);

describe("advisorySignature parity", () => {
  const cases = JSON.parse(readFileSync(FIXTURES, "utf8")) as {
    concern: string | null;
    target: string | null;
    signature: string;
  }[];

  it("has a meaningful fixture set", () => {
    expect(cases.length).toBeGreaterThanOrEqual(10);
  });

  it.each(cases)("byte-matches Python for %#", (fixture) => {
    expect(advisorySignature(fixture.concern, fixture.target)).toBe(
      fixture.signature,
    );
  });
});
