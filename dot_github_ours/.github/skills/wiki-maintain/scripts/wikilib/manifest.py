"""`wiki/.manifest.json` model (plan §8.7.1) and the staleness algorithm (§8.7.2).

API:
  MANIFEST_NAME, load(wiki_dir) -> dict | None, save(wiki_dir, data) -> Path, empty(repo, head, now) -> dict
  page_hashes(text) -> (page_hash, body_hash)
  line_hash_of(text, a, b) -> str
  Resolver(repo, wiki_dir): resolve(resource) -> {scheme, path, line_range, symbol, hashable, kind}
  source_entry(src, resolver, repo, rev, symbol_hash_fn=None) -> entry
  page_entry(page, repo, rev, resolver, run_id=None, model=None, now=None) -> entry
  make_symbol_hash_fn(repo, rev) -> callable(path, symbol) -> hash | None
  compute_stale(manifest, repo, pages, head, full=False, now=None, symbol_hash_fn=None) -> result dict
  STALE_REASONS
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import gitio, symbols
from .cli import iso, parse_iso, utcnow
from .frontmatter import split as fm_split
from .pages import Page, parse_resource
from .textnorm import sha256_lines, sha256_text

__all__ = ["MANIFEST_NAME", "STALE_REASONS", "load", "save", "empty", "page_hashes", "line_hash_of", "Resolver",
           "source_entry", "page_entry", "make_symbol_hash_fn", "compute_stale"]

MANIFEST_NAME = ".manifest.json"
STALE_REASONS = ("blob_changed", "lines_changed", "symbol_changed", "symbol_missing", "missing_source", "renamed",
                 "expired")
_HASHABLE_SCHEMES = ("repo", "api", "event", "adr")


def load(wiki_dir: Path) -> Optional[dict]:
    p = Path(wiki_dir) / MANIFEST_NAME
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(wiki_dir: Path, data: dict) -> Path:
    p = Path(wiki_dir) / MANIFEST_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    if "pages" in data and isinstance(data["pages"], dict):
        data["pages"] = dict(sorted(data["pages"].items()))
    if "generated" in data and isinstance(data["generated"], dict):
        data["generated"] = dict(sorted(data["generated"].items()))
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return p


def empty(repo_slug: str, head: Optional[str], now: Optional[str] = None) -> dict:
    return {"schema_version": 1, "repo": repo_slug or "", "checkpoint_commit": head, "checkpoint_at": now or iso(utcnow()),
            "last_run": None, "generated": {}, "pages": {}}


def page_hashes(text: str) -> tuple[str, str]:
    _, body, _ = fm_split(text)
    return sha256_text(text), sha256_text(body)


def line_hash_of(text: str, a: int, b: int) -> str:
    lines = text.split("\n")
    return sha256_lines(lines[max(0, a - 1):b])


# ---------------------------------------------------------------- resolution

class Resolver:
    """Maps `api://`, `event://`, `adr://` ids to repository paths through the generated indexes."""

    def __init__(self, repo: Path, wiki_dir: Path):
        self.repo = Path(repo)
        self.wiki_dir = Path(wiki_dir)
        self._specs: Optional[dict] = None
        self._decisions: Optional[dict] = None

    def _load(self, name: str) -> dict:
        p = self.wiki_dir / "generated" / name
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    @property
    def specs(self) -> dict:
        if self._specs is None:
            self._specs = self._load("specs.json")
        return self._specs

    @property
    def decisions(self) -> dict:
        if self._decisions is None:
            self._decisions = self._load("decisions.json")
        return self._decisions

    def resolve(self, resource: str) -> dict:
        r = parse_resource(resource)
        out = {"scheme": r.scheme if r else "", "path": None, "line_range": None, "symbol": None,
               "hashable": False, "kind": "file"}
        if not r:
            return out
        if r.scheme == "repo":
            out.update({"path": r.path or None, "hashable": bool(r.path), "kind": "dir" if r.is_dir else "file",
                        "line_range": list(r.line_range) if r.line_range else None, "symbol": r.symbol})
            if r.path and (self.repo / r.path).is_dir():
                out["kind"] = "dir"
            return out
        if r.scheme == "api":
            api = r.path.split("/", 1)[0]
            apis = self.specs.get("apis") or {}
            entry = apis.get(api)
            if entry is None:
                for a in apis.values():
                    if api in (a.get("groups") or {}) or api in (a.get("tags") or []):
                        entry = a
                        break
            if entry and entry.get("file"):
                out.update({"path": entry["file"], "hashable": True})
            return out
        if r.scheme == "event":
            events = self.specs.get("events") or {}
            entry = events.get(r.path) or events.get(r.path.replace("/", "."))
            if entry is None:
                for k, e in events.items():
                    if e.get("slug") == r.path:
                        entry = e
                        break
            if entry and entry.get("file"):
                out.update({"path": entry["file"], "hashable": True})
            return out
        if r.scheme == "adr":
            num = r.path.strip("/")
            for adr in self.decisions.get("adrs") or []:
                if str(adr.get("number")) == num or str(adr.get("id")) == num:
                    out.update({"path": adr.get("path"), "hashable": bool(adr.get("path"))})
                    break
            return out
        return out


def make_symbol_hash_fn(repo: Path, rev: str) -> Callable[[str, str], Optional[str]]:
    cache: dict[str, Optional[dict]] = {}

    def fn(path: str, symbol: str) -> Optional[str]:
        if path not in cache:
            text = gitio.show(rev, path, repo)
            cache[path] = symbols.index_file(path, text) if text is not None else None
        s = symbols.find_symbol(cache[path], symbol)
        return s.get("hash") if s else None

    return fn


def source_entry(src: dict, resolver: Resolver, repo: Path, rev: str,
                 symbol_hash_fn: Optional[Callable[[str, str], Optional[str]]] = None) -> dict:
    resource = str(src.get("resource") or "")
    res = resolver.resolve(resource)
    entry = {"id": str(src.get("id") or ""), "resource": resource, "path": res["path"], "blob_sha": None,
             "line_range": res["line_range"], "line_hash": None, "symbol": res["symbol"], "symbol_hash": None,
             "hashable": bool(res["hashable"]), "kind": res["kind"]}
    if not entry["hashable"] or not entry["path"]:
        return entry
    entry["blob_sha"] = gitio.blob_sha(rev, entry["path"], repo)
    if entry["blob_sha"] is None:
        return entry
    if entry["kind"] == "dir":
        return entry
    if entry["line_range"]:
        text = gitio.show(rev, entry["path"], repo) or ""
        a, b = entry["line_range"]
        entry["line_hash"] = line_hash_of(text, int(a), int(b))
    elif entry["symbol"]:
        fn = symbol_hash_fn or make_symbol_hash_fn(repo, rev)
        entry["symbol_hash"] = fn(entry["path"], entry["symbol"])
    return entry


def page_entry(page: Page, repo: Path, rev: str, resolver: Resolver, run_id: Optional[str] = None,
               model: Optional[str] = None, now: Optional[str] = None,
               symbol_hash_fn: Optional[Callable[[str, str], Optional[str]]] = None,
               previous: Optional[dict] = None) -> dict:
    page_hash, body_hash = page_hashes(page.text)
    gen = page.fm.get("generated") if isinstance(page.fm.get("generated"), dict) else {}
    prev = previous or {}
    return {
        "type": page.type, "owner": page.owner,
        "page_hash": page_hash, "body_hash": body_hash,
        "last_verified_commit": page.fm.get("last_verified_commit") or rev,
        "verified_at": now or prev.get("verified_at") or iso(utcnow()),
        "run_id": run_id or prev.get("run_id"),
        "generated_by": (f"copilot-cli/{model}" if model and page.owner in ("agent", "both") else gen.get("by")) or prev.get("generated_by"),
        "status": page.status,
        "stale_after": page.fm.get("stale_after"),
        "sources": [source_entry(s, resolver, repo, rev, symbol_hash_fn) for s in page.sources],
    }


# ---------------------------------------------------------------- staleness

def _touched(path: str, kind: str, modified: set[str]) -> bool:
    if path in modified:
        return True
    if kind == "dir":
        prefix = path.rstrip("/") + "/"
        return any(m.startswith(prefix) for m in modified)
    return False


def compute_stale(manifest: Optional[dict], repo: Path, pages: Iterable[Page], head: Optional[str],
                  full: bool = False, now: Optional[Any] = None,
                  symbol_hash_fn: Optional[Callable[[str, str], Optional[str]]] = None) -> dict:
    """Plan §8.7.2. Returns {full, checkpoint, head, changed_files, modified, deleted, renamed, stale{page: [reason]},
    untracked[], orphan_entries[], manifest_drift[], warnings[]}."""
    pages = list(pages)
    by_rel = {p.rel: p for p in pages}
    manifest = manifest or {}
    cp = manifest.get("checkpoint_commit")
    warnings: list[str] = []
    result: dict = {"full": False, "checkpoint": cp, "head": head, "changed_files": [], "modified": [], "deleted": [],
                    "renamed": {}, "stale": {}, "untracked": [], "orphan_entries": [], "manifest_drift": [],
                    "warnings": warnings}
    if head is None:
        warnings.append("no HEAD commit")
        return result
    if full or not cp or not gitio.rev_parse(cp, repo) or not gitio.is_ancestor(cp, head, repo):
        result["full"] = True
        if cp and not full:
            warnings.append(f"checkpoint {cp[:10]} is not an ancestor of HEAD; full comparison")
    modified: set[str] = set()
    deleted: set[str] = set()
    renamed: dict[str, str] = {}
    changed: list[dict] = []
    if not result["full"] and cp != head:
        for status, path, new_path in gitio.diff_name_status(cp, head, repo):
            changed.append({"status": status, "path": path, "new_path": new_path})
            if status == "D":
                deleted.add(path)
            elif status in ("R",):
                renamed[path] = new_path or path
                if new_path:
                    modified.add(new_path)
            else:
                modified.add(new_path or path)
    result.update({"changed_files": changed, "modified": sorted(modified), "deleted": sorted(deleted), "renamed": renamed})
    fn = symbol_hash_fn or make_symbol_hash_fn(repo, head)
    now_dt = now if now is not None else utcnow()
    entries = manifest.get("pages") or {}
    for rel, entry in sorted(entries.items()):
        page = by_rel.get(rel)
        if page is None:
            result["orphan_entries"].append(rel)
            continue
        fm_lvc = page.fm.get("last_verified_commit")
        if fm_lvc and entry.get("last_verified_commit") and fm_lvc != entry.get("last_verified_commit"):
            result["manifest_drift"].append(rel)
        reasons: list[dict] = []
        for s in entry.get("sources") or []:
            if not s.get("hashable") or not s.get("path"):
                continue
            path = s["path"]
            kind = s.get("kind") or "file"
            rng = s.get("line_range")
            base = {"source_id": s.get("id"), "path": path, "range": rng, "symbol": s.get("symbol")}
            if path in renamed:
                reasons.append({**base, "kind": "renamed", "new_path": renamed[path]})
                continue
            if path in deleted:
                reasons.append({**base, "kind": "missing_source"})
                continue
            if not result["full"] and not _touched(path, kind, modified):
                continue
            now_blob = gitio.blob_sha(head, path, repo)
            if now_blob is None:
                if s.get("blob_sha") is None:
                    continue
                reasons.append({**base, "kind": "missing_source"})
                continue
            if now_blob == s.get("blob_sha"):
                continue
            if kind == "dir":
                reasons.append({**base, "kind": "blob_changed"})
                continue
            if rng:
                text = gitio.show(head, path, repo) or ""
                if line_hash_of(text, int(rng[0]), int(rng[1])) != s.get("line_hash"):
                    reasons.append({**base, "kind": "lines_changed"})
                continue
            if s.get("symbol"):
                h = fn(path, s["symbol"])
                if h is None:
                    reasons.append({**base, "kind": "symbol_missing"})
                elif h != s.get("symbol_hash"):
                    reasons.append({**base, "kind": "symbol_changed"})
                continue
            reasons.append({**base, "kind": "blob_changed"})
        sa = entry.get("stale_after") or page.fm.get("stale_after")
        if sa:
            try:
                if parse_iso(str(sa)) <= now_dt:
                    reasons.append({"source_id": None, "path": None, "range": None, "kind": "expired", "stale_after": sa})
            except ValueError:
                warnings.append(f"{rel}: unparsable stale_after {sa!r}")
        if reasons:
            result["stale"][rel] = reasons
    for p in pages:
        if p.rel not in entries and p.sources and p.owner in ("agent", "both", "process"):
            result["untracked"].append(p.rel)
    return result
