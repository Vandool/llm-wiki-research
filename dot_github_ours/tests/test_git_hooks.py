"""Git hooks: trampolines + committed bodies. run.py / affected.py / lint.py are stubbed inside the target
(phase 4 writes the real run.py; the stubs only record how they were invoked)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from conftest import SCRIPTS, TempDir, env_with, git, git_out, install_kit, make_repo, read, run_json, run_script, write

SCRIPTS_REL = ".github/skills/wiki-maintain/scripts"
HOOKS_REL = ".github/skills/wiki-maintain/hooks"

STUB_RUN = """#!/usr/bin/env python3
import json, os, sys, pathlib
log = os.environ.get("WIKI_TEST_LOG")
if log:
    env = {k: v for k, v in os.environ.items() if k.startswith("WIKI_") or k == "COPILOT_AUTO_UPDATE"}
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "env": env, "cwd": os.getcwd()}) + "\\n")
print("stub run.py: " + " ".join(sys.argv[1:]))
"""

STUB_AFFECTED = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("WIKI_TEST_LOG")
if log:
    open(log, "a").write("affected " + " ".join(sys.argv[1:]) + "\\n")
rc = int(os.environ.get("STUB_AFFECTED_RC", "1"))
if rc == 1:
    print("stale: modules/orders.md (blob_changed)")
sys.exit(rc)
"""

STUB_LINT = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("WIKI_TEST_LOG")
if log:
    open(log, "a").write("lint " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("STUB_LINT_RC", "0")))
"""


def wait_for(path: Path, timeout: float = 8.0) -> str:
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.read_text().strip():
            time.sleep(0.2)          # let the writer finish the line
            return path.read_text()
        time.sleep(0.1)
    return path.read_text() if path.exists() else ""


class HookRepo:
    """A sample repo with the kit installed (git trampolines), stubs, and a bootstrapped manifest."""

    def __init__(self, tmp: Path, name: str = "repo"):
        self.repo = make_repo(tmp, name=name)
        r = install_kit(self.repo, "--hooks", "git")
        assert r.returncode == 0, r.stdout + r.stderr
        scripts = self.repo / SCRIPTS_REL
        write(scripts / "run.py", STUB_RUN)
        write(scripts / "affected.py", STUB_AFFECTED)
        write(scripts / "lint.py", STUB_LINT)
        write(self.repo / "wiki" / ".manifest.json", json.dumps({"schema_version": 1, "checkpoint_commit": ""}) + "\n")
        self.log = tmp / f"{name}-hook.log"
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "kit installed")

    def env(self, **extra) -> dict:
        e = {"WIKI_HOOK_DISABLE": "0", "WIKI_TEST_LOG": str(self.log)}
        e.update(extra)
        return e

    def commit(self, message: str, paths: dict, **extra) -> subprocess.CompletedProcess:
        for rel, text in paths.items():
            write(self.repo / rel, text)
        git(self.repo, "add", "-A", env=self.env(**extra))
        return git(self.repo, "commit", "-q", "-m", message, env=self.env(**extra), check=False)

    def code_change(self, tag: str) -> dict:
        p = self.repo / "src/orders/service.py"
        return {"src/orders/service.py": read(p) + f"\n# change {tag}\n"}

    def entries(self) -> list[dict]:
        text = wait_for(self.log, timeout=8.0)
        return [json.loads(l) for l in text.splitlines() if l.startswith("{")]

    def assert_no_run(self, tc: unittest.TestCase, wait: float = 1.5) -> None:
        time.sleep(wait)
        tc.assertFalse(self.log.exists() and self.log.read_text().strip(), f"worker was started: {self.log.read_text() if self.log.exists() else ''}")


class PostCommitTests(unittest.TestCase):
    def test_code_commit_starts_worker_in_background(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            r = h.commit("feat: change service", h.code_change("a"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("wiki: maintainer started in the background", r.stderr)
            entries = h.entries()
            self.assertEqual(len(entries), 1, entries)
            self.assertEqual(entries[0]["argv"], ["worker", "--trigger", "post-commit"])
            env = entries[0]["env"]
            self.assertEqual(env["WIKI_HOOK_RUNNING"], "1")
            self.assertEqual(env["WIKI_TRIGGER"], "post-commit")
            self.assertEqual(env["WIKI_BRANCH"], "main")
            self.assertEqual(env["WIKI_HEAD"], git_out(h.repo, "rev-parse", "HEAD"))
            self.assertEqual(env["COPILOT_AUTO_UPDATE"], "false")
            self.assertEqual(Path(entries[0]["cwd"]).resolve(), h.repo.resolve())
            update_log = h.repo / ".git/wiki/update.log"
            self.assertIn("stub run.py: worker --trigger post-commit", wait_for(update_log))

    def test_wiki_only_commit_does_not_start_worker(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            r = h.commit("docs(wiki): page", {"wiki/modules/orders.md": "# Orders\n"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("maintainer started", r.stderr)
            h.assert_no_run(self)

    def test_trailer_commit_does_not_start_worker(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            r = h.commit("docs(wiki): update 2 pages\n\nWiki-Update: auto", h.code_change("t"))
            self.assertEqual(r.returncode, 0, r.stderr)
            h.assert_no_run(self)

    def test_env_off_switch(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            r = h.commit("feat: x", h.code_change("e"), WIKI_HOOK_DISABLE="1")
            self.assertEqual(r.returncode, 0, r.stderr)
            h.assert_no_run(self)

    def test_git_config_off_switch(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            git(h.repo, "config", "wiki.hook.disable", "true")
            r = h.commit("feat: x", h.code_change("g"))
            self.assertEqual(r.returncode, 0, r.stderr)
            h.assert_no_run(self)

    def test_not_bootstrapped_does_not_start_worker(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            (h.repo / "wiki/.manifest.json").unlink()
            r = h.commit("chore: drop manifest", h.code_change("m"))
            self.assertEqual(r.returncode, 0, r.stderr)
            h.assert_no_run(self)

    def test_hook_running_guard(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            r = h.commit("feat: from worker", h.code_change("w"), WIKI_HOOK_RUNNING="1")
            self.assertEqual(r.returncode, 0, r.stderr)
            h.assert_no_run(self)

    def test_existing_hook_is_chained_via_local(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            marker = tmp / "custom-ran"
            hook = repo / ".git/hooks/post-commit"
            hook.write_text(f"#!/bin/sh\necho ran >> '{marker}'\n")
            hook.chmod(0o755)
            h = HookRepo.__new__(HookRepo)
            h.repo = repo
            r = install_kit(repo, "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((repo / ".git/hooks/post-commit.local").is_file())
            write(repo / SCRIPTS_REL / "run.py", STUB_RUN)
            write(repo / "wiki/.manifest.json", "{}\n")
            h.log = tmp / "chain.log"
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "kit")
            r = h.commit("feat: y", h.code_change("c"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(marker.exists(), "pre-existing hook did not run")
            self.assertEqual(h.entries()[0]["argv"], ["worker", "--trigger", "post-commit"])


class PrePushTests(unittest.TestCase):
    def _with_remote(self, tmp: Path) -> HookRepo:
        h = HookRepo(tmp)
        bare = tmp / "remote.git"
        git(tmp, "init", "-q", "--bare", str(bare))
        git(h.repo, "remote", "add", "origin", str(bare))
        return h

    def test_soft_mode_reports_but_pushes(self):
        with TempDir() as tmp:
            h = self._with_remote(tmp)
            r = git(h.repo, "push", "-q", "origin", "main", env=h.env(STUB_AFFECTED_RC="1"), check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("wiki: stale pages listed above", r.stderr)
            self.assertIn("affected --check-only --summary", h.log.read_text())

    def test_strict_env_blocks_push(self):
        with TempDir() as tmp:
            h = self._with_remote(tmp)
            r = git(h.repo, "push", "-q", "origin", "main", env=h.env(STUB_AFFECTED_RC="1", WIKI_STRICT="1"), check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("wiki: stale pages listed above", r.stderr)
            self.assertEqual(git_out(tmp / "remote.git", "for-each-ref", "--format=%(refname)"), "")

    def test_strict_git_config_blocks_push_and_clean_passes(self):
        with TempDir() as tmp:
            h = self._with_remote(tmp)
            git(h.repo, "config", "wiki.strict", "true")
            r = git(h.repo, "push", "-q", "origin", "main", env=h.env(STUB_AFFECTED_RC="1"), check=False)
            self.assertNotEqual(r.returncode, 0)
            r = git(h.repo, "push", "-q", "origin", "main", env=h.env(STUB_AFFECTED_RC="0"), check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("stale pages", r.stderr)

    def test_off_switch_skips_check(self):
        with TempDir() as tmp:
            h = self._with_remote(tmp)
            r = git(h.repo, "push", "-q", "origin", "main", env=h.env(STUB_AFFECTED_RC="1", WIKI_HOOK_DISABLE="1"), check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(h.log.exists())


class PreCommitLintTests(unittest.TestCase):
    def test_body_runs_lint_staged_only_for_wiki_files(self):
        with TempDir() as tmp:
            h = HookRepo(tmp)
            body = h.repo / HOOKS_REL / "pre-commit-lint"
            r = subprocess.run(["sh", str(body)], cwd=str(h.repo), capture_output=True, text=True, env=env_with(h.env()))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(h.log.exists())                     # nothing staged under wiki/
            write(h.repo / "wiki/modules/x.md", "# x\n")
            git(h.repo, "add", "wiki/modules/x.md")
            r = subprocess.run(["sh", str(body)], cwd=str(h.repo), capture_output=True, text=True, env=env_with(h.env()))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(h.log.read_text().strip(), "lint --staged")
            r = subprocess.run(["sh", str(body)], cwd=str(h.repo), capture_output=True, text=True,
                               env=env_with(h.env(STUB_LINT_RC="1")))
            self.assertEqual(r.returncode, 1)

    def test_bodies_are_posix_sh_and_executable(self):
        for name in ("post-commit", "pre-push", "pre-commit-lint"):
            p = SCRIPTS.parent / "hooks" / name
            self.assertTrue(p.is_file(), name)
            self.assertTrue(read(p).startswith("#!/usr/bin/env sh\n"), name)
            self.assertTrue(os.access(p, os.X_OK), f"{name} not executable")
            r = subprocess.run(["sh", "-n", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class HooksScriptTests(unittest.TestCase):
    def test_status_install_uninstall(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            r = install_kit(repo, "--hooks", "none")
            self.assertEqual(r.returncode, 0, r.stderr)
            scripts = repo / SCRIPTS_REL
            st = run_json("hooks", "status", cwd=repo, scripts=scripts)
            self.assertFalse(st["installed"])
            self.assertEqual(st["mode"], "none")
            res = run_json("hooks", "install", "--hooks", "git", cwd=repo, scripts=scripts)
            self.assertEqual(res["mode"], "git")
            self.assertEqual(res["actions"], {"post-commit": "installed", "pre-push": "installed"})
            st = run_json("hooks", "status", cwd=repo, scripts=scripts)
            self.assertTrue(st["installed"])
            self.assertEqual(st["mode"], "git")
            self.assertTrue(st["kit_hooks_present"])
            res = run_json("hooks", "install", "--hooks", "git", cwd=repo, scripts=scripts)
            self.assertEqual(res["actions"], {"post-commit": "unchanged", "pre-push": "unchanged"})
            res = run_json("hooks", "uninstall", cwd=repo, scripts=scripts)
            self.assertEqual(res["actions"], {"post-commit": "removed", "pre-push": "removed"})
            self.assertFalse((repo / ".git/hooks/post-commit").exists())

    def test_core_hookspath_is_honoured(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            install_kit(repo, "--hooks", "none")
            scripts = repo / SCRIPTS_REL
            (repo / ".husky").mkdir()
            git(repo, "config", "core.hooksPath", ".husky")
            r = run_script("hooks", "install", "--hooks", "git", cwd=repo, scripts=scripts)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(".husky/post-commit", r.stdout)
            self.assertIn(".husky/pre-push", r.stdout)
            self.assertFalse((repo / ".husky/post-commit").exists())
            self.assertFalse((repo / ".git/hooks/post-commit").exists())
            st = run_json("hooks", "status", cwd=repo, scripts=scripts)
            self.assertEqual(st["hooks_path"], ".husky")
            self.assertEqual(st["manager"], "husky")
            self.assertFalse(st["installed"])

    def test_auto_prefers_pre_commit_when_configured_and_available(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            install_kit(repo, "--hooks", "none")
            scripts = repo / SCRIPTS_REL
            write(repo / ".pre-commit-config.yaml", "repos: []\n")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            (fake_bin / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
            (fake_bin / "pre-commit").chmod(0o755)
            env = {"PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
            r = run_script("hooks", "install", "--hooks", "auto", cwd=repo, scripts=scripts, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("wiki-post-commit", r.stdout)
            self.assertIn("pre-commit install --hook-type", r.stderr)
            self.assertFalse((repo / ".git/hooks/post-commit").exists())
            r = run_script("hooks", "install", "--hooks", "auto", cwd=repo, scripts=scripts)   # no binary → trampolines
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((repo / ".git/hooks/post-commit").is_file())

    def test_wiki_dir_git_config(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            install_kit(repo, "--hooks", "none", "--wiki-dir", "docs/wiki")
            scripts = repo / SCRIPTS_REL
            res = run_json("hooks", "install", "--hooks", "git", cwd=repo, scripts=scripts)
            self.assertEqual(res["wiki_dir"]["wiki_dir"], "docs/wiki")
            self.assertEqual(git_out(repo, "config", "--get", "wiki.dir"), "docs/wiki")
            run_json("hooks", "uninstall", cwd=repo, scripts=scripts)
            self.assertEqual(git(repo, "config", "--get", "wiki.dir", check=False).returncode, 1)


if __name__ == "__main__":
    unittest.main()
