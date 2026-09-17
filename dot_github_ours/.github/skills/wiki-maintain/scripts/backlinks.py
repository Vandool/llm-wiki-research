#!/usr/bin/env python3
"""backlinks.py — link graph, orphans (L02), broken targets and `related` suggestions.

CLI: backlinks.py (--changed | --all) [--json] [--check] [--suggest] [--plan FILE] [--graph OUT] [--base SHA]
  --changed   report only pages changed in the working tree (plus --base..HEAD)
  --all       report every page
  --check     exit 1 on orphan errors or broken links
  --suggest   propose up to 3 `related` ids per page (pages sharing >= 2 source paths or tags)
  --plan      wiki/.wiki-plan.json (auto-detected): planned pages count as valid link targets and, while
              the plan still has clusters not done, orphan errors are downgraded to warnings
  --graph     write the graph {page: {out, in, related}} as JSON
Orphan = no inbound link from a non-index page and not in any `related`; warning, error for Module and
Feature; exempt: root files, indexes, log archives, owner: process pages.
Output: {orphans[{file, type, severity, message}], broken[{file, line, target, severity}], suggestions{},
         planned, plan_active}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio, pages as wpages  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "backlinks"
PLAN_NAME = ".wiki-plan.json"


def load_plan(wiki_dir: Path, explicit: Optional[str] = None, repo: Optional[Path] = None) -> tuple[set[str], bool]:
    """(planned page rels, plan_active). Missing/invalid plan → (set(), False)."""
    path = Path(explicit) if explicit else wiki_dir / PLAN_NAME
    if explicit and not path.is_absolute() and repo is not None and not path.exists():
        path = repo / explicit
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), False
    planned: set[str] = set()
    active = False
    for c in plan.get("clusters") or []:
        if c.get("status") != "done":
            active = True
        for pg in c.get("pages") or []:
            if isinstance(pg, dict) and pg.get("path"):
                planned.add(str(pg["path"]))
    return planned, active


def orphans(pages: list[wpages.Page], graph: dict, planned: set[str] = frozenset(), plan_active: bool = False) -> list[dict]:
    out: list[dict] = []
    index_rels = {p.rel for p in pages if p.is_index}
    for p in pages:
        if p.is_index or wpages.is_root_file(p.rel) or p.rel.startswith("log/") or p.owner == "process" \
                or wpages.is_process_owned(p.rel):
            continue
        inbound = {r for r in graph.get(p.rel, {}).get("in", set()) if r not in index_rels}
        related = graph.get(p.rel, {}).get("related", set())
        if inbound or related:
            continue
        severity = "error" if p.type in ("Module", "Feature") else "warning"
        note = ""
        if severity == "error" and plan_active:
            severity = "warning"
            note = " (downgraded: the cluster plan still has pending clusters)"
        out.append({"file": p.rel, "type": p.type, "severity": severity,
                    "message": f"orphan page: no inbound link from a non-index page and not in any `related`{note}",
                    "fix": "link it from a topically adjacent page (index links do not count) or add it to a page's `related`"})
    return out


def broken_links(pages: list[wpages.Page], planned: set[str] = frozenset()) -> list[dict]:
    rels = {p.rel for p in pages}
    out: list[dict] = []
    for p in pages:
        for l in wpages.links(p.body):
            r = wpages.classify(p.rel, l.target)
            if r.kind != "internal" or r.rel in rels:
                continue
            if r.rel in planned:
                out.append({"file": p.rel, "line": p.line_of(l.line), "target": l.target, "severity": "info",
                            "message": f"link target {r.rel} is a planned page not written yet"})
                continue
            if p.owner == "process" and r.rel.endswith("-guide.md"):
                out.append({"file": p.rel, "line": p.line_of(l.line), "target": l.target, "severity": "info",
                            "message": f"written guide {r.rel} not created yet"})
                continue
            out.append({"file": p.rel, "line": p.line_of(l.line), "target": l.target, "severity": "error",
                        "message": f"broken link: {r.rel} does not exist"})
    return out


def suggestions(pages: list[wpages.Page], prefix: str, only: Optional[Iterable[str]] = None, limit: int = 3) -> dict[str, list[str]]:
    feats: dict[str, tuple[set[str], set[str]]] = {}
    for p in pages:
        if p.is_index or p.owner == "process":
            continue
        paths = {path for _, path, _ in wpages.source_paths(p)}
        tags = {str(t) for t in (p.fm.get("tags") or []) if isinstance(t, str)}
        feats[p.rel] = (paths, tags)
    out: dict[str, list[str]] = {}
    targets = set(only) if only is not None else set(feats)
    for rel in sorted(targets):
        if rel not in feats:
            continue
        paths, tags = feats[rel]
        scored = []
        for other, (op, ot) in feats.items():
            if other == rel:
                continue
            score = len(paths & op) + len(tags & ot)
            if score >= 2:
                scored.append((-score, other))
        ids = [wpages.page_id(prefix, o) for _, o in sorted(scored)[:limit]]
        if ids:
            out[rel] = ids
    return out


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--changed", action="store_true", help="only pages changed in the working tree")
    g.add_argument("--all", action="store_true", help="every page (default when neither --changed nor --all is given)")
    p.add_argument("--check", action="store_true", help="exit 1 on orphan errors / broken links")
    p.add_argument("--suggest", action="store_true", help="propose related ids")
    p.add_argument("--plan", default=None, help="cluster plan file (default: <wiki>/.wiki-plan.json when present)")
    p.add_argument("--graph", default=None, help="write the link graph JSON to this path")
    p.add_argument("--base", default=None, help="also treat files changed in BASE..HEAD as changed")
    return p


def main(args) -> int:
    if not args.changed and not args.all:
        args.all = True  # bare `backlinks.py --check` (CI include, plan §8.11) means --all
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    wiki = ctx.wiki_dir
    if not wiki.is_dir():
        raise cli.EnvError(f"wiki directory missing: {wiki}")
    pages = wpages.walk(wiki)
    prefix = ctx.cfg.id_prefix
    graph = wpages.link_graph(pages, prefix)
    planned, plan_active = load_plan(wiki, args.plan, ctx.repo)
    scope: Optional[set[str]] = None
    if args.changed:
        wd = ctx.cfg.wiki_dir
        changed = gitio.changed_paths(ctx.repo, [wd], base=args.base)
        scope = {c[len(wd) + 1:] for c in changed if c.startswith(wd + "/") and c.endswith(".md")}
    orph = [o for o in orphans(pages, graph, planned, plan_active) if scope is None or o["file"] in scope]
    broken = [b for b in broken_links(pages, planned) if scope is None or b["file"] in scope]
    sugg = suggestions(pages, prefix, only=scope) if args.suggest else {}
    if args.graph:
        Path(args.graph).parent.mkdir(parents=True, exist_ok=True)
        Path(args.graph).write_text(json.dumps({k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in sorted(graph.items())},
                                               indent=2) + "\n", encoding="utf-8")
    wd = ctx.cfg.wiki_dir
    for b in broken:
        ctx.emit.say(f"{wd}/{b['file']}:{b['line']}: L01 {b['severity']}: {b['message']}")
    for o in orph:
        ctx.emit.say(f"{wd}/{o['file']}: L02 {o['severity']}: {o['message']}")
    for rel, ids in sugg.items():
        ctx.emit.say(f"{wd}/{rel}: suggest related: {', '.join(ids)}")
    n_err = sum(1 for o in orph if o["severity"] == "error") + sum(1 for b in broken if b["severity"] == "error")
    ctx.emit.say(f"backlinks: {len(orph)} orphan(s), {len(broken)} broken link(s), {n_err} error(s)"
                 + (f"; plan active with {len(planned)} planned pages" if plan_active else ""))
    ok = n_err == 0
    ctx.emit.emit({"orphans": orph, "broken": broken, "suggestions": sugg, "planned": len(planned), "plan_active": plan_active,
                   "pages": len(pages)}, ok=ok)
    return cli.EXIT_FINDINGS if (args.check and not ok) else 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
