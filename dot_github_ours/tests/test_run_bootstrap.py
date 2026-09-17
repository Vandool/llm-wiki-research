"""run.py / bootstrap.py with the fake copilot (plan §10 a): guards (trailer, wiki-only commit, lock, dirty wiki,
skip_runs_on), success commits with both trailers touching only wiki/, outside writes abort, noop advances the
checkpoint without a model call, a hung CLI is killed with its process group, cap/lift-cap, --no-model, --dry-run,
begin/status/prompt/defer/end, bootstrap --dry-run, a two-cluster plan end to end, --resume, --only, split, failures."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from conftest import FAKE_COPILOT, TempDir, commit_all, git, git_out, install_kit, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401

SCRIPTS_REL = ".github/skills/wiki-maintain/scripts"
CONSUMERS_REL = ".github/instructions/wiki-consumers.instructions.md"


def page(rel: str, title: str, head: str, source: str = "src/orders/service.py") -> str:
    return (f"---\ntype: Module\nid: sample/{rel[:-3]}\nschema_version: 1\ntitle: {title}\ndescription: {title}.\n"
            f"audience: [agent, dev]\nowner: agent\nsources:\n  - {{ id: svc, resource: \"repo://{source}\" }}\n"
            f"last_verified_commit: {head}\ngenerated: {{ by: \"copilot-cli/test\", at: 2026-09-07T10:00:00Z }}\nstatus: draft\n---\n"
            f"# {title}\n**Read this when:** you change `{source}`.[^svc]\n\n**Does:** keeps orders. **Exposes:** a service.\n\n"
            f"## Structure\n| Component | Path | Responsibility |\n|---|---|---|\n| svc | `{source}` | state machine |\n\n[^svc]: `{source}`\n")


def bootstrapped_repo(tmp: Path, config: dict | None = None, name: str = "repo") -> Path:
    """Installed kit + one narrative page citing src/orders/service.py + facts/index/manifest, committed clean."""
    repo = make_repo(tmp, name=name)
    cfg = {"repo": {"slug": "group/sample", "id_prefix": "sample"}, "sources": {"include": ["src", "web"]},
           "api_spec": {"openapi": ["api/openapi.json"], "asyncapi": ["api/asyncapi.json"]}}
    for k, v in (config or {}).items():
        cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    write_json(repo / ".github/wiki.config.json", cfg)
    r = install_kit(repo, "--hooks", "none")
    assert r.returncode == 0, r.stdout + r.stderr
    head = git_out(repo, "rev-parse", "HEAD")
    write(repo / "wiki/modules/orders.md", page("modules/orders.md", "Orders service", head))
    ov = repo / "wiki/overview.md"
    write(ov, read(ov) + "\n- [Orders service](modules/orders.md)\n")
    scripts = repo / SCRIPTS_REL
    for args in (("facts",), ("index", "--write"), ("manifest", "--init")):
        res = run_script(args[0], *args[1:], cwd=repo, scripts=scripts)
        assert res.returncode == 0, res.stderr
    commit_all(repo, "wiki: install")
    for args in (("facts",), ("index", "--write"), ("manifest", "--touched")):
        run_script(args[0], *args[1:], cwd=repo, scripts=scripts)
    commit_all(repo, "wiki: facts")
    return repo


def code_change(repo: Path, tag: str) -> str:
    p = repo / "src/orders/service.py"
    write(p, read(p) + f"\n# change {tag}\n")
    return commit_all(repo, f"feat: change {tag}")


class Harness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDir("wikikit-run-")
        self.root = self.tmp.__enter__()
        self.fake_log = self.root / "fake.log"

    def tearDown(self) -> None:
        self.tmp.__exit__(None, None, None)

    def fake_env(self, mode: str = "writes-page", **extra) -> dict:
        e = {"WIKI_COPILOT_BIN": str(FAKE_COPILOT), "FAKE_MODE": mode, "FAKE_LOG": str(self.fake_log), "WIKI_RUN": ""}
        e.update(extra)
        return e

    def worker(self, repo: Path, *args: str, mode: str = "writes-page", env: dict | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
        e = self.fake_env(mode)
        if env:
            e.update(env)
        return run_script("run", "worker", "--foreground", *args, cwd=repo, scripts=repo / SCRIPTS_REL, env=e, timeout=timeout)

    def runpy(self, repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return run_script("run", *args, cwd=repo, scripts=repo / SCRIPTS_REL, env={**self.fake_env(), **(env or {})})

    def spawns(self) -> list[dict]:
        if not self.fake_log.exists():
            return []
        return [json.loads(l) for l in read(self.fake_log).splitlines() if l.strip()]

    def head_files(self, repo: Path) -> list[str]:
        return [l for l in git_out(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() if l]

    def manifest(self, repo: Path) -> dict:
        return read_json(repo / "wiki/.manifest.json")

    def wiki_clean(self, repo: Path) -> bool:
        return git_out(repo, "status", "--porcelain", "--", "wiki") == ""

    def metrics(self, repo: Path) -> list[dict]:
        p = repo / ".git/wiki/metrics.jsonl"
        return [json.loads(l) for l in read(p).splitlines() if l.strip()] if p.exists() else []


class WorkerGuardTests(Harness):
    def test_guards_in_order(self):
        repo = bootstrapped_repo(self.root)
        r = self.worker(repo, env={"WIKI_RUN": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("skipped: WIKI_RUN is set", r.stderr)
        # post-commit trigger: HEAD with the trailer, HEAD touching only the wiki
        git(repo, "commit", "-q", "--allow-empty", "-m", "docs(wiki): update\n\nWiki-Update: auto")
        r = self.worker(repo, "--trigger", "post-commit")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Wiki-Update trailer", r.stderr)
        write(repo / "wiki/glossary.md", read(repo / "wiki/glossary.md") + "\nterm.\n")
        commit_all(repo, "docs: glossary by hand")
        r = self.worker(repo, "--trigger", "post-commit")
        self.assertEqual(r.returncode, 0)
        self.assertIn("touches only the wiki", r.stderr)
        # lock held by a live process → 3 in the foreground; a dead pid is reclaimed (the run itself is a noop)
        lock = repo / ".git/wiki/lock"
        lock.mkdir(parents=True)
        write(lock / "info.json", json.dumps({"pid": os.getpid(), "kind": "worker", "started": "now", "started_ts": time.time()}))
        r = self.worker(repo)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("lock held", r.stderr)
        self.assertEqual(self.spawns(), [])
        write(lock / "info.json", json.dumps({"pid": 2 ** 22 + 12345, "kind": "worker", "started": "old", "started_ts": time.time()}))
        r = self.worker(repo, mode="noop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("lock held", r.stderr)
        self.assertFalse(lock.exists(), "lock released after the run")
        self.assertEqual(self.spawns(), [])
        code_change(repo, "g")
        # dirty wiki → 3
        write(repo / "wiki/overview.md", read(repo / "wiki/overview.md") + "dirty\n")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 3)
        self.assertIn("uncommitted changes", r.stderr)
        git(repo, "checkout", "-q", "--", "wiki")
        # skip_runs_on
        git(repo, "checkout", "-q", "-b", "renovate/dep")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 0)
        self.assertIn("skip_runs_on", r.stderr)
        git(repo, "checkout", "-q", "main")
        # not bootstrapped
        (repo / "wiki/.manifest.json").unlink()
        commit_all(repo, "drop manifest")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 3)
        self.assertIn("not bootstrapped", r.stderr)


class WorkerRunTests(Harness):
    def test_success_commits_with_trailers_touching_only_the_wiki(self):
        repo = bootstrapped_repo(self.root)
        code = code_change(repo, "a")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): update 1 page")
        body = git_out(repo, "log", "-1", "--format=%B")
        self.assertIn("Wiki-Update: auto", body)
        self.assertRegex(body, r"Wiki-Run: \d{8}T\d{6}Z-[0-9a-f]{7}")
        files = self.head_files(repo)
        self.assertTrue(files)
        self.assertTrue(all(f.startswith("wiki/") or f == CONSUMERS_REL for f in files), files)
        self.assertIn("wiki/modules/orders.md", files)
        self.assertIn("wiki/.manifest.json", files)
        self.assertTrue(self.wiki_clean(repo))
        m = self.manifest(repo)
        self.assertEqual(m["checkpoint_commit"], code, "checkpoint = the code commit the run processed")
        self.assertEqual(m["last_run"]["result"], "ok")
        self.assertEqual(m["last_run"]["pages_written"], 1)
        self.assertEqual(m["last_run"]["model"], "gpt-5-mini")
        self.assertIn("Updated by the fake copilot", read(repo / "wiki/modules/orders.md"))
        self.assertIn("* **Update**: 1 updated, 0 created: modules/orders.md", read(repo / "wiki/log.md"))
        spawns = self.spawns()
        self.assertEqual(len(spawns), 1)
        argv, env = spawns[0]["argv"], spawns[0]["env"]
        self.assertEqual(argv[0], "-p")
        self.assertIn("/wiki-update", argv[1])
        for flag in ("--agent", "wiki-maintainer", "--model", "gpt-5-mini", "-s", "--no-ask-user", "--add-dir", "wiki", "--share"):
            self.assertIn(flag, argv)
        self.assertIn("shell(python3:*)", argv)
        self.assertEqual(argv[argv.index("--deny-tool") + 1], "shell(git push:*)")
        self.assertIn("web", argv)
        self.assertEqual(env["WIKI_RUN"], "1")
        self.assertEqual(env["WIKI_WORKER"], "1")
        self.assertEqual(env["WIKI_PHASE"], "update")
        self.assertTrue(env["WIKI_RUN_ID"].endswith(code[:7]))
        state = repo / ".git/wiki"
        self.assertFalse((state / "run.json").exists())
        self.assertFalse((state / "lock").exists())
        self.assertTrue((state / "last-output.txt").exists())
        self.assertIn("WIKI-RUN-RESULT:", read(state / "last-output.txt"))
        self.assertTrue((state / "context.md").exists())
        rec = self.metrics(repo)[-1]
        self.assertEqual(rec["result"], "ok")
        self.assertEqual(rec["pages_written"], 1)
        self.assertIsNone(rec["tokens"])
        self.assertFalse(rec["timed_out"])
        self.assertEqual(run_script("backlinks", "--check", cwd=repo, scripts=repo / SCRIPTS_REL).returncode, 0)
        # the update commit is not a trigger: a post-commit run on it skips
        r = self.worker(repo, "--trigger", "post-commit")
        self.assertIn("Wiki-Update trailer", r.stderr)
        self.assertEqual(len(self.spawns()), 1)

    def test_noop_advances_the_checkpoint_without_a_model_call(self):
        repo = bootstrapped_repo(self.root)
        head = git_out(repo, "rev-parse", "HEAD")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing affected", r.stderr)
        self.assertEqual(self.spawns(), [])
        self.assertEqual(self.manifest(repo)["checkpoint_commit"], head)
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): facts")
        self.assertIn("Wiki-Update: auto", git_out(repo, "log", "-1", "--format=%B"))
        self.assertTrue(all(f.startswith("wiki/") or f == CONSUMERS_REL for f in self.head_files(repo)))
        self.assertTrue(self.wiki_clean(repo))
        self.assertEqual(self.metrics(repo)[-1]["result"], "noop")

    def test_writes_outside_abort_without_committing(self):
        repo = bootstrapped_repo(self.root)
        code = code_change(repo, "o")
        r = self.worker(repo, mode="writes-outside")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("ABORTED", r.stderr)
        self.assertIn("README.md", r.stderr)
        self.assertEqual(git_out(repo, "rev-parse", "HEAD"), code, "nothing committed")
        self.assertTrue(self.wiki_clean(repo), "the wiki dir was reset")
        self.assertEqual(git_out(repo, "status", "--porcelain", "--", "README.md").strip(), "M README.md", "outside files are left for a human")
        self.assertNotEqual(self.manifest(repo)["checkpoint_commit"], code)
        self.assertEqual(self.metrics(repo)[-1]["result"], "aborted")

    def test_hung_cli_is_killed_with_its_process_group(self):
        repo = bootstrapped_repo(self.root, {"budgets": {"run_timeout_s": 3}})
        code = code_change(repo, "h")
        t0 = time.monotonic()
        r = self.worker(repo, mode="hangs", timeout=40)
        self.assertLess(time.monotonic() - t0, 20)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("TIMED OUT", r.stderr)
        pid = int(read(repo / ".git/wiki/copilot.pid").strip())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertTrue(self.wiki_clean(repo))
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): facts", "facts committed, narrative reverted")
        self.assertNotEqual(self.manifest(repo)["checkpoint_commit"], code)
        rec = self.metrics(repo)[-1]
        self.assertTrue(rec["timed_out"])
        self.assertEqual(rec["result"], "failed")
        self.assertIn("* **Deferred**: run failed", read(repo / "wiki/log.md"))
        self.assertFalse((repo / ".git/wiki/lock").exists())

    def test_failed_cli_without_sentinel_keeps_nothing(self):
        repo = bootstrapped_repo(self.root)
        code = code_change(repo, "f")
        r = self.worker(repo, mode="fails")
        self.assertEqual(r.returncode, 4)
        self.assertIn("no WIKI-RUN-RESULT line", r.stderr)
        self.assertTrue(self.wiki_clean(repo))
        self.assertNotEqual(self.manifest(repo)["checkpoint_commit"], code)
        self.assertNotIn("Updated by the fake copilot", read(repo / "wiki/modules/orders.md"))

    def test_page_cap_defers_and_lift_cap_runs(self):
        repo = bootstrapped_repo(self.root, {"max_pages": 1})
        head = git_out(repo, "rev-parse", "HEAD")
        write(repo / "wiki/modules/payments.md", page("modules/payments.md", "Payments", head, "src/orders/service.py"))
        ov = repo / "wiki/overview.md"
        write(ov, read(ov) + "- [Payments](modules/payments.md)\n")
        scripts = repo / SCRIPTS_REL
        run_script("index", "--write", cwd=repo, scripts=scripts)
        run_script("manifest", "--touched", cwd=repo, scripts=scripts)
        commit_all(repo, "wiki: second page")
        code = code_change(repo, "c")
        r = self.worker(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deferred: 2 pages exceed max_pages 1", r.stderr)
        self.assertEqual(self.spawns(), [])
        self.assertIn("* **Deferred**: 2 pages affected, cap 1", read(repo / "wiki/log.md"))
        self.assertNotEqual(self.manifest(repo)["checkpoint_commit"], code)
        self.assertTrue(self.wiki_clean(repo))
        r = self.worker(repo, "--lift-cap")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.spawns()), 1)
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): update 2 pages")
        self.assertEqual(self.manifest(repo)["checkpoint_commit"], git_out(repo, "rev-parse", "HEAD~1"), "checkpoint = HEAD before the update commit (the facts commit of the deferred run)")
        self.assertTrue(git_out(repo, "merge-base", "--is-ancestor", code, "HEAD~1") == "")

    def test_no_model_and_dry_run(self):
        repo = bootstrapped_repo(self.root)
        code = code_change(repo, "n")
        r = self.worker(repo, "--no-model")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.spawns(), [])
        self.assertEqual(self.manifest(repo)["checkpoint_commit"], code)
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): facts")
        code2 = code_change(repo, "d")
        r = self.worker(repo, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("modules/orders.md (Module, update", r.stdout)
        self.assertIn("command: WIKI_RUN=1 WIKI_WORKER=1 WIKI_PHASE=update COPILOT_AUTO_UPDATE=false", r.stdout)
        self.assertIn("fake_copilot.py", r.stdout)
        self.assertIn("--no-ask-user", r.stdout)
        self.assertEqual(self.spawns(), [])
        self.assertEqual(git_out(repo, "rev-parse", "HEAD"), code2)
        self.assertTrue(self.wiki_clean(repo))
        j = run_json("run", "worker", "--foreground", "--dry-run", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(j["env"]["WIKI_PHASE"], "update")
        self.assertIn("--agent", j["argv"])

    def test_detached_post_commit_run_completes_in_the_background(self):
        repo = bootstrapped_repo(self.root, {"budgets": {"debounce_s": 120}})
        code = code_change(repo, "bg")
        t0 = time.monotonic()
        r = run_script("run", "worker", "--trigger", "post-commit", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertIn("detached worker pid", r.stderr)
        lock = repo / ".git/wiki/lock"
        end = time.monotonic() + 15
        while time.monotonic() < end and (lock.exists() or git_out(repo, "rev-parse", "HEAD") == code):
            time.sleep(0.2)
        self.assertEqual(git_out(repo, "log", "-1", "--format=%s"), "docs(wiki): update 1 page")
        self.assertIn("done: ok", read(repo / ".git/wiki/update.log"))
        self.assertEqual(self.manifest(repo)["checkpoint_commit"], code)
        self.assertFalse(lock.exists())
        # a second post-commit run inside debounce_s is skipped
        code_change(repo, "bg2")
        r = run_script("run", "worker", "--trigger", "post-commit", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(r.returncode, 0)
        self.assertIn("debounced", r.stderr)
        self.assertEqual(len(self.spawns()), 1)


class InteractiveStateTests(Harness):
    def test_begin_status_prompt_defer_end(self):
        repo = bootstrapped_repo(self.root)
        code_change(repo, "i")
        j = run_json("run", "begin", "--mode", "update", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["mode"], "update")
        self.assertEqual(j["work"], 1)
        run = read_json(repo / ".git/wiki/run.json")
        self.assertIsNone(run["session_id"])
        self.assertEqual(run["mode"], "update")
        self.assertEqual(run["work"][0]["path"], "modules/orders.md")
        self.assertEqual(run["status"], "running")
        self.assertIn("max_source_bytes", run["budget"])
        self.assertTrue((repo / ".git/wiki/lock/info.json").exists())
        self.assertEqual(self.spawns(), [])
        st = run_json("run", "status", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(st["run_id"], run["run_id"])
        self.assertEqual(st["work"][0]["path"], "modules/orders.md")
        r = self.runpy(repo, "prompt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("/wiki-update\n"), r.stdout)
        self.assertNotIn("<!--", r.stdout)
        d = run_json("run", "defer", "--reason", "budget exhausted", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(d["status"], "deferred")
        self.assertEqual(read_json(repo / ".git/wiki/run.json")["deferred_reason"], "budget exhausted")
        self.assertIn("* **Deferred**: update run deferred: budget exhausted", read(repo / "wiki/log.md"))
        e = run_json("run", "end", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(e["status"], "deferred")
        self.assertFalse((repo / ".git/wiki/run.json").exists())
        self.assertTrue((repo / ".git/wiki/run.last.json").exists())
        self.assertFalse((repo / ".git/wiki/lock").exists())
        r = self.runpy(repo, "status", "--json")
        self.assertEqual(r.returncode, 3)
        # query and lint modes: read metering only, no work list
        j = run_json("run", "begin", "--mode", "query", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(j["work"], 0)
        run = read_json(repo / ".git/wiki/run.json")
        self.assertEqual(run["mode"], "query")
        self.assertEqual(run["budget"]["bytes_read"], 0)
        j = run_json("run", "begin", "--mode", "lint", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertTrue(j["ok"], "a new interactive begin reclaims the previous interactive lock")
        self.runpy(repo, "end")

    def test_begin_init_refuses_a_customised_instructions_file(self):
        repo = bootstrapped_repo(self.root)
        r = self.runpy(repo, "begin", "--mode", "init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_json(repo / ".git/wiki/run.json")["mode"], "init")
        self.runpy(repo, "end")
        instr = repo / "wiki/instructions.md"
        text = "\n".join("- Canonical name of this system: Sample · Aliases: none" if l.startswith("- Canonical name of this system:")
                         else "- One paragraph: it takes orders." if l.startswith("- One paragraph:") else l
                         for l in read(instr).splitlines()) + "\n"
        self.assertNotEqual(text, read(instr))
        write(instr, text)
        r = self.runpy(repo, "begin", "--mode", "init")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("already customised", r.stderr)
        self.assertFalse((repo / ".git/wiki/run.json").exists())
        self.assertFalse((repo / ".git/wiki/lock").exists())
        r = self.runpy(repo, "begin", "--mode", "init", "--resume")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(read_json(repo / ".git/wiki/run.json")["resume"])
        self.runpy(repo, "end")


PLAN = {"schema_version": 1, "created_at": "2026-09-07T10:00:00Z", "created_by": "copilot-cli/test", "approved_by": "human:me",
        "repo": "group/sample", "plan_hash": "sha256:x", "no_page": [], "least_understood": [],
        "clusters": [
            {"id": "common", "title": "Common utilities", "kind": "module", "deps": [],
             "pages": [{"path": "modules/common.md", "type": "Module", "audience": ["agent", "dev"], "owner": "agent", "sources": ["repo://src/common/"]}],
             "estimate": {"source_bytes": 1200}, "status": "pending", "attempts": 0},
            {"id": "overview", "title": "Overview", "kind": "overview", "deps": ["*"],
             "pages": [{"path": "overview.md", "type": "Overview", "audience": ["agent", "dev"], "owner": "agent", "sources": ["repo://src/"]}],
             "estimate": {"source_bytes": 5000}, "status": "pending", "attempts": 0}]}


class BootstrapTests(Harness):
    def planned_repo(self, config: dict | None = None, plan: dict | None = None) -> Path:
        repo = bootstrapped_repo(self.root, config)
        write_json(repo / "wiki/.wiki-plan.json", plan or PLAN)
        commit_all(repo, "wiki: plan")
        return repo

    def boot(self, repo: Path, *args: str, mode: str = "writes-page") -> subprocess.CompletedProcess:
        return run_script("bootstrap", *args, cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env(mode), timeout=90)

    def plan(self, repo: Path) -> dict:
        return {c["id"]: c for c in read_json(repo / "wiki/.wiki-plan.json")["clusters"]}

    def test_dry_run_prints_order_and_commands_without_spawning(self):
        repo = self.planned_repo()
        r = self.boot(repo, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertLess(next(i for i, l in enumerate(lines) if l.strip().startswith("common ")), next(i for i, l in enumerate(lines) if l.strip().startswith("overview ")))
        self.assertIn("WIKI_PHASE=bootstrap WIKI_CLUSTER=<ID> WIKI_RUN_ID=<ID>", r.stdout)
        self.assertIn("--model claude-sonnet-4.6", r.stdout)
        self.assertIn("timeout 1800s", r.stdout)
        self.assertEqual(self.spawns(), [])
        self.assertTrue(self.wiki_clean(repo))
        self.assertEqual(self.plan(repo)["common"]["status"], "pending")
        j = run_json("bootstrap", "--dry-run", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual([o["id"] for o in j["order"]], ["common", "overview"])

    def test_invalid_plan_is_rejected(self):
        bad = json.loads(json.dumps(PLAN))
        bad["clusters"][0]["deps"] = ["overview"]
        bad["clusters"][1]["deps"] = ["common"]
        repo = self.planned_repo(plan=bad)
        r = self.boot(repo, "--dry-run")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cycle", r.stderr)
        unapproved = json.loads(json.dumps(PLAN))
        unapproved["approved_by"] = None
        write_json(repo / "wiki/.wiki-plan.json", unapproved)
        r = self.boot(repo, "--dry-run")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not approved", r.stderr)

    def test_two_cluster_plan_end_to_end_then_resume_and_only(self):
        repo = self.planned_repo()
        r = self.boot(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = self.plan(repo)
        self.assertEqual(plan["common"]["status"], "done")
        self.assertEqual(plan["overview"]["status"], "done")
        self.assertEqual(plan["common"]["attempts"], 1)
        self.assertTrue((repo / "wiki/modules/common.md").exists())
        self.assertIn("Updated by the fake copilot", read(repo / "wiki/overview.md"))
        subjects = git_out(repo, "log", "--format=%s", "-6").splitlines()
        self.assertIn("docs(wiki): bootstrap common", subjects)
        self.assertIn("docs(wiki): bootstrap overview", subjects)
        self.assertLess(subjects.index("docs(wiki): bootstrap overview"), subjects.index("docs(wiki): bootstrap common"))
        self.assertEqual(subjects[0], "docs(wiki): bootstrap checkpoint")
        for cid in ("common", "overview"):
            sha = plan[cid]["commit"]
            self.assertEqual(git_out(repo, "log", "-1", "--format=%s", sha), f"docs(wiki): bootstrap {cid}")
            body = git_out(repo, "log", "-1", "--format=%B", sha)
            self.assertIn("Wiki-Update: auto", body)
            self.assertIn(f"Wiki-Run: {cid}", body)
            files = git_out(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
            self.assertTrue(all(f.startswith("wiki/") or f == CONSUMERS_REL for f in files), files)
        self.assertTrue(self.wiki_clean(repo))
        spawns = self.spawns()
        self.assertEqual([s["env"]["WIKI_CLUSTER"] for s in spawns], ["common", "overview"])
        self.assertEqual({s["env"]["WIKI_PHASE"] for s in spawns}, {"bootstrap"})
        self.assertEqual([s["env"]["WIKI_RUN_ID"] for s in spawns], ["common", "overview"])
        self.assertIn("claude-sonnet-4.6", spawns[0]["argv"])
        self.assertIn("/wiki-page common", spawns[0]["argv"][1])
        m = self.manifest(repo)
        self.assertEqual(m["checkpoint_commit"], git_out(repo, "rev-parse", "HEAD~1"), "checkpoint advanced at the end (before the checkpoint commit)")
        self.assertIn("modules/common.md", m["pages"])
        self.assertIn("* **Bootstrap**: cluster common:", read(repo / "wiki/log.md"))
        self.assertIn("Review before the hook takes over", r.stderr)
        self.assertIn("overview.md", r.stderr)
        self.assertIn("glossary.md", r.stderr)
        self.assertEqual(run_script("backlinks", "--check", cwd=repo, scripts=repo / SCRIPTS_REL).returncode, 0)
        recs = [x for x in self.metrics(repo) if x.get("mode") == "page"]
        self.assertEqual([x["cluster"] for x in recs], ["common", "overview"])
        # --resume: everything done → nothing spawned
        self.fake_log.unlink()
        r = self.boot(repo, "--resume")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already done, skipped", r.stderr)
        self.assertEqual(self.spawns(), [])
        # --only overview: only that cluster runs again
        r = self.boot(repo, "--only", "overview")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([s["env"]["WIKI_CLUSTER"] for s in self.spawns()], ["overview"])
        self.assertEqual(self.plan(repo)["overview"]["attempts"], 2)
        self.assertTrue(self.wiki_clean(repo))
        r = self.boot(repo, "--only", "nope", "--dry-run")
        self.assertEqual(r.returncode, 2)

    def test_resume_skips_done_and_runs_the_rest(self):
        plan = json.loads(json.dumps(PLAN))
        plan["clusters"][0]["status"] = "done"
        repo = self.planned_repo(plan=plan)
        r = self.boot(repo, "--resume")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([s["env"]["WIKI_CLUSTER"] for s in self.spawns()], ["overview"])
        self.assertEqual(self.plan(repo)["overview"]["status"], "done")
        self.assertFalse((repo / "wiki/modules/common.md").exists())

    def test_failures_retry_once_and_stop_at_max_failures(self):
        repo = self.planned_repo()
        r = self.boot(repo, "--max-failures", "1", mode="fails")
        self.assertEqual(r.returncode, 4, r.stderr)
        plan = self.plan(repo)
        self.assertEqual(plan["common"]["status"], "failed")
        self.assertEqual(plan["common"]["attempts"], 2)
        self.assertIn("no WIKI-RUN-RESULT", plan["common"]["reason"])
        self.assertEqual(plan["overview"]["status"], "pending")
        self.assertEqual(len(self.spawns()), 2)
        self.assertIn("stopping after 1 consecutive failed", r.stderr)
        self.assertTrue(self.wiki_clean(repo))
        self.assertFalse((repo / "wiki/modules/common.md").exists())
        # a hung cluster is killed and counted as failed too
        repo2 = self.planned_repo({"budgets": {"bootstrap_timeout_s": 2}})
        self.fake_log.unlink()
        t0 = time.monotonic()
        r = self.boot(repo2, "--only", "common", "--max-failures", "1", mode="hangs")
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("TIMED OUT", r.stderr)
        self.assertEqual(self.plan(repo2)["common"]["status"], "failed")

    def test_over_budget_cluster_is_split_once(self):
        repo = self.planned_repo({"budgets": {"max_source_bytes_per_cluster": 800}})
        r = self.boot(repo)
        plan = self.plan(repo)
        self.assertEqual(plan["common"]["status"], "split", r.stderr)
        children = plan["common"]["split_into"]
        self.assertGreaterEqual(len(children), 2)
        self.assertIn("over budget → split into", r.stderr)
        for cid in children:
            self.assertIn(plan[cid]["status"], ("done", "deferred"), cid)
            self.assertFalse(plan[cid].get("split_into"), "a split child is never split again")
        self.assertEqual(plan["overview"]["deps"], ["*"])
        self.assertTrue(self.wiki_clean(repo))
        self.assertTrue(any(s["env"]["WIKI_CLUSTER"] in children for s in self.spawns()))

    def test_run_py_bootstrap_detach_starts_the_driver(self):
        repo = self.planned_repo()
        r = run_script("run", "bootstrap", "--detach", cwd=repo, scripts=repo / SCRIPTS_REL, env=self.fake_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bootstrap driver started", r.stderr)
        log = repo / ".git/wiki/bootstrap.log"
        end = time.monotonic() + 25
        while time.monotonic() < end and not (log.exists() and "finished in" in read(log)):
            time.sleep(0.25)
        self.assertEqual(self.plan(repo)["overview"]["status"], "done")
        self.assertIn("Bootstrap finished", read(log))
        self.assertFalse((repo / ".git/wiki/lock").exists())


if __name__ == "__main__":
    unittest.main()
