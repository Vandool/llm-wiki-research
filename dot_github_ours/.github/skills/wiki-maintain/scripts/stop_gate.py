#!/usr/bin/env python3
"""stop_gate.py — Copilot CLI `agentStop` hook (plan §8.4).

Reads the agentStop payload on stdin, prints exactly ONE JSON object:
  passive mode, or `git status --porcelain -- <wiki_dir>` empty → {"decision": "allow"}
  else lint.py --changed + backlinks.py --changed [--plan] + index.py --check:
    clean → allow; writes `<git-dir>/wiki/verified` (tree hash of the wiki dir); deletes the retry counter
    findings → counter `<git-dir>/wiki/stop-retries.<sessionId>` += 1;
      ≤ 3 → {"decision": "block", "reason": "<≤20 findings>\nFix these, then stop again (attempt k of 3)."}
      > 3 → allow and touch `<git-dir>/wiki/stop-gate-failed` (the driver then refuses to commit narrative pages)
A malformed payload in wiki mode exits non-zero (still one JSON object); in passive mode it allows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio  # noqa: E402
from hook_guard import Env, SCRIPTS_REL  # noqa: E402
from wikilib import runner  # noqa: E402

NAME = "stop_gate"
VERSION = cli.KIT_VERSION
MAX_ATTEMPTS = 3
MAX_FINDINGS = 20
ALLOW = {"decision": "allow"}


def findings_for(env: Env) -> list[str]:
    wd = env.wiki_rel
    run = env.run_active or {}
    plan_args: list[str] = []
    plan_file = env.wiki / ".wiki-plan.json"
    if run.get("mode") in ("page", "bootstrap") and plan_file.exists():
        plan_args = ["--plan", str(plan_file)]
    out: list[str] = []
    lint = runner.run_script(env.repo, "lint", "--changed", *plan_args, timeout=100)
    if lint.data is None:
        out.append(f"lint.py --changed failed: {lint.tail() or 'no output'}")
    for f in (lint.data or {}).get("errors") or []:
        out.append(f"{f.get('file')}:{f.get('line') or 1}: {f.get('rule')} {f.get('message')}" + (f" → {f['fix']}" if f.get("fix") else ""))
    bl = runner.run_script(env.repo, "backlinks", "--changed", *plan_args, timeout=60)
    if bl.data is None:
        out.append(f"backlinks.py --changed failed: {bl.tail() or 'no output'}")
    for o in (bl.data or {}).get("orphans") or []:
        if o.get("severity") == "error":
            out.append(f"{wd}/{o.get('file')}: L02 {o.get('message')}")
    for b in (bl.data or {}).get("broken") or []:
        if b.get("severity") == "error":
            out.append(f"{wd}/{b.get('file')}:{b.get('line') or 1}: L01 {b.get('message')}")
    idx = runner.run_script(env.repo, "index", "--check", timeout=60)
    if idx.data is None:
        out.append(f"index.py --check failed: {idx.tail() or 'no output'}")
    for rel in (idx.data or {}).get("drift") or []:
        out.append(f"{wd}/{rel}: index out of date — run `python3 {SCRIPTS_REL}/index.py --write`")
    return out


def gate(raw: str) -> tuple[dict, int]:
    try:
        payload = json.loads(raw) if raw.strip() else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        payload = None
    env = Env(payload.get("cwd") if payload else None)
    if payload is None:
        mode = env.resolve_mode(None)
        env.glog("stop", "malformed", None, reason="payload is not a JSON object")
        if mode == "wiki":
            return {"decision": "block", "reason": "wiki-guard: malformed agentStop payload — stop again"}, 2
        return dict(ALLOW), 0
    session = str(payload.get("sessionId") or payload.get("session_id") or "") or "unknown"
    mode = env.resolve_mode(session)
    keys = payload.keys()
    if mode != "wiki":
        env.glog("stop", "allow", session, rule="passive", payload_keys=keys)
        return dict(ALLOW), 0
    counter = env.state / f"stop-retries.{session}"
    verified = env.state / "verified"
    try:
        dirty = gitio.status_porcelain(env.repo, [env.wiki_rel])
    except gitio.GitError as e:
        dirty = [f"?? {e}"]
    if not dirty:
        _write_verified(env, verified)
        _unlink(counter)
        env.glog("stop", "allow", session, rule="clean-tree", payload_keys=keys)
        return dict(ALLOW), 0
    found = findings_for(env)
    if not found:
        _write_verified(env, verified)
        _unlink(counter)
        env.glog("stop", "allow", session, rule="verified", payload_keys=keys, reason=f"{len(dirty)} changed path(s)")
        return dict(ALLOW), 0
    k = _bump(counter)
    if k <= MAX_ATTEMPTS:
        reason = "\n".join(found[:MAX_FINDINGS])
        if len(found) > MAX_FINDINGS:
            reason += f"\n(+{len(found) - MAX_FINDINGS} more)"
        reason += f"\nFix these, then stop again (attempt {k} of {MAX_ATTEMPTS})."
        env.glog("stop", "block", session, rule=f"attempt-{k}", payload_keys=keys, reason=found[0][:200])
        return {"decision": "block", "reason": reason}, 0
    try:
        (env.state / "stop-gate-failed").write_text("\n".join(found) + "\n", encoding="utf-8")
    except OSError:
        pass
    _unlink(verified)
    env.glog("stop", "allow", session, rule="gave-up", payload_keys=keys, reason=f"{len(found)} finding(s) after {k - 1} attempts")
    return dict(ALLOW), 0


def _write_verified(env: Env, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(gitio.tree_hash([env.wiki_rel], env.repo) + "\n", encoding="utf-8")
    except (OSError, gitio.GitError):
        pass


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _bump(path: Path) -> int:
    try:
        k = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        k = 0
    k += 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{k}\n", encoding="utf-8")
    except OSError:
        pass
    return k


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        raw = ""
    try:
        out, rc = gate(raw)
    except Exception as e:  # noqa: BLE001 - always one JSON object
        if cli.env_flag("WIKI_RUN"):
            out, rc = {"decision": "block", "reason": f"wiki-guard: stop gate error {type(e).__name__}: {e} — stop again"}, 2
        else:
            out, rc = dict(ALLOW), 0
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return rc


if __name__ == "__main__":
    sys.exit(main())
