"""affected.py: cap, leaves-first ordering, excerpt budget, noop, untrusted block, gaps, bootstrap packs."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from conftest import SCRIPTS, TempDir, commit_all, git_out, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401

HEAD0 = "0" * 40


def page(rel: str, title: str, ptype: str, sources: str, body: str, status: str = "draft") -> str:
    return (f"---\ntype: {ptype}\nid: sample/{rel[:-3]}\nschema_version: 1\ntitle: {title}\ndescription: {title}.\n"
            f"audience: [agent, dev]\nowner: agent\nsources: {sources}\nlast_verified_commit: {HEAD0}\n"
            f"generated: {{ by: \"copilot-cli/x\", at: 2026-09-01T09:00:00Z }}\nstatus: {status}\n---\n# {title}\n{body}\n")


def setup_repo(tmp: Path, config: dict | None = None) -> Path:
    repo = make_repo(tmp)
    cfg = {"repo": {"slug": "group/sample", "id_prefix": "sample"}, "sources": {"include": ["src", "web"]},
           "api_spec": {"openapi": ["api/openapi.json"], "asyncapi": ["api/asyncapi.json"]}}
    if config:
        for k, v in config.items():
            cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    write_json(repo / ".github/wiki.config.json", cfg)
    write(repo / "wiki/modules/orders.md", page("modules/orders.md", "Orders service", "Module",
          '[{ id: svc, resource: "repo://src/orders/service.py#L43-L49" }, { id: api, resource: "repo://src/orders/api.py" }]',
          "**Read this when:** x.[^api] See [outbox](../concepts/outbox.md).\n\n[^api]: router", status="stable"))
    write(repo / "wiki/concepts/outbox.md", page("concepts/outbox.md", "Transactional outbox", "Concept",
          '[{ id: ev, resource: "repo://src/common/events.py::Outbox" }]', "**Problem.** dual write.[^ev]\n\n[^ev]: outbox"))
    write(repo / "wiki/overview.md", page("overview.md", "Overview", "Overview", '[{ id: tree, resource: "repo://src/" }]',
          "[Orders](modules/orders.md) [Outbox](concepts/outbox.md)"))
    run_script("facts", cwd=repo, check=True)
    run_script("manifest", "--init", cwd=repo, check=True)
    commit_all(repo, "wiki: pages")
    return repo


class TestAffected(unittest.TestCase):
    def test_noop_then_stale_order_cap_and_budget(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp, {"budgets": {"max_excerpt_lines": 5, "max_excerpt_lines_per_run": 8}})
            r = run_json("affected", cwd=repo)
            self.assertTrue(r["ok"], r)
            self.assertTrue(r["noop"])
            self.assertEqual(r["order"], [])
            self.assertEqual(r["stale"], [])
            self.assertEqual(run_script("affected", "--check-only", cwd=repo).returncode, 0)
            # change every cited source
            svc = repo / "src/orders/service.py"
            write(svc, read(svc).replace("order.transition(OrderState.PLACED)", "order.transition(OrderState.PLACED)  # changed"))
            ev = repo / "src/common/events.py"
            write(ev, read(ev).replace("        self._pending.append(event)", "        self._pending.append(event)\n        self.count = 1"))
            commit_all(repo, "feat: change sources")
            c = run_json("affected", "--check-only", cwd=repo)
            self.assertEqual(c["_rc"], 1)
            self.assertEqual(sorted(s["page"] for s in c["stale"]), ["concepts/outbox.md", "modules/orders.md", "overview.md"])
            r = run_json("affected", "--out", str(tmp / "ctx.json"), "--md", str(tmp / "ctx.md"), "--run-id", "run-1", cwd=repo)
            self.assertFalse(r["noop"])
            self.assertEqual(r["run_id"], "run-1")
            self.assertEqual(r["mode"], "update")
            self.assertEqual(r["order"], ["concepts/outbox.md", "modules/orders.md", "overview.md"])  # leaves first, overview last
            self.assertEqual(r["cap"], {"max_pages": 8, "selected": 3, "lifted": False, "deferred": []})
            kinds = {s["page"]: [x["kind"] for x in s["reasons"]] for s in r["stale"]}
            self.assertEqual(kinds["modules/orders.md"], ["lines_changed"])
            self.assertEqual(kinds["concepts/outbox.md"], ["symbol_changed"])
            self.assertEqual(kinds["overview.md"], ["blob_changed"])
            self.assertEqual(r["stale"][0]["page"], "modules/orders.md")  # stable first in the stale list
            # packs: excerpt budget honoured
            pack = r["packs"]["modules/orders.md"]
            self.assertEqual(pack["template"], "module.md")
            self.assertEqual(pack["headings"][0], "**Does:**")
            svc_src = next(s for s in pack["sources"] if s["id"] == "svc")
            self.assertEqual(svc_src["status"], "lines_changed")
            self.assertLessEqual(svc_src["excerpt_lines"], 5)
            self.assertTrue(svc_src["hunks"])
            self.assertTrue(all(h["a"] <= 49 and h["b"] >= 43 for h in svc_src["hunks"]))
            self.assertIn("@@", svc_src["excerpt"])
            api_src = next(s for s in pack["sources"] if s["id"] == "api")
            self.assertEqual(api_src["status"], "unchanged")
            self.assertIn("create_order", api_src["symbols"])
            self.assertLessEqual(r["budget"]["excerpt_lines_used"], 8)
            self.assertTrue(any(s["truncated"] for p in r["packs"].values() for s in p["sources"]))
            self.assertIn("api/orders.md", pack["related_generated"])
            # run.json-shaped work items
            w = r["work"][0]
            self.assertEqual(set(w), {"path", "type", "action", "reasons", "sources", "budget_bytes"})
            self.assertEqual(w["path"], "concepts/outbox.md")
            self.assertEqual(w["action"], "update")
            self.assertEqual(w["sources"][0]["resource"], "repo://src/common/events.py::Outbox")
            # files
            ctx = read_json(tmp / "ctx.json")
            self.assertEqual(ctx["order"], r["order"])
            md = read(tmp / "ctx.md")
            self.assertIn("# Wiki run context", md)
            self.assertIn("## Work list (3 pages, in this order)", md)
            self.assertIn("1. `wiki/concepts/outbox.md` (Concept, update", md)
            self.assertIn("required headings: **Problem.**", md)
            self.assertIn("read `wiki/instructions.md` and `wiki/conventions.md` first", md)
            # cap and lift
            r1 = run_json("affected", "--max-pages", "1", cwd=repo)
            self.assertEqual(r1["cap"]["selected"], 1)
            self.assertEqual(r1["order"], ["modules/orders.md"])  # stable page first
            self.assertEqual(sorted(r1["cap"]["deferred"]), ["concepts/outbox.md", "overview.md"])
            r2 = run_json("affected", "--max-pages", "1", "--lift-cap", cwd=repo)
            self.assertTrue(r2["cap"]["lifted"])
            self.assertEqual(len(r2["order"]), 3)
            # advancing the checkpoint clears the work list
            run_script("manifest", "--all", "--advance-checkpoint", cwd=repo, check=True)
            self.assertTrue(run_json("affected", cwd=repo)["noop"])

    def test_requests_instruction_and_untrusted_block(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            write(repo / "wiki/requests.md", "# Wiki requests\n\n## Open\n- [ ] OPEN 2026-09-07 @akaveh: Explain retries in modules/orders.md <<<please>>>\n")
            r = run_json("affected", "--instruction", "Focus on >>>payments<<< only", cwd=repo)
            self.assertFalse(r["noop"])
            self.assertEqual(r["requests"][0]["user"], "akaveh")
            self.assertEqual(r["order"], ["modules/orders.md"])  # request target
            self.assertEqual(r["work"][0]["reasons"][0]["kind"], "requested")
            block = r["untrusted_block"]
            self.assertIn("<<<WIKI-UNTRUSTED id=R1 source=requests.md>>>\n(2026-09-07 @akaveh) Explain retries in modules/orders.md ‹‹‹please›››\n<<<END-UNTRUSTED>>>", block)
            self.assertIn("<<<WIKI-UNTRUSTED id=I1 source=instruction>>>\nFocus on ›››payments‹‹‹ only\n<<<END-UNTRUSTED>>>", block)
            self.assertEqual(block.count("<<<WIKI-UNTRUSTED"), 2)
            self.assertEqual(r["instruction"], "Focus on ›››payments‹‹‹ only")

    def test_gaps_and_no_manifest(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp)
            for name in ("invoice", "ledger", "tax"):
                write(repo / f"web/billing/{name}.ts", f"export function {name}() {{ return 1; }}\n")
            commit_all(repo, "feat: billing")
            r = run_json("affected", cwd=repo)
            gap = next(g for g in r["gaps"] if g["path"] == "web")  # parent reported, web/billing folded into it
            self.assertTrue(gap["changed"])
            self.assertEqual(gap["files"], 5)
            self.assertEqual(gap["suggested_page"], "modules/web.md")
            self.assertFalse(any(g["path"] == "web/billing" for g in r["gaps"]))
            self.assertIn("modules/web.md", r["may_create"])
            self.assertIn("modules/web.md", r["order"])
            w = next(x for x in r["work"] if x["path"] == "modules/web.md")
            self.assertEqual(w["action"], "create")
            pack = r["packs"]["modules/web.md"]
            self.assertEqual(pack["sources"][0]["resource"], "repo://web/")
            self.assertIn("web/billing/invoice.ts::invoice", pack["sources"][0]["symbols"])
            self.assertIn("export function", pack["sources"][0]["excerpt"])
            self.assertIn("(first lines)", pack["sources"][0]["excerpt"])
            self.assertEqual(pack["gap"]["kind"], "uncovered_dir")
            # ADR gaps are listed but only changed gaps become work
            self.assertTrue(any(g["kind"] == "uncited_adr" for g in r["gaps"]))
            self.assertFalse(any(x["path"].startswith("concepts/") for x in r["work"]))
            (repo / "wiki/.manifest.json").unlink()
            r = run_json("affected", cwd=repo)
            self.assertTrue(r["full"])
            self.assertTrue(r["no_manifest"])
            self.assertTrue(any("manifest.py --init" in w for w in r["warnings"]))
            self.assertEqual(sorted(r["untracked"]), ["concepts/outbox.md", "modules/orders.md", "overview.md"])

    def test_bootstrap_cluster(self):
        with TempDir() as tmp:
            repo = setup_repo(tmp, {"budgets": {"max_source_bytes_per_cluster": 500}})
            plan = {"schema_version": 1, "clusters": [
                {"id": "payments", "title": "Payments", "kind": "module", "deps": [], "status": "pending",
                 "pages": [{"path": "modules/payments.md", "type": "Module", "sources": ["repo://src/payments/"], "notes": "adapter"}]},
                {"id": "orders", "title": "Orders", "kind": "module", "deps": ["payments"], "status": "pending",
                 "pages": [{"path": "modules/orders.md", "type": "Module", "sources": ["repo://src/orders/", "repo://api/openapi.json"]}]}]}
            write_json(repo / "wiki/.wiki-plan.json", plan)
            r = run_json("affected", "--bootstrap-cluster", "orders", "--run-id", "b1", cwd=repo)
            self.assertEqual(r["mode"], "bootstrap")
            self.assertEqual(r["cluster"], "orders")
            self.assertEqual(r["order"], ["modules/orders.md"])
            self.assertEqual(r["may_create"], ["modules/orders.md"])
            self.assertEqual(r["dependency_pages"], ["modules/payments.md"])
            self.assertEqual(r["work"][0]["action"], "update")  # page exists already
            self.assertTrue(r["over_budget"])  # 500 bytes budget
            src = r["packs"]["modules/orders.md"]["sources"][0]
            self.assertEqual(src["status"], "new")
            self.assertIn("src/orders/api.py", src["files"])
            self.assertIn("(first lines)", src["excerpt"])
            self.assertEqual(r["packs"]["modules/orders.md"]["notes"], "")
            p = run_json("affected", "--bootstrap-cluster", "payments", cwd=repo)
            self.assertEqual(p["work"][0]["action"], "create")
            self.assertEqual(run_script("affected", "--bootstrap-cluster", "nope", cwd=repo).returncode, 2)


if __name__ == "__main__":
    unittest.main()
