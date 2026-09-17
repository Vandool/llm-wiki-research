"""yamlmini: the YAML subset used by every page's frontmatter."""
from __future__ import annotations

import unittest

from conftest import SCRIPTS  # noqa: F401  (sys.path bootstrap)
from wikilib import yamlmini as y

DOC = """\
type: Module
id: orders/modules/orders
schema_version: 1
title: Orders service
description: Owns the order lifecycle, from checkout to hand-off; exposes api:orders.v2.
audience: [agent, dev]
owner: agent
team: "@shop/checkout"
tags: [backend, python, checkout]   # trailing comment
# full-line comment
provides: []
sources:
  - { id: api-module, resource: "repo://src/orders/api.py", title: HTTP handlers }
  - { id: service, resource: 'repo://src/orders/service.py#L1-L140', title: 'Domain logic' }
  - id: adr-12
    resource: adr://0012
    title: Outbox
last_verified_commit: a1b2c3d4e5f60718293a4b5c6d7e8f9012345678
generated: { by: copilot-cli/gpt-5.2, at: 2026-09-01T09:12:00Z }
verified:
  - { by: "process:wiki-lint/1.0", at: 2026-09-01T09:15:00Z }
status: stable
stale_after: 2026-12-01T00:00:00Z
related: [orders/contracts/orders-v2-guide, payments/modules/payments]
nested:
  a: 1
  b:
    c: true
    d: null
    e:
  list:
  - x
  - "y: z"
empty:
ratio: 1.5
neg: -3
okf_version: "0.2"
quoted: "a \\"b\\" c"
single: 'it''s'
url: https://example.com/x#frag
"""


class TestLoads(unittest.TestCase):
    def setUp(self):
        self.d = y.loads(DOC)

    def test_scalars(self):
        d = self.d
        self.assertEqual(d["type"], "Module")
        self.assertEqual(d["schema_version"], 1)
        self.assertIsInstance(d["schema_version"], int)
        self.assertEqual(d["ratio"], 1.5)
        self.assertEqual(d["neg"], -3)
        self.assertEqual(d["okf_version"], "0.2")  # quoted stays a string
        self.assertEqual(d["team"], "@shop/checkout")
        self.assertEqual(d["quoted"], 'a "b" c')
        self.assertEqual(d["single"], "it's")
        self.assertEqual(d["url"], "https://example.com/x#frag")
        self.assertIsNone(d["empty"])

    def test_timestamps_stay_strings(self):
        self.assertEqual(self.d["generated"]["at"], "2026-09-01T09:12:00Z")
        self.assertEqual(self.d["stale_after"], "2026-12-01T00:00:00Z")
        self.assertEqual(self.d["verified"][0]["at"], "2026-09-01T09:15:00Z")

    def test_flow_collections(self):
        self.assertEqual(self.d["audience"], ["agent", "dev"])
        self.assertEqual(self.d["tags"], ["backend", "python", "checkout"])
        self.assertEqual(self.d["provides"], [])
        self.assertEqual(self.d["generated"], {"by": "copilot-cli/gpt-5.2", "at": "2026-09-01T09:12:00Z"})

    def test_block_list_of_maps(self):
        s = self.d["sources"]
        self.assertEqual(len(s), 3)
        self.assertEqual(s[0], {"id": "api-module", "resource": "repo://src/orders/api.py", "title": "HTTP handlers"})
        self.assertEqual(s[1]["resource"], "repo://src/orders/service.py#L1-L140")
        self.assertEqual(s[2], {"id": "adr-12", "resource": "adr://0012", "title": "Outbox"})

    def test_nested_block_maps_and_lists(self):
        n = self.d["nested"]
        self.assertEqual(n["a"], 1)
        self.assertEqual(n["b"], {"c": True, "d": None, "e": None})
        self.assertEqual(n["list"], ["x", "y: z"])

    def test_comments_are_ignored(self):
        self.assertNotIn("#", str(self.d["tags"]))
        self.assertEqual(y.loads("a: 'x # not a comment'\n")["a"], "x # not a comment")
        self.assertEqual(y.loads("a: x#y\n")["a"], "x#y")

    def test_empty(self):
        self.assertEqual(y.loads(""), {})
        self.assertEqual(y.loads("# only a comment\n"), {})

    def test_booleans_and_null(self):
        d = y.loads("a: true\nb: False\nc: null\nd: ~\ne: yes\n")
        self.assertIs(d["a"], True)
        self.assertIs(d["b"], False)
        self.assertIsNone(d["c"])
        self.assertIsNone(d["d"])
        self.assertEqual(d["e"], "yes")  # YAML 1.2 core: not a boolean

    def test_key_followed_by_list_at_same_indent(self):
        d = y.loads("k:\n- a\n- b\n")
        self.assertEqual(d["k"], ["a", "b"])

    def test_list_item_with_nested_flow(self):
        d = y.loads("k:\n  - [1, 2]\n  - { a: [x, y], b: { c: 1 } }\n")
        self.assertEqual(d["k"], [[1, 2], {"a": ["x", "y"], "b": {"c": 1}}])


class TestErrors(unittest.TestCase):
    def assertYamlError(self, text: str, line: int, fragment: str):
        with self.assertRaises(y.YamlError) as ctx:
            y.loads(text)
        self.assertEqual(ctx.exception.line, line, str(ctx.exception))
        self.assertIn(fragment, ctx.exception.msg)

    def test_block_scalars_rejected(self):
        self.assertYamlError("a: 1\nb: |\n  text\n", 2, "block scalars")
        self.assertYamlError("b: >\n  text\n", 1, "block scalars")

    def test_anchors_rejected(self):
        self.assertYamlError("a: &x 1\n", 1, "anchors")
        self.assertYamlError("a: *x\n", 1, "anchors")

    def test_tabs_rejected(self):
        self.assertYamlError("a:\n\tb: 1\n", 2, "tabs")

    def test_duplicate_key(self):
        self.assertYamlError("a: 1\na: 2\n", 2, "duplicate")

    def test_unterminated_flow(self):
        self.assertYamlError("a: [1, 2\n", 1, "unterminated")
        self.assertYamlError("a: { b: 1\n", 1, "unterminated")

    def test_bad_indentation(self):
        self.assertYamlError("a: 1\n  b: 2\n", 2, "indentation")

    def test_top_level_list(self):
        self.assertYamlError("- a\n", 1, "mapping")


class TestDumps(unittest.TestCase):
    def test_round_trip(self):
        d = y.loads(DOC)
        out = y.dumps(d)
        self.assertEqual(y.loads(out), d)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\t", out)

    def test_flow_style_for_short_collections(self):
        out = y.dumps({"audience": ["agent", "dev"], "generated": {"by": "copilot-cli/x", "at": "2026-09-07T10:00:00Z"}})
        self.assertIn("audience: [agent, dev]\n", out)
        self.assertIn("generated: { by: copilot-cli/x, at: 2026-09-07T10:00:00Z }\n", out)

    def test_block_style_for_long_lists_of_maps(self):
        out = y.dumps({"sources": [{"id": "a", "resource": "repo://x.py", "title": "X"}]})
        self.assertIn('sources:\n  - { id: a, resource: "repo://x.py", title: X }\n', out)

    def test_quoting(self):
        self.assertEqual(y.dump_scalar("0.2"), '"0.2"')
        self.assertEqual(y.dump_scalar("true"), '"true"')
        self.assertEqual(y.dump_scalar("@team"), '"@team"')
        self.assertEqual(y.dump_scalar("human:akaveh"), '"human:akaveh"')
        self.assertEqual(y.dump_scalar("2026-09-07T10:00:00Z"), "2026-09-07T10:00:00Z")
        self.assertEqual(y.dump_scalar("plain words"), "plain words")
        self.assertEqual(y.dump_scalar("a: b"), '"a: b"')
        self.assertEqual(y.dump_scalar(""), '""')
        self.assertEqual(y.dump_scalar(None), "null")
        self.assertEqual(y.dump_scalar(True), "true")
        self.assertEqual(y.loads("k: " + y.dump_scalar('say "hi"'))["k"], 'say "hi"')

    def test_stable_ordering(self):
        d = {"b": 1, "a": 2}
        self.assertEqual(y.dumps(d), "b: 1\na: 2\n")
        self.assertEqual(y.dumps(d), y.dumps(dict(d)))

    def test_empty_collections(self):
        self.assertEqual(y.dumps({"a": [], "b": {}}), "a: []\nb: {}\n")
        self.assertEqual(y.dumps({}), "")


if __name__ == "__main__":
    unittest.main()
