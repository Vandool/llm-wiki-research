"""facts.py golden behaviour: byte-identical across runs and clones, --check, minimal change set."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from conftest import SCRIPTS, TempDir, commit_all, git, make_repo, read, run_json, run_script, write, write_json  # noqa: F401


def _snapshot(wiki: Path) -> dict[str, str]:
    out = {}
    for p in sorted(wiki.rglob("*")):
        if p.is_file():
            out[p.relative_to(wiki).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class TestFactsGolden(unittest.TestCase):
    def test_idempotent_check_and_minimal_change(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            write_json(repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"},
                                                            "sources": {"include": ["src", "web"]},
                                                            "api_spec": {"openapi": ["api/openapi.json"], "asyncapi": ["api/asyncapi.json"]}})
            commit_all(repo, "chore: wiki config")
            r1 = run_json("facts", "--seed-catalog", cwd=repo)
            self.assertTrue(r1["ok"], r1)
            wiki = repo / "wiki"
            snap1 = _snapshot(wiki)
            self.assertIn("generated/symbols.json", snap1)
            self.assertIn("api/orders.md", snap1)
            self.assertIn("events/orders-placed.md", snap1)
            self.assertIn("decisions/index.md", snap1)
            self.assertIn("catalog.yaml", snap1)
            # frontmatter contract of a generated page
            text = read(wiki / "generated/symbols.md")
            self.assertIn("owner: process", text)
            self.assertIn("audience: [agent, dev]", text)
            self.assertIn('generated: { by: "process:facts.py/1.0.0", at: 2026-09-07T10:00:00Z }', text)
            self.assertIn("id: sample/generated/symbols", text)
            head = git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertIn(f"last_verified_commit: {head}", text)
            self.assertNotIn("\r", text)
            self.assertFalse(any(l != l.rstrip() for l in text.split("\n")))
            # second run: identical bytes, nothing rewritten
            r2 = run_json("facts", cwd=repo)
            self.assertEqual(r2["written"], [])
            self.assertEqual(_snapshot(wiki), snap1)
            self.assertEqual(run_script("facts", "--check", cwd=repo).returncode, 0)
            # a clone on "another machine" produces the same bytes
            clone = tmp / "clone"
            git(repo, "clone", "-q", str(repo), str(clone))
            git(clone, "config", "user.name", "Other")
            git(clone, "config", "user.email", "o@example.com")
            run_json("facts", cwd=clone, env={"GIT_COMMITTER_DATE": "2030-01-01T00:00:00+00:00"})
            snap_clone = _snapshot(clone / "wiki")
            for rel, digest in snap1.items():
                if rel == "catalog.yaml":
                    continue
                self.assertEqual(snap_clone.get(rel), digest, rel)
            # modify one source, commit: only symbols (and the changelog, which lists commits) change
            gw = repo / "src/payments/gateway.py"
            write(gw, read(gw) + "\n\ndef refund(txn: str) -> bool:\n    return True\n")
            res = run_script("facts", "--check", cwd=repo)
            self.assertEqual(res.returncode, 1, "facts read the working tree, so the edit already shows as drift")
            commit_all(repo, "feat: refund", env={"GIT_COMMITTER_DATE": "2026-09-08T10:00:00+00:00", "GIT_AUTHOR_DATE": "2026-09-08T10:00:00+00:00"})
            res = run_json("facts", "--check", cwd=repo)
            self.assertEqual(res["_rc"], 1)
            self.assertIn("generated/symbols.json", res["drift"])
            r3 = run_json("facts", cwd=repo)
            self.assertEqual(sorted(r3["written"]), ["generated/changelog.md", "generated/symbols.json", "generated/symbols.md"])
            snap3 = _snapshot(wiki)
            for rel in snap1:
                if rel not in ("generated/changelog.md", "generated/symbols.json", "generated/symbols.md"):
                    self.assertEqual(snap3[rel], snap1[rel], rel)
            sym = json.loads(read(wiki / "generated/symbols.json"))
            self.assertIn("refund", [s["name"] for s in sym["src/payments/gateway.py"]["symbols"]])
            self.assertIn("2026-09-08T10:00:00Z", read(wiki / "generated/symbols.md"))
            # catalog is seeded once only
            write(wiki / "catalog.yaml", "schema_version: 1\nname: custom\n")
            run_json("facts", "--seed-catalog", cwd=repo)
            self.assertEqual(read(wiki / "catalog.yaml"), "schema_version: 1\nname: custom\n")

    def test_generated_content(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            res = run_json("facts", cwd=repo)
            self.assertTrue(res["ok"])
            wiki = repo / "wiki"
            api = read(wiki / "api/orders.md")
            self.assertIn("type: Contract", api)
            self.assertIn("| POST | `/v1/orders/` | `create_order` | Create an order | `src/orders/api.py::create_order` |", api)
            self.assertIn("provides: [\"api:sample-orders-api\"]", api)
            idx = read(wiki / "api/index.md")
            self.assertTrue(idx.startswith("---\ntitle: API contracts\n---\n# API contracts"))
            self.assertIn("[Payments API](payments.md)", idx)
            ev = read(wiki / "events/orders-placed.md")
            self.assertIn("provides: [\"event:orders.placed\"]", ev)
            self.assertIn("`OrderPlaced`", ev)
            dec = read(wiki / "decisions/index.md")
            self.assertIn("| 0001 | Publish domain events through a transactional outbox | accepted | 2026-01-15 | `docs/adr/0001-outbox.md` |", dec)
            self.assertIn("| 0002 | Keep a thin Express front controller | proposed |", dec)
            decisions = json.loads(read(wiki / "generated/decisions.json"))
            self.assertEqual(decisions["adrs"][0]["number"], "0001")
            owners = json.loads(read(wiki / "generated/owners.json"))
            self.assertEqual(owners["rules"][1], {"pattern": "src/orders/", "owners": ["@sample/orders-team"], "section": ""})
            deps = json.loads(read(wiki / "generated/dependencies.json"))
            files = [m["file"] for m in deps["manifests"]]
            self.assertEqual(files, ["package.json", "pyproject.toml"])
            py = next(m for m in deps["manifests"] if m["file"] == "pyproject.toml")
            self.assertIn("fastapi", [d["name"] for d in py["dependencies"]])
            self.assertIn("pytest", [d["name"] for d in py["dependencies"] if d["group"] == "test"])
            inv = json.loads(read(wiki / "generated/inventory.json"))
            self.assertEqual(inv["dirs"]["src/orders"]["files"], 4)
            self.assertIn("**Read this when:**", read(wiki / "generated/inventory.md"))
            ch = read(wiki / "generated/changelog.md")
            self.assertIn("audience: [dev]", ch)
            self.assertIn("| fixture |", ch)
            specs = json.loads(read(wiki / "generated/specs.json"))
            self.assertEqual(specs["apis"]["sample-orders-api"]["groups"], {"orders": "api/orders.md", "payments": "api/payments.md"})
            self.assertEqual(specs["events"]["orders.paid"]["page"], "events/orders-paid.md")
            # test files are not indexed (coverage.ignore_tests)
            sym = json.loads(read(wiki / "generated/symbols.json"))
            self.assertNotIn("tests/test_x.py", sym)
            self.assertIn("web/src/app.ts", sym)

    def test_sharding_only_and_detect_stacks(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            res = run_json("facts", "--shard-lines", "40", cwd=repo)
            self.assertTrue(res["ok"])
            gen = [g for g in res["generated"] if g.startswith("generated/symbols/")]
            self.assertTrue(gen, res["generated"])
            main = read(repo / "wiki/generated/symbols.md")
            self.assertIn("## Shards", main)
            for g in gen:
                self.assertIn(f"({g[len('generated/'):]})", main)
                self.assertIn("type: Generated", read(repo / "wiki" / g))
            res = run_json("facts", "--only", "decisions,owners", cwd=repo)
            self.assertEqual(sorted(res["generated"]), ["decisions/index.md", "generated/decisions.json", "generated/owners.json", "generated/owners.md"])
            self.assertEqual(run_script("facts", "--only", "bogus", cwd=repo).returncode, 2)
            st = run_json("facts", "--detect-stacks", cwd=repo)
            self.assertEqual([s["name"] for s in st["stacks"]], ["python", "node"])

    def test_wiki_update_commits_excluded_from_changelog(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            write(repo / "wiki/x.md", "x\n")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "docs(wiki): update\n\nWiki-Update: auto")
            run_json("facts", "--only", "changelog", cwd=repo)
            ch = read(repo / "wiki/generated/changelog.md")
            self.assertNotIn("docs(wiki)", ch)
            self.assertIn("| fixture |", ch)


if __name__ == "__main__":
    unittest.main()
