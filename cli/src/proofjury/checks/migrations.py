"""pending_migration — a schema source changed with no migration change.

Deterministic proxy, no DB connection: if an uncommitted change touches a
known schema source but nothing under the framework's migrations directory
changed (staged, unstaged, or untracked — a fresh migration file is usually
untracked), the deploy would run new code against an old schema.

Built-in rules cover Prisma and Django. Other stacks (alembic, Rails, …)
opt in via ``.proofjury.toml``::

    [checks.migrations]
    schema = ["db/schema.rb"]
    migrations_dir = "db/migrate"

Alembic is config-only by design: SQLAlchemy models have no canonical path,
and guessing would trade one false negative for many false positives.
Skipped outside a git repo or when no schema source changed.
"""

from __future__ import annotations

import fnmatch

from .base import CheckContext, CheckResult, Evidence, register
from .diffbase import changed_paths

#: (marker file that makes the rule applicable, schema globs, migrations dir)
_BUILTIN_RULES: list[tuple[str, list[str], str]] = [
    ("prisma/schema.prisma", ["prisma/schema.prisma"], "prisma/migrations"),
    # Django: any app's models.py; migrations live in a sibling migrations/
    # package — any change under */migrations/ counts.
    ("manage.py", ["models.py", "*/models.py", "**/models.py"], "migrations"),
]


def _matches(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _under_migrations(path: str, migrations_dir: str) -> bool:
    return path.startswith(migrations_dir.rstrip("/") + "/") or (
        f"/{migrations_dir.rstrip('/')}/" in path
    )


@register
def check_migrations(ctx: CheckContext) -> CheckResult:
    changed = changed_paths(ctx.root)
    if changed is None:
        return CheckResult(name="migrations", passed=True, skipped=True)

    rules: list[tuple[list[str], str]] = []
    for marker, schema_globs, migrations_dir in _BUILTIN_RULES:
        if (ctx.root / marker).exists():
            rules.append((schema_globs, migrations_dir))
    custom = (ctx.config.get("checks") or {}).get("migrations") or {}
    custom_schema = custom.get("schema")
    if isinstance(custom_schema, list) and custom_schema:
        rules.append(
            ([str(g) for g in custom_schema], str(custom.get("migrations_dir") or "migrations"))
        )
    if not rules:
        return CheckResult(name="migrations", passed=True, skipped=True)

    evidence: list[Evidence] = []
    for schema_globs, migrations_dir in rules:
        touched = [p for p in changed if _matches(p, schema_globs)]
        if not touched:
            continue
        if any(_under_migrations(p, migrations_dir) for p in changed):
            continue  # a migration rode along with the schema change
        for path in touched:
            evidence.append(
                Evidence(
                    file=path,
                    line=1,
                    detail=f"schema changed with no change under {migrations_dir}/",
                )
            )
    if not evidence:
        return CheckResult(name="migrations", passed=True)
    return CheckResult(
        name="migrations",
        passed=False,
        failure_class="pending_migration",
        evidence=evidence,
        fix_hint=(
            "Generate and commit a migration for the schema change "
            "(e.g. `prisma migrate dev` / `python manage.py makemigrations`), "
            "or revert the schema edit."
        ),
    )
