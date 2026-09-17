"""plan.py: build (clusters, deps, seeds), commit/validate, next, mark, split, estimate, status."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from conftest import SCRIPTS, TempDir, commit_all, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401

INSTRUCTIONS = """---
type: Instructions
---
# Wiki instructions
## 4. Must-include concepts (one per line; each becomes a Concept page)
- Transactional outbox
- Order state machine

## 5. Must-include flows (one per line; each becomes a How-to or an Architecture "Runtime flows" entry)
- Place and pay an order
- …
"""


def setup_repo(tmp: Path, po: bool = False) -> Path:
    repo = make_repo(tmp)
    write_json(repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"}, "sources": {"include": ["src", "web"]},
                                                    "api_spec": {"openapi": ["api/openapi.json"], "asyncapi": ["api/asyncapi.json"]},
                                                    "po_layer": po, "models": {"bootstrap": "gpt-5-mini"}})
    write(repo / "wiki/instructions.md", INSTRUCTIONS)
    run_script("facts", cwd=repo, check=True)
    commit_all(repo, "wiki: facts")
    return repo


class TestPlan(unittest.TestCase):
    def test_build_commit_next_mark_estimate(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp, po=True)
            b = run_json("plan", "build", cwd=repo)
            self.assertTrue(b["ok"], b)
            clusters = {c["id"]: c for c in b["clusters"]}
            self.assertTrue({"common", "orders", "payments", "web-src", "contract-guides", "concepts", "flows", "product", "overview"} <= set(clusters), sorted(clusters))
            self.assertEqual(clusters["orders"]["deps"], ["common", "payments"])  # from imports, leaves first
            self.assertEqual(clusters["payments"]["deps"], [])
            self.assertEqual(clusters["orders"]["pages"][0]["path"], "modules/orders.md")
            self.assertEqual(clusters["orders"]["pages"][0]["sources"], ["repo://src/orders/"])
            self.assertGreater(clusters["orders"]["estimate"]["source_bytes"], 1000)
            self.assertEqual(clusters["overview"]["deps"], ["*"])
            self.assertEqual([p["path"] for p in clusters["overview"]["pages"]], ["overview.md", "architecture/containers.md", "glossary.md"])
            guides = {p["path"]: p for p in clusters["contract-guides"]["pages"]}
            self.assertIn("api/orders-guide.md", guides)
            self.assertIn("events/orders-placed-guide.md", guides)
            self.assertIn("repo://src/orders/api.py", guides["api/orders-guide.md"]["sources"])
            self.assertIn("orders", clusters["contract-guides"]["deps"])
            self.assertEqual([p["path"] for p in clusters["concepts"]["pages"]], ["concepts/transactional-outbox.md", "concepts/order-state-machine.md"])
            self.assertEqual([p["path"] for p in clusters["flows"]["pages"]], ["howto/place-and-pay-an-order.md"])
            self.assertEqual(clusters["product"]["pages"][0]["audience"], ["po"])
            self.assertEqual(clusters["product"]["deps"], ["*"])
            self.assertTrue(b["no_page"] and b["no_page"][0]["path"] == "scripts/")
            self.assertTrue(Path(b["proposal"]).exists())
            self.assertFalse((repo / "wiki/.wiki-plan.json").exists())
            c = run_json("plan", "commit", "--approved-by", "akaveh", cwd=repo)
            self.assertEqual(c["approved_by"], "human:akaveh")
            plan = read_json(repo / "wiki/.wiki-plan.json")
            self.assertEqual(plan["approved_by"], "human:akaveh")
            self.assertTrue(plan["plan_hash"].startswith("sha256:"))
            self.assertTrue(all(c["status"] == "pending" for c in plan["clusters"]))
            n = run_json("plan", "next", cwd=repo)
            self.assertEqual(n["cluster"]["id"], "common")
            run_json("plan", "mark", "common", "running", "--now", "2026-09-07T10:00:00Z", cwd=repo)
            m = run_json("plan", "mark", "common", "done", "--commit", "abc123", "--pages-written", "1", "--now", "2026-09-07T10:03:00Z", cwd=repo)
            self.assertEqual(m["cluster"]["attempts"], 1)
            self.assertEqual(m["cluster"]["duration_s"], 180)
            self.assertEqual(m["cluster"]["commit"], "abc123")
            self.assertEqual(run_json("plan", "next", cwd=repo)["cluster"]["id"], "payments")
            run_json("plan", "mark", "payments", "done", cwd=repo)
            self.assertEqual(run_json("plan", "next", cwd=repo)["cluster"]["id"], "orders")
            run_json("plan", "mark", "orders", "deferred", "--reason", "budget", cwd=repo)
            nxt = run_json("plan", "next", cwd=repo)
            self.assertNotIn(nxt["cluster"]["id"], ("orders", "overview", "product", "contract-guides"))  # blocked by orders
            for cid in ("web-src", "concepts", "flows"):
                run_json("plan", "mark", cid, "done", cwd=repo)
            run_json("plan", "mark", "orders", "done", cwd=repo)
            self.assertEqual(run_json("plan", "next", cwd=repo)["cluster"]["id"], "contract-guides")
            run_json("plan", "mark", "contract-guides", "done", cwd=repo)
            self.assertIn(run_json("plan", "next", cwd=repo)["cluster"]["id"], ("product", "overview"))
            st = run_json("plan", "status", cwd=repo)
            self.assertEqual(st["counts"]["done"], 7)
            self.assertEqual(st["counts"]["pending"], 2)
            e = run_json("plan", "estimate", cwd=repo)
            self.assertEqual(e["model"], "gpt-5-mini")
            self.assertGreater(e["total_credits"], 0)
            self.assertLess(e["total_credits"], 100)
            s = run_json("plan", "show", "orders", cwd=repo)
            self.assertEqual(s["cluster"]["id"], "orders")
            self.assertEqual(sorted(s["dependency_pages"]), ["modules/common.md", "modules/payments.md"])
            self.assertEqual(run_script("plan", "show", "nope", cwd=repo).returncode, 2)

    def test_validation_and_split(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            bad = {"schema_version": 1, "clusters": [
                {"id": "a", "title": "A", "kind": "module", "deps": ["b"], "pages": [{"path": "modules/a.md", "type": "Module", "sources": ["repo://src/orders/"]}]},
                {"id": "b", "title": "B", "kind": "module", "deps": ["a"], "pages": [{"path": "modules/a.md", "type": "Module", "sources": []}]},
                {"id": "c", "title": "C", "kind": "module", "deps": ["zzz"], "pages": [{"path": "/abs.md", "type": "Module", "sources": []}]}]}
            write_json(tmp / "bad.json", bad)
            res = run_script("plan", "commit", "--from", str(tmp / "bad.json"), cwd=repo)
            self.assertEqual(res.returncode, 2)
            self.assertIn("cycle", res.stderr)
            self.assertIn("planned twice", res.stderr)
            self.assertIn("unknown dep", res.stderr)
            self.assertIn("bad page path", res.stderr)
            self.assertFalse((repo / "wiki/.wiki-plan.json").exists())
            self.assertEqual(run_script("plan", "next", cwd=repo).returncode, 3)
            # split an over-budget cluster
            write_json(repo / ".github/wiki.config.json", {"repo": {"id_prefix": "sample"}, "sources": {"include": ["src"]},
                                                            "budgets": {"max_source_bytes_per_cluster": 1500}})
            b = run_json("plan", "build", cwd=repo)
            ids = [c["id"] for c in b["clusters"]]
            self.assertTrue(any(i.startswith("orders-") for i in ids), ids)  # already split by file groups at build time
            run_json("plan", "commit", "--approved-by", "me", cwd=repo)
            good = {"schema_version": 1, "clusters": [
                {"id": "orders", "title": "Orders", "kind": "module", "deps": [], "pages": [{"path": "modules/orders.md", "type": "Module", "sources": ["repo://src/orders/"]}]},
                {"id": "guides", "title": "G", "kind": "contract", "deps": ["orders"], "pages": [{"path": "api/orders-guide.md", "type": "Contract Guide", "sources": ["api://x"]}]}]}
            write_json(tmp / "good.json", good)
            run_json("plan", "commit", "--from", str(tmp / "good.json"), "--approved-by", "me", cwd=repo)
            s = run_json("plan", "split", "orders", cwd=repo)
            children = [c["id"] for c in s["children"]]
            self.assertGreaterEqual(len(children), 2)
            plan = read_json(repo / "wiki/.wiki-plan.json")
            by_id = {c["id"]: c for c in plan["clusters"]}
            self.assertEqual(by_id["orders"]["status"], "split")
            self.assertEqual(by_id["orders"]["split_into"], children)
            self.assertEqual(by_id["guides"]["deps"], children)
            paths = [p["path"] for cid in children for p in by_id[cid]["pages"]]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertTrue(all(p["sources"] for cid in children for p in by_id[cid]["pages"]))
            self.assertEqual(run_json("plan", "next", cwd=repo)["cluster"]["id"], children[0])
            self.assertEqual(run_script("plan", "mark", "orders", "bogus", cwd=repo).returncode, 2)


if __name__ == "__main__":
    unittest.main()
