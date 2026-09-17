#!/usr/bin/env python3
"""run.py — the headless wiki worker and the run-state manager for interactive skills (plan §8.6, §8.14).

CLI:
  run.py worker [--trigger post-commit|manual|pre-push] [--foreground] [--instruction TEXT] [--issue N]
                [--lift-cap] [--dry-run] [--model M] [--no-model]
  run.py begin --mode init|update|query|lint [--instruction TEXT] [--force] [--resume] [--replan]
  run.py status [--json]
  run.py prompt
  run.py defer --reason TEXT
  run.py end
  run.py bootstrap [--detach] [-- <bootstrap.py args>]

worker: guards in order (exit 0 silently unless --foreground): WIKI_RUN set · HEAD trailer `Wiki-Update` ·
post-commit and HEAD touches only the wiki dir · branch in branches.skip_runs_on · rebase/merge in progress ·
lock `<git-dir>/wiki/lock/` (pid + age < budgets.lock_ttl_min, stale locks reclaimed) · debounce · wiki dirty (exit 3).
Post-commit runs re-execute themselves detached (stdout → `<git-dir>/wiki/update.log`, 1 MB rotation).
Then: facts.py → index.py --write → manifest.py --touched → affected.py; noop ⇒ advance checkpoint + commit facts;
page cap exceeded ⇒ log Deferred; else run.json, prompts/update.md, the §8.14 command line under `run_timeout_s`,
judge (diff confined to the wiki, verified marker, sentinel, lint --all, backlinks --check), post-steps, commit
`docs(wiki): update N pages` with trailers `Wiki-Update: auto` and `Wiki-Run: <id>`, checkpoint advanced in that commit.
Exit codes: 0 ok/skipped · 3 lock held or wiki dirty (foreground) · 4 model/judge failure.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import budget as wbudget, cli, config as wconfig, frontmatter as wfm, gitio, runner  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "run"
MODES = ("init", "update", "query", "lint")
TRIGGERS = ("post-commit", "manual", "pre-push")


# ---------------------------------------------------------------- helpers

def instructions_customised(text: str) -> bool:
    """True when `wiki/instructions.md` no longer looks like the scaffold: section 1 has no `…` placeholder left."""
    try:
        _, body, _ = wfm.split(text)
    except wfm.FrontmatterError:
        body = text
    m = re.search(r"^## 1\. Identity and purpose[^\n]*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    if not m:
        return True
    sec = m.group(1)
    lines = [l.strip() for l in sec.splitlines() if l.strip() and not l.strip().startswith("<!--")]
    if not lines or any(not l.startswith(("- Canonical name of this system:", "- One paragraph:")) for l in lines):
        return True
    return "…" not in sec and "..." not in sec


def run_summary(run: dict) -> str:
    work = run.get("work") or []
    return (f"run {run.get('run_id')} · mode {run.get('mode')} · status {run.get('status')} · model {run.get('model') or '-'} · "
            f"{len(work)} page(s) · bytes_read {((run.get('budget') or {}).get('bytes_read') or 0)}"
            + (f" · cluster {run['cluster']}" if run.get("cluster") else "")
            + (" · OVER BUDGET" if run.get("over_budget") else ""))


class Base:
    def __init__(self, ctx: cli.Ctx, args):
        self.ctx = ctx
        self.args = args
        self.cfg = ctx.cfg
        self.repo: Path = ctx.repo
        self.wd: str = self.cfg.wiki_dir
        self.wiki: Path = ctx.wiki_dir
        self.state: Path = ctx.state_dir
        self.git_dir: Path = ctx.git_dir or (self.repo / ".git")
        self.lock = runner.Lock(self.state, float(self.cfg.budget("lock_ttl_min") or 60))

    def say(self, msg: str) -> None:
        self.ctx.emit.say(f"{NAME}: {msg}")

    def sh(self, name: str, *args, timeout: int = 900) -> runner.ScriptResult:
        return runner.run_script(self.repo, name, *args, timeout=timeout)

    def refresh_facts(self) -> bool:
        """facts.py → index.py --write --consumers → manifest.py --touched. Returns True when the wiki changed."""
        before = runner.status_snapshot(self.repo)
        r = self.sh("facts")
        if not r.ok:
            raise cli.ModelError(f"facts.py failed: {r.tail() or r.rc}")
        r = self.sh("index", "--write", "--consumers")
        if not r.ok:
            raise cli.ModelError(f"index.py failed: {r.tail() or r.rc}")
        r = self.sh("manifest", "--touched")
        if not r.ok:
            raise cli.ModelError(f"manifest.py failed: {r.tail() or r.rc}")
        after = runner.status_snapshot(self.repo)
        return bool(runner.wiki_changes(before, after, self.wd)) or (runner.CONSUMERS_REL in after and after.get(runner.CONSUMERS_REL) != before.get(runner.CONSUMERS_REL))

    def affected(self, run_id: str, instruction: Optional[str] = None, issue: Optional[int] = None,
                 lift_cap: bool = False) -> dict:
        ctx_json = self.state / "context.json"
        ctx_md = self.state / "context.md"
        args = ["--out", str(ctx_json), "--md", str(ctx_md), "--run-id", run_id]
        if instruction:
            args += ["--instruction", instruction]
        if issue:
            args += ["--issue", str(issue)]
        if lift_cap:
            args.append("--lift-cap")
        r = self.sh("affected", *args)
        if r.rc != 0 and r.data is None:
            raise cli.ModelError(f"affected.py failed: {r.tail() or r.rc}")
        try:
            data = json.loads(ctx_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = r.data or {}
        if not isinstance(data, dict) or "work" not in data:
            raise cli.ModelError(f"affected.py produced no work list: {r.tail()}")
        return data

    def run_from_affected(self, aff: dict, run_id: str, mode: str, model: Optional[str], timeout_s: Optional[int],
                          **extra) -> dict:
        b = aff.get("budget") or {}
        run = runner.base_run(run_id, mode, self.cfg, aff.get("head"), aff.get("checkpoint_commit"), self.ctx.now,
                              model=model, timeout_s=timeout_s)
        run.update({
            "work": aff.get("work") or [], "may_create": aff.get("may_create") or [],
            "requests": [{"id": r.get("n"), "text": r.get("text"), "user": r.get("user"), "date": r.get("date")}
                         for r in (aff.get("requests") or [])],
            "instruction": aff.get("instruction"), "untrusted_block": aff.get("untrusted_block") or "",
            "over_budget": bool(aff.get("over_budget")), "cap": aff.get("cap"), "order": aff.get("order") or [],
            "context_md": str(self.state / "context.md"), "context_json": str(self.state / "context.json"),
        })
        run["budget"].update({
            "max_pages": b.get("max_pages", run["budget"]["max_pages"]),
            "max_source_bytes": b.get("max_source_bytes", run["budget"]["max_source_bytes"]),
            "bytes_read": int(b.get("bytes_packed") or 0), "excerpt_lines_used": int(b.get("excerpt_lines_used") or 0),
            "max_excerpt_lines_per_run": b.get("max_excerpt_lines_per_run", run["budget"]["max_excerpt_lines_per_run"]),
            "bytes_packed": int(b.get("bytes_packed") or 0),
        })
        run.update(extra)
        return run

    def commit(self, message: str, run_id: str) -> Optional[str]:
        sha = runner.commit_wiki(self.repo, self.wd, message, run_id, extra_paths=(runner.CONSUMERS_REL,))
        if sha:
            self.say(f"committed {sha[:10]} {message}")
        return sha

    def advance_checkpoint(self) -> None:
        r = self.sh("manifest", "--touched", "--advance-checkpoint")
        if not r.ok:
            raise cli.ModelError(f"manifest.py --advance-checkpoint failed: {r.tail()}")

    def log_add(self, action: str, text: str, run_id: Optional[str] = None, page: Optional[str] = None) -> None:
        args = ["add", "--action", action, "--text", text]
        if run_id:
            args += ["--run-id", run_id]
        if page:
            args += ["--page", page]
        r = self.sh("log", *args)
        if not r.ok:
            self.say(f"log.py add failed: {r.tail()}")

    def finish_run(self, run: Optional[dict], status: str) -> None:
        if run is None:
            return
        run["status"] = status
        run["ended"] = cli.iso(cli.utcnow())
        try:
            (self.state / "run.last.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            wbudget.run_path(self.git_dir).unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- worker

class Worker(Base):
    def __init__(self, ctx: cli.Ctx, args):
        super().__init__(ctx, args)
        self.fg = bool(args.foreground)
        self.trigger = args.trigger or os.environ.get("WIKI_TRIGGER") or "manual"
        self.detached = False
        self.started_ts = time.monotonic()

    def skip(self, reason: str, code: int = 0) -> int:
        self.say(f"skipped: {reason}")
        self.outcome = {"result": "skipped", "reason": reason}
        return code if self.fg else 0

    def run(self) -> int:
        self.outcome: dict = {}
        rc = self._run()
        if self.ctx.emit.as_json and not self.ctx.emit.emitted and not self.detached:
            self.ctx.emit.emit(dict(self.outcome, exit=rc), ok=rc == 0)
        return rc

    def _run(self) -> int:
        if cli.env_flag("WIKI_RUN"):
            return self.skip("WIKI_RUN is set (nested inside a wiki session)")
        head = gitio.head(self.repo)
        if not head:
            return self.skip("repository has no commits")
        if self.trigger == "post-commit" and gitio.trailer("HEAD", runner.TRAILER_UPDATE, self.repo):
            return self.skip("HEAD is a wiki update commit (Wiki-Update trailer)")
        if self.trigger == "post-commit":
            files = gitio.diff_tree_files("HEAD", self.repo)
            if not files or all(f.startswith(self.wd + "/") or f == runner.CONSUMERS_REL for f in files):
                return self.skip("HEAD touches only the wiki")
        branch = gitio.current_branch(self.repo) or ""
        for pat in self.cfg.get("branches.skip_runs_on") or []:
            if branch and fnmatch.fnmatch(branch, str(pat)):
                return self.skip(f"branch {branch} matches skip_runs_on {pat}")
        if gitio.in_progress_rebase_or_merge(self.repo):
            return self.skip("rebase or merge in progress")
        if not (self.wiki / ".manifest.json").exists():
            return self.skip("wiki not bootstrapped (no .manifest.json); run /wiki-init first", cli.EXIT_ENV)
        inherited = os.environ.get("WIKI_DETACHED") == "1"
        if inherited:
            self.lock.inherit("worker")
        else:
            ok, info = self.lock.acquire("worker")
            if not ok:
                return self.skip(f"lock held by {self.lock.describe(info)}", cli.EXIT_ENV)
        try:
            if self.trigger == "post-commit" and not self.fg and not inherited:
                if self.debounced():
                    return self.skip("debounced (a run started less than debounce_s ago)")
            if gitio.status_porcelain(self.repo, [self.wd]):
                self.say(f"{self.wd}/ has uncommitted changes; commit or discard them first")
                self.outcome = {"result": "skipped", "reason": "wiki dirty"}
                return cli.EXIT_ENV
            if self.trigger == "post-commit" and not self.fg and not inherited:
                self.detach()
                return 0
            self.stamp_last_run()
            return self.execute(head, branch)
        finally:
            if not self.detached:
                self.lock.release()

    def debounced(self) -> bool:
        p = self.state / "last-run"
        try:
            last = float(p.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return False
        return (time.time() - last) < float(self.cfg.budget("debounce_s") or 0)

    def stamp_last_run(self) -> None:
        try:
            (self.state / "last-run").write_text(f"{time.time()}\n", encoding="utf-8")
        except OSError:
            pass

    def detach(self) -> None:
        log = self.state / "update.log"
        runner.rotate(log, 1_000_000)
        env = dict(os.environ)
        env["WIKI_DETACHED"] = "1"
        env["WIKI_HOOK_RUNNING"] = "1"
        argv = [sys.executable, str(Path(__file__).resolve()), "worker"] + [a for a in sys.argv[2:] if a != "worker"]
        with open(log, "ab") as out:
            kw: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "cwd": str(self.repo), "env": env, "close_fds": True}
            if os.name == "nt":  # pragma: no cover
                kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kw["start_new_session"] = True
            proc = subprocess.Popen(argv, **kw)
        self.detached = True
        self.say(f"detached worker pid {proc.pid} (log: {log})")

    def execute(self, head: str, branch: str) -> int:
        args = self.args
        now = self.ctx.now
        run_id = runner.new_run_id(head, now)
        self.say(f"run {run_id} on {branch or 'detached HEAD'} ({self.trigger})")
        if args.dry_run:
            aff = self.affected(run_id, args.instruction, args.issue, args.lift_cap)
            return self.dry_run(aff, run_id)
        changed = self.refresh_facts()
        model = args.model or str(self.cfg.get("models.incremental") or "")
        record = {"run_id": run_id, "mode": "update", "trigger": self.trigger, "model": model, "started": cli.iso(now),
                  "head": head, "branch": branch, "pages_written": 0, "bytes_read": None, "tokens": None}
        if args.no_model:
            self.advance_checkpoint()
            self.commit("docs(wiki): facts", run_id)
            self.say("no-model run: facts, index and manifest refreshed; checkpoint advanced")
            self.metrics(record, "no-model")
            return 0
        aff = self.affected(run_id, args.instruction, args.issue, args.lift_cap)
        cap = aff.get("cap") or {}
        if aff.get("noop"):
            self.advance_checkpoint()
            self.commit("docs(wiki): facts", run_id)
            self.say("nothing affected: checkpoint advanced, no model call")
            self.metrics(record, "noop")
            return 0
        deferred = cap.get("deferred") or []
        if deferred and not cap.get("lifted"):
            n = len(deferred) + int(cap.get("selected") or 0)
            self.log_add("Deferred", f"{n} pages affected, cap {cap.get('max_pages')}: run `python3 {runner.SCRIPTS_REL}/run.py worker --foreground --lift-cap`", run_id)
            self.commit("docs(wiki): facts", run_id)
            self.say(f"deferred: {n} pages exceed max_pages {cap.get('max_pages')}; run with --lift-cap by hand")
            self.metrics(record, "deferred-cap")
            return 0
        bin_path = runner.find_copilot(self.cfg, self.repo)
        if not bin_path:
            self.commit("docs(wiki): facts", run_id)
            self.metrics(record, "no-copilot")
            raise cli.ModelError("copilot CLI not found (WIKI_COPILOT_BIN, git config wiki.copilot, copilot.bin, PATH)")
        timeout_s = int(self.cfg.budget("run_timeout_s") or 1200)
        run = self.run_from_affected(aff, run_id, "update", model, timeout_s, trigger=self.trigger)
        runner.clear_markers(self.state)
        wbudget.save_run(self.git_dir, run)
        prompt = runner.render_prompt("update.md", wconfig.scaffold_vars(self.cfg, head=head, model=model, date=cli.iso(now)))
        share = self.state / "last-transcript.md"
        output = self.state / "last-output.txt"
        try:
            output.write_text("", encoding="utf-8")
        except OSError:
            pass
        argv = runner.build_argv(bin_path, prompt, model, self.wd, share)
        env = runner.cli_env("update", run_id)
        before = runner.status_snapshot(self.repo)
        self.say(f"spawning {Path(bin_path).name} --model {model} (timeout {timeout_s}s, {len(run['work'])} page(s))")
        sp = runner.spawn_cli(argv, self.repo, env, timeout_s, output, pid_file=self.state / "copilot.pid")
        record.update({"cli_rc": sp.rc, "cli_duration_s": sp.duration_s, "timed_out": sp.timed_out, "pid": sp.pid})
        self.say(f"cli exited rc={sp.rc} after {sp.duration_s}s" + (" (TIMED OUT, process group killed)" if sp.timed_out else ""))
        v = runner.judge(self.repo, self.wd, self.state, before, sp, output, checkpoint=aff.get("checkpoint_commit"),
                         consumers=True, keep_partial=True, log=self.say)
        self.say(f"judge: {v.summary()}")
        run_now = wbudget.load_run(self.git_dir) or run
        record["bytes_read"] = (run_now.get("budget") or {}).get("bytes_read")
        rc = self.settle(v, run_now, run_id, model, head, branch, sp, record)
        self.finish_run(run_now, v.result)
        return rc

    def settle(self, v: runner.Verdict, run: dict, run_id: str, model: str, head0: str, branch0: str,
               sp: runner.SpawnResult, record: dict) -> int:
        if v.result == "aborted":
            runner.revert_wiki(self.repo, self.wd)
            self.say("ABORTED: the session changed files outside the wiki dir: " + ", ".join(v.outside)
                     + " — nothing committed; the wiki dir was reset to HEAD; inspect and revert those files yourself")
            self.metrics(record, "aborted")
            return cli.EXIT_MODEL
        if gitio.head(self.repo) != head0 or (gitio.current_branch(self.repo) or "") != branch0:
            self.say("HEAD or branch changed during the run; wiki changes left uncommitted in the working tree")
            self.metrics(record, "branch-changed")
            return cli.EXIT_MODEL
        sentinel = v.sentinel or {}
        pages = list(v.kept)
        n_written = len(pages)
        duration = int(time.monotonic() - self.started_ts)
        if v.ok and pages:
            result = "ok" if v.result == "ok" else v.result
            r = self.sh("manifest", "--touched", "--run-id", run_id, "--model", model, "--mode", "incremental",
                        "--result", result, "--duration", str(duration), "--pages-written", str(n_written))
            if not r.ok:
                self.say(f"manifest.py --touched failed: {r.tail()}")
            for n in sentinel.get("requests_done") or []:
                rr = self.sh("requests", "--close", str(n), "--run-id", run_id, "--result", pages[0])
                if not rr.ok:
                    self.say(f"requests.py --close {n}: {rr.tail()}")
            created = [p for p in pages if p in set(sentinel.get("created") or [])]
            updated = [p for p in pages if p not in created]
            text = f"{len(updated)} updated, {len(created)} created"
            if updated:
                text += ": " + ", ".join(updated[:8])
            if created:
                text += "; new: " + ", ".join(created[:8])
            if v.reverted:
                text += f"; reverted (findings): {', '.join(v.reverted[:5])}"
            if result == "deferred":
                text += "; deferred: " + "; ".join(v.reasons)[:200]
            self.log_add("Update", text, run_id)
            self.sh("log", "rotate")
            final = self.sh("lint", "--all")
            if final.data is not None and (final.data.get("errors") or []):
                self.say("final lint --all found errors after the post-steps; reverting the run")
                for f in final.data["errors"][:10]:
                    self.say(f"  {f.get('file')}:{f.get('line') or 1} {f.get('rule')} {f.get('message')}")
                runner.revert_wiki(self.repo, self.wd)
                self.metrics(record, "failed")
                return cli.EXIT_MODEL
            if result == "ok":
                self.advance_checkpoint()
            suffix = "" if result == "ok" else f" ({result})"
            message = f"docs(wiki): update {n_written} page{'s' if n_written != 1 else ''}{suffix}"
            if str(self.cfg.get("commit_policy") or "commit") == "branch-and-mr":
                sha = self.commit_branch_and_mr(message, run_id, v.changed)
            else:
                sha = self.commit(message, run_id)
            record.update({"pages_written": n_written, "commit": sha, "result": result})
            self.metrics(record, result)
            self.issue_note(f"wiki run {run_id}: {result}, {text}" + (f" (commit {sha[:10]})" if sha else ""))
            self.say(f"done: {result}, {n_written} page(s)" + (f", commit {sha[:10]}" if sha else ""))
            return 0
        # nothing usable came back
        if v.result == "noop" or (v.ok and not pages):
            reason = "the model changed no narrative page although the work list was not empty"
            self.say(reason + "; checkpoint not advanced")
            self.log_add("Deferred", f"run produced no page changes ({len(run.get('work') or [])} pages on the work list); pages stay stale", run_id)
        else:
            reason = "; ".join(v.reasons) or "judge failed"
            self.say(f"FAILED: {reason}; narrative changes reverted, checkpoint not advanced")
            self.log_add("Deferred", f"run failed: {reason[:300]}", run_id)
        self.sh("log", "rotate")
        self.commit("docs(wiki): facts", run_id)
        self.metrics(record, "failed" if v.result != "noop" else "noop-model")
        self.issue_note(f"wiki run {run_id}: failed — {reason}")
        return cli.EXIT_MODEL if v.result != "noop" else 0

    def commit_branch_and_mr(self, message: str, run_id: str, changed: list[str]) -> Optional[str]:
        """isolation: worktree — commit the wiki changes on `wiki/update-<id>` in a temporary worktree, push, open an MR."""
        branch = f"wiki/update-{run_id}"
        wt = Path(tempfile.mkdtemp(prefix="wiki-wt-"))
        sha: Optional[str] = None
        try:
            gitio.worktree_remove(wt, self.repo)
            gitio.worktree_add(wt, "HEAD", self.repo, branch=branch)
            for rel in changed + [runner.CONSUMERS_REL]:
                src = self.repo / (f"{self.wd}/{rel}" if rel != runner.CONSUMERS_REL else rel)
                dst = wt / (f"{self.wd}/{rel}" if rel != runner.CONSUMERS_REL else rel)
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                elif dst.exists():
                    dst.unlink()
            sha = runner.commit_wiki(wt, self.wd, message, run_id, extra_paths=(runner.CONSUMERS_REL,))
            if sha:
                self.say(f"committed {sha[:10]} on {branch}")
                push = subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(wt), capture_output=True, text=True,
                                      env={**os.environ, "WIKI_HOOK_RUNNING": "1", "GIT_TERMINAL_PROMPT": "0"})
                if push.returncode != 0:
                    self.say(f"push failed ({push.stderr.strip()[:200]}); branch {branch} exists locally")
                elif shutil.which("glab"):
                    mr = subprocess.run(["glab", "mr", "create", "--fill", "--label", "wiki", "--yes", "--source-branch", branch],
                                        cwd=str(wt), capture_output=True, text=True)
                    self.say("glab mr create: " + (mr.stdout.strip().splitlines()[-1] if mr.returncode == 0 and mr.stdout.strip() else f"failed ({mr.stderr.strip()[:200]})"))
                else:
                    self.say("glab not installed: open the merge request for branch " + branch + " by hand")
        finally:
            gitio.worktree_remove(wt, self.repo)
            shutil.rmtree(wt, ignore_errors=True)
            runner.revert_wiki(self.repo, self.wd)
            gitio.git_rc(["checkout", "-q", "HEAD", "--", runner.CONSUMERS_REL], self.repo)
        return sha

    def issue_note(self, text: str) -> None:
        n = getattr(self.args, "issue", None)
        if not n:
            return
        if not shutil.which("glab"):
            self.say(f"--issue {n}: glab not installed; note not posted")
            return
        try:
            subprocess.run(["glab", "issue", "note", str(n), "-m", text], cwd=str(self.repo), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            self.say(f"glab issue note failed: {e}")

    def metrics(self, record: dict, result: str) -> None:
        record = dict(record)
        record["result"] = result
        record["duration_s"] = round(time.monotonic() - self.started_ts, 3)
        runner.metrics(self.state, record)
        self.outcome = {k: record.get(k) for k in ("run_id", "result", "pages_written", "commit", "timed_out", "duration_s") if k in record}

    def dry_run(self, aff: dict, run_id: str) -> int:
        cap = aff.get("cap") or {}
        model = self.args.model or str(self.cfg.get("models.incremental") or "")
        bin_path = runner.find_copilot(self.cfg, self.repo) or "copilot"
        prompt = runner.render_prompt("update.md", wconfig.scaffold_vars(self.cfg, model=model))
        argv = runner.build_argv(bin_path, prompt, model, self.wd, self.state / "last-transcript.md")
        lines = [f"dry run {run_id}: noop={aff.get('noop')} selected={cap.get('selected')} deferred={len(cap.get('deferred') or [])} lifted={cap.get('lifted')}"]
        for w in aff.get("work") or []:
            lines.append(f"  {w.get('path')} ({w.get('type')}, {w.get('action')}, {w.get('budget_bytes')} bytes)")
        env = runner.cli_env("update", run_id)
        lines.append("command: " + " ".join(f"{k}={env[k]}" for k in ("WIKI_RUN", "WIKI_WORKER", "WIKI_PHASE", "COPILOT_AUTO_UPDATE", "WIKI_RUN_ID"))
                     + f" timeout {self.cfg.budget('run_timeout_s')}s " + " ".join(_q(a) for a in argv))
        text = "\n".join(lines)
        if self.ctx.emit.as_json:
            self.ctx.emit.emit({"run_id": run_id, "noop": aff.get("noop"), "cap": cap, "work": aff.get("work"), "argv": argv, "env": {k: env[k] for k in ("WIKI_RUN", "WIKI_WORKER", "WIKI_PHASE", "COPILOT_AUTO_UPDATE", "WIKI_RUN_ID")}})
        else:
            print(text)
        return 0


def _q(a: str) -> str:
    if len(a) > 80:
        a = a[:77] + "…"
    return json.dumps(a) if re.search(r"[\s'\"()*]", a) else a


# ---------------------------------------------------------------- interactive run state

class Manager(Base):
    def begin(self) -> int:
        args = self.args
        mode = args.mode
        if mode not in MODES:
            raise cli.ConfigError(f"--mode must be one of {', '.join(MODES)}")
        head = gitio.head(self.repo)
        existing = wbudget.load_run(self.git_dir)
        if existing and existing.get("status") == "running" and not args.force and existing.get("session_id"):
            self.say(f"replacing the previous run {existing.get('run_id')} ({existing.get('mode')})")
        ok, info = self.lock.acquire("interactive", pid=None, force=bool(args.force))
        if not ok and info is not None and info.get("kind") == "interactive":
            self.say(f"reclaiming the previous interactive lock ({self.lock.describe(info)})")
            ok, info = self.lock.acquire("interactive", pid=None, force=True)
        if not ok:
            raise cli.EnvError(f"another wiki run holds the lock ({self.lock.describe(info)}); wait, or `run.py end`, or --force")
        try:
            run_id = runner.new_run_id(head, self.ctx.now)
            if mode == "init":
                instr = self.wiki / "instructions.md"
                if instr.exists() and instructions_customised(instr.read_text(encoding="utf-8")) and not (args.resume or args.replan):
                    raise cli.EnvError(f"{self.wd}/instructions.md is already customised: the wiki was initialised. "
                                       "Use `/wiki-init --resume` or `--replan` to continue, or `/wiki-update` for changes.")
                run = runner.base_run(run_id, "init", self.cfg, head, None, self.ctx.now, model=str(self.cfg.get("models.bootstrap") or ""),
                                      resume=bool(args.resume), replan=bool(args.replan))
            elif mode == "update":
                if not (self.wiki / ".manifest.json").exists():
                    raise cli.EnvError("wiki not bootstrapped (no .manifest.json); run /wiki-init first")
                if gitio.status_porcelain(self.repo, [self.wd]) and not args.force:
                    raise cli.EnvError(f"{self.wd}/ has uncommitted changes; commit or stash them first (or --force)")
                self.refresh_facts()
                aff = self.affected(run_id, args.instruction, None, bool(args.force))
                run = self.run_from_affected(aff, run_id, "update", str(self.cfg.get("models.incremental") or ""), None,
                                             trigger="interactive", instruction=args.instruction or aff.get("instruction"))
            else:
                man = {}
                try:
                    man = json.loads((self.wiki / ".manifest.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                run = runner.base_run(run_id, mode, self.cfg, head, man.get("checkpoint_commit"), self.ctx.now,
                                      model=str(self.cfg.get("models.incremental") or ""), instruction=args.instruction)
            run["lock"] = "interactive"
            wbudget.save_run(self.git_dir, run)
        except Exception:
            self.lock.release()
            raise
        self.say(run_summary(run))
        self.ctx.emit.emit({"run_id": run["run_id"], "mode": mode, "work": len(run.get("work") or []),
                            "over_budget": bool(run.get("over_budget")), "run_json": str(wbudget.run_path(self.git_dir))})
        return 0

    def status(self) -> int:
        run = wbudget.load_run(self.git_dir)
        if run is None:
            last = self.state / "run.last.json"
            hint = f"; last run: {last}" if last.exists() else ""
            raise cli.EnvError(f"no active run (no {wbudget.run_path(self.git_dir)}){hint}; `run.py begin --mode …` first")
        if self.ctx.emit.as_json:
            self.ctx.emit.emit(dict(run))
        else:
            print(run_summary(run))
            for i, w in enumerate(run.get("work") or [], 1):
                print(f"  {i}. {w.get('path')} ({w.get('type')}, {w.get('action')}, {w.get('budget_bytes', 0)} bytes)")
        return 0

    def prompt(self) -> int:
        run = wbudget.load_run(self.git_dir) or {}
        mode = run.get("mode") or "update"
        head = run.get("head") or gitio.head(self.repo) or ""
        variables = wconfig.scaffold_vars(self.cfg, head=head, model=str(run.get("model") or ""), date=cli.iso(self.ctx.now))
        if mode == "page" and run.get("cluster"):
            variables["cluster_id"] = run["cluster"]
            text = runner.render_prompt("bootstrap.md", variables)
        elif mode == "update":
            text = runner.render_prompt("update.md", variables)
        else:
            text = f"/wiki-{mode}\nRun the wiki-{mode} skill. Mode: {mode}. Run context: `python3 {runner.SCRIPTS_REL}/run.py status --json`.\n"
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return 0

    def defer(self) -> int:
        run = wbudget.load_run(self.git_dir)
        if run is None:
            raise cli.EnvError("no active run to defer")
        reason = str(self.args.reason or "").strip() or "budget exhausted"
        run["status"] = "deferred"
        run["deferred_reason"] = reason
        run["over_budget"] = True
        wbudget.save_run(self.git_dir, run)
        self.log_add("Deferred", f"{run.get('mode')} run deferred: {reason}", run.get("run_id"))
        self.say(f"run {run.get('run_id')} deferred: {reason}")
        self.ctx.emit.emit({"run_id": run.get("run_id"), "status": "deferred", "reason": reason})
        return 0

    def end(self) -> int:
        run = wbudget.load_run(self.git_dir)
        status = "ended"
        if run is not None:
            if run.get("status") == "deferred":
                status = "deferred"
            self.finish_run(run, status)
        info = self.lock.read()
        if info is not None and (info.get("kind") == "interactive" or info.get("pid") in (None, os.getpid()) or self.lock.is_stale(info)):
            self.lock.release(force=True)
        self.say("run ended" + (f" ({run.get('run_id')}, {status})" if run else " (no active run)"))
        self.ctx.emit.emit({"run_id": run.get("run_id") if run else None, "status": status})
        return 0

    def bootstrap(self) -> int:
        script = Path(__file__).resolve().parent / "bootstrap.py"
        extra = list(getattr(self.args, "extra", None) or [])
        ttl = int(float(self.cfg.budget("lock_ttl_min") or 60) * 60)
        argv = [sys.executable, str(script), "--resume", "--wait-lock", str(ttl), *extra]
        if not self.args.detach:
            return subprocess.call(argv, cwd=str(self.repo))
        log = self.state / "bootstrap.log"
        runner.rotate(log, 1_000_000)
        env = dict(os.environ)
        env.pop("WIKI_RUN", None)
        env["WIKI_HOOK_RUNNING"] = "1"
        with open(log, "ab") as out:
            kw: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "cwd": str(self.repo), "env": env, "close_fds": True}
            if os.name == "nt":  # pragma: no cover
                kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kw["start_new_session"] = True
            proc = subprocess.Popen(argv, **kw)
        self.say(f"bootstrap driver started (pid {proc.pid}); it waits for the session lock, then runs cluster by cluster; log: {log}")
        self.ctx.emit.emit({"pid": proc.pid, "log": str(log), "argv": argv})
        return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    sub = cli.subparsers(p)
    w = sub.add_parser("worker", help="headless run (hooks and humans)")
    w.add_argument("--trigger", choices=TRIGGERS, default=None)
    w.add_argument("--foreground", action="store_true", help="run in this process; guard skips exit non-zero")
    w.add_argument("--instruction", default=None)
    w.add_argument("--issue", type=int, default=None, help="GitLab issue number (glab)")
    w.add_argument("--lift-cap", action="store_true")
    w.add_argument("--dry-run", action="store_true", help="print the work list and the command line; spawn nothing")
    w.add_argument("--model", default=None)
    w.add_argument("--no-model", action="store_true", help="facts + index + manifest only")
    b = sub.add_parser("begin", help="start an interactive run (writes run.json)")
    b.add_argument("--mode", choices=MODES, required=True)
    b.add_argument("--instruction", default=None)
    b.add_argument("--force", action="store_true", help="lift the page cap, tolerate a dirty wiki, reclaim the lock")
    b.add_argument("--resume", action="store_true")
    b.add_argument("--replan", action="store_true")
    sub.add_parser("status", help="print run.json")
    sub.add_parser("prompt", help="print the rendered prompt skeleton for the current run")
    d = sub.add_parser("defer", help="mark the run deferred")
    d.add_argument("--reason", required=True)
    sub.add_parser("end", help="end the interactive run and release the lock")
    bs = sub.add_parser("bootstrap", help="run bootstrap.py (after the session lock is released)")
    bs.add_argument("--detach", action="store_true")
    bs.add_argument("extra", nargs="*", help="extra bootstrap.py arguments")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if ctx.wiki_dir is None or not ctx.wiki_dir.is_dir():
        raise cli.EnvError(f"wiki directory missing: {ctx.wiki_dir}")
    cmd = args.cmd
    if cmd == "worker":
        return Worker(ctx, args).run()
    m = Manager(ctx, args)
    return {"begin": m.begin, "status": m.status, "prompt": m.prompt, "defer": m.defer, "end": m.end, "bootstrap": m.bootstrap}[cmd]()


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
