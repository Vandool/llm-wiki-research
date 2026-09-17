"""install.py: full file map, idempotence, --upgrade, settings carry-over, --uninstall, --check, --dry-run."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from conftest import KIT, SCRIPTS, TempDir, commit_all, git, git_out, install_kit, make_repo, read, read_json, run_json, run_script, write

sys.path.insert(0, str(KIT))
import install as installer  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import ci_integrate as ci  # noqa: E402

CONFIG = ".github/wiki.config.json"
CI_FILE = ".gitlab/ci/wiki.gitlab-ci.yml"
BLOCK_TEMPLATE = KIT / "templates" / "copilot-instructions.block.md"
WIKI_TEMPLATES = KIT / "templates" / "wiki"


class _Opts:
    def __init__(self, **kw):
        self.no_ci = kw.get("no_ci", False)
        self.no_site = kw.get("no_site", False)
        self.issue_template = kw.get("issue_template", False)


def expected_kit_files(**kw) -> list[tuple[Path, str]]:
    """What the installer itself enumerates from the kit tree right now (track A/B files included when present)."""
    return installer.kit_file_map(_Opts(**kw))


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def installed(tmp: Path, *args: str, name: str = "repo") -> tuple[Path, subprocess.CompletedProcess]:
    repo = make_repo(tmp, name=name)
    r = install_kit(repo, *args)
    return repo, r


class InstallTests(unittest.TestCase):
    def test_full_file_map(self):
        with TempDir() as tmp:
            repo, r = installed(tmp, "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            files = expected_kit_files()
            self.assertGreater(len(files), 5)
            cfg = read_json(repo / CONFIG)
            self.assertEqual(cfg["kit"]["version"], read(KIT / "VERSION").strip())
            self.assertTrue(cfg["kit"]["installed_at"])
            for src, rel in files:
                dst = repo / rel
                self.assertTrue(dst.is_file(), f"missing {rel}")
                self.assertEqual(dst.read_bytes(), src.read_bytes(), f"{rel} differs from the kit")
                self.assertEqual(cfg["kit"]["files"].get(rel), sha(src.read_bytes()), f"{rel} not recorded")
                if src.stat().st_mode & stat.S_IXUSR:
                    self.assertTrue(dst.stat().st_mode & stat.S_IXUSR, f"{rel} lost its executable bit")
            self.assertEqual(set(cfg["kit"]["files"]), {rel for _, rel in files})
            # the kit's own instructions/config are never copied verbatim
            self.assertNotIn(".github/wiki.config.json", cfg["kit"]["files"])
            self.assertNotIn(".github/copilot-instructions.md", cfg["kit"]["files"])
            # templates → their target locations
            self.assertEqual(read(repo / CI_FILE), read(KIT / "templates/ci/wiki.gitlab-ci.yml"))
            for name in ("quartz.config.yaml", "build.sh", "README.md"):
                self.assertEqual(read(repo / ".gitlab/wiki-site" / name), read(KIT / "templates/quartz" / name))
            self.assertTrue((repo / ".gitlab/wiki-site/build.sh").stat().st_mode & stat.S_IXUSR)
            # scaffold (meaningful once templates/wiki exists — track A)
            if WIKI_TEMPLATES.is_dir():
                for p in WIKI_TEMPLATES.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(WIKI_TEMPLATES).as_posix()
                        dst = repo / "wiki" / rel
                        self.assertTrue(dst.is_file(), f"scaffold missing wiki/{rel}")
                        if p.suffix in (".md", ".yaml", ".yml", ".json", ".txt"):
                            self.assertNotIn("{{", read(dst), f"placeholder left in wiki/{rel}")
            # block (meaningful once the block template exists — track A)
            if BLOCK_TEMPLATE.is_file():
                text = read(repo / ".github/copilot-instructions.md")
                self.assertIn("<!-- WIKI-AGENT:START", text)
                self.assertIn("<!-- WIKI-AGENT:END -->", text)
                self.assertTrue(text.startswith("# Copilot instructions for repo\n"))
            # lines
            ga = read(repo / ".gitattributes")
            for line in read(KIT / "templates/gitattributes").splitlines():
                self.assertIn(line, ga.splitlines())
            gi = read(repo / ".gitignore")
            for line in ("public/", ".npm/", ".wiki-build/", "# wiki-kit"):
                self.assertIn(line, gi.splitlines())
            self.assertIn("node_modules/", gi)            # the target's own lines survive
            # hooks
            self.assertIn("wiki-kit trampoline", read(repo / ".git/hooks/post-commit"))
            self.assertIn("wiki-kit trampoline", read(repo / ".git/hooks/pre-push"))
            self.assertTrue((repo / ".git/hooks/post-commit").stat().st_mode & stat.S_IXUSR)
            # detection prefill
            self.assertEqual(cfg["repo"]["default_branch"], "main")
            self.assertEqual(cfg["branches"]["staging"], "preprod")   # BRANCH_PREPROD in the fixture pipeline
            self.assertEqual(cfg["wiki_dir"], "wiki")
            # next steps (verbatim §8.13)
            self.assertIn("1) copilot login (once)  2) cd ", r.stdout)
            self.assertIn("WIKI_RUN=1 copilot --agent wiki-maintainer --model claude-sonnet-4.6  3) /wiki-init", r.stdout)
            self.assertIn("python3 .github/skills/wiki-maintain/scripts/hooks.py install", r.stdout)

    def test_second_run_is_up_to_date_and_leaves_git_clean(self):
        with TempDir() as tmp:
            repo, r = installed(tmp, "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            commit_all(repo, "wiki: install")
            r2 = install_kit(repo, "--hooks", "git")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("up to date", r2.stdout)
            self.assertEqual(git_out(repo, "status", "--porcelain"), "")

    def test_upgrade_skips_modified_kit_files_unless_forced(self):
        with TempDir() as tmp:
            repo, _ = installed(tmp, "--hooks", "git")
            target = repo / ".gitlab/wiki-site/README.md"
            write(target, read(target) + "\n# local edit\n")
            r = install_kit(repo, "--upgrade")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("locally modified", r.stderr)
            self.assertTrue(read(target).endswith("# local edit\n"))
            # a plain run is silent about it (it is not an upgrade)
            r = install_kit(repo)
            self.assertEqual(r.returncode, 0)
            self.assertIn("up to date", r.stdout)
            r = install_kit(repo, "--upgrade", "--force")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(read(target), read(KIT / "templates/quartz/README.md"))
            self.assertIn("update    kit      .gitlab/wiki-site/README.md  (forced)", r.stdout)
            self.assertIn("change(s) written", r.stdout)

    def test_upgrade_replaces_unmodified_kit_file_and_keeps_project_settings(self):
        with TempDir() as tmp:
            repo, _ = installed(tmp, "--hooks", "git")
            scripts = repo / ".github/skills/wiki-maintain/scripts"
            res = run_json("ci_integrate", "apply", "--prod-branch", "prod", "--staging-branch", "staging",
                           "--parallel", "true", "--yes", cwd=repo, scripts=scripts)
            self.assertEqual(res["_rc"], 0, res.get("_stderr"))
            # simulate a file installed by an older kit: a TOOLCHAIN value differs, and the record matches that file
            ci_path = repo / CI_FILE
            old = read(ci_path).replace('WIKI_QUARTZ_REF: "v5.0.0"', 'WIKI_QUARTZ_REF: "v4.9.9"')
            self.assertNotEqual(old, read(ci_path))
            write(ci_path, old)
            cfg = read_json(repo / CONFIG)
            cfg["kit"]["files"][CI_FILE] = sha(old.encode("utf-8"))
            cfg["kit"]["version"] = "0.9.0"
            write(repo / CONFIG, json.dumps(cfg, indent=2) + "\n")
            r = install_kit(repo, "--upgrade")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(CI_FILE, r.stdout)
            new = read(ci_path)
            self.assertIn('WIKI_QUARTZ_REF: "v5.0.0"', new)
            settings = ci.read_project_settings(new)
            self.assertEqual(settings["WIKI_PROD_BRANCH"], "prod")
            self.assertEqual(settings["WIKI_STAGING_BRANCH"], "staging")
            self.assertEqual(settings["WIKI_PARALLEL_DEPLOYMENTS"], "true")
            cfg = read_json(repo / CONFIG)
            self.assertEqual(cfg["kit"]["version"], read(KIT / "VERSION").strip())
            self.assertEqual(cfg["kit"]["files"][CI_FILE], sha(new.encode("utf-8")))
            self.assertEqual(cfg["branches"]["production"], "prod")      # answers survive
            # the pipeline include is still exactly one line
            self.assertEqual(sum(1 for l in read(repo / ".gitlab-ci.yml").splitlines() if "wiki.gitlab-ci.yml" in l), 1)

    def test_upgrade_merges_new_config_keys_and_keeps_values(self):
        with TempDir() as tmp:
            repo, _ = installed(tmp, "--hooks", "git")
            cfg = read_json(repo / CONFIG)
            cfg["max_pages"] = 3
            cfg["repo"]["slug"] = "group/thing"
            del cfg["budgets"]
            write(repo / CONFIG, json.dumps(cfg, indent=2) + "\n")
            r = install_kit(repo, "--upgrade")
            self.assertEqual(r.returncode, 0, r.stderr)
            cfg2 = read_json(repo / CONFIG)
            self.assertEqual(cfg2["max_pages"], 3)
            self.assertEqual(cfg2["repo"]["slug"], "group/thing")
            self.assertIn("budgets", cfg2)
            self.assertEqual(cfg2["budgets"]["max_pages_per_cluster"], 6)

    def test_uninstall_restores_pre_existing_hook_and_leaves_wiki(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            hook = repo / ".git/hooks/post-commit"
            hook.write_text("#!/bin/sh\necho custom\n")
            hook.chmod(0o755)
            write(repo / ".github/copilot-instructions.md", "# My rules\n\nKeep tests green.\n")
            r = install_kit(repo, "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("wiki-kit trampoline", read(hook))
            self.assertEqual(read(repo / ".git/hooks/post-commit.local"), "#!/bin/sh\necho custom\n")
            scripts = repo / ".github/skills/wiki-maintain/scripts"
            run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo, scripts=scripts)
            self.assertIn("wiki.gitlab-ci.yml", read(repo / ".gitlab-ci.yml"))
            write(repo / "wiki/modules/orders.md", "# Orders\n")
            r = install_kit(repo, "--uninstall")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(read(hook), "#!/bin/sh\necho custom\n")
            self.assertFalse((repo / ".git/hooks/post-commit.local").exists())
            self.assertFalse((repo / ".git/hooks/pre-push").exists())
            for _, rel in expected_kit_files():
                self.assertFalse((repo / rel).exists(), f"{rel} still present")
            self.assertFalse((repo / ".gitlab").exists())
            self.assertTrue((repo / "wiki/modules/orders.md").is_file())
            self.assertNotIn("wiki.gitlab-ci.yml", read(repo / ".gitlab-ci.yml"))
            self.assertEqual(read(repo / ".gitlab-ci.yml"), read(KIT / "tests/fixtures/sample-repo/.gitlab-ci.yml"))
            text = read(repo / ".github/copilot-instructions.md")
            self.assertNotIn("WIKI-AGENT", text)
            self.assertIn("Keep tests green.", text)
            self.assertFalse((repo / ".gitattributes").exists())
            gi = read(repo / ".gitignore")
            self.assertNotIn("# wiki-kit", gi)
            self.assertNotIn(".wiki-build/", gi)
            self.assertIn("node_modules/", gi)
            cfg = read_json(repo / CONFIG)                     # answers kept, record cleared
            self.assertEqual(cfg["kit"]["files"], {})
            self.assertEqual(cfg["branches"]["production"], "main")

    def test_uninstall_keeps_modified_kit_file(self):
        with TempDir() as tmp:
            repo, _ = installed(tmp, "--hooks", "git")
            target = repo / ".gitlab/wiki-site/README.md"
            write(target, "mine\n")
            r = install_kit(repo, "--uninstall")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(read(target), "mine\n")
            self.assertFalse((repo / ".gitlab/wiki-site/build.sh").exists())

    def test_dry_run_writes_nothing(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git" not in p.parts)
            r = install_kit(repo, "--dry-run", "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dry run", r.stdout)
            self.assertIn("create    kit      .gitlab/ci/wiki.gitlab-ci.yml", r.stdout)
            after = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git" not in p.parts)
            self.assertEqual(before, after)
            self.assertFalse((repo / ".git/hooks/post-commit").exists())

    def test_check_reports_state(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            r = install_kit(repo, "--check")
            self.assertEqual(r.returncode, 1)
            repo2, _ = installed(tmp, "--hooks", "git", name="r2")
            r = install_kit(repo2, "--check")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("installed and up to date", r.stdout)
            write(repo2 / ".gitlab/wiki-site/README.md", "changed\n")
            r = install_kit(repo2, "--check")
            self.assertEqual(r.returncode, 1)
            self.assertIn(".gitlab/wiki-site/README.md", r.stdout)

    def test_non_git_target_refused_unless_hooks_none(self):
        with TempDir() as tmp:
            plain = tmp / "plain"
            plain.mkdir()
            r = install_kit(plain)
            self.assertEqual(r.returncode, 3)
            r = install_kit(plain, "--hooks", "none")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((plain / CI_FILE).is_file())
            self.assertFalse((plain / ".git").exists())

    def test_wiki_dir_option(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            r = install_kit(repo, "--wiki-dir", "docs/wiki", "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            cfg = read_json(repo / CONFIG)
            self.assertEqual(cfg["wiki_dir"], "docs/wiki")
            inc = read(repo / CI_FILE)
            self.assertIn('WIKI_DIR: "docs/wiki"', inc)
            self.assertIn('- "docs/wiki/**/*"', inc)
            self.assertIn("docs/wiki/log.md merge=union", read(repo / ".gitattributes"))
            self.assertEqual(git_out(repo, "config", "--get", "wiki.dir"), "docs/wiki")
            if WIKI_TEMPLATES.is_dir():
                self.assertTrue((repo / "docs/wiki/index.md").is_file())
                self.assertFalse((repo / "wiki").exists())
            if BLOCK_TEMPLATE.is_file():
                self.assertIn("docs/wiki/index.md", read(repo / ".github/copilot-instructions.md"))
            r2 = install_kit(repo, "--hooks", "git")
            self.assertIn("up to date", r2.stdout)

    def test_no_ci_no_site_and_issue_template(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            r = install_kit(repo, "--no-ci", "--no-site", "--issue-template", "--hooks", "none")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((repo / ".gitlab/ci").exists())
            self.assertFalse((repo / ".gitlab/wiki-site").exists())
            self.assertTrue((repo / ".gitlab/issue_templates/Wiki request.md").is_file())
            self.assertFalse((repo / ".git/hooks/post-commit").exists())
            cfg = read_json(repo / CONFIG)
            self.assertNotIn(CI_FILE, cfg["kit"]["files"])

    def test_json_output(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            r = install_kit(repo, "--json", "--hooks", "git")
            self.assertEqual(r.returncode, 0, r.stderr)
            obj = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertTrue(obj["ok"])
            self.assertEqual(obj["mode"], "install")
            self.assertFalse(obj["up_to_date"])
            self.assertTrue(any(a["path"] == CI_FILE and a["op"] == "create" for a in obj["actions"]))
            self.assertEqual(obj["hooks"]["mode"], "git")
            r2 = install_kit(repo, "--json", "--hooks", "git")
            self.assertTrue(json.loads(r2.stdout.strip().splitlines()[-1])["up_to_date"])

    def test_block_and_lines_helpers(self):
        block = "<!-- WIKI-AGENT:START x -->\nbody\n<!-- WIKI-AGENT:END -->\n"
        text, op = installer.upsert_block(None, block, "r")
        self.assertEqual(op, "create")
        self.assertTrue(text.startswith("# Copilot instructions for r\n"))
        self.assertIsNone(installer.remove_block(text))
        text2, op = installer.upsert_block("# mine\n", block, "r")
        self.assertEqual(op, "update")
        self.assertEqual(text2, "# mine\n\n" + block)
        self.assertEqual(installer.upsert_block(text2, block, "r"), (text2, "unchanged"))
        newer = block.replace("body", "body2")
        text3, op = installer.upsert_block(text2, newer, "r")
        self.assertEqual(op, "update")
        self.assertIn("body2", text3)
        self.assertNotIn("body\n", text3)
        self.assertEqual(installer.remove_block(text3), "# mine\n")
        t, op = installer.ensure_lines("x\n", ["a", "b"])
        self.assertEqual((t, op), ("x\n\n# wiki-kit\na\nb\n", "update"))
        self.assertEqual(installer.ensure_lines(t, ["a", "b"]), (t, "unchanged"))
        t2, _ = installer.ensure_lines(t, ["a", "b", "c"])
        self.assertEqual(t2, "x\n\n# wiki-kit\na\nb\nc\n")
        self.assertEqual(installer.drop_lines(t2, ["a", "b", "c"]), "x\n")
        self.assertIsNone(installer.drop_lines("# wiki-kit\na\n", ["a"]))


if __name__ == "__main__":
    unittest.main()
