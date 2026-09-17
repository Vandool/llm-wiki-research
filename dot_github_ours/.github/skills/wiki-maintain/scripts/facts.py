#!/usr/bin/env python3
"""facts.py — deterministic fact pages (owner: process) generated from the repository.

CLI:
  facts.py [--json] [--only inventory,symbols,deps,changelog,decisions,owners,openapi,asyncapi,catalog]
           [--check] [--detect-stacks] [--seed-catalog] [--shard-lines 400]
Generators → files under the wiki dir:
  inventory  generated/inventory.md|json      tracked files minus excludes; tree with counts and language mix
  symbols    generated/symbols.json|md        symbol index (+ generated/symbols/<dir>.md shards above --shard-lines)
  deps       generated/dependencies.md|json   pyproject/requirements/package.json/go.mod/pom.xml/Cargo.toml/gradle
  changelog  generated/changelog.md           git log --no-merges (200), Wiki-Update commits excluded, audience [dev]
  decisions  decisions/index.md + generated/decisions.json   MADR ADRs
  owners     generated/owners.md|json         CODEOWNERS
  openapi    api/<tag>.md + api/index.md + generated/specs.json
  asyncapi   events/<channel>.md + events/index.md (+ specs.json)
  catalog    wiki/catalog.yaml (only with --seed-catalog and only if absent)
Every page: owner process, audience [agent, dev], generated.by process:facts.py/<ver>, generated.at = HEAD
committer date, last_verified_commit = HEAD, sources = inputs. Output is sorted, LF, byte-identical across
machines; unchanged files (ignoring the two volatile lines) are not rewritten.
--check regenerates in memory and lists drift (exit 1). Exit 0 ok · 1 drift · 2 usage · 3 not a repo.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio, specs as wspecs, symbols as wsymbols, textnorm, yamlmini  # noqa: E402
from wikilib.pages import is_excluded, is_test_path  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "facts"
GENERATORS = ("inventory", "symbols", "deps", "changelog", "decisions", "owners", "openapi", "asyncapi", "catalog")
VOLATILE_PREFIXES = ("generated:", "last_verified_commit:")
_ADR_GLOBS = ("docs/adr/", "docs/decisions/", "adr/", "doc/adr/", "architecture/decisions/", "docs/architecture/decisions/")
_ADR_FILE_RE = re.compile(r"(^|/)(ADR-?\d+[^/]*|\d{3,5}-[^/]+)\.md$", re.I)
_CODEOWNERS = ("CODEOWNERS", ".gitlab/CODEOWNERS", "docs/CODEOWNERS", ".github/CODEOWNERS")
_DEP_FILES = ("pyproject.toml", "package.json", "go.mod", "pom.xml", "Cargo.toml", "build.gradle", "build.gradle.kts", "Pipfile")
_TABLE_ESC = str.maketrans({"|": "\\|", "\n": " "})


def _cell(text: Any) -> str:
    return str(text).translate(_TABLE_ESC).strip()


def strip_volatile(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if not l.startswith(VOLATILE_PREFIXES))


class Facts:
    def __init__(self, ctx: cli.Ctx, shard_lines: int = 400):
        self.ctx = ctx
        self.repo = ctx.repo
        self.cfg = ctx.cfg
        self.wiki = ctx.wiki_dir
        self.shard_lines = shard_lines
        self.head = gitio.head(self.repo)
        if not self.head:
            raise cli.EnvError("repository has no commits yet")
        cdate = gitio.committer_date("HEAD", self.repo) or ""
        self.date = cli.iso(cli.parse_iso(cdate)) if cdate else cli.iso(ctx.now)
        self.prefix = self.cfg.id_prefix
        self.excludes = list(self.cfg.get("sources.exclude") or [])
        self.ignore_tests = bool(self.cfg.get("coverage.ignore_tests", True))
        self.all_files = gitio.ls_files(self.repo)
        roots = [str(r).rstrip("/") for r in (self.cfg.get("sources.include") or [])]
        kit_paths = (".github/skills/wiki-maintain/", ".gitlab/wiki-site/")
        wiki_prefix = self.cfg.wiki_dir.rstrip("/") + "/"

        def _skip(f: str) -> bool:
            if f.startswith(wiki_prefix) or is_excluded(f, self.excludes):
                return True
            if f.startswith(kit_paths) and not any(f.startswith(r + "/") for r in roots):
                return True
            return False

        self.files = [f for f in self.all_files if not _skip(f)]
        self.excluded_count = sum(1 for f in self.all_files if not f.startswith(wiki_prefix) and is_excluded(f, self.excludes))
        self.outputs: dict[str, str] = {}
        self.counts: dict[str, Any] = {}
        self._symbols_index: Optional[dict] = None
        self._specs: dict = {"apis": {}, "events": {}}

    # ---------------------------------------------------------------- helpers

    def frontmatter(self, rel: str, page_type: str, title: str, description: str, sources: list[dict],
                    audience: Optional[list] = None, extra: Optional[dict] = None) -> str:
        fm: dict = {"type": page_type, "id": f"{self.prefix}/{rel[:-3]}", "schema_version": 1, "title": title[:80],
                    "description": textnorm.sanitize(description, 200), "audience": audience or ["agent", "dev"],
                    "owner": "process"}
        if extra:
            fm.update(extra)
        fm["sources"] = sources
        fm["last_verified_commit"] = self.head
        fm["generated"] = {"by": f"process:facts.py/{VERSION}", "at": self.date}
        return "---\n" + yamlmini.dumps(fm) + "---\n"

    def page(self, rel: str, page_type: str, title: str, description: str, sources: list[dict], body_lines: list[str],
             audience: Optional[list] = None, extra: Optional[dict] = None) -> None:
        body = "\n".join([f"# {title}"] + body_lines)
        self.outputs[rel] = textnorm.normalize(self.frontmatter(rel, page_type, title, description, sources, audience, extra) + body)

    def index_page(self, rel: str, title: str, body_lines: list[str]) -> None:
        self.outputs[rel] = textnorm.normalize("---\n" + yamlmini.dumps({"title": title}) + "---\n" + "\n".join([f"# {title}"] + body_lines))

    def json_out(self, rel: str, data: Any) -> None:
        self.outputs[rel] = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def read(self, rel: str) -> str:
        try:
            return (self.repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def code_files(self) -> list[str]:
        return [f for f in self.files if wsymbols.language_of(f) and not (self.ignore_tests and is_test_path(f))]

    # ---------------------------------------------------------------- inventory

    def gen_inventory(self) -> None:
        langs: dict[str, int] = {}
        dirs: dict[str, dict] = {}
        for f in self.files:
            lang = wsymbols.language_of(f) or ("markdown" if f.endswith(".md") else "other")
            langs[lang] = langs.get(lang, 0) + 1
            parts = f.split("/")
            for d in range(1, len(parts)):
                key = "/".join(parts[:d])
                e = dirs.setdefault(key, {"files": 0, "languages": {}, "depth": d})
                e["files"] += 1
                e["languages"][lang] = e["languages"].get(lang, 0) + 1
        top_files = sorted(f for f in self.files if "/" not in f)
        roots = list(self.cfg.get("sources.include") or [])
        data = {"total_files": len(self.files), "excluded": self.excluded_count,
                "languages": dict(sorted(langs.items())), "roots": roots, "top_level_files": top_files,
                "dirs": {k: {"files": v["files"], "languages": dict(sorted(v["languages"].items()))} for k, v in sorted(dirs.items())}}
        self.json_out("generated/inventory.json", data)
        lines = ["**Read this when:** you need the shape of the repository before opening any file.", "",
                 f"{len(self.files)} tracked files ({data['excluded']} excluded by `sources.exclude`). "
                 f"Languages: " + ", ".join(f"{k} {v}" for k, v in sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))) + ".", "",
                 "## Top-level directories", "| Directory | Files | Languages | Source root |", "|---|---|---|---|"]
        for d in sorted(k for k, v in dirs.items() if v["depth"] == 1):
            e = dirs[d]
            mix = ", ".join(f"{k} {v}" for k, v in sorted(e["languages"].items(), key=lambda kv: (-kv[1], kv[0])))
            lines.append(f"| `{d}/` | {e['files']} | {mix} | {'yes' if d in roots else ''} |")
        if top_files:
            lines += ["", "## Top-level files", ", ".join(f"`{f}`" for f in top_files)]
        lines += ["", "## Tree (source roots, depth 3)"]
        budget = 360 - len(lines)
        for root in roots:
            for d in sorted(k for k in dirs if k == root or k.startswith(root + "/")):
                e = dirs[d]
                if e["depth"] > 3:
                    continue
                if budget <= 0:
                    lines.append("* … (truncated; see inventory.json)")
                    break
                indent = "  " * (e["depth"] - 1)
                mix = ", ".join(f"{k} {v}" for k, v in sorted(e["languages"].items(), key=lambda kv: (-kv[1], kv[0])))
                lines.append(f"{indent}* `{d}/` — {e['files']} files ({mix})")
                budget -= 1
        self.counts["files"] = len(self.files)
        self.page("generated/inventory.md", "Generated", "Repository inventory",
                  f"Tracked files at HEAD grouped by directory with language mix; {len(self.files)} files.",
                  [{"id": "tree", "resource": "repo://.", "title": "tracked files at HEAD"}], lines)

    # ---------------------------------------------------------------- symbols

    def symbols_index(self) -> dict:
        if self._symbols_index is None:
            idx: dict[str, dict] = {}
            for f in self.code_files():
                d = wsymbols.index_file(f, self.read(f))
                if d is not None:
                    idx[f] = d
            self._symbols_index = dict(sorted(idx.items()))
        return self._symbols_index

    def _symbol_section(self, path: str, d: dict) -> list[str]:
        lines = [f"### `{path}`", ""]
        if d.get("error"):
            lines += [f"_{d['error']}_", ""]
        if d.get("symbols"):
            lines += ["| Symbol | Kind | Lines | Signature |", "|---|---|---|---|"]
            for s in d["symbols"]:
                lines.append(f"| `{_cell(s['name'])}` | {s['kind']} | {s['lines'][0]}–{s['lines'][1]} | `{_cell(s['signature'])}` |")
            lines.append("")
        if d.get("routes"):
            lines += ["Routes:", "", "| Method | Path | Handler | Lines |", "|---|---|---|---|"]
            for r in d["routes"]:
                lines.append(f"| {r['method']} | `{_cell(r['path'])}` | `{_cell(r['handler'])}` | {r['lines'][0]}–{r['lines'][1]} |")
            lines.append("")
        return lines

    def gen_symbols(self) -> None:
        idx = self.symbols_index()
        self.json_out("generated/symbols.json", idx)
        n_sym = sum(len(d.get("symbols", [])) for d in idx.values())
        routes = [(p, r) for p, d in idx.items() for r in d.get("routes", [])]
        self.counts["symbols"] = n_sym
        self.counts["routes"] = len(routes)
        self.counts["indexed_files"] = len(idx)
        roots = list(self.cfg.get("sources.include") or [])
        sources = [{"id": textnorm.slugify(r), "resource": f"repo://{r.rstrip('/')}/", "title": f"{r} sources"} for r in roots
                   if any(f == r or f.startswith(r.rstrip('/') + "/") for f in idx)] or \
                  [{"id": "tree", "resource": "repo://.", "title": "tracked files at HEAD"}]
        route_lines: list[str] = []
        if routes:
            route_lines = ["## Routes", "", "| Method | Path | Handler | File |", "|---|---|---|---|"]
            for p, r in sorted(routes, key=lambda x: (x[1]["path"], x[1]["method"], x[0])):
                route_lines.append(f"| {r['method']} | `{_cell(r['path'])}` | `{_cell(r['handler'])}` | `{p}` |")
            route_lines.append("")
        sections = {p: self._symbol_section(p, d) for p, d in idx.items()}
        total = sum(len(s) for s in sections.values()) + len(route_lines) + 12
        lede = [f"**Read this when:** you need to cite a symbol as `path/file::Symbol` or find a route's handler. "
                f"{n_sym} symbols in {len(idx)} files; {len(routes)} routes.", ""]
        if total <= self.shard_lines:
            body = lede + route_lines + ["## Files", ""]
            for p in idx:
                body += sections[p]
            self.page("generated/symbols.md", "Generated", "Symbol index",
                      f"Functions, classes, methods, constants and routes per file ({n_sym} symbols); cite as path::Symbol.",
                      sources, body)
            return
        # shard by top directory, then by second level when a shard is still too large
        groups: dict[str, list[str]] = {}
        for p in idx:
            groups.setdefault(p.split("/", 1)[0] if "/" in p else "root", []).append(p)
        final: dict[str, list[str]] = {}
        for g, paths in groups.items():
            size = sum(len(sections[p]) for p in paths)
            if size > self.shard_lines and any(p.count("/") >= 2 for p in paths):
                for p in paths:
                    parts = p.split("/")
                    key = "-".join(parts[:2]) if len(parts) > 2 else parts[0]
                    final.setdefault(key, []).append(p)
            else:
                final[g] = paths
        body = lede + route_lines + ["## Shards", "", "| Shard | Files | Symbols |", "|---|---|---|"]
        for key in sorted(final):
            paths = final[key]
            slug = textnorm.slugify(key)
            n = sum(len(idx[p].get("symbols", [])) for p in paths)
            body.append(f"| [{key}](symbols/{slug}.md) | {len(paths)} | {n} |")
            shard_body = [f"**Read this when:** you need symbols under `{key}`.", ""]
            for p in sorted(paths):
                shard_body += sections[p]
            shard_sources = [{"id": "files", "resource": f"repo://{paths[0].rsplit('/', 1)[0]}/" if len(paths) == 1 or all(p.startswith(paths[0].rsplit('/', 1)[0] + '/') for p in paths) else f"repo://{key.split('-')[0]}/", "title": f"{key} sources"}]
            self.page(f"generated/symbols/{slug}.md", "Generated", f"Symbols: {key}",
                      f"Symbol index shard for {key} ({n} symbols in {len(paths)} files).", shard_sources, shard_body)
        self.page("generated/symbols.md", "Generated", "Symbol index",
                  f"Functions, classes, methods, constants and routes per file ({n_sym} symbols), sharded by directory.",
                  sources, body)

    # ---------------------------------------------------------------- deps

    def _parse_pyproject(self, text: str) -> tuple[list[dict], bool]:
        deps: list[dict] = []
        try:
            import tomllib  # type: ignore

            data = tomllib.loads(text)
            proj = data.get("project") or {}
            for d in proj.get("dependencies") or []:
                deps.append({"name": re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0], "spec": d, "group": "main"})
            for grp, items in (proj.get("optional-dependencies") or {}).items():
                for d in items:
                    deps.append({"name": re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0], "spec": d, "group": str(grp)})
            poetry = ((data.get("tool") or {}).get("poetry") or {})
            for grp_name, items in [("main", poetry.get("dependencies") or {})] + \
                    [(g, (v or {}).get("dependencies") or {}) for g, v in (poetry.get("group") or {}).items()]:
                for name, spec in items.items():
                    if name.lower() == "python":
                        continue
                    deps.append({"name": name, "spec": spec if isinstance(spec, str) else json.dumps(spec, sort_keys=True), "group": grp_name})
            return deps, False
        except ImportError:
            pass
        except Exception as e:  # malformed toml
            return [{"name": f"(unparsable: {e})", "spec": "", "group": "main"}], True
        m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
        if m:
            for d in re.findall(r"[\"']([^\"']+)[\"']", m.group(1)):
                deps.append({"name": re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0], "spec": d, "group": "main"})
        return deps, True

    def gen_deps(self) -> None:
        manifests: list[dict] = []
        candidates = [f for f in self.files if f.rsplit("/", 1)[-1] in _DEP_FILES or re.match(r"(^|.*/)requirements[^/]*\.txt$", f)]
        for f in sorted(candidates):
            name = f.rsplit("/", 1)[-1]
            text = self.read(f)
            deps: list[dict] = []
            approx = False
            kind = name
            if name == "pyproject.toml":
                deps, approx = self._parse_pyproject(text)
            elif name.startswith("requirements"):
                for line in text.splitlines():
                    line = line.split("#", 1)[0].strip()
                    if not line or line.startswith("-"):
                        continue
                    deps.append({"name": re.split(r"[<>=!~\[; @]", line, maxsplit=1)[0], "spec": line, "group": "main"})
            elif name == "package.json":
                try:
                    pkg = json.loads(text)
                    for grp in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                        for k, v in sorted((pkg.get(grp) or {}).items()):
                            deps.append({"name": k, "spec": str(v), "group": grp})
                except ValueError:
                    approx = True
            elif name == "go.mod":
                for m in re.finditer(r"^\s*([\w./-]+)\s+(v[\w.+-]+)(\s*//\s*indirect)?", text, re.M):
                    if m.group(1) in ("module", "go", "toolchain"):
                        continue
                    deps.append({"name": m.group(1), "spec": m.group(2), "group": "indirect" if m.group(3) else "main"})
            elif name == "pom.xml":
                for m in re.finditer(r"<dependency>(.*?)</dependency>", text, re.S):
                    g = re.search(r"<groupId>([^<]+)</groupId>", m.group(1))
                    a = re.search(r"<artifactId>([^<]+)</artifactId>", m.group(1))
                    v = re.search(r"<version>([^<]+)</version>", m.group(1))
                    s = re.search(r"<scope>([^<]+)</scope>", m.group(1))
                    if a:
                        deps.append({"name": f"{g.group(1) + ':' if g else ''}{a.group(1)}", "spec": v.group(1) if v else "", "group": s.group(1) if s else "main"})
                approx = True
            elif name == "Cargo.toml":
                section = None
                for line in text.splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line.startswith("["):
                        section = line.strip("[]")
                        continue
                    if section and section.endswith("dependencies") and "=" in line:
                        k, v = line.split("=", 1)
                        deps.append({"name": k.strip(), "spec": v.strip().strip('"'), "group": section})
            elif name.startswith("build.gradle"):
                for m in re.finditer(r"(implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(?\s*[\"']([^\"']+)[\"']", text):
                    deps.append({"name": m.group(2).rsplit(":", 1)[0] if m.group(2).count(":") >= 2 else m.group(2),
                                 "spec": m.group(2), "group": m.group(1)})
                approx = True
            elif name == "Pipfile":
                section = None
                for line in text.splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line.startswith("["):
                        section = line.strip("[]")
                        continue
                    if section in ("packages", "dev-packages") and "=" in line:
                        k, v = line.split("=", 1)
                        deps.append({"name": k.strip().strip('"'), "spec": v.strip().strip('"'), "group": section})
            deps.sort(key=lambda d: (d["group"], d["name"].lower()))
            manifests.append({"file": f, "kind": kind, "approximate": approx, "dependencies": deps})
        self.json_out("generated/dependencies.json", {"manifests": manifests})
        total = sum(len(m["dependencies"]) for m in manifests)
        self.counts["dependencies"] = total
        lines = ["**Read this when:** you need to know which libraries and versions the code relies on.", ""]
        for m in manifests:
            lines += [f"## `{m['file']}`" + (" (approximate parse)" if m["approximate"] else ""), ""]
            if not m["dependencies"]:
                lines += ["_No dependencies listed._", ""]
                continue
            lines += ["| Dependency | Version / spec | Group |", "|---|---|---|"]
            for d in m["dependencies"]:
                lines.append(f"| `{_cell(d['name'])}` | `{_cell(d['spec']) or '-'}` | {d['group']} |")
            lines.append("")
        if not manifests:
            lines += ["_No dependency manifests found._"]
        sources = [{"id": textnorm.slugify(m["file"]), "resource": f"repo://{m['file']}", "title": m["file"]} for m in manifests] or \
                  [{"id": "tree", "resource": "repo://.", "title": "tracked files at HEAD"}]
        self.page("generated/dependencies.md", "Generated", "Dependencies",
                  f"Third-party dependencies from {len(manifests)} manifest(s), {total} entries.", sources, lines)

    # ---------------------------------------------------------------- changelog

    def gen_changelog(self) -> None:
        entries = gitio.log(self.repo, n=600, extra=["--no-merges"])
        kept = []
        for e in entries:
            if re.search(r"^Wiki-Update:", e.get("body", ""), re.M) or e["subject"].startswith("docs(wiki):"):
                continue
            kept.append(e)
            if len(kept) >= 200:
                break
        self.counts["commits"] = len(kept)
        lines = ["**Read this when:** you need the recent history of the code (not of the wiki).", "",
                 "| Date | Commit | Subject |", "|---|---|---|"]
        for e in kept:
            date = e["date"][:10]
            lines.append(f"| {date} | `{e['sha'][:10]}` | {_cell(textnorm.sanitize(e['subject'], 120))} |")
        # Range ends at the newest INCLUDED commit, never at HEAD: HEAD is often a wiki commit (excluded above) and a
        # HEAD-bound range would make `facts.py --check` drift after every `docs(wiki):` commit.
        oldest = kept[-1]["sha"][:10] if kept else self.head[:10]
        newest = kept[0]["sha"][:10] if kept else self.head[:10]
        self.page("generated/changelog.md", "Generated", "Recent changes",
                  f"The newest {len(kept)} non-merge commits (subjects only; wiki commits excluded).",
                  [{"id": "log", "resource": f"changelog://{self.prefix}@{oldest}..{newest}", "title": "git log"}],
                  lines, audience=["dev"])

    # ---------------------------------------------------------------- decisions

    def adr_files(self) -> list[str]:
        out = [f for f in self.files if f.endswith(".md") and (any(f.startswith(g) for g in _ADR_GLOBS) or _ADR_FILE_RE.search(f))]
        return sorted(f for f in out if not f.lower().endswith(("readme.md", "template.md", "index.md")))

    @staticmethod
    def parse_adr(path: str, text: str) -> dict:
        m = re.search(r"^(\d+)", path.rsplit("/", 1)[-1]) or re.search(r"ADR-?(\d+)", path, re.I)
        number = m.group(1).zfill(4) if m else ""
        title = ""
        h1 = re.search(r"^#\s+(.+?)\s*$", text, re.M)
        if h1:
            title = re.sub(r"^(ADR[- ]?\d+[:.\s-]*|\d+[.:\s-]+)", "", h1.group(1)).strip()
        status = ""
        sm = re.search(r"^\s*[\*-]?\s*\**Status\**\s*:\s*\**([A-Za-z][\w -]*?)\**\s*$", text, re.M | re.I)
        if sm:
            status = sm.group(1).strip().lower()
        else:
            sec = re.search(r"^##\s*Status\s*\n+\s*([A-Za-z][\w -]*)", text, re.M | re.I)
            if sec:
                status = sec.group(1).strip().lower()
            else:
                fm = re.search(r"^status:\s*(\S+)", text, re.M | re.I)
                if fm:
                    status = fm.group(1).strip().lower()
        dm = re.search(r"^\s*[\*-]?\s*\**Date\**\s*:\s*(\d{4}-\d{2}-\d{2})", text, re.M | re.I) or re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", text, re.M | re.I)
        return {"number": number, "id": number or path, "title": title or path.rsplit("/", 1)[-1][:-3], "status": status or "unknown",
                "date": dm.group(1) if dm else "", "path": path}

    def gen_decisions(self) -> None:
        files = self.adr_files()
        adrs = [self.parse_adr(f, self.read(f)) for f in files]
        adrs.sort(key=lambda a: (a["number"], a["path"]))
        adr_dir = files[0].rsplit("/", 1)[0] if files and "/" in files[0] else ""
        self.json_out("generated/decisions.json", {"dir": adr_dir, "adrs": adrs})
        self.counts["adrs"] = len(adrs)
        lines = ["Architecture decision records found in the repository (cite as `adr://NNNN`).", ""]
        if adrs:
            lines += ["| # | Title | Status | Date | File |", "|---|---|---|---|---|"]
            for a in adrs:
                lines.append(f"| {a['number'] or '-'} | {_cell(a['title'])} | {a['status']} | {a['date'] or '-'} | `{a['path']}` |")
        else:
            lines.append("_No ADRs found (looked in docs/adr, docs/decisions, adr, doc/adr, architecture/decisions, ADR-*.md)._")
        self.index_page("decisions/index.md", "Decisions", lines)

    # ---------------------------------------------------------------- owners

    def gen_owners(self) -> None:
        path = next((c for c in _CODEOWNERS if c in set(self.all_files)), None)
        rules: list[dict] = []
        if path:
            section = ""
            for line in self.read(path).splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                if raw.startswith("[") or raw.startswith("^["):
                    section = raw.strip("^[]").split("]")[0]
                    continue
                parts = raw.split()
                rules.append({"pattern": parts[0], "owners": parts[1:], "section": section})
        data = {"file": path, "rules": rules}
        self.json_out("generated/owners.json", data)
        self.counts["owner_rules"] = len(rules)
        lines = ["**Read this when:** you need the owning team for a path (cite the team, never a person).", ""]
        if rules:
            lines += ["| Pattern | Owners | Section |", "|---|---|---|"]
            for r in rules:
                lines.append(f"| `{_cell(r['pattern'])}` | {', '.join(f'`{_cell(o)}`' for o in r['owners'])} | {r['section'] or '-'} |")
        else:
            lines.append("_No CODEOWNERS file found._")
        sources = [{"id": "codeowners", "resource": f"repo://{path}", "title": "CODEOWNERS"}] if path else \
                  [{"id": "tree", "resource": "repo://.", "title": "tracked files at HEAD"}]
        self.page("generated/owners.md", "Generated", "Code owners", f"Ownership rules from {path or 'no CODEOWNERS file'} ({len(rules)} rules).",
                  sources, lines)

    # ---------------------------------------------------------------- openapi / asyncapi

    def spec_files(self, kind: str) -> list[str]:
        configured = [str(p) for p in (self.cfg.get(f"api_spec.{kind}") or []) if p]
        if configured:
            return [p for p in configured if (self.repo / p).exists()]
        return wspecs.detect_spec_files(self.all_files)[kind]

    def _handler_for(self, method: str, path: str) -> str:
        idx = self.symbols_index()
        norm = re.sub(r"\{[^/}]+\}|:[^/]+", "{}", path).rstrip("/")
        for f, d in idx.items():
            for r in d.get("routes", []):
                if r["method"] == method and (r["path"] == path or re.sub(r"\{[^/}]+\}|:[^/]+", "{}", r["path"]).rstrip("/") == norm):
                    return f"`{f}::{r['handler']}`"
        return "-"

    def _guide_ref(self, folder: str, slug: str, label: str) -> str:
        """Link to the written `<slug>-guide.md` only when it exists: generated pages must never carry broken
        links into the published site (the missing guide is reported as an L12 gap instead)."""
        guide = f"{slug}-guide.md"
        if (self.wiki / folder / guide).is_file():
            return f"the written guide is [{label}]({guide})"
        return f"the written guide `{guide}` has not been created yet"

    def gen_openapi(self) -> None:
        files = self.spec_files("openapi")
        hint = str(self.cfg.get("api_spec.export_hint") or "")
        all_rows: list[tuple[str, str, str, str, str]] = []
        api_rows: list[str] = []
        many = len(files) > 1
        for f in files:
            try:
                doc = wspecs.load_spec(self.repo / f, hint)
            except wspecs.SpecError as e:
                self.ctx.emit.warn(str(e))
                continue
            if wspecs.spec_kind(doc) != "openapi":
                self.ctx.emit.warn(f"{f}: not an OpenAPI document")
                continue
            api = wspecs.api_id(doc, f)
            info = doc.get("info") or {}
            title = str(info.get("title") or api)
            version = str(info.get("version") or "")
            ops = wspecs.openapi_operations(doc)
            groups = wspecs.group_operations(ops)
            entry = {"file": f, "title": title, "version": version, "kind": "openapi", "groups": {}, "tags": sorted({t for o in ops for t in o["tags"]}),
                     "operations": {}}
            for slug, g in groups.items():
                page_slug = f"{api}-{slug}" if many else slug
                rel = f"api/{page_slug}.md"
                entry["groups"][slug] = rel
                body = [f"**Read this when:** you call or change the `{g['title']}` endpoints of {title}{(' ' + version) if version else ''}. "
                        f"Generated from `{f}`; {self._guide_ref('api', page_slug, g['title'] + ' guide')}.", "",
                        "## Endpoints", "", "| Method | Path | Operation | Summary | Handler |", "|---|---|---|---|---|"]
                for op in g["ops"]:
                    handler = self._handler_for(op["method"], op["path"])
                    dep = " (deprecated)" if op["deprecated"] else ""
                    body.append(f"| {op['method']} | `{_cell(op['path'])}` | `{_cell(op['operationId']) or '-'}` | {_cell(op['summary'])}{dep} | {handler} |")
                    entry["operations"][op["operationId"] or f"{op['method']} {op['path']}"] = {"method": op["method"], "path": op["path"], "group": slug, "page": rel}
                    all_rows.append((op["path"], op["method"], op["operationId"], op["summary"], rel))
                details: list[str] = ["", "## Operations", ""]
                for op in g["ops"]:
                    details.append(f"### {op['method']} `{op['path']}`")
                    if op["operationId"]:
                        details.append(f"Operation `{op['operationId']}`" + (f": {op['summary']}" if op["summary"] else "") + ".")
                    if op["parameters"]:
                        details.append("Parameters: " + ", ".join(f"`{p['name']}` ({p['in']}{', required' if p['required'] else ''})" for p in op["parameters"]) + ".")
                    if op["request_schema"]:
                        details.append(f"Request body: `{op['request_schema']}`.")
                    if op["responses"]:
                        details.append("Responses: " + ", ".join(f"`{c}` {d}".rstrip() for c, d in op["responses"].items()) + ".")
                    details.append("")
                if len(body) + len(details) <= 380:
                    body += details
                self.page(rel, "Contract", f"{g['title'][:1].upper() + g['title'][1:]} API", f"Endpoints tagged {g['title']} in {title}{(' ' + version) if version else ''} ({len(g['ops'])} operations).",
                          [{"id": "spec", "resource": f"repo://{f}", "title": f"OpenAPI {title}"}], body,
                          extra={"provides": [f"api:{api}"], "tags": ["contract", "api"]})
                api_rows.append(f"| {_cell(title)} | {_cell(g['title'])} | [{g['title'][:1].upper() + g['title'][1:]} API]({page_slug}.md) | {len(g['ops'])} | `{f}` |")
            self._specs["apis"][api] = entry
        self.counts["api_groups"] = len(api_rows)
        self.counts["api_operations"] = len(all_rows)
        if not files:
            return
        lines = ["Generated contract pages per router/tag; each has a written `<name>-guide.md` next to it.", "",
                 "| API | Tag | Contract page | Operations | Spec |", "|---|---|---|---|---|"] + api_rows
        if all_rows:
            lines += ["", "## All endpoints", "", "| Method | Path | Operation | Contract |", "|---|---|---|---|"]
            for path, method, opid, summary, rel in sorted(all_rows):
                lines.append(f"| {method} | `{_cell(path)}` | `{_cell(opid) or '-'}` | [{rel[4:-3]}]({rel[4:]}) |")
        self.index_page("api/index.md", "API contracts", lines)

    def gen_asyncapi(self) -> None:
        files = self.spec_files("asyncapi")
        hint = str(self.cfg.get("api_spec.export_hint") or "")
        rows: list[str] = []
        for f in files:
            try:
                doc = wspecs.load_spec(self.repo / f, hint)
            except wspecs.SpecError as e:
                self.ctx.emit.warn(str(e))
                continue
            if wspecs.spec_kind(doc) != "asyncapi":
                self.ctx.emit.warn(f"{f}: not an AsyncAPI document")
                continue
            api = wspecs.api_id(doc, f)
            info = doc.get("info") or {}
            title = str(info.get("title") or api)
            for ch in wspecs.asyncapi_channels(doc):
                rel = f"events/{ch['slug']}.md"
                body = [f"**Read this when:** you produce or consume `{ch['channel']}`. Generated from `{f}` ({title}); "
                        f"{self._guide_ref('events', ch['slug'], ch['channel'] + ' guide')}.", ""]
                if ch["description"]:
                    body += [ch["description"].split("\n")[0], ""]
                body += ["## Operations", "", "| Action | Operation | Summary | Message |", "|---|---|---|---|"]
                for op in ch["operations"]:
                    body.append(f"| {op['action']} | `{_cell(op['operationId']) or '-'}` | {_cell(op['summary'])} | `{_cell(op['message']['name']) or '-'}` |")
                fields = sorted({fld for op in ch["operations"] for fld in op["message"]["fields"]})
                if fields:
                    body += ["", "## Message fields", ""] + [f"* `{_cell(x)}`" for x in fields]
                self.page(rel, "Contract", f"Event {ch['channel']}", (ch["description"].split("\n")[0] if ch["description"] else f"Channel {ch['channel']} of {title}."),
                          [{"id": "spec", "resource": f"repo://{f}", "title": f"AsyncAPI {title}"}], body,
                          extra={"provides": [f"event:{ch['channel']}"], "tags": ["contract", "event"]})
                self._specs["events"][ch["channel"]] = {"file": f, "slug": ch["slug"], "page": rel, "api": api,
                                                        "actions": sorted({op["action"] for op in ch["operations"]})}
                rows.append(f"| `{_cell(ch['channel'])}` | [{ch['channel']}]({ch['slug']}.md) | {', '.join(sorted({op['action'] for op in ch['operations']})) or '-'} | {_cell(ch['description'].split(chr(10))[0]) if ch['description'] else '-'} |")
        self.counts["channels"] = len(rows)
        if not files:
            return
        lines = ["Generated event contract pages per channel; each has a written `<channel>-guide.md` next to it.", "",
                 "| Channel | Page | Actions | Description |", "|---|---|---|---|"] + rows
        self.index_page("events/index.md", "Event contracts", lines)

    def finish_specs(self) -> None:
        if self._specs["apis"] or self._specs["events"]:
            self.json_out("generated/specs.json", self._specs)

    # ---------------------------------------------------------------- catalog

    def catalog_text(self) -> str:
        provides = [f"api:{a}" for a in sorted(self._specs["apis"])] + [f"event:{c}" for c in sorted(self._specs["events"])]
        stacks = [s.get("name") if isinstance(s, dict) else str(s) for s in (self.cfg.get("stacks") or [])]
        data = {"schema_version": 1, "name": self.prefix, "kind": "service", "owner": self.cfg.get("repo.team") or "",
                "lifecycle": "unknown", "provides": provides, "consumes": [], "depends_on": [], "stacks": stacks,
                "links": {"repo": self.cfg.get("repo.gitlab_url") or "", "pages": ""}}
        return yamlmini.dumps(data)

    # ---------------------------------------------------------------- run

    def run(self, only: Iterable[str]) -> None:
        only = list(only)
        for name in only:
            if name == "catalog":
                continue
            getattr(self, f"gen_{name}")()
        if "openapi" in only or "asyncapi" in only:
            if "openapi" not in only or "asyncapi" not in only:
                # keep the other half of specs.json from disk
                prev = self._load_json("generated/specs.json")
                for k in ("apis", "events"):
                    if not self._specs[k] and prev.get(k):
                        self._specs[k] = prev[k]
            self.finish_specs()

    def _load_json(self, rel: str) -> dict:
        try:
            d = json.loads((self.wiki / rel).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def write(self) -> tuple[list[str], list[str]]:
        written: list[str] = []
        unchanged: list[str] = []
        for rel in sorted(self.outputs):
            text = self.outputs[rel]
            path = self.wiki / rel
            if path.exists():
                old = path.read_text(encoding="utf-8", errors="replace")
                if strip_volatile(old) == strip_volatile(text):
                    unchanged.append(rel)
                    continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(rel)
        return written, unchanged

    def check(self) -> tuple[list[str], list[str]]:
        drift: list[str] = []
        missing: list[str] = []
        for rel in sorted(self.outputs):
            path = self.wiki / rel
            if not path.exists():
                missing.append(rel)
                continue
            old = path.read_text(encoding="utf-8", errors="replace")
            if strip_volatile(old) != strip_volatile(self.outputs[rel]):
                drift.append(rel)
        return drift, missing


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    p.add_argument("--only", default=None, help="comma-separated generators: " + ",".join(GENERATORS))
    p.add_argument("--check", action="store_true", help="regenerate in memory and report drift (exit 1)")
    p.add_argument("--detect-stacks", action="store_true", help="print detected stacks and exit")
    p.add_argument("--seed-catalog", action="store_true", help="write wiki/catalog.yaml if absent")
    p.add_argument("--shard-lines", type=int, default=400, help="shard symbols.md above this many lines")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if args.detect_stacks:
        import detect as wdetect

        files = gitio.ls_files(ctx.repo)
        stacks, evidence = wdetect.detect_stacks(files, ctx.repo)
        for s in stacks:
            ctx.emit.out(f"{s['name']}: {', '.join(s['frameworks']) or '-'} ({s['package_manager']}; {s['manifest']})")
        ctx.emit.emit({"stacks": stacks, "evidence": evidence})
        return 0
    only = [g.strip() for g in (args.only.split(",") if args.only else GENERATORS) if g.strip()]
    bad = [g for g in only if g not in GENERATORS]
    if bad:
        raise cli.ConfigError(f"unknown generator(s): {', '.join(bad)}")
    facts = Facts(ctx, shard_lines=args.shard_lines)
    facts.run(only)
    catalog_rel = "catalog.yaml"
    if args.check:
        drift, missing = facts.check()
        for rel in drift:
            ctx.emit.say(f"drift: {ctx.cfg.wiki_dir}/{rel}")
        for rel in missing:
            ctx.emit.say(f"missing: {ctx.cfg.wiki_dir}/{rel}")
        ok = not drift and not missing
        ctx.emit.say("facts: up to date" if ok else f"facts: {len(drift)} drifted, {len(missing)} missing — run facts.py")
        ctx.emit.emit({"drift": drift, "missing": missing, "counts": facts.counts, "generated": sorted(facts.outputs)}, ok=ok)
        return cli.EXIT_OK if ok else cli.EXIT_FINDINGS
    written, unchanged = facts.write()
    catalog_written = False
    if args.seed_catalog or "catalog" in (args.only or "").split(","):
        cpath = facts.wiki / catalog_rel
        if not cpath.exists():
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(facts.catalog_text(), encoding="utf-8", newline="\n")
            catalog_written = True
            written.append(catalog_rel)
    ctx.emit.say(f"facts: wrote {len(written)} file(s), {len(unchanged)} unchanged; " +
                 ", ".join(f"{k}={v}" for k, v in sorted(facts.counts.items())))
    ctx.emit.emit({"generated": sorted(facts.outputs) + ([catalog_rel] if catalog_written else []), "written": written,
                   "unchanged": unchanged, "counts": facts.counts, "stacks": ctx.cfg.get("stacks") or [],
                   "head": facts.head, "generated_at": facts.date})
    return 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
