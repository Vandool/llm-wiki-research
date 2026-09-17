#!/usr/bin/env python3
"""excerpt.py — bounded code reading for the model (never whole files).

CLI: excerpt.py PATH [--hunks] [--symbol NAME] [--lines a-b] [--max-lines N] [--context 20] [--json]
  --hunks     diff hunks since the checkpoint (manifest checkpoint_commit or run.json checkpoint) with
              +-20 lines of context; unchanged file → first N lines
  --symbol    one symbol's definition from generated/symbols.json (live indexing when absent)
  --lines     an explicit 1-based inclusive range
  (default)   the first N lines (N = --max-lines, default budgets.max_excerpt_lines)
Meters bytes and lines into `<git-dir>/wiki/run.json` (`budget.bytes_read`, `budget.excerpt_lines_used`)
when that file exists; when the budget is already exhausted prints one line and exits 3.
Text output: `== path (lines a-b of N) ==` followed by `  12| code` lines. JSON: {path, range, text, bytes,
lines, total_lines, hunks[{a, b}], budget{bytes_read, exhausted}}.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import budget as wbudget, cli, gitio, manifest as wmanifest, symbols as wsymbols  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "excerpt"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def diff_hunks(repo: Path, base: str, path: str, context: int = 20) -> list[dict]:
    """[{a, b, text}] for the new-file side of each hunk of `git diff -U<context> base HEAD -- path`."""
    try:
        diff = gitio.git(["diff", f"-U{context}", "--no-color", base, "HEAD", "--", path], repo)
    except gitio.GitError:
        return []
    hunks: list[dict] = []
    cur: Optional[dict] = None
    for line in diff.split("\n"):
        m = HUNK_RE.match(line)
        if m:
            start = int(m.group(3))
            length = int(m.group(4)) if m.group(4) is not None else 1
            cur = {"a": start, "b": max(start, start + length - 1), "text": [line]}
            hunks.append(cur)
            continue
        if cur is not None and not line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            cur["text"].append(line)
    for h in hunks:
        h["text"] = "\n".join(h["text"])
    return hunks


def numbered(lines: list[str], start: int) -> str:
    return "\n".join(f"{start + i:>5}| {l}" for i, l in enumerate(lines))


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    p.add_argument("path", help="repository-relative file path")
    p.add_argument("--hunks", action="store_true")
    p.add_argument("--symbol", default=None)
    p.add_argument("--lines", default=None, metavar="a-b")
    p.add_argument("--max-lines", type=int, default=None)
    p.add_argument("--context", type=int, default=20)
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    git_dir = ctx.git_dir or (ctx.repo / ".git")
    run = wbudget.load_run(git_dir)
    if wbudget.is_exhausted(run):
        print("excerpt: read budget exhausted — write nothing more, run `run.py defer --reason \"budget exhausted\"` and stop",
              file=sys.stderr)
        return cli.EXIT_ENV
    rel = args.path.replace("\\", "/")
    if Path(rel).is_absolute():
        try:
            rel = Path(rel).resolve().relative_to(ctx.repo.resolve()).as_posix()
        except ValueError:
            raise cli.ConfigError(f"{args.path} is outside the repository")
    full = ctx.repo / rel
    text = None
    if full.is_file():
        text = full.read_text(encoding="utf-8", errors="replace")
    else:
        text = gitio.show("HEAD", rel, ctx.repo)
    if text is None:
        raise cli.ConfigError(f"{rel}: no such file in the working tree or at HEAD")
    all_lines = text.split("\n")
    if all_lines and all_lines[-1] == "":
        all_lines.pop()
    total = len(all_lines)
    max_lines = args.max_lines or int(ctx.cfg.budget("max_excerpt_lines") or 120)
    hunks_out: list[dict] = []
    note = ""
    if args.lines:
        m = re.match(r"^(\d+)-(\d+)$", args.lines)
        if not m:
            raise cli.ConfigError("--lines expects a-b")
        a, b = int(m.group(1)), int(m.group(2))
        a, b = max(1, min(a, b)), min(total, max(a, b))
        body = numbered(all_lines[a - 1:b], a)
        rng = [a, b]
    elif args.symbol:
        idx = None
        try:
            idx = json.loads((ctx.wiki_dir / "generated" / "symbols.json").read_text(encoding="utf-8")).get(rel)
        except (OSError, ValueError):
            idx = None
        if idx is None:
            idx = wsymbols.index_file(rel, text)
        sym = wsymbols.find_symbol(idx, args.symbol)
        if sym is None:
            raise cli.ConfigError(f"symbol {args.symbol!r} not found in {rel} (see generated/symbols.md)")
        a, b = sym["lines"]
        b = min(b, total)
        body = numbered(all_lines[a - 1:b], a)
        rng = [a, b]
    elif args.hunks:
        man = wmanifest.load(ctx.wiki_dir) or {}
        base = (run or {}).get("checkpoint") or man.get("checkpoint_commit")
        head = gitio.head(ctx.repo)
        hunks = diff_hunks(ctx.repo, base, rel, args.context) if base and head and base != head and gitio.rev_parse(base, ctx.repo) else []
        if hunks:
            body = "\n\n".join(h["text"] for h in hunks)
            hunks_out = [{"a": h["a"], "b": h["b"]} for h in hunks]
            rng = [hunks[0]["a"], hunks[-1]["b"]]
        else:
            note = "no changes since the checkpoint; showing the first lines" if base else "no checkpoint; showing the first lines"
            rng = [1, min(total, max_lines)]
            body = numbered(all_lines[:rng[1]], 1)
    else:
        rng = [1, min(total, max_lines)]
        body = numbered(all_lines[:rng[1]], 1)
        if total > max_lines:
            note = f"truncated to {max_lines} of {total} lines; use --lines a-b or --symbol NAME for the rest"
    lines_list = body.split("\n") if body else []
    truncated = False
    if len(lines_list) > max_lines:
        lines_list = lines_list[:max_lines]
        body = "\n".join(lines_list)
        truncated = True
        note = (note + "; " if note else "") + f"output capped at {max_lines} lines"
    nbytes = len(body.encode("utf-8"))
    total_bytes, exhausted = wbudget.add_bytes(git_dir, nbytes)
    wbudget.add_excerpt_lines(git_dir, len(lines_list))
    header = f"== {rel} (lines {rng[0]}-{rng[1]} of {total}) =="
    if not args.json:
        print(header)
        if note:
            print(f"-- {note}")
        print(body)
        if exhausted:
            print("-- read budget exhausted after this excerpt: write nothing more, run `run.py defer` and stop", file=sys.stderr)
    ctx.emit.emit({"path": rel, "range": rng, "text": body, "bytes": nbytes, "lines": len(lines_list), "total_lines": total,
                   "hunks": hunks_out, "truncated": truncated, "note": note,
                   "budget": {"bytes_read": total_bytes, "exhausted": exhausted, "metered": run is not None}})
    return 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
