"""Wiki page model: walk the wiki dir, parse frontmatter, extract links, build the link graph,
classify process-owned paths, compute coverage gaps.

API:
  Page (dataclass): rel, path, text, fm, body, fm_lines, error, type, owner, title, sources
  walk(wiki_dir) -> [Page]                          every *.md except log/ archives, sorted by rel
  load_page(wiki_dir, rel) -> Page
  is_index(rel) / is_root_file(rel) / is_process_owned(rel) / is_facts_folder_index(rel)
  page_id(prefix, rel) / rel_from_id(prefix, id)
  links(body) -> [Link(text, target, line)]         inline markdown links outside code
  wikilinks(body) -> [(line, text)]
  classify(from_rel, target) -> Resolved(kind, rel, fragment)  kind: internal|external|anchor|absolute|escapes
  link_graph(pages, prefix) -> {rel: {"out": set, "in": set, "related": set}}
  headings(body) -> [(level, text, line)]
  footnote_defs(body) / footnote_refs(body) -> set
  source_paths(page) -> [(id, path, is_dir)]        repo:// sources as repository paths
  coverage_gaps(...) -> [gap]
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from . import frontmatter, textnorm, yamlmini

__all__ = ["Page", "Link", "Resolved", "walk", "load_page", "is_index", "is_root_file", "is_process_owned",
           "is_facts_folder_index", "page_id", "rel_from_id", "links", "wikilinks", "classify", "link_graph",
           "headings", "footnote_defs", "footnote_refs", "source_paths", "coverage_gaps", "ROOT_FILES",
           "FACTS_FOLDERS", "NARRATIVE_TYPES", "LOAD_BEARING_TYPES", "parse_resource"]

ROOT_FILES = ("index.md", "log.md", "conventions.md", "requests.md", "instructions.md", "overview.md",
              "glossary.md")
FACTS_FOLDERS = ("decisions", "api", "events")
NARRATIVE_TYPES = ("Module", "Concept", "How-to", "Runbook", "Architecture", "Contract Guide", "Analysis")
LOAD_BEARING_TYPES = ("Contract Guide", "Runbook", "Feature", "Release Notes")

_INDEX_RE = re.compile(r"(^|/)index(-[a-z0-9-]+)?\.md$")
_API_PAGE_RE = re.compile(r"^(api|events)/[^/]+\.md$")


@dataclass
class Page:
    rel: str
    path: Path
    text: str = ""
    fm: dict = field(default_factory=dict)
    body: str = ""
    fm_lines: int = 0
    error: Optional[str] = None
    error_line: int = 1

    @property
    def type(self) -> str:
        return str(self.fm.get("type") or "")

    @property
    def owner(self) -> str:
        return str(self.fm.get("owner") or "")

    @property
    def title(self) -> str:
        return str(self.fm.get("title") or "")

    @property
    def status(self) -> str:
        return str(self.fm.get("status") or "stable")

    @property
    def audience(self) -> list:
        a = self.fm.get("audience")
        return list(a) if isinstance(a, list) else ([a] if a else [])

    @property
    def sources(self) -> list:
        s = self.fm.get("sources")
        return [x for x in s if isinstance(x, dict)] if isinstance(s, list) else []

    @property
    def folder(self) -> str:
        return posixpath.dirname(self.rel)

    @property
    def is_index(self) -> bool:
        return is_index(self.rel)

    def line_of(self, body_line: int) -> int:
        """File line number for a 1-based body line."""
        return self.fm_lines + body_line


@dataclass
class Link:
    text: str
    target: str
    line: int  # 1-based body line


@dataclass
class Resolved:
    kind: str  # internal | external | anchor | absolute | escapes
    rel: Optional[str] = None
    fragment: str = ""


def is_index(rel: str) -> bool:
    return bool(_INDEX_RE.search(rel))


def is_root_file(rel: str) -> bool:
    return "/" not in rel and rel in ROOT_FILES


def is_facts_folder_index(rel: str) -> bool:
    return rel in ("api/index.md", "events/index.md", "decisions/index.md")


def is_process_owned(rel: str) -> bool:
    """Paths the scripts own (guard + L09): indexes, log, manifest, plan, generated, api/events pages."""
    if rel in (".manifest.json", ".wiki-plan.json", "log.md", "index.md"):
        return True
    if rel.startswith("log/") or rel.startswith("generated/"):
        return True
    if is_index(rel):
        return True
    if _API_PAGE_RE.match(rel) and not rel.endswith("-guide.md"):
        return True
    if rel == "decisions/index.md":
        return True
    return False


def page_id(prefix: str, rel: str) -> str:
    r = rel[:-3] if rel.endswith(".md") else rel
    return f"{prefix}/{r}"


def rel_from_id(prefix: str, pid: str) -> Optional[str]:
    if not pid or not pid.startswith(prefix + "/"):
        return None
    return pid[len(prefix) + 1:] + ".md"


def load_page(wiki_dir: Path, rel: str) -> Page:
    p = Path(wiki_dir) / rel
    page = Page(rel=rel, path=p)
    try:
        raw = p.read_bytes()
    except OSError as e:
        page.error = f"unreadable: {e}"
        return page
    text = raw.decode("utf-8", "replace")
    page.text = text
    try:
        fm_text, body, n = frontmatter.split(text)
        page.body = body
        page.fm_lines = n
        if n:
            page.fm = yamlmini.loads(fm_text)
            if not isinstance(page.fm, dict):
                page.fm = {}
                page.error = "frontmatter is not a mapping"
    except yamlmini.YamlError as e:
        page.error = f"frontmatter YAML: {e.msg}"
        page.error_line = e.line + 1
        page.fm = {}
        fm_text, page.body, page.fm_lines = frontmatter.split(text) if frontmatter.has_frontmatter(text) else ("", text, 0)
    except frontmatter.FrontmatterError as e:
        page.error = str(e.msg)
        page.error_line = e.line
        page.body = text
        page.fm_lines = 0
    return page


def walk(wiki_dir: Path, include_archives: bool = False) -> list[Page]:
    wiki_dir = Path(wiki_dir)
    out: list[Page] = []
    if not wiki_dir.is_dir():
        return out
    for p in sorted(wiki_dir.rglob("*.md")):
        if any(part.startswith(".") for part in p.relative_to(wiki_dir).parts):
            continue
        rel = p.relative_to(wiki_dir).as_posix()
        if rel.startswith("log/") and not include_archives:
            continue
        out.append(load_page(wiki_dir, rel))
    return out


# ---------------------------------------------------------------- links

_LINK_RE = re.compile(r"(?<!\!)\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:", re.M)
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _prose_lines(body: str) -> list[tuple[int, str]]:
    """(line_no, text) for lines outside fenced code, with inline code removed."""
    lines = body.split("\n")
    fenced: set[int] = set()
    for a, b in textnorm.fenced_line_ranges(body):
        fenced.update(range(a, b + 1))
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        if i in fenced:
            continue
        out.append((i, textnorm._INLINE_CODE.sub("", line)))
    return out


def links(body: str) -> list[Link]:
    out: list[Link] = []
    for no, line in _prose_lines(body):
        for m in _LINK_RE.finditer(line):
            text, target = m.group(1), m.group(2)
            if text.startswith("^"):
                continue
            out.append(Link(text=text, target=target, line=no))
    return out


def wikilinks(body: str) -> list[tuple[int, str]]:
    return [(no, m.group(1)) for no, line in _prose_lines(body) for m in _WIKILINK_RE.finditer(line)]


def classify(from_rel: str, target: str) -> Resolved:
    t = target.strip()
    if not t:
        return Resolved("anchor", from_rel, "")
    if _SCHEME_RE.match(t) or t.startswith("//"):
        return Resolved("external")
    frag = ""
    if "#" in t:
        t, frag = t.split("#", 1)
    if not t:
        return Resolved("anchor", from_rel, frag)
    if t.startswith("/"):
        return Resolved("absolute", None, frag)
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), t))
    if joined == ".." or joined.startswith("../"):
        return Resolved("escapes", None, frag)
    if joined.endswith("/"):
        joined += "index.md"
    return Resolved("internal", joined, frag)


def link_graph(pages: Iterable[Page], prefix: str) -> dict[str, dict[str, set]]:
    pages = list(pages)
    rels = {p.rel for p in pages}
    id_map = {page_id(prefix, p.rel): p.rel for p in pages}
    for p in pages:
        pid = p.fm.get("id")
        if isinstance(pid, str):
            id_map.setdefault(pid, p.rel)
    g: dict[str, dict[str, set]] = {p.rel: {"out": set(), "in": set(), "related": set()} for p in pages}
    for p in pages:
        for l in links(p.body):
            r = classify(p.rel, l.target)
            if r.kind == "internal" and r.rel in rels and r.rel != p.rel:
                g[p.rel]["out"].add(r.rel)
                g[r.rel]["in"].add(p.rel)
        rel_ids = p.fm.get("related")
        if isinstance(rel_ids, list):
            for rid in rel_ids:
                tgt = id_map.get(str(rid))
                if tgt and tgt in g and tgt != p.rel:
                    g[p.rel]["related"].add(tgt)
                    g[tgt]["related"].add(p.rel)
    return g


def headings(body: str) -> list[tuple[int, str, int]]:
    out: list[tuple[int, str, int]] = []
    fenced: set[int] = set()
    for a, b in textnorm.fenced_line_ranges(body):
        fenced.update(range(a, b + 1))
    for i, line in enumerate(body.split("\n"), 1):
        if i in fenced:
            continue
        m = _HEADING_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), i))
    return out


def footnote_defs(body: str) -> set[str]:
    return set(_FOOTNOTE_DEF_RE.findall(body))


def footnote_refs(body: str) -> set[str]:
    return {m for _, line in _prose_lines(body) for m in _FOOTNOTE_REF_RE.findall(line)}


# ---------------------------------------------------------------- sources

_RES_RE = re.compile(r"^(?P<scheme>[a-z][a-z0-9+]*)://(?P<rest>.*)$")
_RANGE_RE = re.compile(r"^L(\d+)(?:-L?(\d+))?$")


@dataclass
class Resource:
    scheme: str
    path: str
    line_range: Optional[tuple[int, int]] = None
    symbol: Optional[str] = None
    raw: str = ""

    @property
    def is_dir(self) -> bool:
        return self.scheme == "repo" and self.raw.rstrip().endswith("/")


def parse_resource(resource: str) -> Optional[Resource]:
    """`repo://path[#La-Lb|::Symbol]`, `api://id[/op]`, `event://channel`, `adr://NNNN`, …"""
    if not isinstance(resource, str):
        return None
    m = _RES_RE.match(resource.strip())
    if not m:
        return None
    scheme, rest = m.group("scheme"), m.group("rest")
    res = Resource(scheme=scheme, path=rest, raw=resource.strip())
    if scheme == "repo":
        path = rest
        if "::" in path:
            path, sym = path.split("::", 1)
            res.symbol = sym.strip() or None
        elif "#" in path:
            path, frag = path.split("#", 1)
            rm = _RANGE_RE.match(frag.strip())
            if rm:
                a = int(rm.group(1))
                b = int(rm.group(2)) if rm.group(2) else a
                res.line_range = (min(a, b), max(a, b))
        res.path = path.strip().rstrip("/") if path.strip() != "/" else ""
    return res


def source_paths(page: Page) -> list[tuple[str, str, bool]]:
    """(source id, repository path, is_dir) for every repo:// source."""
    out: list[tuple[str, str, bool]] = []
    for s in page.sources:
        r = parse_resource(s.get("resource", ""))
        if r and r.scheme == "repo" and r.path:
            out.append((str(s.get("id", "")), r.path, r.is_dir))
    return out


# ---------------------------------------------------------------- coverage gaps

def _glob_match(path: str, pattern: str) -> bool:
    import fnmatch

    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(path, pattern[3:])
    return False


def is_excluded(path: str, excludes: Iterable[str]) -> bool:
    return any(_glob_match(path, pat) for pat in excludes)


_TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs|test_[^/]*|[^/]*_test\.[a-z]+|[^/]*\.(test|spec)\.[a-z]+)(/|$)")


def is_test_path(path: str) -> bool:
    return bool(_TEST_RE.search(path))


def coverage_gaps(tracked: Iterable[str], cfg: Any, pages: Iterable[Page], code_exts: Iterable[str],
                  decisions: Optional[list] = None, changed_dirs: Optional[set] = None) -> list[dict]:
    """Directories with enough source files that no page cites; api/events pages without guides;
    ADRs nobody cites. `changed_dirs` (optional) marks gaps touched since the checkpoint."""
    include = list(cfg.get("sources.include") or [])
    exclude = list(cfg.get("sources.exclude") or [])
    depth = int(cfg.get("coverage.depth") or 2)
    min_files = int(cfg.get("coverage.min_files") or 3)
    ignore_tests = bool(cfg.get("coverage.ignore_tests", True))
    exts = set(code_exts)
    pages = list(pages)
    cited: set[str] = set()
    cited_dirs: set[str] = set()
    for p in pages:
        for _, path, is_dir in source_paths(p):
            cited.add(path)
            if is_dir:
                cited_dirs.add(path)
    counts: dict[str, int] = {}
    for f in tracked:
        if is_excluded(f, exclude) or (ignore_tests and is_test_path(f)):
            continue
        if Path(f).suffix.lower() not in exts:
            continue
        root = next((r for r in include if f == r or f.startswith(r.rstrip("/") + "/")), None)
        if root is None:
            continue
        parts = f.split("/")
        root_parts = root.rstrip("/").split("/")
        for d in range(len(root_parts), min(len(parts) - 1, len(root_parts) + depth) + 1):
            dir_path = "/".join(parts[:d])
            counts[dir_path] = counts.get(dir_path, 0) + 1

    def _covered(d: str) -> bool:
        if d in cited:
            return True
        for c in cited:
            if c.startswith(d + "/") or d.startswith(c + "/"):
                return True
        return False

    gaps: list[dict] = []
    seen_slugs: set[str] = set()
    for d, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < min_files or _covered(d):
            continue
        if any(g["path"] != d and d.startswith(g["path"] + "/") for g in gaps):
            continue  # parent already reported
        slug = textnorm.slugify(d.rsplit("/", 1)[-1])
        if slug in seen_slugs:
            slug = textnorm.slugify(d)
        seen_slugs.add(slug)
        gaps.append({"kind": "uncovered_dir", "path": d, "files": n, "suggested_page": f"modules/{slug}.md",
                     "suggested_type": "Module",
                     "changed": bool(changed_dirs and any(c == d or c.startswith(d + "/") for c in changed_dirs))})
    gaps = gaps[:20]
    rels = {p.rel for p in pages}
    for p in pages:
        if _API_PAGE_RE.match(p.rel) and not is_index(p.rel) and not p.rel.endswith("-guide.md"):
            guide = p.rel[:-3] + "-guide.md"
            if guide not in rels:
                gaps.append({"kind": "missing_guide", "path": p.rel, "files": 1, "suggested_page": guide,
                             "suggested_type": "Contract Guide",
                             "changed": bool(changed_dirs and p.rel in changed_dirs)})
    if decisions:
        cited_adrs: set[str] = set()
        for p in pages:
            for s in p.sources:
                r = parse_resource(s.get("resource", ""))
                if r and r.scheme == "adr":
                    cited_adrs.add(r.path.strip("/"))
                elif r and r.scheme == "repo":
                    cited.add(r.path)
        for adr in decisions:
            num = str(adr.get("number") or adr.get("id") or "")
            path = str(adr.get("path") or "")
            if num in cited_adrs or path in cited:
                continue
            gaps.append({"kind": "uncited_adr", "path": path, "files": 1,
                         "suggested_page": f"concepts/{textnorm.slugify(adr.get('title') or num)}.md",
                         "suggested_type": "Concept", "adr": num,
                         "changed": bool(changed_dirs and path in changed_dirs)})
    return gaps
