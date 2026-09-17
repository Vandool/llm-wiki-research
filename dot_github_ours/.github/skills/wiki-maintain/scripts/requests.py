#!/usr/bin/env python3
"""requests.py — the human request channel `<wiki>/requests.md` (plan §8.8.3).

CLI:
  requests.py --parse [--json]                                  OPEN lines → sanitised list + untrusted block
  requests.py --close N [N ...] --run-id ID --result PATH       rewrite line(s) in place as DONE
  requests.py --skip N --reason TEXT [--run-id ID]              → SKIPPED
  requests.py --defer N --reason TEXT [--run-id ID]             → DEFERRED
  requests.py --lint [--json]                                   grammar check of every `- [ ]` line (exit 1)
Grammar: `- [ ] OPEN YYYY-MM-DD @user: text` (`- [x] DONE … → run <id> (…)` once processed).
N is the 1-based position in the OPEN list as printed by --parse (oldest first). Sanitising: hidden and
control characters stripped, whitespace collapsed, text capped at budgets.max_request_chars, at most
budgets.max_requests_per_run requests per run (oldest first), delimiters escaped.
Untrusted block: `<<<WIKI-UNTRUSTED id=R1 source=requests.md>>>\\n(date @user) text\\n<<<END-UNTRUSTED>>>`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, textnorm  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "requests"
LINE_RE = re.compile(r"^- \[( |x)\] (OPEN|DONE|SKIPPED|DEFERRED) (\d{4}-\d{2}-\d{2}) @([\w.-]+): (.+?)( → run (\S+)(.*))?$")
ITEM_RE = re.compile(r"^- \[")
START = "<<<WIKI-UNTRUSTED"
END = "<<<END-UNTRUSTED>>>"


def escape_delims(text: str) -> str:
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def parse(text: str, max_chars: int = 500, max_count: int = 5) -> dict:
    """{open: [{n, line, date, user, text}], block: str, deferred_by_cap: [n...], all: [...]}"""
    items: list[dict] = []
    for no, line in enumerate(text.split("\n"), 1):
        m = LINE_RE.match(line.rstrip("\r"))
        if not m:
            continue
        items.append({"line": no, "checked": m.group(1) == "x", "state": m.group(2), "date": m.group(3), "user": m.group(4),
                      "raw_text": m.group(5), "run": m.group(7), "tail": (m.group(8) or "").strip()})
    open_items = sorted([i for i in items if i["state"] == "OPEN"], key=lambda i: (i["date"], i["line"]))
    result_open: list[dict] = []
    for n, it in enumerate(open_items, 1):
        result_open.append({"n": n, "line": it["line"], "date": it["date"], "user": it["user"],
                            "text": textnorm.sanitize(escape_delims(it["raw_text"]), max_chars)})
    selected = result_open[:max_count]
    blocks = [f"{START} id=R{r['n']} source=requests.md>>>\n({r['date']} @{r['user']}) {r['text']}\n{END}" for r in selected]
    return {"open": result_open, "selected": selected, "deferred_by_cap": [r["n"] for r in result_open[max_count:]],
            "block": "\n\n".join(blocks), "all": items}


def lint(text: str) -> list[dict]:
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        if ITEM_RE.match(line) and not LINE_RE.match(line.rstrip("\r")):
            out.append({"line": no, "message": "request line does not match `- [ ] OPEN YYYY-MM-DD @user: text`"})
    return out


def rewrite(text: str, numbers: list[int], state: str, run_id: str, note: str) -> tuple[str, list[int]]:
    parsed = parse(text, max_chars=10_000, max_count=10_000)
    by_n = {r["n"]: r for r in parsed["open"]}
    lines = text.split("\n")
    done: list[int] = []
    for n in numbers:
        r = by_n.get(n)
        if not r:
            continue
        idx = r["line"] - 1
        m = LINE_RE.match(lines[idx].rstrip("\r"))
        if not m:
            continue
        box = "x" if state in ("DONE", "SKIPPED") else " "
        tail = f" → run {run_id} ({textnorm.sanitize(note, 200)})" if note else f" → run {run_id}"
        lines[idx] = f"- [{box}] {state} {m.group(3)} @{m.group(4)}: {m.group(5)}{tail}"
        done.append(n)
    return "\n".join(lines), done


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--parse", action="store_true", help="list OPEN requests and the untrusted block")
    g.add_argument("--close", nargs="+", type=int, metavar="N", help="mark request(s) DONE")
    g.add_argument("--skip", type=int, metavar="N", help="mark a request SKIPPED")
    g.add_argument("--defer", type=int, metavar="N", help="mark a request DEFERRED")
    p.add_argument("--lint", action="store_true", help="check every request line against the grammar")
    p.add_argument("--run-id", default=None)
    p.add_argument("--result", default=None, help="page path written for --close")
    p.add_argument("--reason", default=None, help="reason for --skip / --defer")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    path = ctx.wiki_dir / "requests.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    wd = ctx.cfg.wiki_dir
    if not (args.parse or args.close or args.skip or args.defer or args.lint):
        args.parse = True
    findings = lint(text) if args.lint else []
    for f in findings:
        ctx.emit.say(f"{wd}/requests.md:{f['line']}: L10 error: {f['message']}")
    if args.close or args.skip is not None or args.defer is not None:
        if not text:
            raise cli.EnvError(f"{path} does not exist")
        if args.close:
            if not args.run_id:
                raise cli.ConfigError("--close needs --run-id")
            new, done = rewrite(text, list(args.close), "DONE", args.run_id, args.result or "")
        elif args.skip is not None:
            if not args.reason:
                raise cli.ConfigError("--skip needs --reason")
            new, done = rewrite(text, [args.skip], "SKIPPED", args.run_id or "manual", args.reason)
        else:
            if not args.reason:
                raise cli.ConfigError("--defer needs --reason")
            new, done = rewrite(text, [args.defer], "DEFERRED", args.run_id or "manual", args.reason)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
        missing = [n for n in (args.close or [args.skip if args.skip is not None else args.defer]) if n not in done]
        ctx.emit.say(f"requests: updated {len(done)} line(s)" + (f"; unknown: {missing}" if missing else ""))
        ctx.emit.emit({"updated": done, "unknown": missing, "findings": findings}, ok=not missing and not findings)
        return cli.EXIT_FINDINGS if (missing or findings) else 0
    res = parse(text, int(ctx.cfg.budget("max_request_chars") or 500), int(ctx.cfg.budget("max_requests_per_run") or 5))
    if not text:
        ctx.emit.say(f"requests: {path} not found (no requests)")
    for r in res["open"]:
        ctx.emit.say(f"R{r['n']} ({r['date']} @{r['user']}, line {r['line']}): {r['text']}")
    ctx.emit.say(f"requests: {len(res['open'])} open, {len(res['selected'])} selected, {len(res['deferred_by_cap'])} deferred by cap")
    if not args.json and res["block"]:
        ctx.emit.out(res["block"])
    ctx.emit.emit({"open": res["open"], "selected": res["selected"], "deferred_by_cap": res["deferred_by_cap"],
                   "block": res["block"], "findings": findings}, ok=not findings)
    return cli.EXIT_FINDINGS if findings else 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
