#!/usr/bin/env python3
"""lint.py — deterministic lint rules L01–L17 (L11 is the LLM pass and is skipped).

CLI: lint.py (--file PATH | --changed | --staged | --all) [--json] [--fix] [--strict] [--base SHA] [--full]
              [--anchors] [--plan FILE]
  --file     one page, fast subset (L01 L04 L05 L06 L07 L08 L13 L14 L16) — for the postToolUse hook
  --changed  pages changed in the working tree (plus --base..HEAD); adds L17
  --staged   staged pages only
  --all      every page plus L02 orphans, L03 staleness, L09 ownership (needs --base), L10 index/log/facts
             integrity, L12 coverage gaps, L15 duplicated headings, L17 churn; secret-scans non-markdown files
  --fix      CRLF→LF, trailing whitespace, final newline, hidden Unicode removed, `# <title>` inserted when
             no H1, canonical `id` (idempotent; process-owned files are left to their generators)
  --strict   warnings count as errors
  --plan     cluster plan (default <wiki>/.wiki-plan.json): links to planned pages are warnings, not errors
Findings: {rule, code, severity, file, line, message, fix}. JSON: {errors[], warnings[], info[], summary{}}.
Exit 0 clean · 1 errors · 2 usage · 3 not a repo / wiki missing.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, frontmatter as wfm, gitio, manifest as wmanifest, pages as wpages, symbols as wsymbols, textnorm  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "lint"

TYPES = ("Conventions", "Instructions", "Requests", "Overview", "Architecture", "Module", "Concept", "How-to", "Contract",
         "Contract Guide", "Runbook", "Glossary", "Feature", "Capability Map", "Release Notes", "What Changed", "Analysis",
         "Generated", "Log Archive")
STATUSES = ("draft", "stable", "deprecated")
AUDIENCES = ("agent", "dev", "po")
OWNERS = ("human", "agent", "process", "both")
REQUIRED = ("type", "title", "description", "id", "schema_version", "audience", "owner", "generated")
OPTIONAL = ("resource", "tags", "sources", "verified", "status", "stale_after", "team", "last_verified_commit", "provides",
            "consumes", "related", "capability", "aliases")
QUARTZ_RESERVED = ("date", "created", "modified", "updated", "lastmod", "published", "image", "cover", "permalink", "draft")
ACTOR_RE = re.compile(r"^(copilot-cli/[A-Za-z0-9._-]+|process:[A-Za-z0-9._-]+/[A-Za-z0-9.-]+|human:[A-Za-z0-9._@-]+)$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
SOURCE_RES_RE = re.compile(r"^(repo|api|event|adr|changelog|flag|https?)://\S+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")
SECRET_PATTERNS = [
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("gitlab token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack token", re.compile(r"\bxox[abp]-[0-9A-Za-z-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("credential assignment", re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{16,}")),
    ("url with credentials", re.compile(r"://[^/\s:]+:[^@\s]+@")),
]
MANAGED_COMMENT_RE = re.compile(r"^\s*(WIKI-AGENT:(START|END)|generated:(start|end))\b")
HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
CITATION_RE = re.compile(r"`([\w./-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|go|java|kt|rs))::([\w.$]+)`")
PATH_RE = re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|go|java|md|json|ya?ml|toml|sql|sh)\b")
GENERIC_HEADINGS = {"overview", "summary", "introduction", "notes", "see also", "references", "steps", "goal"}
FAST_RULES = ("L01", "L04", "L05", "L06", "L07", "L08", "L13", "L14", "L16")


class Finding(dict):
    pass


def _f(rule: str, code: str, severity: str, file: str, line: Optional[int], message: str, fix: Optional[str] = None) -> Finding:
    return Finding(rule=rule, code=code, severity=severity, file=file, line=line, message=message, fix=fix)


def heading_slug(text: str) -> str:
    t = re.sub(r"[`*_~]", "", text).strip().lower()
    t = re.sub(r"[^\w\s-]", "", t)
    return re.sub(r"\s+", "-", t)


class Linter:
    def __init__(self, ctx: cli.Ctx, *, anchors: bool = False, plan: Optional[str] = None, full: bool = False,
                 base: Optional[str] = None):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.repo = ctx.repo
        self.wiki = ctx.wiki_dir
        self.wd = ctx.cfg.wiki_dir
        self.prefix = ctx.cfg.id_prefix
        self.anchors = anchors
        self.full = full
        self.base = base
        self.findings: list[Finding] = []
        self.pages = wpages.walk(self.wiki, include_archives=True)
        self.by_rel = {p.rel: p for p in self.pages}
        self.rels = set(self.by_rel)
        import backlinks as wbacklinks

        self.backlinks = wbacklinks
        self.planned, self.plan_active = wbacklinks.load_plan(self.wiki, plan, self.repo)
        self._symbols: Optional[dict] = None
        self._tracked: Optional[set[str]] = None
        self._stale: Optional[dict] = None
        self.max_lines = dict(self.cfg.get("budgets.max_lines") or {})
        self.po_words = [str(w) for w in (self.cfg.get("po.forbidden_words") or [])]
        self.po_max_words = int(self.cfg.get("po.max_sentence_words") or 25)
        self.denylist = [str(w) for w in (self.cfg.get("secrets_denylist") or []) if str(w).strip()]

    # ---------------------------------------------------------------- helpers

    def add(self, *a, **kw) -> None:
        self.findings.append(_f(*a, **kw))

    def file_of(self, rel: str) -> str:
        return f"{self.wd}/{rel}"

    @property
    def symbols(self) -> Optional[dict]:
        if self._symbols is None:
            p = self.wiki / "generated" / "symbols.json"
            try:
                self._symbols = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._symbols = {}
        return self._symbols or None

    @property
    def tracked(self) -> set[str]:
        if self._tracked is None:
            try:
                self._tracked = set(gitio.ls_files(self.repo))
            except gitio.GitError:
                self._tracked = set()
        return self._tracked

    def repo_path_exists(self, path: str) -> bool:
        if path in (".", ""):
            return True
        if path in self.tracked:
            return True
        if any(t.startswith(path.rstrip("/") + "/") for t in self.tracked):
            return True
        return (self.repo / path).exists()

    # ---------------------------------------------------------------- L06 frontmatter

    def check_frontmatter(self, p: wpages.Page) -> None:
        f = self.file_of(p.rel)
        if p.error:
            self.add("L06", "L06.parse", "error", f, p.error_line, f"frontmatter: {p.error}", "fix the YAML (subset: no anchors, no block scalars)")
            return
        if p.rel == "log.md":
            if p.fm_lines:
                self.add("L06", "L06.log", "warning", f, 1, "log.md must not carry frontmatter", "remove it")
            return
        fm = p.fm
        if not p.fm_lines:
            self.add("L06", "L06.missing", "error", f, 1, "no frontmatter block", "add the frontmatter contract (type, title, description, id, …)")
            return
        if p.rel == "index.md":
            keys = set(fm)
            if keys != {"okf_version", "title"}:
                self.add("L06", "L06.root_index", "error", f, 1, f"root index.md frontmatter must be exactly okf_version + title, got {sorted(keys)}",
                         "run index.py --write")
            elif str(fm.get("okf_version")) != "0.2":
                self.add("L06", "L06.root_index", "error", f, 1, "root index.md okf_version must be \"0.2\"", "run index.py --write")
            return
        if p.is_index and not re.search(r"index-[a-z0-9-]+\.md$", p.rel):
            if set(fm) != {"title"}:
                self.add("L06", "L06.folder_index", "error", f, 1, f"folder index.md frontmatter must be `title` only, got {sorted(fm)}",
                         "run index.py --write")
            elif not isinstance(fm.get("title"), str) or not fm["title"].strip():
                self.add("L06", "L06.folder_index", "error", f, 1, "folder index.md needs a non-empty title", "run index.py --write")
            return
        for k in REQUIRED:
            if k not in fm:
                self.add("L06", "L06.required", "error", f, 1, f"missing required key `{k}`", f"add `{k}`")
        t = fm.get("type")
        if t is not None and t not in TYPES:
            self.add("L06", "L06.enum", "error", f, 1, f"unknown type {t!r}", "use one of " + ", ".join(TYPES))
        title = fm.get("title")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            self.add("L06", "L06.title", "error", f, 1, "title must be a non-empty string")
        elif isinstance(title, str) and len(title) > 80:
            self.add("L06", "L06.title", "error", f, 1, f"title longer than 80 characters ({len(title)})", "shorten the title")
        desc = fm.get("description")
        if desc is not None and (not isinstance(desc, str) or not desc.strip()):
            self.add("L06", "L06.description", "error", f, 1, "description must be a non-empty one-line string")
        elif isinstance(desc, str) and (len(desc) > 200 or "\n" in desc):
            self.add("L06", "L06.description", "error", f, 1, f"description must be one line of at most 200 characters ({len(desc)})", "shorten it")
        want_id = wpages.page_id(self.prefix, p.rel)
        if "id" in fm and fm.get("id") != want_id:
            self.add("L06", "L06.id", "error", f, 1, f"id {fm.get('id')!r} must equal path-derived {want_id!r}", "lint.py --fix rewrites it")
        sv = fm.get("schema_version")
        if sv is not None and sv != 1:
            self.add("L06", "L06.schema_version", "error", f, 1, f"schema_version must be 1, got {sv!r}")
        aud = fm.get("audience")
        if aud is not None:
            if not isinstance(aud, list) or not aud or any(a not in AUDIENCES for a in aud):
                self.add("L06", "L06.enum", "error", f, 1, f"audience must be a non-empty list of {AUDIENCES}, got {aud!r}")
        owner = fm.get("owner")
        if owner is not None and owner not in OWNERS:
            self.add("L06", "L06.enum", "error", f, 1, f"owner must be one of {OWNERS}, got {owner!r}")
        gen = fm.get("generated")
        if gen is not None:
            if not isinstance(gen, dict) or "by" not in gen or "at" not in gen:
                self.add("L06", "L06.generated", "error", f, 1, "generated must be `{ by: actor, at: ISO-8601 }`")
            else:
                if not isinstance(gen["by"], str) or not ACTOR_RE.match(gen["by"]):
                    self.add("L06", "L06.actor", "error", f, 1, f"generated.by {gen['by']!r} is not an actor (copilot-cli/<model>, process:<script>/<ver>, human:<user>)")
                if not isinstance(gen["at"], str) or not _is_iso(gen["at"]):
                    self.add("L06", "L06.date", "error", f, 1, f"generated.at {gen['at']!r} is not an ISO-8601 timestamp")
        if owner in ("agent", "process"):
            if "sources" not in fm:
                self.add("L06", "L06.conditional", "error", f, 1, f"owner {owner} requires `sources`", "add `sources: []` at least")
            if "last_verified_commit" not in fm:
                self.add("L06", "L06.conditional", "error", f, 1, f"owner {owner} requires `last_verified_commit`", "manifest.py --touched sets it")
        lvc = fm.get("last_verified_commit")
        if lvc is not None and (not isinstance(lvc, str) or not SHA_RE.match(lvc)):
            self.add("L06", "L06.sha", "error", f, 1, "last_verified_commit must be a 40-hex commit sha")
        src = fm.get("sources")
        if src is not None:
            if not isinstance(src, list):
                self.add("L06", "L06.sources", "error", f, 1, "sources must be a list")
            else:
                seen: set[str] = set()
                for i, s in enumerate(src):
                    if not isinstance(s, dict) or "id" not in s or "resource" not in s:
                        self.add("L06", "L06.sources", "error", f, 1, f"sources[{i}] needs `id` and `resource`")
                        continue
                    sid = str(s["id"])
                    if not SOURCE_ID_RE.match(sid):
                        self.add("L06", "L06.sources", "error", f, 1, f"sources[{i}].id {sid!r} must match [a-z0-9][a-z0-9_.-]*")
                    if sid in seen:
                        self.add("L06", "L06.sources", "error", f, 1, f"duplicate source id {sid!r}")
                    seen.add(sid)
                    res = str(s["resource"])
                    if not SOURCE_RES_RE.match(res):
                        self.add("L06", "L06.sources", "error", f, 1, f"sources[{i}].resource {res!r} must be repo://, api://, event://, adr://, changelog://, flag:// or https://")
        st = fm.get("status")
        if st is not None and st not in STATUSES:
            self.add("L06", "L06.enum", "error", f, 1, f"status must be one of {STATUSES}, got {st!r}")
        ver = fm.get("verified")
        if ver is not None:
            if not isinstance(ver, list) or any(not isinstance(v, dict) or "by" not in v or "at" not in v for v in ver):
                self.add("L06", "L06.verified", "error", f, 1, "verified must be a list of `{ by, at }`")
            else:
                for v in ver:
                    if not ACTOR_RE.match(str(v["by"])):
                        self.add("L06", "L06.actor", "error", f, 1, f"verified.by {v['by']!r} is not an actor")
                    if not _is_iso(str(v["at"])):
                        self.add("L06", "L06.date", "error", f, 1, f"verified.at {v['at']!r} is not ISO-8601")
        sa = fm.get("stale_after")
        if sa is not None and not _is_iso(str(sa)):
            self.add("L06", "L06.date", "error", f, 1, f"stale_after {sa!r} is not ISO-8601")
        tags = fm.get("tags")
        if tags is not None and (not isinstance(tags, list) or any(not isinstance(x, str) or not TAG_RE.match(x) for x in tags)):
            self.add("L06", "L06.tags", "error", f, 1, "tags must be a list of lowercase slugs")
        team = fm.get("team")
        if team is not None and (not isinstance(team, str) or not team.startswith("@")):
            self.add("L06", "L06.team", "error", f, 1, "team must be an @group handle")
        for k in ("provides", "consumes"):
            v = fm.get(k)
            if v is not None and (not isinstance(v, list) or any(not isinstance(x, str) or not re.match(r"^(api|event):", x) for x in v)):
                self.add("L06", "L06.contract_ids", "error", f, 1, f"{k} must list `api:<id>` / `event:<channel>` ids")
        rel = fm.get("related")
        if rel is not None and (not isinstance(rel, list) or any(not isinstance(x, str) for x in rel)):
            self.add("L06", "L06.related", "error", f, 1, "related must be a list of page ids")
        for k in fm:
            if k in QUARTZ_RESERVED:
                self.add("L06", "L06.quartz_key", "error", f, 1, f"`{k}` is reserved by Quartz; never use it for another meaning", f"remove `{k}`")
            elif k not in REQUIRED and k not in OPTIONAL:
                self.add("L06", "L06.unknown_key", "warning", f, 1, f"unknown frontmatter key `{k}`")

    # ---------------------------------------------------------------- L01 / L08 links

    def check_links(self, p: wpages.Page) -> None:
        f = self.file_of(p.rel)
        for line, text in wpages.wikilinks(p.body):
            self.add("L08", "L08.wikilink", "error", f, p.line_of(line), f"wikilink [[{text}]] is not allowed", "use a file-relative markdown link with .md")
        for l in wpages.links(p.body):
            r = wpages.classify(p.rel, l.target)
            ln = p.line_of(l.line)
            if r.kind == "absolute":
                self.add("L08", "L08.absolute", "error", f, ln, f"absolute link {l.target!r}", "use a file-relative link")
            elif r.kind == "escapes":
                self.add("L08", "L08.escapes", "error", f, ln, f"relative link {l.target!r} leaves the wiki", "link code with a GitLab blob URL or a backticked path")
            elif r.kind == "internal":
                if r.rel and not r.rel.endswith(".md") and "." not in r.rel.rsplit("/", 1)[-1]:
                    self.add("L08", "L08.no_extension", "error", f, ln, f"relative link {l.target!r} must end with .md", "append .md")
                    continue
                if r.rel and r.rel.endswith(".md"):
                    if r.rel == "log.md" or r.rel.startswith("log/"):
                        self.add("L10", "L10.log_cited", "error", f, ln, "no page may link to or cite the log", "remove the link")
                    if r.rel not in self.rels:
                        if r.rel in self.planned:
                            self.add("L01", "L01.planned", "warning", f, ln, f"link target {r.rel} is a planned page not written yet")
                        elif p.owner == "process" and r.rel.endswith("-guide.md"):
                            self.add("L01", "L01.guide_pending", "info", f, ln, f"written guide {r.rel} not created yet", "create it (Contract Guide)")
                        else:
                            self.add("L01", "L01.missing", "error", f, ln, f"broken link: {r.rel} does not exist", "fix the path or create the page")
                    elif self.anchors and r.fragment:
                        target = self.by_rel[r.rel]
                        slugs = {heading_slug(h) for _, h, _ in wpages.headings(target.body)}
                        if r.fragment.lower() not in slugs:
                            self.add("L01", "L01.anchor", "error", f, ln, f"anchor #{r.fragment} not found in {r.rel}")
                elif r.rel and not (self.wiki / r.rel).exists():
                    self.add("L01", "L01.missing", "error", f, ln, f"broken link: {r.rel} does not exist")
        for s in p.sources:
            res = str(s.get("resource") or "")
            if "log.md" in res or res.startswith("repo://" + self.wd + "/"):
                self.add("L10", "L10.log_cited", "error", f, 1, f"source {res!r} cites the wiki itself", "cite code, specs or ADRs only")

    # ---------------------------------------------------------------- L04 size

    def check_size(self, p: wpages.Page) -> None:
        f = self.file_of(p.rel)
        n = len(p.body.rstrip("\n").split("\n")) if p.body.strip() else 0
        if p.rel == "log.md":
            keep = int(self.cfg.budget("log_entries") or 200)
            entries = sum(1 for l in p.body.split("\n") if l.startswith("* "))
            if entries > keep:
                self.add("L04", "L04.log", "warning", f, 1, f"log has {entries} entries (budget {keep})", "run log.py rotate")
            return
        if p.rel == "index.md":
            limit = int(self.cfg.budget("index_root_lines") or 120)
        elif p.is_index:
            limit = int(self.cfg.budget("index_folder_lines") or 200)
        else:
            limit = self.max_lines.get(p.type)
        if limit and n > limit:
            self.add("L04", "L04.lines", "error", f, p.fm_lines + limit + 1, f"{n} body lines exceed the cap of {limit} for {p.type or 'index'}",
                     "split the page or drop empty sections")

    # ---------------------------------------------------------------- L05 secrets

    def check_secrets(self, text: str, file: str) -> None:
        for no, line in enumerate(text.split("\n"), 1):
            for name, rx in SECRET_PATTERNS:
                if rx.search(line):
                    self.add("L05", f"L05.{name.replace(' ', '_')}", "error", file, no, f"possible secret ({name})", "remove it; refer to secrets by name only")
                    break
            low = line.lower()
            for word in self.denylist:
                if word.lower() in low:
                    self.add("L05", "L05.denylist", "error", file, no, f"denylisted string {word!r}", "remove it")
                    break

    # ---------------------------------------------------------------- L07 PO

    def check_po(self, p: wpages.Page) -> None:
        if "po" not in p.audience or p.type == "Glossary":
            return
        f = self.file_of(p.rel)
        if "```" in p.body or "~~~" in p.body:
            self.add("L07", "L07.code_fence", "error", f, p.line_of(next((i for i, l in enumerate(p.body.split("\n"), 1) if l.startswith(("```", "~~~"))), 1)),
                     "PO page contains a code fence", "describe behaviour in words")
        for s in p.sources:
            if str(s.get("resource") or "").startswith("repo://"):
                self.add("L07", "L07.repo_source", "error", f, 1, f"PO page cites a repo:// source ({s.get('id')})", "cite api://, event://, flag:// or changelog://")
        prose = re.sub(r"\]\([^)]*\)", "]()", textnorm.strip_code(p.body))  # wiki links are allowed on PO pages
        with_code = re.sub(r"\]\([^)]*\)", "]()", textnorm.strip_fences(p.body)).split("\n")
        first_table = None
        plain_seen = False
        for i, line in enumerate(prose.split("\n"), 1):
            if line.lstrip().startswith("|") and first_table is None:
                first_table = i
            if "**In plain words" in line and first_table is None:
                plain_seen = True
            m = PATH_RE.search(with_code[i - 1] if i - 1 < len(with_code) else line)
            if m and not line.lstrip().startswith("#"):
                self.add("L07", "L07.path", "error", f, p.line_of(i), f"PO page mentions a file path {m.group(0)!r}", "remove the path")
            for w in self.po_words:
                rx = re.compile(r"\b" + re.escape(w) + r"\b", 0 if w.isupper() else re.I)
                if rx.search(line) and not line.lstrip().startswith("#"):
                    self.add("L07", "L07.vocabulary", "error", f, p.line_of(i), f"forbidden vocabulary {w!r} on a PO page", "rephrase for a non-developer")
                    break
        if first_table is not None and not plain_seen:
            self.add("L07", "L07.plain_words", "error", f, p.line_of(first_table), 'PO page needs an "**In plain words.**" paragraph before its first table')
        for i, line in enumerate(prose.split("\n"), 1):
            if line.lstrip().startswith(("#", "|", "[^")) or not line.strip():
                continue
            for sent in textnorm.sentences(line):
                if textnorm.word_count(sent) > self.po_max_words:
                    self.add("L07", "L07.sentence", "error", f, p.line_of(i), f"sentence longer than {self.po_max_words} words ({textnorm.word_count(sent)})", "split it")
                    break

    # ---------------------------------------------------------------- L13 citations

    def check_citations(self, p: wpages.Page) -> None:
        f = self.file_of(p.rel)
        narrative = p.type in wpages.NARRATIVE_TYPES and p.owner in ("agent", "both") and "po" not in p.audience
        repo_sources = [s for s in p.sources if str(s.get("resource") or "").startswith("repo://")]
        if narrative and not repo_sources:
            self.add("L13", "L13.no_repo_source", "error", f, 1, f"{p.type} page has no repo:// source", "cite at least one code path in `sources`")
        for s in p.sources:
            r = wpages.parse_resource(str(s.get("resource") or ""))
            if not r or r.scheme != "repo":
                continue
            if not self.repo_path_exists(r.path):
                self.add("L13", "L13.missing_path", "error", f, 1, f"source {s.get('id')}: {r.path!r} does not exist in the repository", "fix the path")
            elif r.symbol:
                self._check_symbol(f, 1, r.path, r.symbol)
        describes_microformat = p.owner == "human" or p.type in ("Instructions", "Conventions", "Requests", "Glossary")
        for i, line in enumerate(p.body.split("\n"), 1):
            if describes_microformat:
                break  # example tokens such as `path/file.py::Symbol` are documentation, not citations
            for m in CITATION_RE.finditer(line):
                path, sym = m.group(1), m.group(2)
                if not self.repo_path_exists(path):
                    self.add("L13", "L13.missing_path", "error", f, p.line_of(i), f"citation `{path}::{sym}`: file does not exist")
                else:
                    self._check_symbol(f, p.line_of(i), path, sym)
        refs = wpages.footnote_refs(p.body)
        defs = wpages.footnote_defs(p.body)
        for r in sorted(refs - defs):
            self.add("L13", "L13.footnote_undefined", "warning", f, 1, f"footnote [^{r}] is referenced but never defined")
        ids = {str(s.get("id")) for s in p.sources}
        for d in sorted(defs - ids):
            if p.sources:
                self.add("L13", "L13.footnote_unkeyed", "warning", f, 1, f"footnote [^{d}] does not match any sources[].id")

    def _check_symbol(self, file: str, line: int, path: str, sym: str) -> None:
        idx = self.symbols
        if not idx:
            return
        entry = idx.get(path)
        if entry is None:
            if wsymbols.language_of(path):
                self.add("L13", "L13.not_indexed", "warning", file, line, f"`{path}` is not in generated/symbols.json (run facts.py)")
            return
        if wsymbols.find_symbol(entry, sym) is None:
            self.add("L13", "L13.unknown_symbol", "error", file, line, f"symbol `{path}::{sym}` not found in the symbol index", "cite a symbol that exists")

    # ---------------------------------------------------------------- L14 hidden

    def check_hidden(self, text: str, file: str, exempt_comments: bool = False) -> None:
        for n, (ln, col, cp) in enumerate(textnorm.find_hidden(text)):
            if n >= 5:
                self.add("L14", "L14.hidden", "error", file, ln, "more hidden characters follow", "lint.py --fix strips them")
                break
            self.add("L14", "L14.hidden", "error", file, ln, f"hidden character U+{cp:04X} at column {col}", "lint.py --fix strips them")
        if exempt_comments:
            return
        for m in HTML_COMMENT_RE.finditer(text):
            if not MANAGED_COMMENT_RE.match(m.group(1)):
                ln = text.count("\n", 0, m.start()) + 1
                self.add("L14", "L14.html_comment", "error", file, ln, "HTML comment other than a managed marker", "delete the comment")

    # ---------------------------------------------------------------- L16 trust gate

    def check_trust(self, p: wpages.Page) -> None:
        if p.type not in wpages.LOAD_BEARING_TYPES:
            return
        f = self.file_of(p.rel)
        explicit = p.fm.get("status")
        human = any(isinstance(v, dict) and str(v.get("by", "")).startswith("human:") for v in (p.fm.get("verified") or []) if p.fm.get("verified"))
        if explicit == "stable" and not human:
            self.add("L16", "L16.trust", "error", f, 1, f"{p.type} marked stable without a human: entry in `verified`", "set status: draft or add a human verification")
        elif explicit is None and not human:
            self.add("L16", "L16.trust", "warning", f, 1, f"{p.type} has no status (counts as stable) and no human verification", "set status: draft")

    # ---------------------------------------------------------------- per-file driver

    def lint_page(self, p: wpages.Page, rules: Iterable[str]) -> None:
        rules = set(rules)
        f = self.file_of(p.rel)
        if "L06" in rules:
            self.check_frontmatter(p)
        if p.rel.startswith("log/") and p.rel != "log.md":
            return
        if "L01" in rules or "L08" in rules:
            self.check_links(p)
        if "L04" in rules:
            self.check_size(p)
        if "L05" in rules:
            self.check_secrets(p.text, f)
        if "L07" in rules:
            self.check_po(p)
        if "L13" in rules and not p.is_index and p.rel != "log.md":
            self.check_citations(p)
        if "L14" in rules:
            self.check_hidden(p.text, f, exempt_comments=(p.owner == "human" or p.type in ("Instructions", "Requests")))
        if "L16" in rules:
            self.check_trust(p)
        if "\r" in p.text:
            self.add("L14", "L14.crlf", "warning", f, 1, "CRLF line endings", "lint.py --fix converts to LF")
        if p.text and not p.text.endswith("\n"):
            self.add("L14", "L14.newline", "warning", f, 1, "no final newline", "lint.py --fix adds it")
        if not p.is_index and p.rel != "log.md" and p.fm_lines and not any(l.startswith("# ") for l in p.body.split("\n")):
            self.add("L06", "L06.h1", "warning", f, p.fm_lines + 1, "no H1 heading", "lint.py --fix inserts `# <title>`")

    # ---------------------------------------------------------------- global rules (--all)

    def check_orphans(self) -> None:
        graph = wpages.link_graph(self.pages, self.prefix)
        for o in self.backlinks.orphans(self.pages, graph, self.planned, self.plan_active):
            self.add("L02", "L02.orphan", o["severity"], self.file_of(o["file"]), 1, o["message"], o.get("fix"))

    def staleness(self) -> dict:
        if self._stale is None:
            man = wmanifest.load(self.wiki)
            head = gitio.head(self.repo)
            self._stale = wmanifest.compute_stale(man, self.repo, [p for p in self.pages if not p.rel.startswith("log/")], head,
                                                  full=self.full, now=self.ctx.now) if man else {"stale": {}, "untracked": [], "manifest_drift": [], "warnings": [], "missing": True}
        return self._stale

    def check_stale(self) -> None:
        st = self.staleness()
        if st.get("missing"):
            self.add("L03", "L03.no_manifest", "warning", self.file_of(".manifest.json"), 1, "no .manifest.json; staleness cannot be computed", "run manifest.py --init")
            return
        for rel, reasons in sorted(st["stale"].items()):
            p = self.by_rel.get(rel)
            if p is None or p.owner == "process":
                continue
            sev = "error" if p.status == "stable" else "info"
            summary = "; ".join(f"{r['kind']} {r.get('path') or ''}".strip() for r in reasons[:4])
            self.add("L03", "L03.stale", sev, self.file_of(rel), 1, f"sources changed since last_verified_commit: {summary}", "run /wiki-update")
        for rel in st.get("untracked", []):
            self.add("L03", "L03.untracked", "warning", self.file_of(rel), 1, "page has sources but no manifest entry", "run manifest.py --touched")
        for rel in st.get("manifest_drift", []):
            self.add("L03", "L03.manifest_drift", "warning", self.file_of(rel), 1, "last_verified_commit differs from the manifest entry", "run manifest.py --touched")
        for w in st.get("warnings", []):
            self.add("L03", "L03.warning", "warning", self.file_of(".manifest.json"), 1, w)

    def check_ownership(self) -> None:
        if not self.base:
            return
        head = gitio.head(self.repo)
        if not head or not gitio.rev_parse(self.base, self.repo):
            self.add("L09", "L09.base", "warning", self.file_of(".manifest.json"), 1, f"--base {self.base} is not a commit; ownership not checked")
            return
        allowed_outside = {".github/instructions/wiki-consumers.instructions.md"}
        for e in gitio.log(self.repo, n=500, rev_range=f"{self.base}..{head}"):
            if not re.search(r"^Wiki-Update:", e.get("body", ""), re.M):
                continue
            for path in gitio.diff_tree_files(e["sha"], self.repo):
                short = e["sha"][:10]
                if not path.startswith(self.wd + "/"):
                    if path not in allowed_outside:
                        self.add("L09", "L09.outside_wiki", "error", path, 1, f"bot commit {short} touches a file outside {self.wd}/", "revert it; bots write only the wiki")
                    continue
                rel = path[len(self.wd) + 1:]
                if rel == "instructions.md":
                    self.add("L09", "L09.human_page", "error", path, 1, f"bot commit {short} edits the human-owned instructions.md")
                    continue
                before = gitio.show(f"{e['sha']}~1", path, self.repo)
                if before is not None:
                    owner = wfm.get_key(before, "owner") if wfm.has_frontmatter(before) else None
                    if owner == "human":
                        self.add("L09", "L09.human_page", "error", path, 1, f"bot commit {short} edits an owner: human page")

    def check_integrity(self) -> None:
        import index as windex
        import log as wlog

        try:
            ix = windex.Indexer(self.ctx)
            ix.generate()
            for rel in ix.drift():
                self.add("L10", "L10.index", "error", self.file_of(rel), 1, "index differs from the generated one", "run index.py --write")
        except Exception as e:  # noqa: BLE001
            self.add("L10", "L10.index", "warning", self.file_of("index.md"), 1, f"index check failed: {e}")
        try:
            import facts as wfacts

            fx = wfacts.Facts(self.ctx)
            fx.run([g for g in wfacts.GENERATORS if g != "catalog"])
            drift, missing = fx.check()
            for rel in drift:
                self.add("L10", "L10.facts", "error", self.file_of(rel), 1, "generated page differs from regeneration", "run facts.py")
            for rel in missing:
                self.add("L10", "L10.facts", "warning", self.file_of(rel), 1, "generated page missing", "run facts.py")
        except cli.KitError as e:
            self.add("L10", "L10.facts", "warning", self.file_of("generated"), 1, f"facts check skipped: {e}")
        log_path = self.wiki / "log.md"
        if log_path.exists():
            for fnd in wlog.check_text(log_path.read_text(encoding="utf-8"), "log.md"):
                self.add("L10", "L10.log", "error", self.file_of("log.md"), fnd["line"], fnd["message"], "fix the entry; entries are `* **Action**: text`")
        for arch in sorted((self.wiki / "log").glob("*.md")) if (self.wiki / "log").is_dir() else []:
            for fnd in wlog.check_text(arch.read_text(encoding="utf-8"), f"log/{arch.name}", archive=True):
                self.add("L10", "L10.log", "error", self.file_of(f"log/{arch.name}"), fnd["line"], fnd["message"])
        req = self.wiki / "requests.md"
        if req.exists():
            import requests as wreq

            for fnd in wreq.lint(req.read_text(encoding="utf-8")):
                self.add("L10", "L10.requests", "error", self.file_of("requests.md"), fnd["line"], fnd["message"])

    def check_coverage(self) -> None:
        decisions = []
        try:
            decisions = json.loads((self.wiki / "generated" / "decisions.json").read_text(encoding="utf-8")).get("adrs") or []
        except (OSError, ValueError):
            pass
        narrative = [p for p in self.pages if p.owner != "process" and not p.is_index]
        for g in wpages.coverage_gaps(self.tracked, self.cfg, narrative, wsymbols.CODE_EXTS, decisions):
            if g["kind"] == "uncovered_dir":
                msg = f"no page cites {g['path']} ({g['files']} source files); suggested {g['suggested_page']}"
            elif g["kind"] == "missing_guide":
                msg = f"{g['path']} has no written guide {g['suggested_page']}"
            else:
                msg = f"ADR {g.get('adr')} ({g['path']}) is cited by no page"
            # info, never a failure: gaps are work for bootstrap/affected.py, not an invalid wiki (plan §10 b expects a
            # freshly installed wiki to pass `lint --all --strict`)
            self.add("L12", f"L12.{g['kind']}", "info", g["path"] if g["kind"] != "missing_guide" else self.file_of(g["path"]), 1, msg,
                     f"create {g['suggested_page']} ({g['suggested_type']})")

    def check_duplicates(self) -> None:
        files = [self.repo / ".github" / "copilot-instructions.md", self.repo / "AGENTS.md", self.repo / "CLAUDE.md"]
        inst = self.repo / ".github" / "instructions"
        if inst.is_dir():
            files += sorted(inst.glob("*.instructions.md"))
        external: dict[str, str] = {}
        for fp in files:
            if not fp.exists():
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            _, body, _ = wfm.split(text) if wfm.has_frontmatter(text) else ("", text, 0)
            for level, h, _ in wpages.headings(body):
                if level >= 2:
                    external.setdefault(h.strip().lower(), fp.relative_to(self.repo).as_posix())
        if not external:
            return
        for p in self.pages:
            if p.is_index or p.owner == "process" or p.rel.startswith("log/"):
                continue
            for level, h, line in wpages.headings(p.body):
                key = h.strip().lower()
                if level >= 2 and key in external and key not in GENERIC_HEADINGS:
                    self.add("L15", "L15.duplicate_heading", "warning", self.file_of(p.rel), p.line_of(line),
                             f"heading {h!r} also appears in {external[key]}", "keep knowledge in the wiki; instruction files only point to it")

    def check_churn(self, rels: Iterable[str]) -> None:
        st = self.staleness()
        if st.get("missing"):
            return
        head = gitio.head(self.repo)
        for rel in rels:
            p = self.by_rel.get(rel)
            if p is None or p.owner == "process" or p.is_index:
                continue
            before = gitio.show(self.base or head or "HEAD", f"{self.wd}/{rel}", self.repo)
            if before is None:
                continue
            _, old_body, _ = wfm.split(before) if wfm.has_frontmatter(before) else ("", before, 0)
            ratio = difflib.SequenceMatcher(None, old_body, p.body).ratio()
            if ratio < 0.7 and rel not in st.get("stale", {}):
                self.add("L17", "L17.churn", "warning", self.file_of(rel), 1, f"body changed {int((1 - ratio) * 100)}% although no declared source changed",
                         "keep edits to the affected sections")

    # ---------------------------------------------------------------- fix

    def fix(self, rels: Iterable[str]) -> list[str]:
        fixed: list[str] = []
        for rel in rels:
            p = self.by_rel.get(rel)
            if p is None or wpages.is_process_owned(rel) or p.owner == "process":
                continue
            text = p.text
            new = text.replace("\r\n", "\n").replace("\r", "\n")
            new = textnorm.strip_hidden(new)
            new = "\n".join(l.rstrip() for l in new.split("\n"))
            if new.strip() and not new.endswith("\n"):
                new += "\n"
            if wfm.has_frontmatter(new) and not p.error:
                try:
                    fm, body = wfm.parse(new)
                    if "id" in fm and fm.get("id") != wpages.page_id(self.prefix, rel) and not p.is_index:
                        new = wfm.replace_key(new, "id", wpages.page_id(self.prefix, rel))
                        fm, body = wfm.parse(new)
                    if not p.is_index and not any(l.startswith("# ") for l in body.split("\n")) and fm.get("title"):
                        head_txt, body_txt, _ = wfm.split(new)
                        new = "---\n" + head_txt + "\n---\n" + f"# {fm['title']}\n" + body_txt
                except Exception:  # noqa: BLE001
                    pass
            if new != text:
                p.path.write_text(new, encoding="utf-8", newline="\n")
                fixed.append(rel)
        if fixed:
            self.pages = wpages.walk(self.wiki, include_archives=True)
            self.by_rel = {p.rel: p for p in self.pages}
        return fixed


def _is_iso(text: str) -> bool:
    try:
        cli.parse_iso(text)
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}", text))
    except (ValueError, TypeError):
        return False


def _to_rel(ctx: cli.Ctx, path: str) -> Optional[str]:
    wd = ctx.cfg.wiki_dir
    p = Path(path)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(ctx.wiki_dir.resolve()).as_posix()
        except ValueError:
            return None
        return rel
    s = path.replace("\\", "/")
    if s.startswith(wd + "/"):
        return s[len(wd) + 1:]
    if (ctx.wiki_dir / s).exists():
        return s
    return None


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", default=None, help="one page (fast subset)")
    g.add_argument("--changed", action="store_true")
    g.add_argument("--staged", action="store_true")
    g.add_argument("--all", action="store_true")
    p.add_argument("--fix", action="store_true")
    p.add_argument("--strict", action="store_true", help="warnings become errors")
    p.add_argument("--base", default=None, help="checkpoint commit for --changed / L09 / L17")
    p.add_argument("--full", action="store_true", help="full staleness comparison (ignore the checkpoint)")
    p.add_argument("--anchors", action="store_true", help="check link fragments against headings")
    p.add_argument("--plan", default=None, help="cluster plan file (default: <wiki>/.wiki-plan.json)")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if not ctx.wiki_dir.is_dir():
        raise cli.EnvError(f"wiki directory missing: {ctx.wiki_dir}")
    linter = Linter(ctx, anchors=args.anchors, plan=args.plan, full=args.full, base=args.base)
    wd = ctx.cfg.wiki_dir
    mode = "file" if args.file else "changed" if args.changed else "staged" if args.staged else "all"
    if args.file:
        rel = _to_rel(ctx, args.file)
        if rel is None:
            raise cli.ConfigError(f"{args.file} is not inside the wiki directory {wd}/")
        if rel not in linter.by_rel:
            if (ctx.wiki_dir / rel).exists():
                ctx.emit.say(f"lint: {args.file} is not a markdown page; secret scan only")
                linter.check_secrets((ctx.wiki_dir / rel).read_text(encoding="utf-8", errors="replace"), f"{wd}/{rel}")
                targets: list[str] = []
            else:
                raise cli.ConfigError(f"{args.file} does not exist")
        else:
            targets = [rel]
        rules = FAST_RULES
    elif args.all:
        targets = [p.rel for p in linter.pages if not p.rel.startswith("log/")]
        rules = FAST_RULES
    else:
        changed = gitio.changed_paths(ctx.repo, [wd], base=args.base, staged_only=args.staged)
        targets = [c[len(wd) + 1:] for c in changed if c.startswith(wd + "/") and c.endswith(".md") and c[len(wd) + 1:] in linter.by_rel]
        rules = FAST_RULES
    fixed: list[str] = []
    if args.fix:
        fixed = linter.fix(targets)
    for rel in targets:
        page = linter.by_rel.get(rel)
        if page is not None:
            linter.lint_page(page, rules)
    if args.all:
        linter.check_orphans()
        linter.check_stale()
        linter.check_ownership()
        linter.check_integrity()
        linter.check_coverage()
        linter.check_duplicates()
        changed = gitio.changed_paths(ctx.repo, [wd], base=args.base)
        linter.check_churn([c[len(wd) + 1:] for c in changed if c.startswith(wd + "/") and c.endswith(".md")])
        for f in sorted(ctx.wiki_dir.rglob("*")):
            if f.is_file() and f.suffix != ".md" and not any(part.startswith(".") and part != ".manifest.json" for part in f.relative_to(ctx.wiki_dir).parts):
                linter.check_secrets(f.read_text(encoding="utf-8", errors="replace"), f"{wd}/{f.relative_to(ctx.wiki_dir).as_posix()}")
    elif args.changed and targets:
        linter.check_churn(targets)
    findings = linter.findings
    if args.strict:
        for fnd in findings:
            if fnd["severity"] == "warning":
                fnd["severity"] = "error"
                fnd["strict"] = True
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]
    order = {"error": 0, "warning": 1, "info": 2}
    for fnd in sorted(findings, key=lambda x: (x["file"], x["line"] or 0, order[x["severity"]], x["rule"])):
        ctx.emit.say(f"{fnd['file']}:{fnd['line'] or 1}: {fnd['rule']} {fnd['severity']}: {fnd['message']}" + (f" → {fnd['fix']}" if fnd.get("fix") else ""))
    rules_count: dict[str, int] = {}
    for fnd in findings:
        rules_count[fnd["rule"]] = rules_count.get(fnd["rule"], 0) + 1
    summary = {"mode": mode, "files": len(targets), "errors": len(errors), "warnings": len(warnings), "info": len(infos),
               "rules": dict(sorted(rules_count.items())), "fixed": fixed, "strict": bool(args.strict)}
    ctx.emit.say(f"lint: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info in {len(targets)} file(s)" + (f"; fixed {len(fixed)}" if fixed else ""))
    ctx.emit.emit({"errors": errors, "warnings": warnings, "info": infos, "summary": summary}, ok=not errors)
    return cli.EXIT_FINDINGS if errors else 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
