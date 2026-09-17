"""lint.py: every deterministic rule against tests/fixtures/fixture-wiki, --fix idempotence, PO rules, modes."""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from conftest import FIXTURES, SCRIPTS, TempDir, commit_all, git, git_out, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401

COPILOT_BLOCK = """# Project instructions
<!-- WIKI-AGENT:START Wiki-Kit: 1.0.0 (managed by the wiki kit; edit outside this block only) -->
## Repository wiki: the context layer
- read the wiki first
<!-- WIKI-AGENT:END -->
"""


def fixture_repo(tmp: Path) -> Path:
    repo = make_repo(tmp)
    shutil.copytree(FIXTURES / "fixture-wiki", repo / "wiki", dirs_exist_ok=True)
    (repo / "wiki" / "expected.json").unlink()
    write_json(repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"},
                                                    "sources": {"include": ["src", "web"]}, "coverage": {"min_files": 2}})
    write(repo / ".github/copilot-instructions.md", COPILOT_BLOCK)
    res = run_script("facts", "--only", "symbols", cwd=repo)
    assert res.returncode == 0, res.stderr
    commit_all(repo, "wiki: fixture")
    return repo


def rules_by_file(result: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in result["errors"] + result["warnings"] + result["info"]:
        out.setdefault(f["file"], set()).add(f["rule"])
    return out


def codes_for(result: dict, file: str) -> set[str]:
    return {f["code"] for f in result["errors"] + result["warnings"] + result["info"] if f["file"] == file}


class TestRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TempDir()
        cls.tmp = cls._tmp.__enter__()
        cls.repo = fixture_repo(cls.tmp)
        cls.expected = read_json(FIXTURES / "fixture-wiki" / "expected.json")
        cls.result = run_json("lint", "--all", cwd=cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.__exit__(None, None, None)

    def test_json_shape(self):
        r = self.result
        self.assertEqual(r["_rc"], 1)
        self.assertFalse(r["ok"])
        for key in ("errors", "warnings", "info", "summary"):
            self.assertIn(key, r)
        for f in r["errors"] + r["warnings"] + r["info"]:
            self.assertEqual(set(f) - {"strict"}, {"rule", "code", "severity", "file", "line", "message", "fix"}, f)
        self.assertEqual(r["summary"]["mode"], "all")
        self.assertEqual(r["summary"]["errors"], len(r["errors"]))

    def test_each_expected_file_has_its_rules(self):
        by_file = rules_by_file(self.result)
        for file, rules in self.expected.items():
            if file.startswith("_"):
                continue
            self.assertTrue(set(rules) <= by_file.get(file, set()), f"{file}: expected {rules}, got {sorted(by_file.get(file, set()))}")

    def test_every_static_rule_fires(self):
        fired = {f["rule"] for f in self.result["errors"] + self.result["warnings"] + self.result["info"]}
        static = set(self.expected["_all_rules"]) - set(self.expected["_dynamic"])
        self.assertTrue(static <= fired, f"missing rules: {sorted(static - fired)}")
        self.assertNotIn("L11", fired)

    def test_specific_codes(self):
        r = self.result
        self.assertTrue({"L01.missing", "L08.wikilink", "L08.absolute", "L08.escapes", "L08.no_extension"} <= codes_for(r, "wiki/modules/broken.md"))
        self.assertTrue({"L06.enum", "L06.id", "L06.required", "L06.quartz_key", "L06.unknown_key"} <= codes_for(r, "wiki/concepts/badfm.md"))
        self.assertTrue({"L07.vocabulary", "L07.code_fence", "L07.repo_source", "L07.sentence", "L07.plain_words", "L07.path"} <= codes_for(r, "wiki/product/features/tracking.md"))
        self.assertTrue({"L05.aws_access_key", "L14.hidden", "L14.html_comment"} <= codes_for(r, "wiki/concepts/secret.md"))
        self.assertIn("L13.no_repo_source", codes_for(r, "wiki/concepts/nosource.md"))
        self.assertTrue({"L02.orphan", "L13.unknown_symbol", "L13.missing_path"} <= codes_for(r, "wiki/modules/payments.md"))
        self.assertIn("L04.lines", codes_for(r, "wiki/concepts/toolong.md"))
        self.assertIn("L16.trust", codes_for(r, "wiki/runbooks/restart.md"))
        self.assertIn("L15.duplicate_heading", codes_for(r, "wiki/conventions.md"))
        self.assertIn("L10.log", codes_for(r, "wiki/log.md"))
        self.assertIn("L10.requests", codes_for(r, "wiki/requests.md"))
        self.assertIn("L10.index", codes_for(r, "wiki/index.md"))
        self.assertIn("L12.uncovered_dir", codes_for(r, "web"))
        # staleness: manifest blob differs → stable page → error
        stale = [f for f in r["errors"] if f["code"] == "L03.stale" and f["file"] == "wiki/modules/orders.md"]
        self.assertTrue(stale, "expected L03.stale error on modules/orders.md")
        self.assertIn("symbol_changed", stale[0]["message"])
        # orphan Module is an error (no plan)
        orphan = [f for f in r["errors"] if f["code"] == "L02.orphan" and f["file"] == "wiki/modules/payments.md"]
        self.assertTrue(orphan)

    def test_clean_pages_pass_file_mode(self):
        for rel in self.expected["_clean"]:
            r = run_json("lint", "--file", rel, cwd=self.repo)
            self.assertEqual(r["errors"], [], f"{rel}: {r['errors']}")
        r = run_json("lint", "--file", "wiki/modules/broken.md", cwd=self.repo)
        self.assertEqual(r["_rc"], 1)
        self.assertIn("L01", {f["rule"] for f in r["errors"]})
        self.assertNotIn("L02", {f["rule"] for f in r["errors"] + r["warnings"]})  # not part of the fast subset
        self.assertEqual(run_script("lint", "--file", "README.md", cwd=self.repo).returncode, 2)

    def test_strict_promotes_warnings(self):
        r = run_json("lint", "--file", "wiki/concepts/badfm.md", cwd=self.repo)
        warn_codes = {f["code"] for f in r["warnings"]}
        self.assertIn("L06.unknown_key", warn_codes)
        s = run_json("lint", "--file", "wiki/concepts/badfm.md", "--strict", cwd=self.repo)
        self.assertEqual(s["warnings"], [])
        self.assertIn("L06.unknown_key", {f["code"] for f in s["errors"]})
        self.assertTrue(all(f.get("strict") for f in s["errors"] if f["code"] == "L06.unknown_key"))

    def test_plan_downgrades_planned_targets_and_orphans(self):
        plan = {"schema_version": 1, "clusters": [{"id": "x", "status": "pending", "pages": [{"path": "modules/nope.md", "type": "Module"}]}]}
        write_json(self.repo / "wiki/.wiki-plan.json", plan)
        try:
            r = run_json("lint", "--all", cwd=self.repo)
            planned = [f for f in r["warnings"] if f["code"] == "L01.planned" and f["file"] == "wiki/modules/broken.md"]
            self.assertTrue(planned)
            self.assertFalse([f for f in r["errors"] if f["code"] == "L01.missing" and "nope.md" in f["message"]])
            orphan = [f for f in r["warnings"] if f["code"] == "L02.orphan" and f["file"] == "wiki/modules/payments.md"]
            self.assertTrue(orphan, "orphan error downgraded to warning while the plan is active")
            b = run_json("backlinks", "--all", cwd=self.repo)
            self.assertTrue(b["plan_active"])
            self.assertEqual([o["severity"] for o in b["orphans"] if o["file"] == "modules/payments.md"], ["warning"])
        finally:
            (self.repo / "wiki/.wiki-plan.json").unlink()


class TestDynamicRules(unittest.TestCase):
    def test_fix_is_idempotent(self):
        with TempDir() as tmp:
            repo = fixture_repo(tmp)
            page = repo / "wiki/concepts/messy.md"
            text = ("---\r\ntype: Concept\r\nid: sample/concepts/wrong\r\nschema_version: 1\r\ntitle: Messy\r\ndescription: Needs fixing.\r\n"
                    "audience: [agent, dev]\r\nowner: agent\r\nsources: [{ id: m, resource: \"repo://src/orders/models.py\" }]\r\n"
                    "last_verified_commit: 0000000000000000000000000000000000000000\r\n"
                    "generated: { by: \"copilot-cli/x\", at: 2026-09-01T09:00:00Z }\r\nstatus: draft\r\n---\r\n"
                    "**Problem.** zero​width and trailing spaces.   \r\n[^m]: models")
            page.write_bytes(text.encode("utf-8"))
            r1 = run_json("lint", "--file", "wiki/concepts/messy.md", cwd=repo)
            self.assertTrue({"L06.id", "L14.hidden", "L14.crlf"} <= {f["code"] for f in r1["errors"] + r1["warnings"]})
            r2 = run_json("lint", "--file", "wiki/concepts/messy.md", "--fix", cwd=repo)
            self.assertEqual(r2["summary"]["fixed"], ["concepts/messy.md"])
            fixed = read(page)
            self.assertNotIn("\r", fixed)
            self.assertNotIn("​", fixed)
            self.assertIn("id: sample/concepts/messy\n", fixed)
            self.assertIn("\n---\n# Messy\n", fixed)
            self.assertTrue(fixed.endswith("\n"))
            self.assertFalse(any(l != l.rstrip() for l in fixed.split("\n")))
            r3 = run_json("lint", "--file", "wiki/concepts/messy.md", "--fix", cwd=repo)
            self.assertEqual(r3["summary"]["fixed"], [])
            self.assertEqual(read(page), fixed)
            self.assertFalse({"L06.id", "L14.hidden", "L14.crlf", "L06.h1"} & {f["code"] for f in r3["errors"] + r3["warnings"]})

    def test_ownership_and_churn(self):
        with TempDir() as tmp:
            repo = fixture_repo(tmp)
            base = git_out(repo, "rev-parse", "HEAD")
            write(repo / "wiki/instructions.md", "---\ntype: Instructions\nid: sample/instructions\nschema_version: 1\ntitle: Wiki instructions\n"
                                                 "description: Project brief.\naudience: [agent, dev]\nowner: human\n"
                                                 "generated: { by: \"human:akaveh\", at: 2026-09-01T09:00:00Z }\n---\n# Wiki instructions\n")
            commit_all(repo, "human edits instructions")
            write(repo / "wiki/instructions.md", read(repo / "wiki/instructions.md") + "\nbot edit\n")
            write(repo / "README.md", "bot touched the readme\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "docs(wiki): update\n\nWiki-Update: auto\nWiki-Run: r1")
            r = run_json("lint", "--all", "--base", base, cwd=repo)
            codes = {(f["code"], f["file"]) for f in r["errors"]}
            self.assertIn(("L09.human_page", "wiki/instructions.md"), codes)
            self.assertIn(("L09.outside_wiki", "README.md"), codes)
            # churn: rewrite a page whose sources did not change
            page = repo / "wiki/concepts/outbox.md"
            head, body = read(page).split("\n# Transactional outbox\n", 1)
            write(page, head + "\n# Transactional outbox\n" + "Completely different prose. " * 40 + "\n\n[^outbox]: outbox class\n")
            r = run_json("lint", "--changed", cwd=repo)
            self.assertIn("L17.churn", {f["code"] for f in r["warnings"]})
            self.assertEqual(r["summary"]["mode"], "changed")
            self.assertEqual(r["summary"]["files"], 1)
            s = run_json("lint", "--staged", cwd=repo)
            self.assertEqual(s["summary"]["files"], 0)


if __name__ == "__main__":
    unittest.main()
