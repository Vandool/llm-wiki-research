"""frontmatter: split / parse / surgical replace_key / serialize."""
from __future__ import annotations

import unittest

from conftest import SCRIPTS  # noqa: F401
from wikilib import frontmatter as fm
from wikilib import yamlmini

PAGE = """\
---
type: Module
id: proj/modules/orders
schema_version: 1
title: Orders service
description: Owns the order lifecycle.
audience: [agent, dev]
owner: agent
sources:
  - { id: api, resource: "repo://src/orders/api.py", title: HTTP handlers }
  - { id: svc, resource: "repo://src/orders/service.py::OrderService.place" }
last_verified_commit: 0000000000000000000000000000000000000000
generated: { by: "copilot-cli/gpt-5-mini", at: 2026-09-01T09:12:00Z }
status: draft
---
# Orders service
**Read this when:** you touch orders.

Body with --- inside a line and a horizontal rule:

---

[^api]: handlers
"""


class TestSplitParse(unittest.TestCase):
    def test_split(self):
        head, body, n = fm.split(PAGE)
        self.assertTrue(head.startswith("type: Module"))
        self.assertTrue(head.endswith("status: draft"))
        self.assertEqual(n, 15)
        self.assertTrue(body.startswith("# Orders service\n"))
        self.assertIn("\n---\n", body)  # the body's own rule survives

    def test_parse(self):
        d, body = fm.parse(PAGE)
        self.assertEqual(d["type"], "Module")
        self.assertEqual(d["sources"][1]["resource"], "repo://src/orders/service.py::OrderService.place")
        self.assertEqual(d["generated"]["at"], "2026-09-01T09:12:00Z")
        self.assertTrue(body.startswith("# Orders service"))

    def test_no_frontmatter(self):
        self.assertFalse(fm.has_frontmatter("# Title\n"))
        self.assertEqual(fm.split("# Title\n"), ("", "# Title\n", 0))
        self.assertEqual(fm.parse("# Title\n"), ({}, "# Title\n"))

    def test_unterminated(self):
        with self.assertRaises(fm.FrontmatterError):
            fm.split("---\ntype: Module\n# no closing\n")

    def test_crlf(self):
        text = PAGE.replace("\n", "\r\n")
        d, body = fm.parse(text)
        self.assertEqual(d["title"], "Orders service")
        self.assertTrue(body.startswith("# Orders service"))

    def test_get_key(self):
        self.assertEqual(fm.get_key(PAGE, "owner"), "agent")
        self.assertEqual(fm.get_key(PAGE, "audience"), ["agent", "dev"])
        self.assertIsNone(fm.get_key(PAGE, "missing"))
        self.assertIsNone(fm.get_key("# no fm\n", "owner"))


class TestReplaceKey(unittest.TestCase):
    def test_scalar_replaced_in_place(self):
        new = fm.replace_key(PAGE, "last_verified_commit", "f" * 40)
        self.assertIn("last_verified_commit: " + "f" * 40 + "\n", new)
        # exactly one line differs
        diff = [(a, b) for a, b in zip(PAGE.split("\n"), new.split("\n")) if a != b]
        self.assertEqual(len(diff), 1)
        self.assertEqual(len(PAGE.split("\n")), len(new.split("\n")))
        self.assertEqual(fm.parse(new)[0]["last_verified_commit"], "f" * 40)

    def test_nested_flow_map(self):
        new = fm.replace_key(PAGE, "generated.at", "2026-09-07T10:00:00Z")
        self.assertIn('generated: { by: copilot-cli/gpt-5-mini, at: 2026-09-07T10:00:00Z }\n', new)
        self.assertEqual(fm.parse(new)[0]["generated"]["by"], "copilot-cli/gpt-5-mini")
        self.assertEqual(new.count("\n"), PAGE.count("\n"))

    def test_nested_block_map(self):
        text = "---\ntitle: X\ngenerated:\n  by: human:me\n  at: 2020-01-01T00:00:00Z\nstatus: draft\n---\n# X\n"
        new = fm.replace_key(text, "generated.at", "2026-09-07T10:00:00Z")
        self.assertIn("  at: 2026-09-07T10:00:00Z\n", new)
        self.assertEqual(fm.parse(new)[0]["generated"], {"by": "human:me", "at": "2026-09-07T10:00:00Z"})
        self.assertIn("status: draft", new)

    def test_insert_when_missing(self):
        new = fm.replace_key(PAGE, "team", "@shop/checkout")
        d, body = fm.parse(new)
        self.assertEqual(d["team"], "@shop/checkout")
        self.assertEqual(body, fm.parse(PAGE)[1])
        new2 = fm.replace_key(PAGE, "generated2.at", "x")
        self.assertEqual(fm.parse(new2)[0]["generated2"], {"at": "x"})

    def test_body_untouched_and_idempotent(self):
        new = fm.replace_key(PAGE, "status", "stable")
        self.assertEqual(fm.split(new)[1], fm.split(PAGE)[1])
        self.assertEqual(fm.replace_key(new, "status", "stable"), new)

    def test_replace_block_value_with_scalar(self):
        new = fm.replace_key(PAGE, "sources", [])
        d, _ = fm.parse(new)
        self.assertEqual(d["sources"], [])
        self.assertNotIn("repo://src/orders/api.py", new)

    def test_crlf_preserved(self):
        text = PAGE.replace("\n", "\r\n")
        new = fm.replace_key(text, "status", "stable")
        self.assertIn("status: stable\r\n", new)
        self.assertNotIn("stable\n", new.replace("\r\n", ""))

    def test_no_frontmatter_raises(self):
        with self.assertRaises(fm.FrontmatterError):
            fm.replace_key("# no\n", "a", 1)


class TestSerialize(unittest.TestCase):
    def test_round_trip(self):
        d, body = fm.parse(PAGE)
        out = fm.serialize(d, body)
        d2, body2 = fm.parse(out)
        self.assertEqual(d, d2)
        self.assertEqual(body, body2)
        self.assertTrue(out.startswith("---\ntype: Module\n"))

    def test_serialize_uses_yamlmini(self):
        out = fm.serialize({"title": "T", "okf_version": "0.2"}, "# T\n")
        self.assertEqual(out, "---\ntitle: T\nokf_version: \"0.2\"\n---\n# T\n")
        self.assertEqual(yamlmini.loads(fm.split(out)[0])["okf_version"], "0.2")


if __name__ == "__main__":
    unittest.main()
