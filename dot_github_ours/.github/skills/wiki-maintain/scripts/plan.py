#!/usr/bin/env python3
"""plan.py — cluster plan for the bootstrap (`<wiki>/.wiki-plan.json`, plan §8.7.3).

CLI:
  plan.py build [--json] [--out FILE]             propose clusters from the inventory + internal dependency
                                                   graph (leaves first), sized by budgets.max_source_bytes_per_cluster
                                                   and max_pages_per_cluster, seeded with instructions.md §4/§5
                                                   must-includes and the PO layer; writes <git-dir>/wiki/plan-proposal.json
  plan.py commit [--from FILE] [--approved-by USER] validate the proposal and write <wiki>/.wiki-plan.json
  plan.py show ID [--json]
  plan.py mark ID pending|running|done|deferred|failed [--reason TEXT] [--commit SHA] [--duration N]
                                                   [--pages-written N] [--lint-errors N]
  plan.py split ID                                divide an over-budget cluster (sub-directories, then file groups,
                                                   then #La-Lb ranges of one file's top-level symbols)
  plan.py next [--json]                           first pending cluster whose deps are done (`["*"]` = after all)
  plan.py estimate [--json] [--model M]           credits from source bytes (README §6 assumptions)
  plan.py status [--json]
Cluster status: pending | running | done | deferred | failed | split.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio, pages as wpages, symbols as wsymbols, textnorm  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "plan"
PLAN_NAME = ".wiki-plan.json"
STATUSES = ("pending", "running", "done", "deferred", "failed", "split")
GENERIC_ROOTS = {"src", "app", "lib", "pkg", "cmd", "services", "packages", "apps", "internal"}
PRICES = {  # $ per million tokens (in, out) — README §6
    "gpt-5-mini": (0.25, 2.0), "claude-haiku-4.5": (1.0, 5.0), "claude-sonnet-4.6": (3.0, 15.0),
}
TOKENS_OUT_PER_CLUSTER = 15_000
TOKENS_IN_OVERHEAD = 20_000
TOKENS_IN_CAP = 150_000


def proposal_path(ctx: cli.Ctx) -> Path:
    return ctx.state_dir / "plan-proposal.json"


def load_plan(wiki: Path) -> dict:
    p = wiki / PLAN_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        raise cli.EnvError(f"{p} not found; run plan.py build, then plan.py commit")
    except ValueError as e:
        raise cli.EnvError(f"{p}: invalid JSON: {e}")


def save_plan(wiki: Path, plan: dict) -> None:
    (wiki / PLAN_NAME).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def plan_hash(clusters: list[dict]) -> str:
    core = [{"id": c["id"], "deps": c.get("deps", []), "pages": [{"path": p["path"], "sources": p.get("sources", [])} for p in c.get("pages", [])]}
            for c in clusters]
    return textnorm.sha256_text(json.dumps(core, sort_keys=True))


# ---------------------------------------------------------------- dependency graph

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
_JS_IMPORT = re.compile(r"(?:from\s+|import\s*\(?\s*|require\s*\(\s*)['\"](\.{1,2}/[^'\"]+)['\"]")
_GO_IMPORT = re.compile(r"\"([\w./-]+)\"")
_JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)


def imports_of(path: str, text: str, tracked: set[str], go_module: str = "") -> set[str]:
    """Repository paths this file imports (best effort, internal only)."""
    lang = wsymbols.language_of(path)
    out: set[str] = set()
    if lang == "python":
        for m in _PY_IMPORT.finditer(text):
            mod = (m.group(1) or m.group(2) or "").strip()
            if not mod:
                continue
            if mod.startswith("."):
                base = path.rsplit("/", 1)[0] if "/" in path else ""
                dots = len(mod) - len(mod.lstrip("."))
                for _ in range(dots - 1):
                    base = base.rsplit("/", 1)[0] if "/" in base else ""
                rest = mod.lstrip(".").replace(".", "/")
                cands = [f"{base}/{rest}.py", f"{base}/{rest}/__init__.py"] if base else [f"{rest}.py", f"{rest}/__init__.py"]
            else:
                rel = mod.replace(".", "/")
                cands = [f"{rel}.py", f"{rel}/__init__.py"]
                top = path.split("/", 1)[0] if "/" in path else ""
                if top:
                    cands += [f"{top}/{rel}.py", f"{top}/{rel}/__init__.py"]
            for c in cands:
                c = c.lstrip("/")
                if c in tracked:
                    out.add(c)
                    break
                parent = c.rsplit("/", 1)[0] if "/" in c else ""
                if parent and f"{parent}.py" in tracked:
                    out.add(f"{parent}.py")
                    break
    elif lang in ("javascript", "typescript"):
        base = path.rsplit("/", 1)[0] if "/" in path else ""
        for m in _JS_IMPORT.finditer(text):
            target = m.group(1)
            joined = _normpath(f"{base}/{target}" if base else target)
            for c in (joined, *[f"{joined}{ext}" for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs")],
                      *[f"{joined}/index{ext}" for ext in (".ts", ".tsx", ".js", ".jsx")]):
                if c in tracked:
                    out.add(c)
                    break
    elif lang == "go" and go_module:
        for m in _GO_IMPORT.finditer(text):
            imp = m.group(1)
            if imp.startswith(go_module + "/") or imp == go_module:
                d = imp[len(go_module):].lstrip("/")
                for f in tracked:
                    if f.endswith(".go") and (f.rsplit("/", 1)[0] if "/" in f else "") == d:
                        out.add(f)
    elif lang == "java":
        for m in _JAVA_IMPORT.finditer(text):
            parts = m.group(1).split(".")
            for n in range(len(parts), 1, -1):
                suffix = "/".join(parts[:n]) + ".java"
                hit = next((f for f in tracked if f.endswith("/" + suffix) or f == suffix), None)
                if hit:
                    out.add(hit)
                    break
    return out


def _normpath(p: str) -> str:
    import posixpath

    return posixpath.normpath(p)


# ---------------------------------------------------------------- build

def instructions_must_include(wiki: Path) -> tuple[list[str], list[str]]:
    """Bullets under instructions.md §4 (concepts) and §5 (flows)."""
    p = wiki / "instructions.md"
    if not p.exists():
        return [], []
    text = p.read_text(encoding="utf-8", errors="replace")
    concepts: list[str] = []
    flows: list[str] = []
    cur: Optional[list[str]] = None
    for line in text.split("\n"):
        if line.startswith("## "):
            h = line.lower()
            cur = concepts if ("must-include concept" in h or re.match(r"^## 4\.", line)) else \
                flows if ("must-include flow" in h or re.match(r"^## 5\.", line)) else None
            continue
        if cur is not None and re.match(r"^\s*[-*]\s+\S", line):
            item = re.sub(r"^\s*[-*]\s+", "", line).strip()
            if item and item not in ("…", "...") and not item.startswith("<!--"):
                cur.append(item)
    return concepts, flows


class Builder:
    def __init__(self, ctx: cli.Ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.repo = ctx.repo
        self.wiki = ctx.wiki_dir
        self.tracked = set(gitio.ls_files(self.repo))
        self.excludes = list(self.cfg.get("sources.exclude") or [])
        self.roots = [str(r).rstrip("/") for r in (self.cfg.get("sources.include") or [])]
        self.max_bytes = int(self.cfg.budget("max_source_bytes_per_cluster") or 120000)
        self.max_pages = int(self.cfg.budget("max_pages_per_cluster") or 6)
        self.min_files = int(self.cfg.get("coverage.min_files") or 3)
        self.depth = int(self.cfg.get("coverage.depth") or 2)
        self.ignore_tests = bool(self.cfg.get("coverage.ignore_tests", True))
        self.go_module = ""
        if "go.mod" in self.tracked:
            m = re.search(r"^module\s+(\S+)", (self.repo / "go.mod").read_text(encoding="utf-8", errors="replace"), re.M)
            self.go_module = m.group(1) if m else ""

    def code_files(self) -> list[str]:
        out = []
        for f in sorted(self.tracked):
            if wpages.is_excluded(f, self.excludes) or not wsymbols.language_of(f):
                continue
            if self.ignore_tests and wpages.is_test_path(f):
                continue
            if f.startswith(self.cfg.wiki_dir + "/"):
                continue
            if any(f == r or f.startswith(r + "/") for r in self.roots):
                out.append(f)
        return out

    def size(self, f: str) -> int:
        try:
            return (self.repo / f).stat().st_size
        except OSError:
            return 0

    def cluster_id(self, dir_path: str) -> str:
        parts = dir_path.split("/")
        if len(parts) > 1 and parts[0] in GENERIC_ROOTS:
            parts = parts[1:]
        return textnorm.slugify("-".join(parts)) or "root"

    def group_dirs(self, files: list[str]) -> dict[str, list[str]]:
        """Directory → files, one level below each root (deeper when a root has no sub-directories)."""
        groups: dict[str, list[str]] = {}
        for f in files:
            root = next((r for r in self.roots if f == r or f.startswith(r + "/")), None)
            if root is None:
                continue
            rel = f[len(root) + 1:] if f != root else f
            parts = rel.split("/")
            key = f"{root}/{parts[0]}" if len(parts) > 1 else root
            groups.setdefault(key, []).append(f)
        # files directly under a root join the root group only when there are enough of them
        for key in list(groups):
            if key in self.roots and len(groups[key]) < self.min_files:
                # attach loose root files to the largest sibling group so nothing is lost
                siblings = [k for k in groups if k.startswith(key + "/")]
                if siblings:
                    target = max(siblings, key=lambda k: len(groups[k]))
                    groups[target] = sorted(groups[target] + groups.pop(key))
        return dict(sorted(groups.items()))

    def split_group(self, key: str, files: list[str], cid: str) -> list[tuple[str, str, list[str], list[str]]]:
        """(cluster id, dir, files, sources) chunks within the byte budget."""
        total = sum(self.size(f) for f in files)
        if total <= self.max_bytes:
            return [(cid, key, files, [f"repo://{key}/"])]
        # by sub-directory
        subs: dict[str, list[str]] = {}
        for f in files:
            rel = f[len(key) + 1:] if f.startswith(key + "/") else f
            sub = f"{key}/{rel.split('/')[0]}" if "/" in rel else key
            subs.setdefault(sub, []).append(f)
        out = []
        if len(subs) > 1:
            for sub, sfiles in sorted(subs.items()):
                sub_id = cid if sub == key else f"{cid}-{textnorm.slugify(sub.rsplit('/', 1)[-1])}"
                out.extend(self.split_group(sub, sfiles, sub_id))
            return out
        # by file groups
        chunk: list[str] = []
        chunk_bytes = 0
        n = 1
        for f in sorted(files, key=lambda x: (-self.size(x), x)):
            fb = self.size(f)
            if fb > self.max_bytes:
                out.extend(self.split_file(f, f"{cid}-{n}"))
                n += 1
                continue
            if chunk and chunk_bytes + fb > self.max_bytes:
                out.append((f"{cid}-{n}", key, sorted(chunk), [f"repo://{x}" for x in sorted(chunk)]))
                n += 1
                chunk, chunk_bytes = [], 0
            chunk.append(f)
            chunk_bytes += fb
        if chunk:
            out.append((f"{cid}-{n}" if n > 1 else cid, key, sorted(chunk), [f"repo://{x}" for x in sorted(chunk)]))
        return out

    def split_file(self, f: str, cid: str) -> list[tuple[str, str, list[str], list[str]]]:
        """One over-budget file → clusters of #La-Lb ranges cut at top-level symbol boundaries."""
        try:
            text = (self.repo / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [(cid, f.rsplit("/", 1)[0], [f], [f"repo://{f}"])]
        idx = wsymbols.index_file(f, text) or {"symbols": []}
        lines = text.split("\n")
        tops = [s for s in idx.get("symbols", []) if "." not in s["name"]]
        ranges: list[tuple[int, int]] = []
        start = 1
        acc = 0
        for s in tops:
            a, b = s["lines"]
            seg = sum(len(l) + 1 for l in lines[start - 1:b])
            if acc and acc + seg > self.max_bytes:
                ranges.append((start, a - 1))
                start, acc = a, 0
            acc += seg if not acc else seg - acc if False else seg
        ranges.append((start, len(lines)))
        out = []
        for n, (a, b) in enumerate(ranges, 1):
            out.append((f"{cid}-{n}" if len(ranges) > 1 else cid, f.rsplit("/", 1)[0] if "/" in f else "", [f], [f"repo://{f}#L{a}-L{b}"]))
        return out

    def build(self) -> dict:
        files = self.code_files()
        groups = self.group_dirs(files)
        chunks: list[tuple[str, str, list[str], list[str]]] = []
        for key, gfiles in groups.items():
            chunks.extend(self.split_group(key, gfiles, self.cluster_id(key)))
        # dedupe ids
        seen: dict[str, int] = {}
        fixed = []
        for cid, key, cfiles, sources in chunks:
            if cid in seen:
                seen[cid] += 1
                cid = f"{cid}-{seen[cid]}"
            else:
                seen[cid] = 1
            fixed.append((cid, key, cfiles, sources))
        chunks = fixed
        file_to_cluster = {f: cid for cid, _, cfiles, _ in chunks for f in cfiles}
        deps: dict[str, set[str]] = {cid: set() for cid, *_ in chunks}
        for cid, _, cfiles, _ in chunks:
            for f in cfiles:
                try:
                    text = (self.repo / f).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for imp in imports_of(f, text, self.tracked, self.go_module):
                    other = file_to_cluster.get(imp)
                    if other and other != cid:
                        deps[cid].add(other)
        clusters: list[dict] = []
        for cid, key, cfiles, sources in chunks:
            langs: dict[str, int] = {}
            for f in cfiles:
                lg = wsymbols.language_of(f) or "other"
                langs[lg] = langs.get(lg, 0) + 1
            title = key.rsplit("/", 1)[-1].replace("_", " ").replace("-", " ")
            title = title[:1].upper() + title[1:]
            page = {"path": f"modules/{cid}.md", "type": "Module", "audience": ["agent", "dev"], "owner": "agent", "sources": sources,
                    "notes": f"{len(cfiles)} files, " + ", ".join(f"{k} {v}" for k, v in sorted(langs.items()))}
            clusters.append(self._cluster(cid, f"{title} module", "module", sorted(deps[cid]), [page], sum(self.size(f) for f in cfiles), cfiles))
        # contract guides
        specs = {}
        try:
            specs = json.loads((self.wiki / "generated" / "specs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        guide_pages = []
        guide_deps: set[str] = set()
        for api_id, api in sorted((specs.get("apis") or {}).items()):
            for slug, rel in sorted((api.get("groups") or {}).items()):
                guide = rel[:-3] + "-guide.md"
                handlers: set[str] = set()
                sym = {}
                try:
                    sym = json.loads((self.wiki / "generated" / "symbols.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                for path, entry in sym.items():
                    for r in entry.get("routes", []):
                        for op in (api.get("operations") or {}).values():
                            if op.get("group") == slug and r["path"] == op.get("path") and r["method"] == op.get("method"):
                                handlers.add(path)
                for h in handlers:
                    if h in file_to_cluster:
                        guide_deps.add(file_to_cluster[h])
                guide_pages.append({"path": guide, "type": "Contract Guide", "audience": ["agent", "dev"], "owner": "agent",
                                    "sources": [f"api://{api_id}"] + [f"repo://{h}" for h in sorted(handlers)],
                                    "notes": f"written guide next to {rel}"})
        for channel, ev in sorted((specs.get("events") or {}).items()):
            guide_pages.append({"path": ev["page"][:-3] + "-guide.md", "type": "Contract Guide", "audience": ["agent", "dev"], "owner": "agent",
                                "sources": [f"event://{channel}"], "notes": f"written guide next to {ev['page']}"})
        for i in range(0, len(guide_pages), self.max_pages):
            batch = guide_pages[i:i + self.max_pages]
            cid = "contract-guides" if i == 0 else f"contract-guides-{i // self.max_pages + 1}"
            clusters.append(self._cluster(cid, "Contract guides", "contract", sorted(guide_deps), batch, 0, []))
        # must-includes from instructions.md
        concepts, flows = instructions_must_include(self.wiki)
        if concepts:
            pages = [{"path": f"concepts/{textnorm.slugify(c)}.md", "type": "Concept", "audience": ["agent", "dev"], "owner": "agent",
                      "sources": [], "notes": f"must-include concept from instructions.md: {c}"} for c in concepts]
            for i in range(0, len(pages), self.max_pages):
                cid = "concepts" if i == 0 else f"concepts-{i // self.max_pages + 1}"
                clusters.append(self._cluster(cid, "Must-include concepts", "concept", [c["id"] for c in clusters if c["kind"] == "module"],
                                              pages[i:i + self.max_pages], 0, []))
        if flows:
            pages = [{"path": f"howto/{textnorm.slugify(f)}.md", "type": "How-to", "audience": ["agent", "dev"], "owner": "agent",
                      "sources": [], "notes": f"must-include flow from instructions.md: {f}"} for f in flows]
            for i in range(0, len(pages), self.max_pages):
                cid = "flows" if i == 0 else f"flows-{i // self.max_pages + 1}"
                clusters.append(self._cluster(cid, "Must-include flows", "howto", [c["id"] for c in clusters if c["kind"] == "module"],
                                              pages[i:i + self.max_pages], 0, []))
        if self.cfg.get("po_layer"):
            pages = [{"path": f"product/features/{c['id']}.md", "type": "Feature", "audience": ["po"], "owner": "both",
                      "sources": [], "notes": f"PO view of {c['title']}; cite api://, event://, changelog:// only"}
                     for c in clusters if c["kind"] == "module"]
            for i in range(0, len(pages), self.max_pages):
                cid = "product" if i == 0 else f"product-{i // self.max_pages + 1}"
                clusters.append(self._cluster(cid, "Product features", "product", ["*"], pages[i:i + self.max_pages], 0, []))
        overview_pages = [
            {"path": "overview.md", "type": "Overview", "audience": ["agent", "dev", "po"], "owner": "agent", "sources": [], "notes": "update the scaffold"},
            {"path": "architecture/containers.md", "type": "Architecture", "audience": ["agent", "dev"], "owner": "agent", "sources": [],
             "notes": "Context · Containers · Runtime flows · Deployment"},
            {"path": "glossary.md", "type": "Glossary", "audience": ["po", "dev", "agent"], "owner": "both", "sources": [], "notes": "extend the scaffold"},
        ]
        clusters.append(self._cluster("overview", "Overview, glossary, architecture", "overview", ["*"], overview_pages, 0, []))
        no_page = []
        for f in sorted(self.tracked):
            if f.startswith(("scripts/", "script/", "tools/", "migrations/")) and wsymbols.language_of(f):
                no_page.append({"path": f.split("/", 1)[0] + "/", "reason": "one-off scripts and tooling (confirm)"})
                break
        return {"schema_version": 1, "created_at": cli.iso(self.ctx.now), "created_by": f"process:plan.py/{VERSION}", "approved_by": None,
                "repo": self.cfg.get("repo.slug") or "", "plan_hash": plan_hash(clusters), "clusters": clusters, "no_page": no_page,
                "least_understood": []}

    @staticmethod
    def _cluster(cid: str, title: str, kind: str, deps: list[str], pages: list[dict], source_bytes: int, files: list[str]) -> dict:
        return {"id": cid, "title": title, "kind": kind, "deps": deps, "pages": pages, "estimate": {"source_bytes": source_bytes, "files": len(files)},
                "status": "pending", "attempts": 0, "commit": None, "started": None, "ended": None, "duration_s": None,
                "pages_written": 0, "lint_errors": 0, "log": f".git/wiki/bootstrap-{cid}.log"}


# ---------------------------------------------------------------- validation / order

def validate_plan(plan: dict, wiki_dir: str) -> list[str]:
    errors: list[str] = []
    clusters = plan.get("clusters")
    if not isinstance(clusters, list) or not clusters:
        return ["plan has no clusters"]
    ids = [c.get("id") for c in clusters]
    if len(set(ids)) != len(ids):
        errors.append("cluster ids are not unique")
    known = set(ids)
    paths: set[str] = set()
    for c in clusters:
        if not c.get("id") or not re.match(r"^[a-z0-9][a-z0-9-]*$", str(c["id"])):
            errors.append(f"bad cluster id {c.get('id')!r} (lowercase slug)")
        for d in c.get("deps") or []:
            if d != "*" and d not in known:
                errors.append(f"cluster {c.get('id')}: unknown dep {d!r}")
        if c.get("status") not in STATUSES:
            errors.append(f"cluster {c.get('id')}: bad status {c.get('status')!r}")
        for p in c.get("pages") or []:
            path = str(p.get("path") or "")
            if not path.endswith(".md") or path.startswith(("/", "../")) or ".." in path.split("/") or path.startswith(wiki_dir + "/"):
                errors.append(f"cluster {c.get('id')}: bad page path {path!r} (wiki-relative .md)")
            if path in paths:
                errors.append(f"page {path} planned twice")
            paths.add(path)
    # cycles (ignoring "*")
    graph = {c["id"]: [d for d in (c.get("deps") or []) if d != "*"] for c in clusters if c.get("id")}
    state: dict[str, int] = {}

    def visit(n: str, stack: list[str]) -> None:
        if state.get(n) == 1:
            errors.append("dependency cycle: " + " → ".join(stack + [n]))
            return
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in graph.get(n, []):
            visit(d, stack + [n])
        state[n] = 2

    for n in graph:
        visit(n, [])
    return errors


def next_cluster(plan: dict) -> Optional[dict]:
    clusters = plan.get("clusters") or []
    done = {c["id"] for c in clusters if c.get("status") == "done"}
    finished = done | {c["id"] for c in clusters if c.get("status") == "split"}
    for c in clusters:
        if c.get("status") != "pending":
            continue
        deps = c.get("deps") or []
        if "*" in deps:
            others = [o for o in clusters if o["id"] != c["id"] and "*" not in (o.get("deps") or []) and o.get("status") != "split"]
            if all(o.get("status") == "done" for o in others):
                return c
            continue
        if all(d in finished for d in deps):
            return c
    return None


def estimate(plan: dict, model: str) -> dict:
    price = PRICES.get(model)
    note = None
    if price is None:
        price = PRICES["claude-sonnet-4.6"]
        note = f"unknown model {model!r}; priced like claude-sonnet-4.6"
    rows = []
    total = 0.0
    for c in plan.get("clusters") or []:
        if c.get("status") == "split":
            continue
        sb = int((c.get("estimate") or {}).get("source_bytes") or 0)
        tokens_in = min(TOKENS_IN_CAP, TOKENS_IN_OVERHEAD + sb // 4 + 8_000 * len(c.get("pages") or []))
        tokens_out = TOKENS_OUT_PER_CLUSTER * max(1, len(c.get("pages") or [])) // 3
        credits = (tokens_in * price[0] + tokens_out * price[1]) / 1e6 / 0.01
        rows.append({"id": c["id"], "source_bytes": sb, "pages": len(c.get("pages") or []), "tokens_in": tokens_in, "tokens_out": tokens_out,
                     "credits": round(credits, 1)})
        total += credits
    return {"model": model, "clusters": rows, "total_credits": round(total, 1), "note": note,
            "assumptions": "README §6: ~4 bytes/token, 20k overhead, 15k output tokens per 3 pages, capped at 150k input"}


# ---------------------------------------------------------------- CLI

def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    sub = cli.subparsers(p)
    b = sub.add_parser("build", help="propose clusters")
    b.add_argument("--out", default=None, help="proposal file (default <git-dir>/wiki/plan-proposal.json)")
    c = sub.add_parser("commit", help="write <wiki>/.wiki-plan.json from the proposal")
    c.add_argument("--from", dest="src", default=None)
    c.add_argument("--approved-by", default=None)
    s = sub.add_parser("show")
    s.add_argument("id")
    m = sub.add_parser("mark")
    m.add_argument("id")
    m.add_argument("status", choices=[x for x in STATUSES if x != "split"])
    m.add_argument("--reason", default=None)
    m.add_argument("--commit", dest="commit_sha", default=None)
    m.add_argument("--duration", type=float, default=None)
    m.add_argument("--pages-written", type=int, default=None)
    m.add_argument("--lint-errors", type=int, default=None)
    sp = sub.add_parser("split")
    sp.add_argument("id")
    sub.add_parser("next")
    e = sub.add_parser("estimate")
    e.add_argument("--model", default=None)
    sub.add_parser("status")
    return p


def cmd_build(ctx: cli.Ctx, args) -> int:
    plan = Builder(ctx).build()
    out = Path(args.out) if args.out else proposal_path(ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    errors = validate_plan(plan, ctx.cfg.wiki_dir)
    ctx.emit.say(f"plan: {len(plan['clusters'])} clusters proposed → {out}" + (f"; {len(errors)} validation error(s)" if errors else ""))
    for c in plan["clusters"]:
        ctx.emit.say(f"  {c['id']:<24} {c['kind']:<9} deps={','.join(c['deps']) or '-':<30} pages={len(c['pages'])} bytes={c['estimate']['source_bytes']}")
    ctx.emit.emit({"proposal": str(out), "errors": errors, **plan}, ok=not errors)
    return cli.EXIT_FINDINGS if errors else 0


def cmd_commit(ctx: cli.Ctx, args) -> int:
    src = Path(args.src) if args.src else proposal_path(ctx)
    if not src.is_absolute() and not src.exists():
        src = ctx.repo / src
    try:
        plan = json.loads(src.read_text(encoding="utf-8"))
    except OSError:
        raise cli.EnvError(f"proposal not found: {src} (run plan.py build)")
    except ValueError as e:
        raise cli.ConfigError(f"{src}: invalid JSON: {e}")
    for c in plan.get("clusters") or []:
        c.setdefault("status", "pending")
        for k, v in (("attempts", 0), ("commit", None), ("started", None), ("ended", None), ("duration_s", None), ("pages_written", 0), ("lint_errors", 0)):
            c.setdefault(k, v)
        c.setdefault("log", f".git/wiki/bootstrap-{c.get('id')}.log")
        c.setdefault("estimate", {"source_bytes": 0})
    errors = validate_plan(plan, ctx.cfg.wiki_dir)
    if errors:
        for e in errors:
            ctx.emit.say(f"error: {e}")
        raise cli.ConfigError(f"plan rejected: {len(errors)} error(s)")
    user = args.approved_by or gitio.config_get("user.name", ctx.repo) or "unknown"
    plan["approved_by"] = user if user.startswith("human:") else f"human:{user}"
    plan.setdefault("schema_version", 1)
    plan["created_at"] = plan.get("created_at") or cli.iso(ctx.now)
    plan["created_by"] = plan.get("created_by") or f"process:plan.py/{VERSION}"
    plan["repo"] = plan.get("repo") or ctx.cfg.get("repo.slug") or ""
    plan["plan_hash"] = plan_hash(plan["clusters"])
    plan.setdefault("no_page", [])
    plan.setdefault("least_understood", [])
    save_plan(ctx.wiki_dir, plan)
    ctx.emit.say(f"plan: committed {len(plan['clusters'])} clusters to {ctx.wiki_dir / PLAN_NAME} (approved by {plan['approved_by']})")
    ctx.emit.emit({"path": str(ctx.wiki_dir / PLAN_NAME), "clusters": len(plan["clusters"]), "approved_by": plan["approved_by"], "plan_hash": plan["plan_hash"]})
    return 0


def _find(plan: dict, cid: str) -> dict:
    for c in plan.get("clusters") or []:
        if c.get("id") == cid:
            return c
    raise cli.ConfigError(f"cluster {cid!r} not in the plan")


def cmd_show(ctx: cli.Ctx, args) -> int:
    plan = load_plan(ctx.wiki_dir)
    c = _find(plan, args.id)
    deps = [d for d in c.get("deps") or [] if d != "*"]
    dep_pages = [p["path"] for o in plan["clusters"] if o["id"] in deps for p in o.get("pages") or []]
    ctx.emit.say(f"{c['id']}: {c.get('title')} [{c.get('status')}] pages={len(c.get('pages') or [])} deps={','.join(c.get('deps') or []) or '-'}")
    for p in c.get("pages") or []:
        ctx.emit.say(f"  {p['path']} ({p.get('type')}) sources={', '.join(p.get('sources') or []) or '-'}")
    ctx.emit.emit({"cluster": c, "dependency_pages": dep_pages, "no_page": plan.get("no_page") or [], "plan_hash": plan.get("plan_hash")})
    return 0


def cmd_mark(ctx: cli.Ctx, args) -> int:
    plan = load_plan(ctx.wiki_dir)
    c = _find(plan, args.id)
    now = cli.iso(ctx.now)
    c["status"] = args.status
    if args.status == "running":
        c["attempts"] = int(c.get("attempts") or 0) + 1
        c["started"] = now
        c["ended"] = None
    elif args.status in ("done", "deferred", "failed"):
        c["ended"] = now
        if c.get("started"):
            try:
                c["duration_s"] = int((cli.parse_iso(now) - cli.parse_iso(c["started"])).total_seconds())
            except ValueError:
                pass
    if args.duration is not None:
        c["duration_s"] = args.duration
    if args.reason is not None:
        c["reason"] = textnorm.sanitize(args.reason, 300)
    if args.commit_sha:
        c["commit"] = args.commit_sha
    if args.pages_written is not None:
        c["pages_written"] = args.pages_written
    if args.lint_errors is not None:
        c["lint_errors"] = args.lint_errors
    save_plan(ctx.wiki_dir, plan)
    ctx.emit.say(f"plan: {c['id']} → {args.status}")
    ctx.emit.emit({"cluster": c})
    return 0


def cmd_split(ctx: cli.Ctx, args) -> int:
    plan = load_plan(ctx.wiki_dir)
    c = _find(plan, args.id)
    b = Builder(ctx)
    files: list[str] = []
    for p in c.get("pages") or []:
        for s in p.get("sources") or []:
            r = wpages.parse_resource(s if isinstance(s, str) else s.get("resource", ""))
            if r and r.scheme == "repo" and r.path:
                if (ctx.repo / r.path).is_dir():
                    files.extend(b.files_under(r.path) if hasattr(b, "files_under") else [f for f in b.code_files() if f.startswith(r.path + "/")])
                else:
                    files.append(r.path)
    files = sorted(set(files))
    if not files:
        raise cli.ConfigError(f"cluster {c['id']} has no repo:// sources to split")
    key = files[0].rsplit("/", 1)[0] if "/" in files[0] else ""
    common = key
    for f in files[1:]:
        d = f.rsplit("/", 1)[0] if "/" in f else ""
        while common and not d.startswith(common):
            common = common.rsplit("/", 1)[0] if "/" in common else ""
    saved = b.max_bytes
    b.max_bytes = max(1, min(saved, max(sum(b.size(f) for f in files) // 2, 1)))
    chunks = b.split_group(common or key, files, c["id"])
    b.max_bytes = saved
    if len(chunks) < 2:
        raise cli.ConfigError(f"cluster {c['id']} cannot be split further")
    children = []
    for i, (cid, cdir, cfiles, sources) in enumerate(chunks, 1):
        child_id = cid if cid != c["id"] else f"{c['id']}-{i}"
        pages = []
        for p in c.get("pages") or []:
            pages.append({**p, "path": p["path"][:-3] + f"-{i}.md" if i > 1 or child_id != c["id"] else p["path"], "sources": sources,
                          "notes": (p.get("notes") or "") + f" (split {i}/{len(chunks)} of {c['id']})"})
        children.append(Builder._cluster(child_id, f"{c.get('title')} ({i}/{len(chunks)})", c.get("kind", "module"),
                                          [d for d in c.get("deps") or []], pages, sum(b.size(f) for f in cfiles), cfiles))
    child_ids = [ch["id"] for ch in children]
    for o in plan["clusters"]:
        if c["id"] in (o.get("deps") or []):
            o["deps"] = [d for d in o["deps"] if d != c["id"]] + child_ids
    c["status"] = "split"
    c["split_into"] = child_ids
    idx = plan["clusters"].index(c)
    plan["clusters"][idx + 1:idx + 1] = children
    plan["plan_hash"] = plan_hash(plan["clusters"])
    save_plan(ctx.wiki_dir, plan)
    ctx.emit.say(f"plan: {c['id']} split into {', '.join(child_ids)}")
    ctx.emit.emit({"split": c["id"], "children": children})
    return 0


def cmd_next(ctx: cli.Ctx, args) -> int:
    plan = load_plan(ctx.wiki_dir)
    c = next_cluster(plan)
    remaining = [x["id"] for x in plan["clusters"] if x.get("status") in ("pending", "running", "deferred", "failed")]
    if c:
        ctx.emit.say(f"plan: next cluster {c['id']} ({len(remaining)} remaining)")
    else:
        ctx.emit.say("plan: no runnable cluster" + (f"; {len(remaining)} remaining (blocked or not pending)" if remaining else "; all done"))
    ctx.emit.emit({"cluster": c, "remaining": remaining})
    return 0


def cmd_estimate(ctx: cli.Ctx, args) -> int:
    try:
        plan = load_plan(ctx.wiki_dir)
    except cli.EnvError:
        p = proposal_path(ctx)
        if not p.exists():
            raise
        plan = json.loads(p.read_text(encoding="utf-8"))
    model = args.model or ctx.cfg.get("models.bootstrap") or "claude-sonnet-4.6"
    est = estimate(plan, model)
    for r in est["clusters"]:
        ctx.emit.say(f"  {r['id']:<24} {r['source_bytes']:>8} bytes  {r['pages']} pages  ~{r['credits']} credits")
    ctx.emit.say(f"plan: ~{est['total_credits']} credits with {model} for {len(est['clusters'])} clusters" + (f" ({est['note']})" if est["note"] else ""))
    ctx.emit.emit(est)
    return 0


def cmd_status(ctx: cli.Ctx, args) -> int:
    plan = load_plan(ctx.wiki_dir)
    counts: dict[str, int] = {}
    for c in plan["clusters"]:
        counts[c.get("status", "?")] = counts.get(c.get("status", "?"), 0) + 1
        ctx.emit.say(f"  {c['id']:<24} {c.get('status', '?'):<9} pages={len(c.get('pages') or [])} attempts={c.get('attempts', 0)} "
                     f"bytes={(c.get('estimate') or {}).get('source_bytes', 0)}" + (f" reason={c['reason']}" if c.get("reason") else ""))
    ctx.emit.say("plan: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"; approved by {plan.get('approved_by') or '-'}")
    ctx.emit.emit({"counts": counts, "approved_by": plan.get("approved_by"), "plan_hash": plan.get("plan_hash"),
                   "clusters": [{k: c.get(k) for k in ("id", "title", "kind", "status", "deps", "attempts", "pages_written", "reason")} for c in plan["clusters"]]})
    return 0


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if not ctx.wiki_dir.is_dir() and args.cmd != "build":
        raise cli.EnvError(f"wiki directory missing: {ctx.wiki_dir}")
    return {"build": cmd_build, "commit": cmd_commit, "show": cmd_show, "mark": cmd_mark, "split": cmd_split, "next": cmd_next,
            "estimate": cmd_estimate, "status": cmd_status}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
