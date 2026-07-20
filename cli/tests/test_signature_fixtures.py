"""PINNED: advisory_signature parity with the dashboard's TS port.

The fixture file is shared with dashboard/tests/signature.test.ts — both
sides must produce these exact strings. E2 graduation groups by signature
and rejection suppression matches on it, so drift silently breaks both.
Regenerate ONLY deliberately (and update both sides' expectations):
the fixtures are the contract, not a snapshot.
"""

import json
from pathlib import Path

from proofjury.memory.recall import advisory_signature

FIXTURES = Path(__file__).parent / "fixtures" / "advisory_signatures.json"


def test_signatures_match_fixtures():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert len(cases) >= 10
    for case in cases:
        assert advisory_signature(case["concern"], case["target"]) == case["signature"], (
            f"signature drift for concern={case['concern']!r} target={case['target']!r}"
        )
