"""wikilib/runner.py — shared launcher, judge and commit helpers for run.py and bootstrap.py (plan §8.6, §8.14).

API:
  script_path(name) -> Path                       sibling script inside scripts/
  run_script(repo, name, *args) -> ScriptResult   run a kit script with --json; .data is its one JSON object
  Lock(state_dir, ttl_min)                        `<git-dir>/wiki/lock/` with pid + age; stale locks are reclaimed
  find_copilot(cfg, repo) -> str | None           WIKI_COPILOT_BIN → git config wiki.copilot → copilot.bin → PATH → fallbacks
  build_argv(bin, prompt, model, wiki_dir, share) the §8.14 command line as an argv list (a .py bin runs under sys.executable)
  cli_env(phase, run_id, extra) -> dict           WIKI_RUN=1 WIKI_WORKER=1 WIKI_PHASE=… COPILOT_AUTO_UPDATE=false WIKI_RUN_ID=…
  spawn_cli(...) -> SpawnResult                   Popen(start_new_session=True), wall clock, killpg + --kill-after
  parse_sentinel(text) -> dict | None             the final `WIKI-RUN-RESULT: {…}` line
  status_snapshot / outside_changes / wiki_changes / revert_paths / revert_wiki
  judge(...) -> Verdict                           diff confined · verified marker · sentinel · lint --all · backlinks --check
  commit_wiki(repo, wiki_dir, message, run_id)    `git add -- <wiki>` + commit with trailers Wiki-Update: auto, Wiki-Run: <id>
  metrics(state_dir, record) · rotate(path) · render_prompt(name, vars) · new_run_id(head, now) · base_run(...)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import budget as wbudget, cli, config as wconfig, gitio, pages as wpages
from .cli import iso, utcnow

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS_DIR.parent
PROMPTS_DIR = SKILL_DIR / "prompts"
SCRIPTS_REL = ".github/skills/wiki-maintain/scripts"
CONSUMERS_REL = ".github/instructions/wiki-consumers.instructions.md"
SENTINEL = "WIKI-RUN-RESULT:"
TRAILER_UPDATE = "Wiki-Update"
TRAILER_RUN = "Wiki-Run"
AGENT = "wiki-maintainer"
SENTINEL_STATUSES = ("ok", "deferred", "failed")
ALLOW_TOOLS = ["read", "write", "shell(python3:*)", "shell(git:*)", "shell(grep:*)", "shell(rg:*)", "shell(ls:*)",
               "shell(find:*)", "shell(head:*)", "shell(tail:*)", "shell(sed:*)", "shell(wc:*)"]
DENY_TOOLS = ["shell(git push:*)", "shell(git commit:*)", "shell(git add:*)", "shell(git reset:*)",
              "shell(git checkout:*)", "shell(git stash:*)", "shell(git clean:*)", "shell(git rebase:*)",
              "shell(git merge:*)", "shell(rm:*)", "shell(mv:*)", "shell(curl:*)", "shell(wget:*)", "shell(npm:*)",
              "shell(npx:*)", "shell(pip:*)", "shell(sudo:*)", "web", "agent"]
COPILOT_FALLBACKS = ["~/.local/bin/copilot", "/usr/local/bin/copilot", "/opt/homebrew/bin/copilot"]
MARKERS = ("verified", "stop-gate-failed")

__all__ = ["SCRIPTS_DIR", "SKILL_DIR", "PROMPTS_DIR", "SCRIPTS_REL", "CONSUMERS_REL", "SENTINEL", "TRAILER_UPDATE",
           "TRAILER_RUN", "AGENT", "ScriptResult", "script_path", "run_script", "Lock", "pid_alive", "find_copilot",
           "build_argv", "cli_env", "SpawnResult", "spawn_cli", "parse_sentinel", "status_snapshot", "outside_changes",
           "wiki_changes", "revert_paths", "revert_wiki", "verify_marker", "clear_markers", "Verdict", "judge",
           "commit_wiki", "metrics", "rotate", "render_prompt", "new_run_id", "base_run", "narrative_rels",
           "read_output_tail"]


# ---------------------------------------------------------------- scripts

def script_path(name: str) -> Path:
    return SCRIPTS_DIR / (name if name.endswith(".py") else f"{name}.py")


@dataclass
class ScriptResult:
    rc: int
    data: Optional[dict]
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0 and (self.data is None or bool(self.data.get("ok", True)))

    def tail(self, n: int = 6) -> str:
        lines = [l for l in (self.stderr or "").splitlines() if l.strip()]
        return "; ".join(lines[-n:])


def run_script(repo: Path, name: str, *args: Any, env: Optional[dict] = None, timeout: int = 900,
               json_out: bool = True) -> ScriptResult:
    """Run `python3 <scripts>/<name>.py <args> [--json]` in the repo; parse the single JSON object."""
    cmd = [sys.executable, str(script_path(name)), *[str(a) for a in args]]
    if json_out and "--json" not in cmd:
        cmd.append("--json")
    e = dict(os.environ)
    e["WIKI_HOOK_RUNNING"] = "1"
    e.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if env:
        e.update(env)
    try:
        res = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, env=e, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ScriptResult(124, None, "", f"{name}.py timed out after {timeout}s")
    data = None
    if json_out:
        out = res.stdout.strip()
        if out:
            try:
                data = json.loads(out)
            except ValueError:
                for line in reversed(out.splitlines()):
                    try:
                        data = json.loads(line)
                        break
                    except ValueError:
                        continue
        if not isinstance(data, dict):
            data = None
    return ScriptResult(res.returncode, data, res.stdout, res.stderr)


# ---------------------------------------------------------------- lock

def pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


class Lock:
    """`<git-dir>/wiki/lock/` (atomic mkdir) holding `info.json` {pid, kind, started, started_ts}.

    A lock is stale when its pid is dead (pid-less interactive locks never are) or older than `ttl_min`.
    """

    def __init__(self, state_dir: Path, ttl_min: float = 60):
        self.dir = Path(state_dir) / "lock"
        self.info_path = self.dir / "info.json"
        self.ttl_s = float(ttl_min or 60) * 60
        self.held = False

    def read(self) -> Optional[dict]:
        if not self.dir.exists():
            return None
        try:
            data = json.loads(self.info_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def age_s(self, info: Optional[dict] = None) -> float:
        info = info if info is not None else (self.read() or {})
        ts = info.get("started_ts")
        if isinstance(ts, (int, float)):
            return max(0.0, time.time() - float(ts))
        try:
            return max(0.0, time.time() - self.dir.stat().st_mtime)
        except OSError:
            return 0.0

    def is_stale(self, info: Optional[dict] = None) -> bool:
        info = info if info is not None else (self.read() or {})
        pid = info.get("pid")
        if pid and not pid_alive(int(pid)):
            return True
        return self.age_s(info) > self.ttl_s

    def _write(self, kind: str, pid: Optional[int]) -> None:
        self.info_path.write_text(json.dumps({"pid": pid, "kind": kind, "started": iso(utcnow()),
                                              "started_ts": time.time()}) + "\n", encoding="utf-8")

    def acquire(self, kind: str = "worker", pid: Optional[int] = None, force: bool = False) -> tuple[bool, Optional[dict]]:
        """(True, None) when acquired; (False, info) when held by a live run. Stale or forced → reclaimed."""
        if kind == "worker" and pid is None:
            pid = os.getpid()
        self.dir.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            try:
                os.mkdir(self.dir)
            except FileExistsError:
                info = self.read() or {}
                if force or self.is_stale(info):
                    shutil.rmtree(self.dir, ignore_errors=True)
                    continue
                return False, info
            self._write(kind, pid)
            self.held = True
            return True, None
        return False, self.read()

    def wait(self, timeout_s: float, kind: str = "worker", poll_s: float = 2.0) -> bool:
        end = time.time() + max(0.0, timeout_s)
        while True:
            ok, _ = self.acquire(kind)
            if ok:
                return True
            if time.time() >= end:
                return False
            time.sleep(poll_s)

    def inherit(self, kind: str = "worker") -> None:
        """A detached child takes over the parent's lock (rewrites the pid)."""
        if self.dir.exists():
            self._write(kind, os.getpid())
        else:
            os.makedirs(self.dir, exist_ok=True)
            self._write(kind, os.getpid())
        self.held = True

    def release(self, force: bool = False) -> None:
        if self.held or force:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.held = False

    def describe(self, info: Optional[dict] = None) -> str:
        info = info if info is not None else (self.read() or {})
        return f"pid {info.get('pid') or '-'} ({info.get('kind') or 'unknown'}) since {info.get('started') or 'unknown'}"


# ---------------------------------------------------------------- CLI discovery and launch

def find_copilot(cfg: wconfig.Config, repo: Path) -> Optional[str]:
    """Discovery order (plan §8.6): WIKI_COPILOT_BIN → git config wiki.copilot → config copilot.bin →
    shutil.which → ~/.local/bin, /usr/local/bin, /opt/homebrew/bin, $(npm prefix -g)/bin, Windows copilot.cmd."""
    cands: list[str] = []
    env = os.environ.get("WIKI_COPILOT_BIN")
    if env:
        cands.append(env)
    g = gitio.config_get("wiki.copilot", repo)
    if g:
        cands.append(g)
    c = cfg.get("copilot.bin")
    if c:
        cands.append(str(c))
    for name in ("copilot", "copilot.cmd", "copilot.exe"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    cands += COPILOT_FALLBACKS
    for cand in cands:
        p = Path(os.path.expanduser(cand))
        if p.is_file():
            return str(p)
        w = shutil.which(cand)
        if w:
            return w
    npm = shutil.which("npm")
    if npm:
        try:
            res = subprocess.run([npm, "prefix", "-g"], capture_output=True, text=True, timeout=10)
            prefix = res.stdout.strip()
            if res.returncode == 0 and prefix:
                for name in ("copilot", "copilot.cmd"):
                    p = Path(prefix) / "bin" / name
                    if p.is_file():
                        return str(p)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def build_argv(bin_path: str, prompt: str, model: str, wiki_dir: str, share_path: Path,
               agent: str = AGENT) -> list[str]:
    """The §8.14 command line (without the shell `timeout` wrapper: spawn_cli enforces the wall clock)."""
    cmd = [sys.executable, bin_path] if bin_path.lower().endswith(".py") else [bin_path]
    cmd += ["-p", prompt, "--agent", agent, "--model", model, "-s", "--no-ask-user", "--add-dir", wiki_dir]
    for t in ALLOW_TOOLS:
        cmd += ["--allow-tool", t]
    for t in DENY_TOOLS:
        cmd += ["--deny-tool", t]
    cmd += ["--share", str(share_path)]
    return cmd


def cli_env(phase: str, run_id: str, extra: Optional[dict] = None) -> dict:
    e = dict(os.environ)
    e.update({"WIKI_RUN": "1", "WIKI_WORKER": "1", "WIKI_PHASE": phase, "COPILOT_AUTO_UPDATE": "false",
              "WIKI_RUN_ID": run_id, "WIKI_HOOK_RUNNING": "1"})
    if extra:
        e.update({k: str(v) for k, v in extra.items()})
    return e


@dataclass
class SpawnResult:
    rc: Optional[int]
    timed_out: bool
    duration_s: float
    pid: int
    killed: bool = False


def _terminate_group(proc: subprocess.Popen, kill_after: float) -> None:
    if os.name == "nt":  # pragma: no cover - Windows has no process groups in this sense
        proc.terminate()
        try:
            proc.wait(timeout=kill_after)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return
    for sig, wait_s in ((signal.SIGTERM, kill_after), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def spawn_cli(argv: list[str], cwd: Path, env: dict, timeout_s: float, output_path: Path, kill_after: float = 30.0,
              pid_file: Optional[Path] = None) -> SpawnResult:
    """Run the CLI in its own session; stdout+stderr → output_path; killpg after timeout_s (+kill_after)."""
    t0 = time.monotonic()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "ab") as out:
        kw: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "cwd": str(cwd), "env": env}
        if os.name == "nt":  # pragma: no cover
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(argv, **kw)
        if pid_file:
            try:
                pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
            except OSError:
                pass
        timed_out = killed = False
        try:
            rc: Optional[int] = proc.wait(timeout=timeout_s if timeout_s and timeout_s > 0 else None)
        except subprocess.TimeoutExpired:
            timed_out = killed = True
            _terminate_group(proc, kill_after)
            rc = proc.returncode
    return SpawnResult(rc, timed_out, round(time.monotonic() - t0, 3), proc.pid, killed)


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_sentinel(text: str) -> Optional[dict]:
    """The last `WIKI-RUN-RESULT: {…}` line, normalised; None when absent or unparseable."""
    for line in reversed((text or "").splitlines()):
        clean = _ANSI.sub("", line).strip()
        idx = clean.find(SENTINEL)
        if idx < 0:
            continue
        body = clean[idx + len(SENTINEL):].strip()
        try:
            obj = json.loads(body)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        out = {"status": str(obj.get("status") or "").lower()}
        if out["status"] not in SENTINEL_STATUSES:
            out["status"] = "failed"
        for key in ("updated", "created", "proposed", "needs_confirmation", "declined"):
            val = obj.get(key)
            out[key] = [str(x) for x in val] if isinstance(val, list) else []
        req = obj.get("requests_done") or obj.get("requests")
        out["requests_done"] = [int(x) for x in req if str(x).isdigit()] if isinstance(req, list) else []
        out["raw"] = obj
        return out
    return None


def read_output_tail(path: Path, max_bytes: int = 200_000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-max_bytes:].decode("utf-8", "replace")


# ---------------------------------------------------------------- working-tree accounting

def _hash_file(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def status_snapshot(repo: Path) -> dict[str, tuple[str, Optional[str]]]:
    """{repo-relative path: (XY status, sha256 of the working file)} for every dirty/untracked path."""
    try:
        raw = gitio.git(["status", "--porcelain", "--untracked-files=all", "-z"], repo, text=False)
    except gitio.GitError:
        return {}
    parts = [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0")]
    snap: dict[str, tuple[str, Optional[str]]] = {}
    i = 0
    while i < len(parts):
        rec = parts[i]
        if not rec:
            i += 1
            continue
        status, path = rec[:2], rec[3:]
        snap[path] = (status, _hash_file(repo / path))
        if status[0] in ("R", "C") and i + 1 < len(parts):
            i += 1
        i += 1
    return snap


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def outside_changes(before: dict, after: dict, wiki_dir: str, allowed: Iterable[str] = ()) -> list[str]:
    """Paths outside the wiki dir whose state changed between two snapshots (new, modified, reverted, deleted)."""
    allow = set(allowed)
    out: set[str] = set()
    for path, st in after.items():
        if _under(path, wiki_dir) or path in allow:
            continue
        if before.get(path) != st:
            out.add(path)
    for path, st in before.items():
        if _under(path, wiki_dir) or path in allow:
            continue
        if path not in after:
            out.add(path)
    return sorted(out)


def wiki_changes(before: dict, after: dict, wiki_dir: str) -> list[str]:
    """Wiki-relative paths whose state changed between the snapshots."""
    out: set[str] = set()
    n = len(wiki_dir.rstrip("/")) + 1
    for path, st in after.items():
        if _under(path, wiki_dir) and before.get(path) != st:
            out.add(path[n:])
    for path in before:
        if _under(path, wiki_dir) and path not in after:
            out.add(path[n:])
    return sorted(out)


def narrative_rels(rels: Iterable[str]) -> list[str]:
    """Pages the model may own: markdown, not process-generated, not the manifest/plan/log/requests."""
    out = []
    for rel in rels:
        if not rel.endswith(".md"):
            continue
        if wpages.is_process_owned(rel) or rel in ("requests.md", "instructions.md"):
            continue
        out.append(rel)
    return sorted(out)


def revert_paths(repo: Path, wiki_dir: str, rels: Iterable[str], before: dict) -> list[str]:
    """Restore wiki paths to the pre-run state: tracked → HEAD content; new untracked → deleted."""
    reverted: list[str] = []
    for rel in rels:
        path = f"{wiki_dir}/{rel}"
        full = repo / path
        was = before.get(path)
        tracked = gitio.rev_parse(f"HEAD:{path}", repo) is not None
        if tracked:
            if gitio.git_rc(["checkout", "-q", "HEAD", "--", path], repo) == 0:
                reverted.append(rel)
        elif was is None or was[0] != "??":
            try:
                if full.exists():
                    full.unlink()
                    reverted.append(rel)
            except OSError:
                pass
        # an untracked file that already existed before the run cannot be restored; it is left as is
    return reverted


def revert_wiki(repo: Path, wiki_dir: str) -> None:
    """Whole wiki dir back to HEAD (tracked restored, untracked removed; ignored files kept)."""
    gitio.git_rc(["checkout", "-q", "HEAD", "--", wiki_dir], repo)
    gitio.git_rc(["clean", "-fdq", "--", wiki_dir], repo)


def verify_marker(state_dir: Path, repo: Path, wiki_dir: str) -> tuple[bool, bool]:
    """(present, matches the current tree hash of the wiki dir)."""
    p = Path(state_dir) / "verified"
    if not p.exists():
        return False, False
    try:
        content = p.read_text(encoding="utf-8").strip()
    except OSError:
        return True, False
    try:
        current = gitio.tree_hash([wiki_dir], repo)
    except gitio.GitError:
        return True, False
    return True, content == current


def clear_markers(state_dir: Path) -> None:
    state_dir = Path(state_dir)
    for name in MARKERS:
        try:
            (state_dir / name).unlink()
        except OSError:
            pass
    for p in state_dir.glob("stop-retries.*"):
        try:
            p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- judge

@dataclass
class Verdict:
    result: str = "failed"                 # ok | partial | deferred | failed | aborted | noop
    reasons: list[str] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)      # wiki-relative paths the session changed
    narrative: list[str] = field(default_factory=list)    # narrative pages among them (before reverts)
    kept: list[str] = field(default_factory=list)         # narrative pages that survived
    reverted: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)      # expected pages that do not exist
    lint_errors: list[dict] = field(default_factory=list)
    backlink_errors: list[dict] = field(default_factory=list)
    sentinel: Optional[dict] = None
    verified: bool = False
    verified_match: bool = False
    stop_gate_failed: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.result in ("ok", "partial", "deferred")

    def summary(self) -> str:
        parts = [self.result]
        if self.reasons:
            parts.append("; ".join(self.reasons))
        return ": ".join(parts)


def _quality(repo: Path, wiki_dir: str, checkpoint: Optional[str], consumers: bool, log: Callable[[str], None]) -> tuple[list[dict], list[dict], set[str]]:
    """index --write [--consumers] → lint --all [--base] → backlinks --check. Returns (lint errors, backlink errors, failing pages)."""
    idx = run_script(repo, "index", "--write", *(["--consumers"] if consumers else []))
    if not idx.ok:
        log(f"index.py --write failed: {idx.tail()}")
    lint_args = ["--all"]
    if checkpoint and gitio.rev_parse(checkpoint, repo):
        lint_args += ["--base", checkpoint]
    lint = run_script(repo, "lint", *lint_args)
    lint_errors = list((lint.data or {}).get("errors") or [])
    if lint.data is None:
        lint_errors.append({"rule": "L00", "file": f"{wiki_dir}", "line": 0, "message": f"lint.py failed: {lint.tail()}"})
    bl = run_script(repo, "backlinks", "--check")
    bl_errors = [o for o in ((bl.data or {}).get("orphans") or []) if o.get("severity") == "error"]
    bl_errors += [b for b in ((bl.data or {}).get("broken") or []) if b.get("severity") == "error"]
    if bl.data is None:
        bl_errors.append({"file": "", "message": f"backlinks.py failed: {bl.tail()}", "severity": "error"})
    failing: set[str] = set()
    n = len(wiki_dir.rstrip("/")) + 1
    for f in lint_errors:
        path = str(f.get("file") or "")
        if _under(path, wiki_dir):
            failing.add(path[n:])
    for f in bl_errors:
        path = str(f.get("file") or "")
        failing.add(path[n:] if _under(path, wiki_dir) else path)
    return lint_errors, bl_errors, failing


def judge(repo: Path, wiki_dir: str, state_dir: Path, before: dict, spawn: Optional[SpawnResult], output_path: Path,
          checkpoint: Optional[str] = None, expected: Iterable[str] = (), consumers: bool = False,
          keep_partial: bool = True, log: Callable[[str], None] = lambda m: None) -> Verdict:
    """Success judgement (plan §2.2): never the exit code.

    1. working-tree diff confined to the wiki dir (+ the consumers instruction file) — else `aborted`
    2. `<git-dir>/wiki/verified` present and equal to the wiki tree hash; no `stop-gate-failed`; no timeout
    3. the model's final `WIKI-RUN-RESULT:` line
    4. index --write, lint --all [--base cp], backlinks --check clean; failing pages reverted when keep_partial
    5. expected pages exist (bootstrap)
    """
    v = Verdict()
    after = status_snapshot(repo)
    v.outside = outside_changes(before, after, wiki_dir, allowed=(CONSUMERS_REL,))
    v.changed = wiki_changes(before, after, wiki_dir)
    v.narrative = narrative_rels(v.changed)
    v.timed_out = bool(spawn and spawn.timed_out)
    v.verified, v.verified_match = verify_marker(state_dir, repo, wiki_dir)
    v.stop_gate_failed = (Path(state_dir) / "stop-gate-failed").exists()
    v.sentinel = parse_sentinel(read_output_tail(output_path))
    expected = list(expected)
    if v.outside:
        v.result = "aborted"
        v.reasons.append("files changed outside the wiki dir: " + ", ".join(v.outside[:10]))
        return v
    hard: list[str] = []
    if v.timed_out:
        hard.append("session timed out")
    if v.stop_gate_failed:
        hard.append("stop gate gave up after 3 attempts (stop-gate-failed)")
    if not v.verified:
        hard.append("no verified marker (stop gate never passed)")
    elif not v.verified_match:
        hard.append("wiki changed after the last stop-gate pass")
    if v.sentinel is None:
        hard.append("no WIKI-RUN-RESULT line")
    if hard and v.narrative:
        v.reverted = revert_paths(repo, wiki_dir, v.changed, before)
        v.result = "failed"
        v.reasons += hard
        run_script(repo, "index", "--write", *(["--consumers"] if consumers else []))
        return v
    if hard:
        v.result = "failed"
        v.reasons += hard
        return v
    lint_errors, bl_errors, failing = _quality(repo, wiki_dir, checkpoint, consumers, log)
    v.lint_errors, v.backlink_errors = lint_errors, bl_errors
    partial = False
    if failing:
        failing_narr = sorted(f for f in failing if f in v.narrative)
        others = sorted(f for f in failing if f not in v.narrative)
        if keep_partial and failing_narr and not others:
            for f in lint_errors + bl_errors:
                log(f"  finding: {f.get('file')}:{f.get('line') or 1} {f.get('rule') or ''} {f.get('message')}")
            v.reverted = revert_paths(repo, wiki_dir, failing_narr, before)
            v.reasons.append("reverted pages with findings: " + ", ".join(failing_narr))
            lint_errors, bl_errors, failing = _quality(repo, wiki_dir, checkpoint, consumers, log)
            v.lint_errors, v.backlink_errors = lint_errors, bl_errors
            partial = True
        if failing:
            for f in lint_errors + bl_errors:
                log(f"  finding: {f.get('file')}:{f.get('line') or 1} {f.get('rule') or ''} {f.get('message')}")
            v.reverted += revert_paths(repo, wiki_dir, [c for c in v.changed if c not in v.reverted], before)
            run_script(repo, "index", "--write", *(["--consumers"] if consumers else []))
            v.result = "failed"
            v.reasons.append(f"{len(lint_errors)} lint error(s), {len(bl_errors)} backlink error(s) remain")
            v.kept = []
            return v
    v.kept = [p for p in v.narrative if p not in v.reverted and (repo / wiki_dir / p).exists()]
    v.missing = [p for p in expected if not (repo / wiki_dir / p).exists()]
    status = v.sentinel["status"] if v.sentinel else "failed"
    if status == "deferred":
        v.result = "deferred"
        why = (v.sentinel or {}).get("raw", {}).get("reason") if v.sentinel else None
        v.reasons.append(f"model deferred: {why}" if why else "model reported deferred")
    elif v.missing:
        v.result = "partial" if v.kept else "failed"
        v.reasons.append("expected pages missing: " + ", ".join(v.missing))
    elif partial or v.reverted:
        v.result = "partial"
    elif status == "failed":
        v.result = "partial" if v.kept else "failed"
        v.reasons.append("model reported failed")
    elif not v.narrative and not expected:
        v.result = "noop"
        v.reasons.append("model changed no narrative page")
    else:
        v.result = "ok"
    return v


# ---------------------------------------------------------------- commit, metrics, misc

def commit_wiki(repo: Path, wiki_dir: str, message: str, run_id: str, extra_paths: Iterable[str] = (),
                retries: int = 5, env: Optional[dict] = None) -> Optional[str]:
    """`git add -- <wiki> [extra]` then a pathspec commit with the trailers. None when nothing to commit."""
    paths = [wiki_dir] + [p for p in extra_paths if (repo / p).exists()]
    last: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            gitio.add(paths, repo)
            if gitio.git_rc(["diff", "--cached", "--quiet", "--", *paths], repo) == 0:
                return None
            return gitio.commit(message, repo, trailers={TRAILER_UPDATE: "auto", TRAILER_RUN: run_id}, paths=paths, env=env)
        except gitio.GitError as e:
            last = e
            if "index.lock" in str(e) or "Unable to create" in str(e):
                time.sleep(2.0)
                continue
            raise
    assert last is not None
    raise last


def metrics(state_dir: Path, record: dict) -> None:
    try:
        p = Path(state_dir) / "metrics.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def rotate(path: Path, max_bytes: int = 1_000_000) -> None:
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass


def render_prompt(name: str, variables: Optional[dict] = None) -> str:
    """Prompt skeleton from prompts/<name> with {{placeholders}} substituted; leading HTML comments dropped."""
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    lines = text.split("\n")
    while lines and lines[0].strip().startswith("<!--") and lines[0].strip().endswith("-->"):
        lines.pop(0)
    text = "\n".join(lines).strip() + "\n"
    return wconfig.scaffold(text, variables or {})


def new_run_id(head: Optional[str], now) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{(head or '0000000')[:7]}"


def base_run(run_id: str, mode: str, cfg: wconfig.Config, head: Optional[str], checkpoint: Optional[str], now,
             model: Optional[str] = None, timeout_s: Optional[int] = None, **extra) -> dict:
    """A §8.7.4 run.json skeleton with `session_id: null`."""
    run = {
        "schema_version": 1, "run_id": run_id, "mode": mode, "session_id": None, "started": iso(now),
        "timeout_s": timeout_s, "model": model, "checkpoint": checkpoint, "head": head, "wiki_dir": cfg.wiki_dir,
        "cluster": None, "work": [], "may_create": [], "requests": [], "instruction": None, "untrusted_block": "",
        "budget": {"max_pages": int(cfg.get("max_pages") or 8),
                   "max_source_bytes": int(cfg.budget("max_source_bytes_per_run") or 200000),
                   "bytes_read": 0, "excerpt_lines_used": 0,
                   "max_excerpt_lines_per_run": int(cfg.budget("max_excerpt_lines_per_run") or 800)},
        "over_budget": False, "status": "running", "deferred_reason": None,
    }
    run.update(extra)
    return run
