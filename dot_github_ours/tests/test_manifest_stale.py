"""manifest.py and wikilib.manifest.compute_stale: reasons for every kind of source change."""
from __future__ import annotations

import unittest
from pathlib import Path

from conftest import SCRIPTS, TempDir, commit_all, git, git_out, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401
from wikilib import manifest as wmanifest, pages as wpages

FM = """---
type: Module
id: sample/modules/orders
schema_version: 1
title: Orders service
description: Fixture page with every kind of source.
audience: [agent, dev]
owner: agent
sources:
  - { id: svc-range, resource: "repo://src/orders/service.py#L43-L49", title: place() }
  - { id: api, resource: "repo://src/orders/api.py" }
  - { id: transition, resource: "repo://src/orders/models.py::Order.transition" }
  - { id: gateway, resource: "repo://src/payments/gateway.py" }
  - { id: clock, resource: "repo://src/common/clock.py" }
  - { id: pay-api, resource: "repo://src/payments/api.py" }
  - { id: common, resource: "repo://src/common/" }
  - { id: spec, resource: "api://sample-orders-api" }
  - { id: adr, resource: "adr://0001" }
  - { id: changes, resource: "changelog://sample@v1..v2" }
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:00:00Z }
status: stable
---
# Orders service
**Read this when:** testing staleness.[^api]

[^api]: router
"""


def setup_repo(tmp: Path) -> Path:
    repo = make_repo(tmp)
    write_json(repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"}, "sources": {"include": ["src", "web"]}})
    write(repo / "wiki/modules/orders.md", FM)
    write(repo / "wiki/overview.md", "---\ntype: Overview\nid: sample/overview\nschema_version: 1\ntitle: Overview\ndescription: x\n"
                                     "audience: [agent, dev]\nowner: agent\nsources: []\nlast_verified_commit: " + "0" * 40 +
                                     "\ngenerated: { by: \"copilot-cli/x\", at: 2026-09-01T09:00:00Z }\nstatus: draft\n---\n# Overview\n[Orders](modules/orders.md)\n")
    run_script("facts", "--only", "openapi,asyncapi,decisions,symbols", cwd=repo, check=True)
    commit_all(repo, "wiki: pages")
    return repo


def reasons(result: dict, rel: str = "modules/orders.md") -> dict[str, str]:
    return {r["source_id"] or "expired": r["kind"] for r in result["stale"].get(rel, [])}


class TestManifestCli(unittest.TestCase):
    def test_init_shape_and_touched(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            head = git_out(repo, "rev-parse", "HEAD")
            r = run_json("manifest", "--init", cwd=repo)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["checkpoint"], head)
            man = read_json(repo / "wiki/.manifest.json")
            self.assertEqual(man["schema_version"], 1)
            self.assertEqual(man["repo"], "group/sample")
            self.assertEqual(man["checkpoint_commit"], head)
            self.assertIn("api/orders.md", man["generated"])
            e = man["pages"]["modules/orders.md"]
            self.assertEqual(e["type"], "Module")
            self.assertEqual(e["owner"], "agent")
            self.assertTrue(e["page_hash"].startswith("sha256:") and e["body_hash"].startswith("sha256:"))
            self.assertEqual(e["last_verified_commit"], "0" * 40)  # --init does not rewrite pages
            by_id = {s["id"]: s for s in e["sources"]}
            self.assertEqual(by_id["svc-range"]["line_range"], [43, 49])
            self.assertTrue(by_id["svc-range"]["line_hash"].startswith("sha256:"))
            self.assertEqual(by_id["svc-range"]["path"], "src/orders/service.py")
            self.assertEqual(by_id["transition"]["symbol"], "Order.transition")
            self.assertTrue(by_id["transition"]["symbol_hash"].startswith("sha256:"))
            self.assertEqual(len(by_id["api"]["blob_sha"]), 40)
            self.assertEqual(by_id["common"]["kind"], "dir")
            self.assertEqual(by_id["spec"]["path"], "api/openapi.json")
            self.assertTrue(by_id["spec"]["hashable"])
            self.assertEqual(by_id["adr"]["path"], "docs/adr/0001-outbox.md")
            self.assertFalse(by_id["changes"]["hashable"])
            self.assertIsNone(by_id["changes"]["path"])
            # --touched rewrites last_verified_commit / generated.at surgically (HEAD commit = unrelated change)
            write(repo / "README.md", "unrelated\n")
            commit_all(repo, "unrelated")
            head = git_out(repo, "rev-parse", "HEAD")
            page = repo / "wiki/modules/orders.md"
            write(page, read(page).replace("**Read this when:** testing staleness.", "**Read this when:** testing staleness, edited."))
            r = run_json("manifest", "--touched", "--run-id", "run-1", "--model", "gpt-5-mini", "--now", "2026-09-07T12:00:00Z", cwd=repo)
            self.assertEqual(r["pages_updated"], ["modules/orders.md"])
            text = read(page)
            self.assertIn(f"last_verified_commit: {head}\n", text)
            self.assertIn('generated: { by: copilot-cli/gpt-5-mini, at: 2026-09-07T12:00:00Z }\n', text)
            self.assertIn('  - { id: svc-range, resource: "repo://src/orders/service.py#L43-L49", title: place() }\n', text)  # untouched line
            man = read_json(repo / "wiki/.manifest.json")
            self.assertEqual(man["pages"]["modules/orders.md"]["last_verified_commit"], head)
            self.assertEqual(man["pages"]["modules/orders.md"]["run_id"], "run-1")
            self.assertEqual(man["last_run"]["id"], "run-1")
            self.assertEqual(man["last_run"]["result"], "ok")
            # --advance-checkpoint after a commit; --prune drops deleted pages
            commit_all(repo, "wiki: edit")
            new_head = git_out(repo, "rev-parse", "HEAD")
            (repo / "wiki/overview.md").unlink()
            r = run_json("manifest", "--touched", "--advance-checkpoint", "--prune", cwd=repo)
            self.assertEqual(r["checkpoint"], new_head)
            self.assertEqual(r["pruned"], ["overview.md"])


class TestStaleness(unittest.TestCase):
    def compute(self, repo: Path, **kw) -> dict:
        man = wmanifest.load(repo / "wiki")
        pages = wpages.walk(repo / "wiki")
        return wmanifest.compute_stale(man, repo, pages, git_out(repo, "rev-parse", "HEAD"), **kw)

    def test_reasons(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            run_json("manifest", "--init", cwd=repo)
            self.assertEqual(self.compute(repo)["stale"], {})
            # 1. edit outside the line range → not stale (blob changed, lines identical)
            svc = repo / "src/orders/service.py"
            write(svc, read(svc).replace('"""Application service for orders."""', '"""Application service for orders (edited)."""'))
            commit_all(repo, "docstring")
            res = self.compute(repo)
            self.assertNotIn("modules/orders.md", res["stale"])
            self.assertFalse(res["full"])
            self.assertIn("src/orders/service.py", res["modified"])
            # 2. edit inside the range → lines_changed
            write(svc, read(svc).replace("order.transition(OrderState.PLACED)", "order.transition(OrderState.PLACED)  # inside range"))
            commit_all(repo, "inside range")
            self.assertEqual(reasons(self.compute(repo))["svc-range"], "lines_changed")
            run_json("manifest", "--all", "--advance-checkpoint", cwd=repo)
            self.assertEqual(self.compute(repo)["stale"], {})
            # 3. symbol-only reformat → not stale; body change → symbol_changed; removal → symbol_missing
            models = repo / "src/orders/models.py"
            write(models, read(models).replace("        self.state = new_state", "        self.state = (new_state)"))
            commit_all(repo, "reformat")
            self.assertNotIn("transition", reasons(self.compute(repo)))
            write(models, read(models).replace("        self.state = (new_state)", "        self.state = new_state\n        self.touched = True"))
            commit_all(repo, "change transition")
            self.assertEqual(reasons(self.compute(repo))["transition"], "symbol_changed")
            write(models, read(models).replace("    def transition(", "    def move_to("))
            commit_all(repo, "rename transition")
            self.assertEqual(reasons(self.compute(repo))["transition"], "symbol_missing")
            run_json("manifest", "--all", "--advance-checkpoint", cwd=repo)
            # 4. delete, rename, modify, revert, directory
            git(repo, "rm", "-q", "src/payments/gateway.py")
            git(repo, "mv", "src/common/clock.py", "src/common/clocks.py")
            api = repo / "src/orders/api.py"
            write(api, read(api) + "\n# trailing comment\n")
            pay = repo / "src/payments/api.py"
            original = read(pay)
            write(pay, original + "\n# temp\n")
            commit_all(repo, "many changes")
            write(pay, original)
            commit_all(repo, "revert payments api")
            res = self.compute(repo)
            r = reasons(res)
            self.assertEqual(r["gateway"], "missing_source")
            self.assertEqual(r["clock"], "renamed")
            self.assertEqual(r["api"], "blob_changed")
            self.assertEqual(r["common"], "blob_changed")  # directory tree changed by the rename
            self.assertNotIn("pay-api", r)  # reverted → same blob
            self.assertEqual(res["renamed"], {"src/common/clock.py": "src/common/clocks.py"})
            renamed = [x for x in res["stale"]["modules/orders.md"] if x["kind"] == "renamed"][0]
            self.assertEqual(renamed["new_path"], "src/common/clocks.py")
            # spec and ADR sources are hashable through generated indexes
            spec = repo / "api/openapi.json"
            write(spec, read(spec).replace('"version": "1.0.0"', '"version": "1.1.0"'))
            commit_all(repo, "bump spec")
            self.assertEqual(reasons(self.compute(repo))["spec"], "blob_changed")

    def test_full_mode_expired_untracked_and_drift(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            run_json("manifest", "--init", cwd=repo)
            man = read_json(repo / "wiki/.manifest.json")
            man["checkpoint_commit"] = "1" * 40  # unknown commit → full comparison with a warning
            man["pages"]["modules/orders.md"]["sources"][1]["blob_sha"] = "deadbeef" * 5
            man["pages"]["modules/orders.md"]["stale_after"] = "2026-01-01T00:00:00Z"
            man["pages"]["modules/orders.md"]["last_verified_commit"] = "2" * 40
            write_json(repo / "wiki/.manifest.json", man)
            write(repo / "wiki/modules/other.md", FM.replace("sample/modules/orders", "sample/modules/other"))
            res = self.compute(repo)
            self.assertTrue(res["full"])
            self.assertTrue(any("not an ancestor" in w for w in res["warnings"]))
            r = reasons(res)
            self.assertEqual(r["api"], "blob_changed")
            self.assertEqual(r["expired"], "expired")
            self.assertEqual(res["untracked"], ["modules/other.md"])
            self.assertEqual(res["manifest_drift"], ["modules/orders.md"])
            (repo / "wiki/modules/other.md").unlink()
            man["pages"]["modules/gone.md"] = man["pages"]["modules/orders.md"]
            write_json(repo / "wiki/.manifest.json", man)
            self.assertEqual(self.compute(repo)["orphan_entries"], ["modules/gone.md"])
            # --pages with an unknown page is a usage error; --touched with nothing touched is fine
            self.assertEqual(run_script("manifest", "--pages", "modules/nope.md", cwd=repo).returncode, 2)
            write(repo / "README.md", "unrelated change\n")
            commit_all(repo, "unrelated")
            self.assertEqual(run_json("manifest", "--touched", cwd=repo)["pages_updated"], [])


if __name__ == "__main__":
    unittest.main()
