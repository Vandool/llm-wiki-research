#!/usr/bin/env python3
"""log.py — append-only wiki log (`<wiki>/log.md`), rotation and grammar check.

CLI:
  log.py add --action A --text T [--page P] [--run-id ID] [--json]
  log.py rotate [--json]          keep the newest `budgets.log_entries`; older go to log/<yyyy>-q<n>.md
  log.py check [--json]           L10 grammar: `## YYYY-MM-DD` headings (newest first),
                                  `* **Action**: text` entries with a known action; exit 1 on violations
Actions: Bootstrap, Creation, Update, Deprecation, Lint, Query, Instruction, Deferred.
Entry: `* **Update**: [Title](modules/x.md) — text (run <id>)`. Newest entries first under today's heading.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio, textnorm, yamlmini  # noqa: E402
from wikilib.frontmatter import get_key, split as fm_split  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "log"
ACTIONS = ("Bootstrap", "Creation", "Update", "Deprecation", "Lint", "Query", "Instruction", "Deferred")
ENTRY_RE = re.compile(r"^\* \*\*(Bootstrap|Creation|Update|Deprecation|Lint|Query|Instruction|Deferred)\*\*: ")
DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
H1 = "# Wiki log"


def parse_log(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(preamble lines before the first date heading, [(date, [entry blocks])]); entries keep continuation lines."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    cur: Optional[list[str]] = None
    for line in text.split("\n"):
        m = DATE_RE.match(line)
        if m:
            cur = []
            sections.append((m.group(1), cur))
            continue
        if cur is None:
            preamble.append(line)
            continue
        if not line.strip():
            continue
        if line.startswith("* ") or not cur:
            cur.append(line)
        else:
            cur[-1] += "\n" + line
    while preamble and not preamble[-1].strip():
        preamble.pop()
    return preamble, sections


def render_log(preamble: list[str], sections: list[tuple[str, list[str]]]) -> str:
    out = list(preamble) if preamble else [H1]
    for date, entries in sections:
        if not entries:
            continue
        out += ["", f"## {date}"] + entries
    return "\n".join(out).rstrip("\n") + "\n"


def entries_count(sections) -> int:
    return sum(len(e) for _, e in sections)


def check_text(text: str, rel: str = "log.md", archive: bool = False) -> list[dict]:
    findings: list[dict] = []
    body = text
    if archive:
        try:
            _, body, n = fm_split(text)
        except Exception as e:  # noqa: BLE001
            return [{"file": rel, "line": 1, "message": f"archive frontmatter unreadable: {e}"}]
        offset = n
    else:
        offset = 0
        if text.startswith("---"):
            findings.append({"file": rel, "line": 1, "message": "log.md must not carry frontmatter"})
    last_date = None
    in_section = False
    for i, line in enumerate(body.split("\n"), 1):
        ln = i + offset
        m = DATE_RE.match(line)
        if m:
            in_section = True
            if last_date and m.group(1) > last_date:
                findings.append({"file": rel, "line": ln, "message": f"date headings must be newest first ({m.group(1)} after {last_date})"})
            last_date = m.group(1)
            continue
        if line.startswith("## "):
            findings.append({"file": rel, "line": ln, "message": f"heading is not a date: {line.strip()!r}"})
            continue
        if line.startswith("* ") or line.startswith("- "):
            if not in_section:
                findings.append({"file": rel, "line": ln, "message": "entry outside a date section"})
            if not ENTRY_RE.match(line):
                findings.append({"file": rel, "line": ln, "message": "entry does not match `* **Action**: text` with a known action"})
            if "log.md" in line and "](" in line:
                findings.append({"file": rel, "line": ln, "message": "an entry may not link to the log itself"})
    return findings


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    sub = cli.subparsers(p)
    a = sub.add_parser("add", help="append an entry under today's heading")
    a.add_argument("--action", required=True, choices=ACTIONS)
    a.add_argument("--text", required=True)
    a.add_argument("--page", default=None, help="wiki-relative page path to link")
    a.add_argument("--run-id", default=None)
    sub.add_parser("rotate", help="move old entries to log/<yyyy>-q<n>.md")
    sub.add_parser("check", help="verify the log grammar")
    return p


def _page_title(wiki: Path, rel: str) -> str:
    p = wiki / rel
    if p.exists():
        try:
            t = get_key(p.read_text(encoding="utf-8"), "title")
            if isinstance(t, str) and t.strip():
                return t.strip()
        except Exception:  # noqa: BLE001
            pass
    return rel


def cmd_add(ctx: cli.Ctx, args) -> int:
    wiki = ctx.wiki_dir
    log_path = wiki / "log.md"
    text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    preamble, sections = parse_log(text)
    if not text:
        preamble = [H1]
    body = textnorm.sanitize(args.text, 500)
    entry = f"* **{args.action}**: "
    if args.page:
        rel = args.page.replace("\\", "/")
        wd = ctx.cfg.wiki_dir + "/"
        if rel.startswith(wd):
            rel = rel[len(wd):]
        entry += f"[{textnorm.sanitize(_page_title(wiki, rel), 80)}]({rel}) — "
    entry += body
    if args.run_id:
        entry += f" (run {textnorm.sanitize(args.run_id, 60)})"
    today = cli.iso(ctx.now)[:10]
    if sections and sections[0][0] == today:
        sections[0][1].insert(0, entry)
    else:
        sections.insert(0, (today, [entry]))
    wiki.mkdir(parents=True, exist_ok=True)
    log_path.write_text(render_log(preamble, sections), encoding="utf-8", newline="\n")
    ctx.emit.say(f"log: added under {today}: {entry[:100]}")
    ctx.emit.emit({"entry": entry, "date": today, "entries": entries_count(sections), "path": str(log_path)})
    return 0


def _quarter(date: str) -> str:
    y, m = date[:4], int(date[5:7])
    return f"{y}-q{(m - 1) // 3 + 1}"


def cmd_rotate(ctx: cli.Ctx, args) -> int:
    wiki = ctx.wiki_dir
    log_path = wiki / "log.md"
    keep = int(ctx.cfg.budget("log_entries") or 200)
    if not log_path.exists():
        ctx.emit.say("log: nothing to rotate")
        ctx.emit.emit({"rotated": 0, "archives": []})
        return 0
    preamble, sections = parse_log(log_path.read_text(encoding="utf-8"))
    total = entries_count(sections)
    if total <= keep:
        ctx.emit.say(f"log: {total} entries, within budget {keep}")
        ctx.emit.emit({"rotated": 0, "archives": [], "entries": total})
        return 0
    kept: list[tuple[str, list[str]]] = []
    moved: dict[str, dict[str, list[str]]] = {}
    remaining = keep
    for date, entries in sections:
        if remaining >= len(entries):
            kept.append((date, entries))
            remaining -= len(entries)
        else:
            if remaining > 0:
                kept.append((date, entries[:remaining]))
            for e in entries[remaining:]:
                moved.setdefault(_quarter(date), {}).setdefault(date, []).append(e)
            remaining = 0
    head = gitio.head(ctx.repo) or ""
    archives: list[str] = []
    for q, by_date in moved.items():
        rel = f"log/{q}.md"
        path = wiki / rel
        existing_sections: list[tuple[str, list[str]]] = []
        if path.exists():
            _, body, _ = fm_split(path.read_text(encoding="utf-8"))
            _, existing_sections = parse_log(body)
        merged: dict[str, list[str]] = {}
        for date, entries in existing_sections:
            merged.setdefault(date, []).extend(entries)
        for date, entries in by_date.items():
            bucket = merged.setdefault(date, [])
            for e in entries:
                if e not in bucket:
                    bucket.append(e)
        ordered = sorted(merged.items(), key=lambda kv: kv[0], reverse=True)
        n = sum(len(e) for _, e in ordered)
        dates = [d for d, _ in ordered]
        title = f"Log archive {q[:4]} Q{q[-1]}"
        fm = {"type": "Log Archive", "id": f"{ctx.cfg.id_prefix}/{rel[:-3]}", "schema_version": 1, "title": title,
              "description": f"Wiki log entries from {min(dates)} to {max(dates)} ({n} entries).", "audience": ["dev"],
              "owner": "process", "sources": [], "last_verified_commit": head,
              "generated": {"by": f"process:log.py/{VERSION}", "at": cli.iso(ctx.now)}}
        text = "---\n" + yamlmini.dumps(fm) + "---\n" + render_log([f"# {title}"], ordered)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        archives.append(rel)
    log_path.write_text(render_log(preamble, kept), encoding="utf-8", newline="\n")
    rotated = total - entries_count(kept)
    ctx.emit.say(f"log: rotated {rotated} entries into {', '.join(archives)}")
    ctx.emit.emit({"rotated": rotated, "archives": archives, "entries": entries_count(kept)})
    return 0


def cmd_check(ctx: cli.Ctx, args) -> int:
    wiki = ctx.wiki_dir
    findings: list[dict] = []
    log_path = wiki / "log.md"
    entries = 0
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8")
        findings += check_text(text, "log.md")
        entries = entries_count(parse_log(text)[1])
        keep = int(ctx.cfg.budget("log_entries") or 200)
        if entries > keep:
            findings.append({"file": "log.md", "line": 1, "message": f"{entries} entries exceed the budget of {keep}; run log.py rotate"})
    for arch in sorted((wiki / "log").glob("*.md")) if (wiki / "log").is_dir() else []:
        findings += check_text(arch.read_text(encoding="utf-8"), f"log/{arch.name}", archive=True)
    wd = ctx.cfg.wiki_dir
    for f in findings:
        ctx.emit.say(f"{wd}/{f['file']}:{f['line']}: L10 error: {f['message']}")
    ctx.emit.say(f"log: {entries} entries, {len(findings)} finding(s)")
    ctx.emit.emit({"entries": entries, "findings": findings}, ok=not findings)
    return cli.EXIT_FINDINGS if findings else 0


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    return {"add": cmd_add, "rotate": cmd_rotate, "check": cmd_check}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
