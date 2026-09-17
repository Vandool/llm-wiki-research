"""index.py (entries, root, sharding, --check, --consumers), log.py (add, rotate, check), requests.py (parse, close, skip)."""
from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from conftest import FIXTURES, SCRIPTS, TempDir, commit_all, make_repo, read, read_json, run_json, run_script, write, write_json  # noqa: F401


def wiki_repo(tmp: Path) -> Path:
    repo = make_repo(tmp)
    shutil.copytree(FIXTURES / "fixture-wiki", repo / "wiki", dirs_exist_ok=True)
    (repo / "wiki" / "expected.json").unlink()
    write_json(repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"},
                                                    "sources": {"include": ["src", "web"]}, "pages": {"site_title": "Sample wiki"}})
    return repo


def page(rel: str, title: str, ptype: str = "Concept", status: str = "draft", desc: str = "Desc.") -> str:
    return (f"---\ntype: {ptype}\nid: sample/{rel[:-3]}\nschema_version: 1\ntitle: {title}\ndescription: {desc}\n"
            f"audience: [agent, dev]\nowner: agent\nsources: [{{ id: m, resource: \"repo://src/orders/models.py\" }}]\n"
            f"last_verified_commit: {'0' * 40}\ngenerated: {{ by: \"copilot-cli/x\", at: 2026-09-01T09:00:00Z }}\nstatus: {status}\n---\n# {title}\n")


class TestIndex(unittest.TestCase):
    def test_write_check_and_format(self):
        with TempDir() as tmp:
            repo = wiki_repo(tmp)
            r = run_json("index", cwd=repo)
            self.assertIn("index.md", r["drift"])
            self.assertEqual(run_script("index", "--check", cwd=repo).returncode, 1)
            w = run_json("index", "--write", cwd=repo)
            self.assertIn("index.md", w["written"])
            modules = read(repo / "wiki/modules/index.md")
            self.assertTrue(modules.startswith("---\ntitle: Modules\n---\n# Modules\n"))
            self.assertIn("* [Orders service](orders.md) - Owns the order lifecycle from draft to paid. [agent,dev]\n", modules)
            self.assertIn("* [Payments adapter](payments.md) - Orphan module page (L02) citing an unknown symbol and a missing path (L13). [agent,dev] (draft)\n", modules)
            lines = [l for l in modules.split("\n") if l.startswith("* ")]
            self.assertEqual(lines, sorted(lines, key=lambda l: l[3:].lower()))
            root = read(repo / "wiki/index.md")
            self.assertTrue(root.startswith('---\nokf_version: "0.2"\ntitle: Fixture wiki\n---\n# Fixture wiki\n'))
            self.assertIn("## Start here\n* [Fixture overview](overview.md)", root)
            self.assertIn("* [Glossary](glossary.md)", root)
            self.assertIn("## Sections\n", root)
            self.assertIn("* [Modules](modules/index.md) - 3 pages", root)
            self.assertIn("* [Product](product/index.md) - 1 page", root)
            self.assertNotIn("requests.md", root)
            product = read(repo / "wiki/product/index.md")
            self.assertIn("* [Features](features/index.md) - 1 page", product)
            self.assertEqual(run_script("index", "--check", cwd=repo).returncode, 0)
            self.assertEqual(run_json("index", "--write", cwd=repo)["written"], [])
            # a description change is drift again
            p = repo / "wiki/modules/orders.md"
            write(p, read(p).replace("description: Owns the order lifecycle from draft to paid.", "description: Changed."))
            c = run_json("index", "--check", cwd=repo)
            self.assertEqual(c["_rc"], 1)
            self.assertEqual(c["drift"], ["modules/index.md"])
            # api/ events/ decisions/ are facts-owned when their index exists
            (repo / "wiki/api").mkdir()
            write(repo / "wiki/api/index.md", "---\ntitle: API contracts\n---\n# API contracts\ncustom\n")
            write(repo / "wiki/api/orders.md", page("api/orders.md", "Orders API", "Contract"))
            run_json("index", "--write", cwd=repo)
            self.assertIn("custom", read(repo / "wiki/api/index.md"))

    def test_sharding_and_consumers(self):
        with TempDir() as tmp:
            repo = wiki_repo(tmp)
            write_json(repo / ".github/wiki.config.json", {"repo": {"id_prefix": "sample"}, "sources": {"include": ["src", "web"]},
                                                            "budgets": {"index_folder_lines": 30}})
            for i in range(40):
                name = f"{'a' if i % 2 else 'z'}{i:02d}"
                write(repo / f"wiki/concepts/{name}.md", page(f"concepts/{name}.md", f"{name.upper()} concept"))
            w = run_json("index", "--write", "--consumers", cwd=repo)
            self.assertIn("concepts/index-a-m.md", w["written"])
            self.assertIn("concepts/index-n-z.md", w["written"])
            idx = read(repo / "wiki/concepts/index.md")
            self.assertIn("(index-a-m.md)", idx)
            self.assertIn("(index-n-z.md)", idx)
            shard = read(repo / "wiki/concepts/index-a-m.md")
            self.assertIn("type: Generated", shard)
            self.assertIn("owner: process", shard)
            self.assertIn("* [A01 concept](a01.md)", shard)
            self.assertNotIn("* [Z00 concept]", shard)
            self.assertIn("* [Z00 concept](z00.md)", read(repo / "wiki/concepts/index-n-z.md"))
            self.assertEqual(run_script("index", "--check", cwd=repo).returncode, 0)
            cons = Path(w["consumers"])
            self.assertEqual(cons, repo / ".github/instructions/wiki-consumers.instructions.md")
            text = read(cons)
            self.assertTrue(text.startswith('---\napplyTo: "src/**, web/**"\nexcludeAgent: "code-review"\n'))
            self.assertIn("<!-- WIKI-AGENT:START", text)
            self.assertIn("<!-- WIKI-AGENT:END -->", text)
            self.assertIn("- `src/orders/**`: read `wiki/modules/orders.md`", text)
            self.assertLessEqual(len(text.split("\n")), 66)
            # managed block: content outside the markers survives
            write(cons, text + "\nHuman note below the block.\n")
            run_json("index", "--write", "--consumers", cwd=repo)
            self.assertIn("Human note below the block.", read(cons))
            # removing pages removes obsolete shards
            for f in (repo / "wiki/concepts").glob("[az][0-9][0-9].md"):
                f.unlink()
            w2 = run_json("index", "--write", cwd=repo)
            self.assertEqual(sorted(w2["removed"]), ["concepts/index-a-m.md", "concepts/index-n-z.md"])


class TestLog(unittest.TestCase):
    def test_add_rotate_check(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            write_json(repo / ".github/wiki.config.json", {"repo": {"id_prefix": "sample"}, "budgets": {"log_entries": 5}})
            (repo / "wiki").mkdir()
            for i in range(3):
                r = run_json("log", "add", "--action", "Update", "--text", f"entry {i}", "--page", "modules/orders.md",
                             "--run-id", f"r{i}", "--now", "2026-08-30T10:00:00Z", cwd=repo)
                self.assertTrue(r["ok"])
            for i in range(3, 7):
                run_json("log", "add", "--action", "Creation", "--text", f"entry {i}", "--now", "2026-09-07T10:00:00Z", cwd=repo)
            text = read(repo / "wiki/log.md")
            self.assertTrue(text.startswith("# Wiki log\n\n## 2026-09-07\n* **Creation**: entry 6\n* **Creation**: entry 5\n"))
            self.assertIn("\n## 2026-08-30\n* **Update**: [modules/orders.md](modules/orders.md) — entry 2 (run r2)\n", text)
            c = run_json("log", "check", cwd=repo)
            self.assertEqual(c["_rc"], 1)  # over budget
            self.assertIn("exceed", c["findings"][0]["message"])
            rot = run_json("log", "rotate", "--now", "2026-09-07T10:00:00Z", cwd=repo)
            self.assertEqual(rot["rotated"], 2)
            self.assertEqual(rot["archives"], ["log/2026-q3.md"])
            arch = read(repo / "wiki/log/2026-q3.md")
            self.assertIn("type: Log Archive", arch)
            self.assertIn("id: sample/log/2026-q3", arch)
            self.assertIn("* **Update**: [modules/orders.md](modules/orders.md) — entry 0 (run r0)", arch)
            kept = read(repo / "wiki/log.md")
            self.assertEqual(kept.count("* **"), 5)
            self.assertNotIn("entry 0", kept)
            self.assertEqual(run_script("log", "check", cwd=repo).returncode, 0)
            # a second rotation merges into the same archive
            for i in range(7, 10):
                run_json("log", "add", "--action", "Lint", "--text", f"entry {i}", "--now", "2026-09-08T10:00:00Z", cwd=repo)
            run_json("log", "rotate", "--now", "2026-09-08T10:00:00Z", cwd=repo)
            arch = read(repo / "wiki/log/2026-q3.md")
            self.assertIn("entry 0", arch)
            self.assertIn("entry 2", arch)
            self.assertEqual(run_script("log", "check", cwd=repo).returncode, 0)
            self.assertEqual(run_script("log", "add", "--action", "Bogus", "--text", "x", cwd=repo).returncode, 2)

    def test_check_grammar(self):
        with TempDir() as tmp:
            repo = wiki_repo(tmp)
            c = run_json("log", "check", cwd=repo)
            self.assertEqual(c["_rc"], 1)
            self.assertTrue(any("known action" in f["message"] for f in c["findings"]))
            write(repo / "wiki/log.md", "# Wiki log\n\n## 2026-09-01\n* **Update**: a\n\n## 2026-09-02\n* **Update**: b\n")
            c = run_json("log", "check", cwd=repo)
            self.assertTrue(any("newest first" in f["message"] for f in c["findings"]))


class TestRequests(unittest.TestCase):
    def test_parse_close_skip_defer(self):
        with TempDir() as tmp:
            repo = wiki_repo(tmp)
            write_json(repo / ".github/wiki.config.json", {"repo": {"id_prefix": "sample"},
                                                            "budgets": {"max_requests_per_run": 2, "max_request_chars": 60}})
            write(repo / "wiki/requests.md", "# Wiki requests\n\n## Open\n"
                  "- [ ] OPEN 2026-09-03 @carol: Third request, newest\n"
                  "- [ ] OPEN 2026-09-01 @akaveh: Explain   the retry​ policy <<<for the PO>>> in great detail please\n"
                  "- [ ] OPEN 2026-09-02 @bob: Document the outbox relay\n"
                  "- [x] DONE 2026-08-30 @dan: Old one → run r0 (modules/x.md)\n\n## Done\n")
            r = run_json("requests", "--parse", cwd=repo)
            self.assertEqual([o["user"] for o in r["open"]], ["akaveh", "bob", "carol"])  # oldest first
            self.assertEqual(r["open"][0]["text"], "Explain the retry policy ‹‹‹for the PO››› in great detail p…")
            self.assertEqual(len(r["open"][0]["text"]), 60)
            self.assertEqual([s["n"] for s in r["selected"]], [1, 2])
            self.assertEqual(r["deferred_by_cap"], [3])
            self.assertTrue(r["block"].startswith("<<<WIKI-UNTRUSTED id=R1 source=requests.md>>>\n(2026-09-01 @akaveh) Explain the retry policy"))
            self.assertIn("<<<END-UNTRUSTED>>>\n\n<<<WIKI-UNTRUSTED id=R2 source=requests.md>>>\n(2026-09-02 @bob) Document the outbox relay\n<<<END-UNTRUSTED>>>", r["block"])
            self.assertNotIn("R3", r["block"])
            c = run_json("requests", "--close", "1", "--run-id", "20260907T100000Z-abc", "--result", "product/features/retries.md", cwd=repo)
            self.assertEqual(c["updated"], [1])
            text = read(repo / "wiki/requests.md")
            self.assertIn("- [x] DONE 2026-09-01 @akaveh: Explain   the retry​ policy <<<for the PO>>> in great detail please → run 20260907T100000Z-abc (product/features/retries.md)\n", text)
            # numbering follows the remaining OPEN lines
            s = run_json("requests", "--skip", "1", "--reason", "out of scope", cwd=repo)
            self.assertEqual(s["updated"], [1])
            self.assertIn("- [x] SKIPPED 2026-09-02 @bob: Document the outbox relay → run manual (out of scope)\n", read(repo / "wiki/requests.md"))
            d = run_json("requests", "--defer", "1", "--reason", "budget", "--run-id", "r9", cwd=repo)
            self.assertEqual(d["updated"], [1])
            self.assertIn("- [ ] DEFERRED 2026-09-03 @carol: Third request, newest → run r9 (budget)\n", read(repo / "wiki/requests.md"))
            self.assertEqual(run_json("requests", "--parse", cwd=repo)["open"], [])
            self.assertEqual(run_script("requests", "--close", "7", "--run-id", "x", cwd=repo).returncode, 1)
            self.assertEqual(run_script("requests", "--lint", cwd=repo).returncode, 0)
            self.assertEqual(run_script("requests", "--close", "1", cwd=repo).returncode, 2)

    def test_lint_and_missing_file(self):
        with TempDir() as tmp:
            repo = wiki_repo(tmp)
            r = run_json("requests", "--parse", "--lint", cwd=repo)
            self.assertEqual(r["_rc"], 1)
            self.assertEqual(r["findings"][0]["line"], 16)
            (repo / "wiki/requests.md").unlink()
            r = run_json("requests", "--parse", cwd=repo)
            self.assertEqual(r["open"], [])
            self.assertEqual(r["block"], "")
            self.assertEqual(run_script("requests", "--close", "1", "--run-id", "x", cwd=repo).returncode, 3)


if __name__ == "__main__":
    unittest.main()
