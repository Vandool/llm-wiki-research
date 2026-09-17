#!/usr/bin/env python3
"""Stand-in for the `copilot` binary used by run.py / bootstrap.py tests.

Behaviour selected by env FAKE_MODE:
  writes-page    (default) write lint-clean pages for the run's work list / cluster, emulate the
                 agentStop hook (stop_gate.py) so `.git/wiki/verified` appears, print the sentinel.
  writes-outside like writes-page but also writes README.md at the repo root (must be rejected).
  noop           write nothing, print sentinel ok with empty lists.
  hangs          sleep until killed (timeout / killpg test).
  fails          exit 1 with no sentinel.
Env FAKE_HOOKS=0 skips the stop-gate emulation. FAKE_LOG=<path> appends the argv it was called with.
Accepts (and mostly ignores) the real CLI flags: -p PROMPT --agent A --model M -s --no-ask-user
--add-dir D --allow-tool X --deny-tool Y --share FILE.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORDS = ("The service keeps orders in memory and moves them through a small state machine. "
         "Each transition is validated before it is applied, and every successful transition emits an event "
         "through the outbox so that downstream consumers see the change after the surrounding transaction "
         "commits. Payment failures do not change the order state; the order stays placed and a declined "
         "event is recorded instead. Line items are capped to keep payloads bounded. Configuration is read "
         "by name only. Tests construct the service with the fake gateway and a frozen clock.")


def log_argv() -> None:
    p = os.environ.get("FAKE_LOG")
    if p:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": sys.argv[1:], "env": {k: v for k, v in os.environ.items()
                                                                 if k.startswith("WIKI_")}}) + "\n")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def load_run() -> dict:
    gd = git("rev-parse", "--git-dir") or ".git"
    p = Path(gd) / "wiki" / "run.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def head() -> str:
    return git("rev-parse", "HEAD") or "0" * 40


def cfg() -> dict:
    p = Path(".github/wiki.config.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def planned_pages(run: dict, wiki: Path) -> list[dict]:
    """Pages to write: run.json work list (update) or the cluster's pages (bootstrap)."""
    pages: list[dict] = []
    for w in run.get("work", []) or []:
        pages.append({"path": w.get("path"), "type": w.get("type", "Module"),
                      "sources": [s.get("resource") for s in (w.get("sources") or []) if s.get("resource")],
                      "action": w.get("action", "update")})
    cluster = run.get("cluster") or os.environ.get("WIKI_CLUSTER")
    if cluster:
        plan_path = wiki / ".wiki-plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            for c in plan.get("clusters", []):
                if c.get("id") == cluster:
                    for pg in c.get("pages", []):
                        pages.append({"path": pg["path"], "type": pg.get("type", "Module"),
                                      "sources": list(pg.get("sources") or []), "action": "create"})
    seen: set[str] = set()
    out: list[dict] = []
    for p in pages:
        if p.get("path") and p["path"] not in seen:
            seen.add(p["path"])
            out.append(p)
    return out


def first_repo_source(sources: list[str]) -> str:
    for s in sources:
        if s.startswith("repo://"):
            return s
    return "repo://README.md"


def page_text(page: dict, id_prefix: str, model: str, now: str) -> str:
    path = page["path"]
    slug = Path(path).stem
    title = slug.replace("-", " ").title()
    ptype = page.get("type") or "Module"
    src = first_repo_source(page.get("sources") or [])
    src_path = src[len("repo://"):].split("#")[0].split("::")[0].rstrip("/")
    if src_path.endswith("/"):
        src_path = src_path.rstrip("/")
    # a directory source is fine for repo://; cite it as-is
    fm = [
        "---",
        f"type: {ptype}",
        f"id: {id_prefix}/{path[:-3]}",
        "schema_version: 1",
        f"title: {title}",
        f"description: Fake page for {title} written by the test double.",
        "audience: [agent, dev]",
        "owner: agent",
        "tags: []",
        "sources:",
        f'  - {{ id: main, resource: "{src}", title: "{src_path}" }}',
        f"last_verified_commit: {head()}",
        f'generated: {{ by: "copilot-cli/{model}", at: {now} }}',
        "status: draft",
        "related: []",
        "---",
    ]
    body = [
        f"# {title}",
        f"**Read this when:** you need to know what `{src_path}` does.",
        "",
    ]
    if ptype == "Module":
        body += ["**Does:** keeps orders. **Exposes:** a service. **Emits:** events. **Consumes:** a gateway.", "",
                 "## Structure", "| Component | Path | Responsibility |", "|---|---|---|",
                 f"| main | `{src_path}` | see source [^main] |", "", "## Gotchas", WORDS, ""]
    elif ptype == "Concept":
        body += ["**Problem:** " + WORDS[:120], "", "**Solution here:** see the source [^main].", "",
                 "**Consequences:** none recorded.", "", "**Where to look:** `" + src_path + "`.", ""]
    else:
        body += [WORDS + " [^main]", ""]
    body += [f"[^main]: `{src_path}`", ""]
    return "\n".join(fm + body)


def ensure_inbound_link(wiki: Path, page_path: str, title: str) -> None:
    """Give a new page an inbound link from overview.md (index links do not count)."""
    ov = wiki / "overview.md"
    if not ov.exists():
        return
    text = ov.read_text(encoding="utf-8")
    rel = page_path
    if f"]({rel})" in text:
        return
    line = f"- [{title}]({rel})"
    if "## Where to start" in text:
        text = text.rstrip("\n") + "\n" + line + "\n"
    else:
        text = text.rstrip("\n") + "\n\n## Where to start\n" + line + "\n"
    ov.write_text(text, encoding="utf-8")


def emulate_stop_gate(session_id: str) -> None:
    if os.environ.get("FAKE_HOOKS", "1") == "0":
        return
    sg = Path(".github/skills/wiki-maintain/scripts/stop_gate.py")
    if not sg.exists():
        return
    env = dict(os.environ)
    env["WIKI_RUN"] = "1"
    payload = json.dumps({"sessionId": session_id, "timestamp": "2026-09-07T10:00:00Z", "cwd": ".",
                          "transcriptPath": "", "stopReason": "end_turn", "stop_hook_active": False})
    subprocess.run([sys.executable, str(sg)], input=payload, capture_output=True, text=True, env=env)


def main() -> int:
    log_argv()
    mode = os.environ.get("FAKE_MODE", "writes-page")
    if mode == "hangs":
        while True:
            time.sleep(1)
    if mode == "fails":
        print("fake copilot: simulated failure", file=sys.stderr)
        return 1
    run = load_run()
    c = cfg()
    wiki = Path(c.get("wiki_dir", "wiki") or "wiki")
    model = "fake"
    for i, a in enumerate(sys.argv):
        if a == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
    id_prefix = (c.get("repo") or {}).get("id_prefix") or (c.get("repo") or {}).get("slug", "").rsplit("/", 1)[-1] \
        or Path.cwd().name
    now = git("log", "-1", "--format=%cI") or "2026-09-07T10:00:00+00:00"
    now = now.replace("+00:00", "Z")
    updated: list[str] = []
    created: list[str] = []
    if mode in ("writes-page", "writes-outside"):
        for page in planned_pages(run, wiki):
            target = wiki / page["path"]
            existed = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                text = target.read_text(encoding="utf-8")
                marker = "\n<!-- -->\n"
                text = text.rstrip("\n") + "\n\nUpdated by the fake copilot: " + WORDS[:80] + "\n"
                target.write_text(text, encoding="utf-8")
                updated.append(page["path"])
            else:
                target.write_text(page_text(page, id_prefix, model, now), encoding="utf-8")
                ensure_inbound_link(wiki, page["path"], Path(page["path"]).stem.replace("-", " ").title())
                created.append(page["path"])
        if mode == "writes-outside":
            Path("README.md").write_text("hello from the fake copilot\n", encoding="utf-8")
        # generated indexes are the scripts' job, but a real session runs index.py --write before stopping
        idx = Path(".github/skills/wiki-maintain/scripts/index.py")
        if idx.exists():
            subprocess.run([sys.executable, str(idx), "--write"], capture_output=True, text=True)
        emulate_stop_gate(run.get("session_id") or "fake-session")
    result = {"status": "ok", "updated": updated, "created": created, "proposed": [], "needs_confirmation": [],
              "declined": []}
    print("Fake copilot finished.")
    print("WIKI-RUN-RESULT: " + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
