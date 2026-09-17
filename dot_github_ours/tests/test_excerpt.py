"""excerpt.py: bounded reads, hunks, symbols, ranges, metering into run.json and the exhausted exit."""
from __future__ import annotations

import json
import unittest

from conftest import SCRIPTS, TempDir, commit_all, git_out, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401


class TestExcerpt(unittest.TestCase):
    def test_modes_and_metering(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            write_json(repo / ".github/wiki.config.json", {"repo": {"id_prefix": "sample"}, "budgets": {"max_excerpt_lines": 10}})
            (repo / "wiki").mkdir()
            run_script("facts", "--only", "symbols", cwd=repo, check=True)
            run_script("manifest", "--init", cwd=repo, check=True)
            commit_all(repo, "wiki")
            # default: first N lines
            res = run_script("excerpt", "src/orders/service.py", cwd=repo)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(res.stdout.startswith("== src/orders/service.py (lines 1-10 of "))
            self.assertIn("-- truncated to 10 of", res.stdout)
            self.assertEqual(sum(1 for l in res.stdout.split("\n") if "| " in l), 10)
            # explicit range and JSON shape
            r = run_json("excerpt", "src/orders/api.py", "--lines", "8-9", cwd=repo)
            self.assertEqual(r["range"], [8, 9])
            self.assertEqual(r["lines"], 2)
            self.assertIn('    8| router = APIRouter(prefix="/v1/orders", tags=["orders"])', r["text"])
            self.assertEqual(r["bytes"], len(r["text"].encode("utf-8")))
            self.assertFalse(r["budget"]["metered"])
            # symbol from symbols.json
            r = run_json("excerpt", "src/orders/models.py", "--symbol", "Order.transition", cwd=repo)
            self.assertEqual(r["range"][0], 45)
            self.assertIn("def transition(self, new_state: OrderState) -> None:", r["text"])
            self.assertEqual(run_script("excerpt", "src/orders/models.py", "--symbol", "Nope", cwd=repo).returncode, 2)
            self.assertEqual(run_script("excerpt", "nope.py", cwd=repo).returncode, 2)
            # hunks: nothing changed since the checkpoint → first lines with a note
            r = run_json("excerpt", "src/orders/service.py", "--hunks", cwd=repo)
            self.assertIn("no changes since the checkpoint", r["note"])
            self.assertEqual(r["hunks"], [])
            svc = repo / "src/orders/service.py"
            write(svc, read(svc).replace("MAX_LINES_PER_ORDER = 50", "MAX_LINES_PER_ORDER = 60"))
            commit_all(repo, "bump")
            r = run_json("excerpt", "src/orders/service.py", "--hunks", "--context", "2", cwd=repo)
            self.assertEqual(len(r["hunks"]), 1)
            self.assertLessEqual(r["hunks"][0]["a"], 9)
            self.assertGreaterEqual(r["hunks"][0]["b"], 9)
            self.assertIn("+MAX_LINES_PER_ORDER = 60", r["text"])
            self.assertIn("-MAX_LINES_PER_ORDER = 50", r["text"])
            # metering into run.json
            git_dir = repo / ".git"
            write_json(git_dir / "wiki/run.json", {"run_id": "r1", "mode": "update", "budget": {"max_source_bytes": 400, "bytes_read": 0}})
            r = run_json("excerpt", "src/orders/api.py", "--lines", "1-5", cwd=repo)
            self.assertTrue(r["budget"]["metered"])
            self.assertEqual(r["budget"]["bytes_read"], r["bytes"])
            self.assertEqual(read_json(git_dir / "wiki/run.json")["budget"]["bytes_read"], r["bytes"])
            self.assertEqual(read_json(git_dir / "wiki/run.json")["budget"]["excerpt_lines_used"], 5)
            r = run_json("excerpt", "src/orders/service.py", "--lines", "1-10", cwd=repo)
            self.assertTrue(r["budget"]["exhausted"])
            self.assertTrue(read_json(git_dir / "wiki/run.json")["over_budget"])
            res = run_script("excerpt", "src/orders/api.py", "--lines", "1-2", cwd=repo)
            self.assertEqual(res.returncode, 3)
            self.assertEqual(res.stdout, "")
            self.assertEqual(len(res.stderr.strip().split("\n")), 1)
            self.assertIn("budget exhausted", res.stderr)


if __name__ == "__main__":
    unittest.main()
