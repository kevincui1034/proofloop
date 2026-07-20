"""Deterministic blast-radius analysis — reverse-import graph at gate time.

From the changed files, build a reverse-import graph — Python via ``ast``,
JS/TS via ``import``/``require`` regex — depth-limited and repo-relative.
No LLM, no subprocess. Same discipline as the diff-scoped checks: any
failure (unparseable file, oversized repo, no analyzable changes) degrades
to ``None`` — impact is context only and NEVER affects the gate decision.

The resulting ``impact.json`` is a proof file: per changed file, its
dependents with edge type + depth. Later it is the dashboard's
blast-radius view; today it feeds the deny payload and the advisory judge.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath

PY_EXTENSIONS = {".py"}
JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

#: More relevant-extension files than this → skip entirely (monorepo guard).
MAX_SCAN_FILES = 4000
#: Files larger than this are not parsed (generated bundles, vendored blobs).
MAX_FILE_BYTES = 1_000_000

#: ``import … from '…'`` / bare ``import '…'`` / ``export … from '…'``.
_JS_IMPORT_RE = re.compile(
    r"""(?:^|\s)(?:import|export)\s+(?:[^'";()]*?\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
#: ``require('…')`` and dynamic ``import('…')``.
_JS_REQUIRE_RE = re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""")

#: Resolution order for extensionless JS/TS specifiers.
_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _rel_posix(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _read_bounded(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- Python


def _py_module_names(rel: str) -> list[str]:
    """Dotted-name candidates for a repo-relative ``.py`` path.

    Both the full path from the repo root AND the path after the last
    ``src`` component, so ``cli/src/pkg/mod.py`` is findable as
    ``cli.src.pkg.mod`` and as ``pkg.mod`` (src-layout imports).
    """
    parts = list(PurePosixPath(rel).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    if not parts:
        return []
    names = [".".join(parts)]
    prefix = parts[:-1]
    if "src" in prefix:
        idx = len(prefix) - 1 - prefix[::-1].index("src")
        stripped = parts[idx + 1 :]
        if stripped:
            names.append(".".join(stripped))
    return names


def _py_package(rel: str) -> list[str]:
    """The containing package parts of a repo-relative ``.py`` path."""
    parts = list(PurePosixPath(rel).parts)[:-1]
    return parts


class _PyIndex:
    """module dotted-name → repo-relative file path (first wins)."""

    def __init__(self, py_files: list[str]) -> None:
        self.by_name: dict[str, str] = {}
        for rel in py_files:
            for name in _py_module_names(rel):
                self.by_name.setdefault(name, rel)

    def resolve(self, dotted: str) -> str | None:
        """Longest resolvable prefix of ``dotted`` (a.b.c → a.b → a)."""
        parts = dotted.split(".")
        while parts:
            hit = self.by_name.get(".".join(parts))
            if hit is not None:
                return hit
            parts.pop()
        return None


def _py_edges(rel: str, source: str, index: _PyIndex) -> set[str]:
    """Repo-relative files that ``rel`` imports."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    targets: set[str] = set()
    package = _py_package(rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = index.resolve(alias.name)
                if hit:
                    targets.add(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                bases = [node.module] if node.module else []
            else:
                # from ..mod import x — anchor to the importing package.
                if node.level - 1 > len(package):
                    continue
                anchor = package[: len(package) - (node.level - 1)]
                base = ".".join(anchor)
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
                if not base:
                    continue
                bases = [base]
            for base in bases:
                for alias in node.names:
                    # ``from M import x`` — x may be a submodule file…
                    hit = index.resolve(f"{base}.{alias.name}")
                    if hit is None:
                        # …or a name inside M itself.
                        hit = index.resolve(base)
                    if hit:
                        targets.add(hit)
    targets.discard(rel)
    return targets


# ---------------------------------------------------------------- JS/TS


def _js_resolve(spec: str, importer: str, file_set: set[str]) -> str | None:
    """Resolve a RELATIVE specifier against the repo file set.

    Bare/package specifiers are ignored — only ``./`` and ``../`` paths
    form repo-internal edges.
    """
    if not spec.startswith("."):
        return None
    base = PurePosixPath(importer).parent
    joined: list[str] = list(base.parts)
    for part in PurePosixPath(spec).parts:
        if part == ".":
            continue
        if part == "..":
            if not joined:
                return None  # escapes the repo
            joined.pop()
        else:
            joined.append(part)
    candidate = "/".join(joined)
    if not candidate:
        return None
    stems = [candidate]
    # NodeNext style: ``./foo.js`` on disk as ``foo.ts``/``foo.tsx``.
    for ext in (".js", ".jsx", ".mjs", ".cjs"):
        if candidate.endswith(ext):
            stems.append(candidate[: -len(ext)])
            break
    for stem in stems:
        if stem in file_set:
            return stem
        for ext in _JS_RESOLVE_EXTS:
            if f"{stem}{ext}" in file_set:
                return f"{stem}{ext}"
        for ext in _JS_RESOLVE_EXTS:
            if f"{stem}/index{ext}" in file_set:
                return f"{stem}/index{ext}"
    return None


def _js_edges(rel: str, source: str, file_set: set[str]) -> set[tuple[str, str]]:
    """(target, edge-label) pairs for the imports of one JS/TS file."""
    out: set[tuple[str, str]] = set()
    for regex, label in (
        (_JS_IMPORT_RE, "import"),
        (_JS_DYNAMIC_RE, "import"),
        (_JS_REQUIRE_RE, "require"),
    ):
        for match in regex.finditer(source):
            target = _js_resolve(match.group(1), rel, file_set)
            if target and target != rel:
                out.add((target, label))
    return out


# ---------------------------------------------------------------- graph


def build_impact(
    root: Path,
    changed_files: list[str],
    files: list[Path],
    *,
    depth: int = 2,
    max_files: int = 50,
) -> dict | None:
    """Reverse-import blast radius for the changed files.

    ``files`` is the already-captured source list (``RunContext.files``) —
    no second walk. Returns ``None`` when there is nothing analyzable
    (no changed source files, oversized repo); never raises.
    """
    try:
        return _build_impact(Path(root), changed_files, files, depth, max_files)
    except Exception:
        return None


def _build_impact(
    root: Path,
    changed_files: list[str],
    files: list[Path],
    depth: int,
    max_files: int,
) -> dict | None:
    relevant: dict[str, Path] = {}
    for path in files:
        if path.suffix in PY_EXTENSIONS or path.suffix in JS_EXTENSIONS:
            rel = _rel_posix(path, root)
            if rel is not None:
                relevant[rel] = path
    if not relevant or len(relevant) > MAX_SCAN_FILES:
        return None

    changed = sorted(
        {
            f
            for f in changed_files
            if PurePosixPath(f).suffix in PY_EXTENSIONS | JS_EXTENSIONS
        }
    )
    if not changed:
        return None

    # Forward edges (importer → imported), one parse per file — the graph
    # stays within each language (py↔py, js/ts↔js/ts).
    py_index = _PyIndex(sorted(r for r in relevant if r.endswith(".py")))
    js_set = {r for r in relevant if PurePosixPath(r).suffix in JS_EXTENSIONS}
    reverse: dict[str, dict[str, str]] = {}  # imported → {importer: edge}
    for rel in sorted(relevant):
        source = _read_bounded(relevant[rel])
        if source is None:
            continue
        if rel.endswith(".py"):
            edges = {(t, "import") for t in _py_edges(rel, source, py_index)}
        else:
            edges = _js_edges(rel, source, js_set)
        for target, label in edges:
            reverse.setdefault(target, {}).setdefault(rel, label)

    # BFS up the reverse graph from each changed file.
    emitted = 0
    truncated = False
    entries = []
    for start in changed:
        dependents = []
        seen = {start}
        frontier = [start]
        for level in range(1, depth + 1):
            next_frontier: list[str] = []
            for node in frontier:
                for importer in sorted(reverse.get(node, {})):
                    if importer in seen:
                        continue
                    seen.add(importer)
                    dependents.append(
                        {
                            "file": importer,
                            "edge": reverse[node][importer],
                            "depth": level,
                        }
                    )
                    next_frontier.append(importer)
            frontier = next_frontier
        if emitted + len(dependents) > max_files:
            dependents = dependents[: max(0, max_files - emitted)]
            truncated = True
        emitted += len(dependents)
        entries.append({"file": start, "dependents": dependents})

    return {"depth": depth, "truncated": truncated, "changed": entries}


def summary_line(impact: dict | None) -> str | None:
    """One agent-facing sentence for the deny payload / advisory input.

    Names the changed file with the widest direct blast radius; ``None``
    when no changed file has any dependent.
    """
    if not impact:
        return None
    scored = []
    for entry in impact.get("changed", []):
        direct = [d["file"] for d in entry["dependents"] if d["depth"] == 1]
        total = len(entry["dependents"])
        if total:
            scored.append((len(direct), total, entry["file"], direct))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    n_direct, total, top, direct = scored[0]
    shown = ", ".join(direct[:3]) if direct else "indirect dependents only"
    line = (
        f"this change touches {top}, imported by {n_direct} "
        f"module{'s' if n_direct != 1 else ''} including {shown}"
        if n_direct
        else f"this change touches {top}, with {total} indirect dependents"
    )
    others = len(scored) - 1
    if others:
        line += f" (+{others} more changed file{'s' if others != 1 else ''} with dependents)"
    return line
