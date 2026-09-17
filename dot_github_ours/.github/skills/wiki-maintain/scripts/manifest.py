#!/usr/bin/env python3
"""manifest.py — maintain `<wiki>/.manifest.json` (plan §8.7.1): page → source hashes at HEAD.

CLI: manifest.py [--json] (--init | --touched | --pages P ... | --all) [--run-id ID] [--model M] [--mode M]
                 [--result R] [--duration N] [--advance-checkpoint] [--prune]
  --init       create the manifest (checkpoint = HEAD) and record every page
  --all        record every page with sources; prune deleted pages
  --touched    pages changed in the working tree or in the HEAD commit: record them and set their
               `last_verified_commit` (= HEAD) and `generated.at` (= now) via frontmatter.replace_key
  --pages      explicit page paths (wiki- or repo-relative), treated like --touched
  --run-id     record last_run {id, mode, model, at, duration_s, pages_written, result}; with --model the
               touched agent pages also get `generated.by: copilot-cli/<model>`
  --advance-checkpoint   set checkpoint_commit = HEAD (only after a successful commit)
  --prune      drop entries whose page no longer exists
Never re-serialises page frontmatter; process-owned pages are recorded but never edited.
Output: {pages_updated[], checkpoint, entries, pruned[], generated}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, frontmatter as wfm, gitio, manifest as wmanifest, pages as wpages, textnorm  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "manifest"


def _rel(ctx: cli.Ctx, path: str) -> Optional[str]:
    wd = ctx.cfg.wiki_dir
    s = path.replace("\\", "/")
    if Path(s).is_absolute():
        try:
            return Path(s).resolve().relative_to(ctx.wiki_dir.resolve()).as_posix()
        except ValueError:
            return None
    if s.startswith(wd + "/"):
        return s[len(wd) + 1:]
    return s


def touched_pages(ctx: cli.Ctx) -> set[str]:
    wd = ctx.cfg.wiki_dir
    out = set()
    for p in gitio.changed_paths(ctx.repo, [wd]):
        if p.startswith(wd + "/") and p.endswith(".md"):
            out.add(p[len(wd) + 1:])
    head = gitio.head(ctx.repo)
    if head:
        try:
            for p in gitio.diff_tree_files("HEAD", ctx.repo):
                if p.startswith(wd + "/") and p.endswith(".md"):
                    out.add(p[len(wd) + 1:])
        except gitio.GitError:
            pass
    return out


def generated_hashes(pages: list[wpages.Page]) -> dict[str, str]:
    out = {}
    for p in pages:
        if p.owner == "process" or (wpages.is_process_owned(p.rel) and not p.is_index):
            out[p.rel] = textnorm.sha256_text(p.text)
    return out


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true")
    g.add_argument("--touched", action="store_true")
    g.add_argument("--pages", nargs="+", metavar="P")
    g.add_argument("--all", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--mode", default="incremental", help="last_run.mode (incremental|bootstrap|manual)")
    p.add_argument("--result", default="ok", help="last_run.result")
    p.add_argument("--duration", type=float, default=None, help="last_run.duration_s")
    p.add_argument("--pages-written", type=int, default=None)
    p.add_argument("--advance-checkpoint", action="store_true")
    p.add_argument("--prune", action="store_true")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    wiki = ctx.wiki_dir
    if not wiki.is_dir():
        raise cli.EnvError(f"wiki directory missing: {wiki}")
    head = gitio.head(ctx.repo)
    if not head:
        raise cli.EnvError("repository has no commits yet")
    now = cli.iso(ctx.now)
    man = wmanifest.load(wiki)
    if man is None or args.init:
        man = wmanifest.empty(ctx.cfg.get("repo.slug") or "", head, now)
    man.setdefault("pages", {})
    man.setdefault("generated", {})
    pages = wpages.walk(wiki)
    by_rel = {p.rel: p for p in pages}
    eligible = {p.rel for p in pages if not p.is_index and p.rel != "log.md" and p.fm_lines and not p.error
                and p.owner in ("agent", "both", "process")}
    if args.init or args.all:
        targets = set(eligible)
        edit = False
    else:
        if args.pages:
            targets = {r for r in (_rel(ctx, x) for x in args.pages) if r}
            unknown = [r for r in targets if r not in by_rel]
            if unknown:
                raise cli.ConfigError(f"unknown page(s): {', '.join(sorted(unknown))}")
        else:
            targets = touched_pages(ctx)
        targets &= eligible
        edit = True
    resolver = wmanifest.Resolver(ctx.repo, wiki)
    sym_fn = wmanifest.make_symbol_hash_fn(ctx.repo, head)
    updated: list[str] = []
    for rel in sorted(targets):
        page = by_rel[rel]
        if edit and page.owner in ("agent", "both"):
            text = page.text
            if "last_verified_commit" in page.fm or page.owner == "agent":
                text = wfm.replace_key(text, "last_verified_commit", head)
            if isinstance(page.fm.get("generated"), dict) or page.owner == "agent":
                text = wfm.replace_key(text, "generated.at", now)
                if args.model:
                    text = wfm.replace_key(text, "generated.by", f"copilot-cli/{args.model}")
            if text != page.text:
                page.path.write_text(text, encoding="utf-8", newline="\n")
                page = wpages.load_page(wiki, rel)
                by_rel[rel] = page
        man["pages"][rel] = wmanifest.page_entry(page, ctx.repo, head, resolver, run_id=args.run_id, model=args.model,
                                                  now=now if edit else None, symbol_hash_fn=sym_fn,
                                                  previous=man["pages"].get(rel))
        updated.append(rel)
    pruned: list[str] = []
    if args.prune or args.all or args.init:
        for rel in list(man["pages"]):
            if rel not in by_rel:
                del man["pages"][rel]
                pruned.append(rel)
    man["generated"] = generated_hashes(pages)
    if args.run_id:
        man["last_run"] = {"id": args.run_id, "mode": args.mode, "model": args.model, "at": now, "duration_s": args.duration,
                           "pages_written": args.pages_written if args.pages_written is not None else len(updated),
                           "result": args.result}
    if args.advance_checkpoint or args.init:
        man["checkpoint_commit"] = head
        man["checkpoint_at"] = now
    if not man.get("repo"):
        man["repo"] = ctx.cfg.get("repo.slug") or ""
    wmanifest.save(wiki, man)
    ctx.emit.say(f"manifest: {len(updated)} page(s) recorded, {len(pruned)} pruned, checkpoint {str(man.get('checkpoint_commit'))[:10]}")
    ctx.emit.emit({"pages_updated": updated, "checkpoint": man.get("checkpoint_commit"), "entries": len(man["pages"]),
                   "pruned": pruned, "generated": len(man["generated"]), "head": head})
    return 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
