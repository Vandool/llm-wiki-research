"""config: defaults, validation, dotted access, scaffold placeholders, the config.py CLI, detect.py and template.py."""
from __future__ import annotations

import json
import os
import unittest

from conftest import FIXTURES, SCRIPTS, TempDir, make_repo, read_json, run_json, run_script, write, write_json  # noqa: F401
from wikilib import cli, config as wconfig


class TestConfigLib(unittest.TestCase):
    def test_defaults_and_dotted_access(self):
        d = wconfig.defaults()
        self.assertEqual(d["wiki_dir"], "wiki")
        self.assertEqual(wconfig.get_dotted(d, "budgets.max_lines.Module"), 200)
        self.assertIsNone(wconfig.get_dotted(d, "nope.x"))
        wconfig.set_dotted(d, "repo.slug", "g/p")
        self.assertEqual(d["repo"]["slug"], "g/p")

    def test_merge_and_unknown_keys_warn(self):
        data = wconfig.merge_defaults({"max_pages": 3, "extra_key": 1, "_comment": "x", "budgets": {"max_lines": {"Custom": 10}}})
        self.assertEqual(data["max_pages"], 3)
        self.assertEqual(data["budgets"]["max_lines"]["Module"], 200)
        self.assertEqual(data["budgets"]["max_lines"]["Custom"], 10)
        self.assertNotIn("_comment", data)
        warnings = wconfig.validate(data)
        self.assertTrue(any("unknown key extra_key" in w for w in warnings))

    def test_wrong_type_raises(self):
        with self.assertRaises(cli.ConfigError):
            wconfig.validate(wconfig.merge_defaults({"max_pages": "eight"}))
        with self.assertRaises(cli.ConfigError):
            wconfig.validate(wconfig.merge_defaults({"po_layer": "yes"}))
        with self.assertRaises(cli.ConfigError):
            wconfig.validate(wconfig.merge_defaults({"commit_policy": "yolo"}))
        with self.assertRaises(cli.ConfigError):
            wconfig.validate(wconfig.merge_defaults({"wiki_dir": "../outside"}))

    def test_branch_and_mr_forces_worktree(self):
        data = wconfig.merge_defaults({"commit_policy": "branch-and-mr"})
        wconfig.validate(data)
        self.assertEqual(data["isolation"], "worktree")

    def test_load_missing_uses_defaults(self):
        with TempDir() as tmp:
            cfg = wconfig.load(tmp, warn=False)
            self.assertEqual(cfg.wiki_dir, "wiki")
            self.assertTrue(cfg.warnings)
            with self.assertRaises(cli.ConfigError):
                wconfig.load(tmp, strict=True, warn=False)

    def test_load_env_override_and_save(self):
        with TempDir() as tmp:
            p = write_json(tmp / "custom.json", {"max_pages": 2, "repo": {"slug": "g/p"}})
            os.environ["WIKI_CONFIG"] = str(p)
            try:
                cfg = wconfig.load(tmp, warn=False)
            finally:
                del os.environ["WIKI_CONFIG"]
            self.assertEqual(cfg.get("max_pages"), 2)
            self.assertEqual(cfg.id_prefix, "p")
            cfg.set("max_pages", 4)
            cfg.save()
            self.assertEqual(read_json(p)["max_pages"], 4)

    def test_scaffold(self):
        self.assertEqual(wconfig.scaffold("a {{x}} b {{ y }} {{unknown}}", {"x": 1, "y": "z"}), "a 1 b z {{unknown}}")
        with TempDir() as tmp:
            cfg = wconfig.load(tmp, warn=False)
            cfg.set("repo.slug", "group/proj")
            cfg.set("repo.team", "@t")
            v = wconfig.scaffold_vars(cfg, head="abc", user="me", date="2026-09-07T00:00:00Z")
            self.assertEqual(v["id_prefix"], "proj")
            self.assertEqual(v["site_title"], "proj wiki")
            self.assertEqual(v["team"], "t")
            self.assertEqual(v["head"], "abc")
            self.assertEqual(v["model"], "claude-sonnet-4.6")

    def test_coerce(self):
        self.assertEqual(wconfig.coerce_value("5"), 5)
        self.assertEqual(wconfig.coerce_value("true"), True)
        self.assertEqual(wconfig.coerce_value('["a"]'), ["a"])
        self.assertEqual(wconfig.coerce_value("plain"), "plain")


class TestConfigCli(unittest.TestCase):
    def test_get_set_validate(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            res = run_script("config", "get", "models.incremental", cwd=repo)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout.strip(), "gpt-5-mini")
            self.assertEqual(run_json("config", "get", "budgets.max_lines.Module", cwd=repo)["value"], 200)
            res = run_script("config", "set", "max_pages", "5", cwd=repo)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(read_json(repo / ".github/wiki.config.json")["max_pages"], 5)
            self.assertEqual(run_script("config", "get", "max_pages", cwd=repo).stdout.strip(), "5")
            res = run_script("config", "set", "max_pages", "many", cwd=repo)
            self.assertEqual(res.returncode, 2)
            res = run_script("config", "get", "no.such.key", cwd=repo)
            self.assertEqual(res.returncode, 2)
            self.assertEqual(run_script("config", "validate", cwd=repo).returncode, 0)
            self.assertEqual(run_json("config", "quartz-ignore", cwd=repo)["ignore"][:1], ["private"])
            # --json accepted before and after the sub-command
            self.assertTrue(run_json("config", "--json", "get", "wiki_dir", cwd=repo)["ok"])

    def test_init_from_detect_and_answers(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            det = run_json("detect", cwd=repo)
            self.assertTrue(det["ok"], det)
            self.assertEqual(det["roots"], ["src", "web"])
            self.assertEqual(det["specs"], {"openapi": ["api/openapi.json"], "asyncapi": ["api/asyncapi.json"]})
            self.assertEqual(det["adr_dir"], "docs/adr")
            self.assertEqual(det["codeowners"], "CODEOWNERS")
            self.assertEqual(det["team"], "@sample/platform")
            self.assertEqual(det["branches"]["suggest_staging"], "preprod")
            self.assertEqual(det["test_runner"], "pytest")
            self.assertEqual([s["name"] for s in det["stacks"]], ["python", "node"])
            self.assertIn("fastapi", det["stacks"][0]["frameworks"])
            self.assertIn("express", det["stacks"][1]["frameworks"])
            write_json(tmp / "detect.json", det)
            write_json(tmp / "answers.json", {"repo.slug": "group/orders", "models": {"incremental": "gpt-5-mini"},
                                              "po_layer": True, "pages.site_title": "Orders wiki"})
            res = run_json("config", "init", "--from", str(tmp / "detect.json"), "--answers", str(tmp / "answers.json"),
                           cwd=repo, env={"GIT_AUTHOR_DATE": ""})
            self.assertTrue(res["ok"], res)
            cfg = read_json(repo / ".github/wiki.config.json")
            self.assertEqual(cfg["repo"]["slug"], "group/orders")
            self.assertEqual(cfg["repo"]["id_prefix"], "sample-orders")
            self.assertEqual(cfg["sources"]["include"], ["src", "web"])
            self.assertEqual(cfg["api_spec"]["openapi"], ["api/openapi.json"])
            self.assertEqual(cfg["branches"]["staging"], "preprod")
            self.assertTrue(cfg["po_layer"])
            self.assertEqual(cfg["pages"]["site_title"], "Orders wiki")
            self.assertTrue(cfg["kit"]["installed_at"])
            # second init keeps answers
            run_json("config", "init", "--from", str(tmp / "detect.json"), cwd=repo)
            self.assertEqual(read_json(repo / ".github/wiki.config.json")["repo"]["slug"], "group/orders")


class TestTemplateCli(unittest.TestCase):
    def test_render_with_override_dir(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            tdir = tmp / "templates"
            write(tdir / "concept.md", "---\ntype: Concept\nid: {{id_prefix}}/concepts/{{slug}}\ntitle: {{title}}\n"
                                        "last_verified_commit: {{head}}\ngenerated: { by: \"copilot-cli/{{model}}\", at: {{date}} }\n---\n# {{title}}\n")
            env = {"WIKI_TEMPLATES_DIR": str(tdir)}
            res = run_json("template", "Concept", "--vars", "slug=outbox", "title=Outbox", "model=m1", "--now",
                           "2026-09-07T10:00:00Z", cwd=repo, env=env)
            self.assertTrue(res["ok"], res)
            self.assertIn("id: repo/concepts/outbox", res["text"])
            self.assertIn("title: Outbox", res["text"])
            self.assertIn("at: 2026-09-07T10:00:00Z", res["text"])
            self.assertIn("copilot-cli/m1", res["text"])
            self.assertRegex(res["text"], r"last_verified_commit: [0-9a-f]{40}")
            self.assertEqual(res["headings"][0], "**Problem.**")
            self.assertEqual(res["max_lines"], 120)
            res = run_script("template", "Module", cwd=repo, env=env)
            self.assertEqual(res.returncode, 3, res.stderr)  # file missing in the override dir
            self.assertEqual(run_script("template", "Nope", cwd=repo, env=env).returncode, 2)
            self.assertEqual(run_script("template", "--list", cwd=repo, env=env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
