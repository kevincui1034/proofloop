"""missing_env_var — the flagship check.

Scans Python via AST (regex fallback on SyntaxError) and JS/TS/JSX/Vue
via regex for environment variable reads. Reads WITH a literal default
are satisfied; reads without one are required. Required names missing
from the deploy environment fail with per-name file:line evidence.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .base import CheckContext, CheckResult, Evidence, register, rel

PY_EXTENSIONS = {".py"}
JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"}

#: Framework-injected names that are always defined at build time.
JS_BUILTIN_NAMES = {"MODE", "DEV", "PROD", "SSR", "BASE_URL", "NODE_ENV"}

_NAME_RE = r"[A-Za-z_][A-Za-z0-9_]*"
#: ``\??\.`` / ``\??\[`` allow optional-chaining reads (process.env?.X).
JS_PATTERNS = [
    re.compile(rf"process\.env\??\.({_NAME_RE})"),
    re.compile(rf"""process\.env\??\[\s*["']({_NAME_RE})["']\s*\]"""),
    re.compile(rf"import\.meta\.env\??\.({_NAME_RE})"),
]
#: Destructuring reads: ``const { API_KEY, HOST: h, PORT = 3000 } = process.env``.
JS_DESTRUCTURE_RE = re.compile(
    rf"\{{([^{{}}]*)\}}\s*=\s*(?:process\.env|import\.meta\.env)\b"
)
#: One entry inside the destructuring braces. The env name is always the
#: left identifier (``{ API_KEY: k }`` reads API_KEY); a ``=`` in the entry
#: (``{ PORT = 3000 }`` or ``{ PORT: p = 3000 }``) is a default.
_DESTRUCTURE_ENTRY_RE = re.compile(rf"({_NAME_RE})\s*(?::\s*{_NAME_RE}\s*)?(=)?")
#: A read followed by `|| fallback` or `?? fallback` has a default,
#: matching the Python `os.environ.get(x, default)` semantics.
_JS_DEFAULT_TAIL_RE = re.compile(r"\s*(?:\|\||\?\?)")

# Regex fallback for Python files that fail to parse.
PY_FALLBACK_REQUIRED = [
    re.compile(rf"""os\.environ\[\s*["']({_NAME_RE})["']\s*\]"""),
    re.compile(rf"""os\.environ\.get\(\s*["']({_NAME_RE})["']\s*\)"""),
    re.compile(rf"""os\.getenv\(\s*["']({_NAME_RE})["']\s*\)"""),
]


class _EnvRead:
    __slots__ = ("name", "file", "line", "has_default")

    def __init__(self, name: str, file: str, line: int, has_default: bool):
        self.name = name
        self.file = file
        self.line = line
        self.has_default = has_default


class _PyEnvVisitor(ast.NodeVisitor):
    """Collects env reads: subscript, ``.get(...)`` and ``getenv(...)``.

    Tracks import bindings so all common idioms are recognized:
    ``import os`` / ``import os as o``, ``from os import environ [as e]``,
    ``from os import getenv [as g]``. The literal name ``os`` is always
    treated as the os module (matching the regex fallback's behavior even
    when the import lives in another file).
    """

    def __init__(self, file: str):
        self.file = file
        self.reads: list[_EnvRead] = []
        self.os_names: set[str] = {"os"}       # names bound to the os module
        self.environ_names: set[str] = set()   # names bound to os.environ
        self.getenv_names: set[str] = set()    # names bound to os.getenv

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "os":
                self.os_names.add(alias.asname or "os")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "os" and not node.level:
            for alias in node.names:
                if alias.name == "environ":
                    self.environ_names.add(alias.asname or "environ")
                elif alias.name == "getenv":
                    self.getenv_names.add(alias.asname or "getenv")
        self.generic_visit(node)

    def _is_os_environ(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in self.environ_names:
            return True
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.os_names
        )

    def _is_getenv(self, func: ast.AST) -> bool:
        if isinstance(func, ast.Name) and func.id in self.getenv_names:
            return True
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id in self.os_names
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_os_environ(node.value):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.reads.append(_EnvRead(key.value, self.file, node.lineno, has_default=False))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name: str | None = None
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and self._is_os_environ(func.value)
        ):
            name = "environ.get"
        elif self._is_getenv(func):
            name = "getenv"
        if name and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                has_default = len(node.args) >= 2 or any(
                    kw.arg == "default" for kw in node.keywords
                )
                self.reads.append(
                    _EnvRead(first.value, self.file, node.lineno, has_default=has_default)
                )
        self.generic_visit(node)


def _scan_python(path: Path, relpath: str) -> list[_EnvRead]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _scan_python_fallback(source, relpath)
    visitor = _PyEnvVisitor(relpath)
    visitor.visit(tree)
    return visitor.reads


def _scan_python_fallback(source: str, relpath: str) -> list[_EnvRead]:
    reads: list[_EnvRead] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for pattern in PY_FALLBACK_REQUIRED:
            for match in pattern.finditer(line):
                reads.append(_EnvRead(match.group(1), relpath, lineno, has_default=False))
    return reads


def _strip_js_comments(source: str) -> str:
    """Blank out ``//`` line tails and ``/* ... */`` blocks.

    Comment text is replaced with spaces (newlines kept) so line numbers
    are preserved. Quote-aware: ``//`` and ``/*`` inside '…', "…" or `…`
    string literals are left alone (so URLs like http://x survive).
    Regex literals are not modeled — good enough for env-read scanning.
    """
    out: list[str] = []
    i, n = 0, len(source)
    state: str | None = None  # None | "'" | '"' | '`' | "line" | "block"
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                out.append("  ")
                i += 2
                continue
            if c in "'\"`":
                state = c
            out.append(c)
        elif state == "line":
            if c == "\n":
                state = None
                out.append(c)
            else:
                out.append(" ")
        elif state == "block":
            if c == "*" and nxt == "/":
                state = None
                out.append("  ")
                i += 2
                continue
            out.append(c if c == "\n" else " ")
        else:  # inside a string literal
            if c == "\\":
                out.append(c)
                out.append(nxt)
                i += 2
                continue
            if c == state or (c == "\n" and state in "'\""):
                state = None
            out.append(c)
        i += 1
    return "".join(out)


def _scan_js(path: Path, relpath: str) -> list[_EnvRead]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    source = _strip_js_comments(source)
    reads: list[_EnvRead] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for pattern in JS_PATTERNS:
            for match in pattern.finditer(line):
                name = match.group(1)
                if name in JS_BUILTIN_NAMES:
                    continue
                # `process.env.X || fallback` / `?? fallback` = default.
                has_default = bool(_JS_DEFAULT_TAIL_RE.match(line, match.end()))
                reads.append(_EnvRead(name, relpath, lineno, has_default=has_default))
        for dmatch in JS_DESTRUCTURE_RE.finditer(line):
            for part in dmatch.group(1).split(","):
                part = part.strip()
                entry = _DESTRUCTURE_ENTRY_RE.match(part) if part else None
                if not entry:
                    continue  # empty slot or ...rest spread
                name = entry.group(1)
                if name in JS_BUILTIN_NAMES:
                    continue
                reads.append(
                    _EnvRead(name, relpath, lineno, has_default=entry.group(2) is not None)
                )
    return reads


def collect_env_reads(ctx: CheckContext) -> list[_EnvRead]:
    reads: list[_EnvRead] = []
    for path in ctx.files:
        suffix = path.suffix.lower()
        relpath = rel(path, ctx.root)
        if suffix in PY_EXTENSIONS:
            reads.extend(_scan_python(path, relpath))
        elif suffix in JS_EXTENSIONS:
            reads.extend(_scan_js(path, relpath))
    return reads


@register
def check_env_vars(ctx: CheckContext) -> CheckResult:
    reads = collect_env_reads(ctx)

    # A name is required unless *every* read of it carries a default.
    # Dedupe by name, keeping the first reference (file order, then line).
    required: dict[str, _EnvRead] = {}
    satisfied_only: set[str] = set()
    for read in reads:
        if read.has_default:
            satisfied_only.add(read.name)
            continue
        if read.name not in required:
            required[read.name] = read

    missing = [read for name, read in required.items() if name not in ctx.env]
    if not missing:
        return CheckResult(name="env_vars", passed=True)

    missing.sort(key=lambda r: (r.file, r.line))
    evidence = [Evidence(file=r.file, line=r.line, detail=r.name) for r in missing]
    exports = "; ".join(f"export {r.name}=<value>" for r in missing)
    return CheckResult(
        name="env_vars",
        passed=False,
        failure_class="missing_env_var",
        evidence=evidence,
        evidence_suffix="unset",
        fix_hint=f"Set the missing env vars in the deploy environment: {exports}",
    )
