"""impact.py — deterministic reverse-import blast radius.

Unit tests for the graph builder (Python + JS/TS fixtures), the caps,
and the summary line. Gate integration lives in test_gate.py.
"""

from pathlib import Path

from proofjury.context import iter_source_files
from proofjury.impact import (
    MAX_SCAN_FILES,
    build_impact,
    summary_line,
)


def _impact(repo, changed, **kwargs):
    return build_impact(
        repo.root, changed, iter_source_files(repo.root), **kwargs
    )


def _dependents(impact, changed_file):
    for entry in impact["changed"]:
        if entry["file"] == changed_file:
            return {(d["file"], d["depth"]) for d in entry["dependents"]}
    raise AssertionError(f"{changed_file} not in impact")


# ---------------------------------------------------------------- Python


def test_python_reverse_chain(tmp_repo):
    # c imports a, a imports b — change b: a is depth 1, c is depth 2.
    tmp_repo.write("b.py", "X = 1\n")
    tmp_repo.write("a.py", "import b\n")
    tmp_repo.write("c.py", "import a\n")
    impact = _impact(tmp_repo, ["b.py"])
    assert _dependents(impact, "b.py") == {("a.py", 1), ("c.py", 2)}


def test_python_from_import_and_relative(tmp_repo):
    tmp_repo.write("pkg/__init__.py", "")
    tmp_repo.write("pkg/util.py", "X = 1\n")
    tmp_repo.write("pkg/sibling.py", "from . import util\n")
    tmp_repo.write("pkg/deep/__init__.py", "")
    tmp_repo.write("pkg/deep/mod.py", "from ..util import X\n")
    tmp_repo.write("top.py", "from pkg.util import X\n")
    impact = _impact(tmp_repo, ["pkg/util.py"], depth=1)
    assert _dependents(impact, "pkg/util.py") == {
        ("pkg/sibling.py", 1),
        ("pkg/deep/mod.py", 1),
        ("top.py", 1),
    }


def test_python_src_layout_resolves(tmp_repo):
    # src-layout: imports name the package, files live under src/.
    tmp_repo.write("src/mypkg/__init__.py", "")
    tmp_repo.write("src/mypkg/core.py", "X = 1\n")
    tmp_repo.write("src/mypkg/api.py", "from mypkg.core import X\n")
    impact = _impact(tmp_repo, ["src/mypkg/core.py"], depth=1)
    assert _dependents(impact, "src/mypkg/core.py") == {("src/mypkg/api.py", 1)}


def test_python_syntax_error_file_skipped(tmp_repo):
    tmp_repo.write("b.py", "X = 1\n")
    tmp_repo.write("broken.py", "def (\n")
    tmp_repo.write("a.py", "import b\n")
    impact = _impact(tmp_repo, ["b.py"])
    assert _dependents(impact, "b.py") == {("a.py", 1)}


# ---------------------------------------------------------------- JS/TS


def test_js_relative_imports_and_index(tmp_repo):
    tmp_repo.write("lib/util.ts", "export const x = 1\n")
    tmp_repo.write("lib/index.ts", "export * from './util'\n")
    tmp_repo.write("app.ts", "import { x } from './lib'\n")  # → lib/index.ts
    tmp_repo.write("direct.tsx", "import { x } from './lib/util'\n")
    impact = _impact(tmp_repo, ["lib/util.ts"])
    assert _dependents(impact, "lib/util.ts") == {
        ("lib/index.ts", 1),
        ("direct.tsx", 1),
        ("app.ts", 2),  # via lib/index.ts
    }


def test_js_require_and_nodenext_js_suffix(tmp_repo):
    tmp_repo.write("core.ts", "export const x = 1\n")
    tmp_repo.write("cjs.js", "const c = require('./core.js')\n")  # .js → .ts
    impact = _impact(tmp_repo, ["core.ts"], depth=1)
    assert _dependents(impact, "core.ts") == {("cjs.js", 1)}
    entry = impact["changed"][0]["dependents"][0]
    assert entry["edge"] == "require"


def test_js_bare_specifiers_ignored(tmp_repo):
    tmp_repo.write("react.ts", "export const notReallyReact = 1\n")
    tmp_repo.write("app.ts", "import React from 'react'\n")
    impact = _impact(tmp_repo, ["react.ts"], depth=1)
    assert _dependents(impact, "react.ts") == set()


def test_languages_do_not_cross(tmp_repo):
    tmp_repo.write("util.py", "X = 1\n")
    tmp_repo.write("util.ts", "export const x = 1\n")
    tmp_repo.write("app.ts", "import { x } from './util'\n")
    impact = _impact(tmp_repo, ["util.py"], depth=1)
    assert _dependents(impact, "util.py") == set()


# ---------------------------------------------------------------- caps/skips


def test_no_analyzable_changes_returns_none(tmp_repo):
    tmp_repo.write("a.py", "X = 1\n")
    assert _impact(tmp_repo, []) is None
    assert _impact(tmp_repo, ["README.md", "config.yaml"]) is None


def test_oversized_repo_skips(tmp_repo, monkeypatch):
    monkeypatch.setattr("proofjury.impact.MAX_SCAN_FILES", 1)
    tmp_repo.write("a.py", "import b\n")
    tmp_repo.write("b.py", "X = 1\n")
    assert MAX_SCAN_FILES > 1  # the module constant itself is untouched
    assert _impact(tmp_repo, ["b.py"]) is None


def test_max_files_truncates(tmp_repo):
    tmp_repo.write("core.py", "X = 1\n")
    for i in range(5):
        tmp_repo.write(f"dep{i}.py", "import core\n")
    impact = _impact(tmp_repo, ["core.py"], max_files=3)
    assert impact["truncated"] is True
    assert len(impact["changed"][0]["dependents"]) == 3


def test_never_raises_on_garbage(tmp_repo):
    tmp_repo.write_bytes("evil.py", b"\xff\xfe\x00garbage")
    tmp_repo.write("a.py", "import evil\n")
    impact = _impact(tmp_repo, ["evil.py"])
    assert impact is None or isinstance(impact, dict)
    # A nonexistent root degrades to None, never an exception.
    assert build_impact(Path("/nonexistent"), ["a.py"], []) is None


def test_deterministic_ordering(tmp_repo):
    tmp_repo.write("core.py", "X = 1\n")
    for name in ("zeta.py", "alpha.py", "mid.py"):
        tmp_repo.write(name, "import core\n")
    first = _impact(tmp_repo, ["core.py"])
    second = _impact(tmp_repo, ["core.py"])
    assert first == second
    files = [d["file"] for d in first["changed"][0]["dependents"]]
    assert files == sorted(files)


# ---------------------------------------------------------------- summary


def test_summary_line_names_widest_blast_radius(tmp_repo):
    tmp_repo.write("payments.py", "X = 1\n")
    tmp_repo.write("checkout.py", "import payments\n")
    tmp_repo.write("orders.py", "import payments\n")
    tmp_repo.write("lonely.py", "Y = 2\n")
    impact = _impact(tmp_repo, ["payments.py", "lonely.py"])
    line = summary_line(impact)
    assert "payments.py" in line
    assert "2 modules" in line
    assert "checkout.py" in line


def test_summary_line_none_without_dependents(tmp_repo):
    tmp_repo.write("lonely.py", "X = 1\n")
    assert summary_line(_impact(tmp_repo, ["lonely.py"])) is None
    assert summary_line(None) is None


# ---------------------------------------------------------------- config


def test_impact_settings_defaults_and_validation():
    from proofjury.config import IMPACT_DEFAULTS, impact_settings

    assert impact_settings({}) == IMPACT_DEFAULTS
    assert impact_settings(None) == IMPACT_DEFAULTS
    assert impact_settings({"impact": "not-a-table"}) == IMPACT_DEFAULTS
    good = impact_settings({"impact": {"enabled": False, "depth": 3, "max_files": 10}})
    assert good == {"enabled": False, "depth": 3, "max_files": 10}
    # malformed values fall back per-key, never crash
    bad = impact_settings({"impact": {"enabled": "yes", "depth": 0, "max_files": True}})
    assert bad == IMPACT_DEFAULTS
