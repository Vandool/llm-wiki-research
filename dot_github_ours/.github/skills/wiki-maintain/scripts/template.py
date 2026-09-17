#!/usr/bin/env python3
"""template.py — print the page template for a page type with placeholders substituted.

CLI:
  template.py TYPE [--vars k=v ...] [--json] [--list]
    TYPE: Module | Concept | How-to | Runbook | Architecture | Contract Guide | Feature | Analysis | Conventions
    --vars   extra `{{name}}` substitutions (e.g. slug=orders title="Orders service")
    --list   print the type → file → required headings table
    --json   {type, file, text, headings[], max_lines}
Templates live in `references/templates/` next to this scripts dir; env WIKI_TEMPLATES_DIR overrides.
Standard placeholders: repo_slug, id_prefix, site_title, date, head, model, user, team, wiki_dir.
Exit 0 ok · 2 unknown type · 3 template file missing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, config as wconfig, gitio  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "template"

TEMPLATE_FILES = {
    "Module": "module.md", "Concept": "concept.md", "How-to": "howto.md", "Runbook": "runbook.md",
    "Architecture": "architecture.md", "Contract Guide": "contract-guide.md", "Feature": "feature.md",
    "Analysis": "analysis.md", "Conventions": "conventions.md",
}

# Fixed heading order per type (plan §8.8.2). Bold ledes are listed with their marker text.
TYPE_HEADINGS = {
    "Module": ["**Does:**", "## Structure", "## Configuration", "## Tests", "## Gotchas"],
    "Concept": ["**Problem.**", "**Solution here.**", "**Consequences.**", "**Where to look.**"],
    "How-to": ["## Goal", "## Steps", "## Validation", "## Related code"],
    "Runbook": ["## Trigger", "## Steps", "## Verify", "## Escalate"],
    "Architecture": ["## Context", "## Containers", "## Runtime flows", "## Deployment"],
    "Contract Guide": ["## Purpose", "## Callers", "## Semantics", "## Errors", "## Versioning"],
    "Feature": ["**In plain words.**", "## Who uses it", "## How it behaves", "## Limits and known issues",
                "## What changed recently", "## Related features", "## For developers"],
    "Analysis": ["## Question", "## Answer", "## Evidence", "## Open questions"],
    "Conventions": ["## Glossary", "## Naming", "## Page templates (heading order per type)",
                    "## Citation microformat", "## Operational invariants to state consistently"],
    "Overview": ["## What it is", "## Who uses it", "## How a request flows", "## Where to start"],
}

_ALIASES = {"howto": "How-to", "how-to": "How-to", "contract-guide": "Contract Guide", "contractguide": "Contract Guide"}


def canonical_type(name: str) -> Optional[str]:
    if name in TEMPLATE_FILES or name in TYPE_HEADINGS:
        return name
    key = name.strip().lower().replace("_", "-")
    if key in _ALIASES:
        return _ALIASES[key]
    for t in TEMPLATE_FILES:
        if t.lower() == key or t.lower().replace(" ", "-") == key:
            return t
    return None


def templates_dir() -> Path:
    env = os.environ.get("WIKI_TEMPLATES_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "references" / "templates"


def template_path(page_type: str) -> Path:
    return templates_dir() / TEMPLATE_FILES[page_type]


def headings_for(page_type: str) -> list[str]:
    return list(TYPE_HEADINGS.get(page_type, []))


def render(page_type: str, cfg, variables: Optional[dict] = None, *, head: str = "", date: str = "",
           user: str = "", model: str = "") -> str:
    """Template text with placeholders substituted (unknown placeholders stay as they are)."""
    path = template_path(page_type)
    if not path.exists():
        raise cli.EnvError(f"template file missing: {path}")
    base = wconfig.scaffold_vars(cfg, head=head, user=user, model=model, date=date)
    base.update(variables or {})
    return wconfig.scaffold(path.read_text(encoding="utf-8"), base)


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    p.add_argument("type", nargs="?", help="page type (see --list)")
    p.add_argument("--vars", nargs="*", default=[], metavar="k=v", help="extra placeholder values")
    p.add_argument("--list", action="store_true", help="list types, files and required headings")
    return p


def main(args) -> int:
    try:
        ctx = cli.Ctx(args, need_config=True, need_repo=True)
    except cli.EnvError:
        ctx = cli.Ctx(args, need_config=True, need_repo=False)
    if args.list or not args.type:
        rows = [{"type": t, "file": f, "headings": headings_for(t), "exists": template_path(t).exists()}
                for t, f in TEMPLATE_FILES.items()]
        for r in rows:
            ctx.emit.out(f"{r['type']:<15} {r['file']:<18} {'ok' if r['exists'] else 'MISSING':<8} {' → '.join(r['headings'])}")
        ctx.emit.emit({"templates": rows, "dir": str(templates_dir())})
        return 0 if args.list else cli.EXIT_USAGE
    page_type = canonical_type(args.type)
    if page_type is None or page_type not in TEMPLATE_FILES:
        raise cli.ConfigError(f"unknown page type {args.type!r}; one of {', '.join(TEMPLATE_FILES)}")
    variables = {}
    for kv in args.vars:
        if "=" not in kv:
            raise cli.ConfigError(f"--vars expects k=v, got {kv!r}")
        k, v = kv.split("=", 1)
        variables[k.strip()] = v
    head = gitio.head(ctx.repo) or "" if ctx.repo else ""
    user = variables.get("user") or gitio.config_get("user.name", ctx.repo) or os.environ.get("USER", "") if ctx.repo else os.environ.get("USER", "")
    text = render(page_type, ctx.cfg, variables, head=head, date=cli.iso(ctx.now), user=user or "",
                  model=variables.get("model", ""))
    ctx.emit.out(text.rstrip("\n"))
    ctx.emit.emit({"type": page_type, "file": str(template_path(page_type)), "text": text,
                   "headings": headings_for(page_type), "max_lines": ctx.cfg.max_lines(page_type)})
    return 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
