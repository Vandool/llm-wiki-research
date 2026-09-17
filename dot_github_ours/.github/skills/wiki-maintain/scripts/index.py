#!/usr/bin/env python3
"""index.py — generate every folder `index.md` (and the root index) from page frontmatter.

CLI: index.py [--json] [--check] [--write] [--consumers]
  (no flag)     report what would change (exit 0)
  --check       exit 1 when a committed index differs from the generated one
  --write       write changed indexes; remove obsolete index-*.md shards
  --consumers   also write .github/instructions/wiki-consumers.instructions.md (managed block)
Entry format: `* [Title](file.md) - description [agent,dev]` (+ ` (draft)` / ` (deprecated)`), sorted by
title, sub-folders first. Root: `okf_version: "0.2"` + `title`; sections "Start here" and "Sections".
Folder index frontmatter: `title` only (existing titles are kept). Folders above `index_folder_lines`
are sharded into index-a-m.md / index-n-z.md (`type: Generated`). api/, events/ and decisions/ are
facts.py-owned and skipped when their index exists. Output: {written[], drift[], removed[], consumers}.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, config as wconfig, gitio, manifest as wmanifest, pages as wpages, textnorm, yamlmini  # noqa: E402
from wikilib.frontmatter import get_key  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "index"
MARK_START = "<!-- WIKI-AGENT:START"
MARK_END = "<!-- WIKI-AGENT:END -->"
DEFAULT_TITLES = {
    "architecture": "Architecture", "modules": "Modules", "concepts": "Concepts", "howto": "How-to guides",
    "runbooks": "Runbooks", "analyses": "Analyses", "api": "API contracts", "events": "Event contracts",
    "decisions": "Decisions", "generated": "Generated facts", "product": "Product", "features": "Features",
    "symbols": "Symbol shards", "release-notes": "Release notes",
}
SECTION_ORDER = ["architecture", "modules", "concepts", "howto", "runbooks", "api", "events", "decisions", "analyses",
                 "product", "generated"]
VOLATILE = ("generated:", "last_verified_commit:")


def _strip_volatile(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if not l.startswith(VOLATILE))


def folder_title(name: str, existing: Optional[str]) -> str:
    if existing:
        return existing
    base = name.rsplit("/", 1)[-1]
    return DEFAULT_TITLES.get(base, base.replace("-", " ").replace("_", " ").capitalize())


def entry_line(p: wpages.Page, link: str) -> str:
    title = p.title or Path(p.rel).stem.replace("-", " ").capitalize()
    desc = textnorm.sanitize(str(p.fm.get("description") or ""), 200)
    aud = ",".join(str(a) for a in p.audience) if p.audience else ""
    line = f"* [{title}]({link})"
    if desc:
        line += f" - {desc}"
    if aud:
        line += f" [{aud}]"
    if p.status == "draft":
        line += " (draft)"
    elif p.status == "deprecated":
        line += " (deprecated)"
    return line


class Indexer:
    def __init__(self, ctx: cli.Ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.wiki = ctx.wiki_dir
        self.prefix = self.cfg.id_prefix
        self.head = gitio.head(ctx.repo) or ""
        cdate = gitio.committer_date("HEAD", ctx.repo) if self.head else None
        self.date = cli.iso(cli.parse_iso(cdate)) if cdate else cli.iso(ctx.now)
        self.pages = wpages.walk(self.wiki)
        self.by_rel = {p.rel: p for p in self.pages}
        self.folder_limit = int(self.cfg.budget("index_folder_lines") or 200)
        self.root_limit = int(self.cfg.budget("index_root_lines") or 120)
        self.outputs: dict[str, str] = {}

    # ---- structure

    def folders(self) -> list[str]:
        found: set[str] = set()
        if self.wiki.is_dir():
            for d in self.wiki.rglob("*"):
                if d.is_dir():
                    rel = d.relative_to(self.wiki).as_posix()
                    if rel == "log" or rel.startswith("log/") or any(part.startswith(".") for part in rel.split("/")):
                        continue
                    found.add(rel)
        for p in self.pages:
            if p.folder:
                parts = p.folder.split("/")
                for i in range(1, len(parts) + 1):
                    found.add("/".join(parts[:i]))
        return sorted(found)

    def existing_title(self, rel: str) -> Optional[str]:
        p = self.by_rel.get(rel)
        if p and isinstance(p.fm.get("title"), str) and p.fm["title"].strip():
            return p.fm["title"].strip()
        return None

    def title_of(self, folder: str) -> str:
        return folder_title(folder, self.existing_title(f"{folder}/index.md"))

    def pages_in(self, folder: str) -> list[wpages.Page]:
        out = [p for p in self.pages if p.folder == folder and not p.is_index and p.rel != "log.md"]
        return sorted(out, key=lambda p: ((p.title or p.rel).lower(), p.rel))

    def subfolders(self, folder: str, all_folders: list[str]) -> list[str]:
        depth = folder.count("/") + 1 if folder else 0
        return [f for f in all_folders if f.count("/") == depth and (not folder or f.startswith(folder + "/"))]

    def sub_line(self, sub: str, all_folders: list[str]) -> str:
        n = len(self.pages_in(sub)) + sum(len(self.pages_in(s)) for s in all_folders if s.startswith(sub + "/"))
        base = sub.rsplit("/", 1)[-1]
        return f"* [{self.title_of(sub)}]({base}/index.md) - {n} page{'s' if n != 1 else ''}"

    # ---- generation

    def gen_folder(self, folder: str, all_folders: list[str]) -> None:
        rel = f"{folder}/index.md"
        title = self.title_of(folder)
        subs = [self.sub_line(s, all_folders) for s in self.subfolders(folder, all_folders)]
        entries = [entry_line(p, p.rel.rsplit("/", 1)[-1]) for p in self.pages_in(folder)]
        head = "---\n" + yamlmini.dumps({"title": title}) + "---\n" + f"# {title}\n"
        if len(subs) + len(entries) + 2 <= self.folder_limit:
            body = subs + entries
            if not body:
                body = ["_No pages yet._"]
            self.outputs[rel] = head + "\n".join(body) + "\n"
            return
        first = [e for e in entries if _initial(e) <= "m"]
        second = [e for e in entries if _initial(e) > "m"]
        shards = [("index-a-m.md", "A–M", first), ("index-n-z.md", "N–Z", second)]
        lines = subs[:]
        for fname, label, items in shards:
            srel = f"{folder}/{fname}"
            stitle = f"{title} ({label})"
            fm = {"type": "Generated", "id": f"{self.prefix}/{srel[:-3]}", "schema_version": 1, "title": stitle,
                  "description": f"Index shard {label} of {title} ({len(items)} pages).", "audience": ["agent", "dev"],
                  "owner": "process", "sources": [], "last_verified_commit": self.head,
                  "generated": {"by": f"process:index.py/{VERSION}", "at": self.date}}
            self.outputs[srel] = "---\n" + yamlmini.dumps(fm) + "---\n" + f"# {stitle}\n" + "\n".join(items or ["_No pages._"]) + "\n"
            lines.append(f"* [{stitle}]({fname}) - {len(items)} pages")
        self.outputs[rel] = head + "\n".join(lines) + "\n"

    def gen_root(self, all_folders: list[str]) -> None:
        existing = self.existing_title("index.md")
        title = existing or self.cfg.get("pages.site_title") or wconfig.scaffold_vars(self.cfg)["site_title"]
        fm = {"okf_version": "0.2", "title": title}
        lines = [f"# {title}", "", "## Start here"]
        start: list[str] = []
        for name in ("overview.md", "glossary.md", "conventions.md"):
            p = self.by_rel.get(name)
            if p:
                start.append(entry_line(p, name))
        tagged = [p for p in self.pages if not p.is_index and p.rel not in ("overview.md", "glossary.md", "conventions.md")
                  and isinstance(p.fm.get("tags"), list) and "start-here" in p.fm["tags"]]
        for p in sorted(tagged, key=lambda p: (p.title.lower(), p.rel))[:20 - len(start)]:
            start.append(entry_line(p, p.rel))
        lines += start or ["_No overview yet._"]
        lines += ["", "## Sections"]
        tops = self.subfolders("", all_folders)
        ordered = [t for t in SECTION_ORDER if t in tops] + sorted(t for t in tops if t not in SECTION_ORDER)
        lines += [self.sub_line(t, all_folders) for t in ordered] or ["_No sections yet._"]
        others = [p for p in self.pages_in("") if p.rel not in ("overview.md", "glossary.md", "conventions.md", "instructions.md",
                                                                    "requests.md") and p not in tagged]
        if others:
            lines += ["", "## Other pages"] + [entry_line(p, p.rel) for p in others]
        if len(lines) > self.root_limit:
            lines = lines[: self.root_limit - 1] + ["* … (root index truncated; see the folder indexes)"]
        self.outputs["index.md"] = "---\n" + yamlmini.dumps(fm) + "---\n" + "\n".join(lines) + "\n"

    def generate(self) -> None:
        all_folders = self.folders()
        for folder in all_folders:
            if folder in wpages.FACTS_FOLDERS and (self.wiki / folder / "index.md").exists():
                continue
            self.gen_folder(folder, all_folders)
        self.gen_root(all_folders)

    # ---- output

    def obsolete_shards(self) -> list[str]:
        out = []
        for p in self.wiki.rglob("index-*.md"):
            rel = p.relative_to(self.wiki).as_posix()
            if rel not in self.outputs and not rel.startswith("log/"):
                out.append(rel)
        return sorted(out)

    def drift(self) -> list[str]:
        out = []
        for rel, text in sorted(self.outputs.items()):
            path = self.wiki / rel
            if not path.exists():
                out.append(rel)
                continue
            if _strip_volatile(path.read_text(encoding="utf-8", errors="replace")) != _strip_volatile(text):
                out.append(rel)
        return out + self.obsolete_shards()

    def write(self) -> tuple[list[str], list[str]]:
        written = []
        for rel in self.drift():
            path = self.wiki / rel
            if rel not in self.outputs:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.outputs[rel], encoding="utf-8", newline="\n")
            written.append(rel)
        removed = []
        for rel in self.obsolete_shards():
            (self.wiki / rel).unlink()
            removed.append(rel)
        return written, removed

    # ---- consumers instruction file

    def consumers_text(self) -> str:
        include = [str(x).rstrip("/") for x in (self.cfg.get("sources.include") or [])]
        man = wmanifest.load(self.wiki) or {}
        cited: dict[str, set[str]] = {}
        entries = man.get("pages") or {}
        if entries:
            for rel, entry in entries.items():
                for s in entry.get("sources") or []:
                    if s.get("path") and (s.get("resource") or "").startswith("repo://"):
                        cited.setdefault(s["path"], set()).add(rel)
        else:
            for p in self.pages:
                for _, path, _ in wpages.source_paths(p):
                    cited.setdefault(path, set()).add(p.rel)
        depth = int(self.cfg.get("coverage.depth") or 2)
        folders: dict[str, set[str]] = {}
        for path, rels in cited.items():
            root = next((r for r in include if path == r or path.startswith(r + "/")), None)
            if root is None:
                continue
            parts = path.split("/")
            key = "/".join(parts[: min(len(parts) - (0 if (self.ctx.repo / path).is_dir() else 1), len(root.split("/")) + 1)])
            key = key or root
            folders.setdefault(key, set()).update(rels)
        wd = self.cfg.wiki_dir
        lines = [f"{MARK_START} Wiki-Kit: {VERSION} (managed by the wiki kit; regenerated by index.py --consumers) -->",
                 "# Wiki pages for these sources",
                 f"Before changing code under a folder below, read `{wd}/index.md`, then the listed pages, then follow their `sources`.", ""]
        for key in sorted(folders)[:40]:
            rels = sorted(folders[key])
            mods = [r for r in rels if r.startswith("modules/")] or rels[:2]
            guides = [r for r in rels if r.startswith("api/") and r.endswith("-guide.md")]
            text = " and ".join(f"`{wd}/{r}`" for r in mods[:2])
            if guides:
                text += " (and " + ", ".join(f"`{wd}/{g}`" for g in guides[:2]) + " for routes)"
            lines.append(f"- `{key}/**`: read {text} first")
        if not folders:
            lines.append(f"- (no pages cite sources yet; read `{wd}/index.md`)")
        lines += ["", "After a behaviour change leave the wiki update to the post-commit hook or run `/wiki-update`.", MARK_END]
        block = "\n".join(lines[:58]) if len(lines) <= 60 else "\n".join(lines[:57] + [lines[-2], MARK_END])
        apply_to = ", ".join(f"{r}/**" for r in include) or "**"
        fm = f"---\napplyTo: \"{apply_to}\"\nexcludeAgent: \"code-review\"\ndescription: Which wiki pages to read before changing each source folder (generated by index.py --consumers).\n---\n"
        return fm, block

    def write_consumers(self) -> Path:
        fm, block = self.consumers_text()
        path = self.ctx.repo / ".github" / "instructions" / "wiki-consumers.instructions.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if MARK_START in existing and MARK_END in existing:
            pre = existing[: existing.index(MARK_START)]
            post = existing[existing.index(MARK_END) + len(MARK_END):]
            text = pre + block + post
            if not text.endswith("\n"):
                text += "\n"
        else:
            text = fm + block + "\n"
        if text != existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        return path


def _initial(entry: str) -> str:
    m = re.match(r"\* \[(.)", entry)
    return (m.group(1).lower() if m else "z")


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="exit 1 when committed indexes differ")
    p.add_argument("--write", action="store_true", help="write changed indexes")
    p.add_argument("--consumers", action="store_true", help="also write .github/instructions/wiki-consumers.instructions.md")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if not ctx.wiki_dir.is_dir():
        raise cli.EnvError(f"wiki directory missing: {ctx.wiki_dir}")
    ix = Indexer(ctx)
    ix.generate()
    consumers = None
    if args.write:
        written, removed = ix.write()
        if args.consumers:
            consumers = str(ix.write_consumers())
        ctx.emit.say(f"index: wrote {len(written)} file(s), removed {len(removed)}" + (f", consumers → {consumers}" if consumers else ""))
        ctx.emit.emit({"written": written, "removed": removed, "drift": [], "consumers": consumers, "folders": sorted(ix.outputs)})
        return 0
    drift = ix.drift()
    for rel in drift:
        ctx.emit.say(f"drift: {ctx.cfg.wiki_dir}/{rel}")
    ok = not drift
    ctx.emit.say("index: up to date" if ok else f"index: {len(drift)} file(s) differ — run index.py --write")
    if args.consumers and not args.check:
        consumers = str(ix.write_consumers())
    ctx.emit.emit({"written": [], "removed": [], "drift": drift, "consumers": consumers, "folders": sorted(ix.outputs)}, ok=ok)
    return cli.EXIT_FINDINGS if (args.check and drift) else 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
