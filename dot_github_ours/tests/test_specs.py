"""specs: OpenAPI / AsyncAPI loaders and grouping."""
from __future__ import annotations

import unittest
from pathlib import Path

from conftest import FIXTURES, SCRIPTS, TempDir, write  # noqa: F401
from wikilib import specs

SAMPLE = FIXTURES / "sample-repo"


class TestOpenApi(unittest.TestCase):
    def setUp(self):
        self.doc = specs.load_spec(SAMPLE / "api/openapi.json")

    def test_kind_and_id(self):
        self.assertEqual(specs.spec_kind(self.doc), "openapi")
        self.assertEqual(specs.api_id(self.doc, "api/openapi.json"), "sample-orders-api")

    def test_operations(self):
        ops = specs.openapi_operations(self.doc)
        self.assertEqual(len(ops), 5)
        get = next(o for o in ops if o["operationId"] == "get_order")
        self.assertEqual(get["method"], "GET")
        self.assertEqual(get["path"], "/v1/orders/{order_id}")
        self.assertEqual(get["parameters"], [{"name": "order_id", "in": "path", "required": True}])
        self.assertEqual(get["responses"], {"200": "OK", "404": "Not found"})
        self.assertEqual(get["tags"], ["orders"])

    def test_grouping_by_tag(self):
        groups = specs.group_operations(specs.openapi_operations(self.doc))
        self.assertEqual(list(groups), ["orders", "payments"])
        self.assertEqual(len(groups["orders"]["ops"]), 4)
        self.assertEqual(groups["payments"]["ops"][0]["operationId"], "list_methods")

    def test_grouping_without_tags_uses_first_segment(self):
        ops = [{"method": "GET", "path": "/v1/things/{id}", "tags": [], "operationId": "a"},
               {"method": "GET", "path": "/other", "tags": [], "operationId": "b"}]
        groups = specs.group_operations(ops)
        self.assertEqual(sorted(groups), ["other", "things"])

    def test_refs_resolved(self):
        doc = {"openapi": "3.1.0", "info": {"title": "T"},
               "components": {"parameters": {"P": {"name": "q", "in": "query"}},
                              "schemas": {"Body": {"type": "object", "properties": {"a": {}}}}},
               "paths": {"/x": {"post": {"parameters": [{"$ref": "#/components/parameters/P"}],
                                         "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Body"}}}},
                                         "responses": {"200": {"$ref": "#/components/responses/Nope"}}}}}}
        op = specs.openapi_operations(doc)[0]
        self.assertEqual(op["parameters"][0]["name"], "q")
        self.assertEqual(op["request_schema"], "Body")


class TestAsyncApi(unittest.TestCase):
    def test_v2_channels(self):
        doc = specs.load_spec(SAMPLE / "api/asyncapi.json")
        self.assertEqual(specs.spec_kind(doc), "asyncapi")
        chans = specs.asyncapi_channels(doc)
        self.assertEqual([c["channel"] for c in chans], ["orders.paid", "orders.payment_declined", "orders.placed"])
        placed = chans[-1]
        self.assertEqual(placed["slug"], "orders-placed")
        self.assertEqual(placed["operations"][0]["action"], "publish")
        self.assertEqual(placed["operations"][0]["message"]["name"], "OrderPlaced")
        self.assertEqual(placed["operations"][0]["message"]["fields"], ["order_id: string", "total_cents: integer"])

    def test_v3_channels(self):
        doc = {"asyncapi": "3.0.0", "info": {"title": "E"},
               "channels": {"userSignedUp": {"address": "user.signedup", "messages": {"UserSignedUp": {"$ref": "#/components/messages/UserSignedUp"}}}},
               "operations": {"sendUserSignedUp": {"action": "send", "channel": {"$ref": "#/channels/userSignedUp"},
                                                   "messages": [{"$ref": "#/components/messages/UserSignedUp"}]}},
               "components": {"messages": {"UserSignedUp": {"name": "UserSignedUp", "payload": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}
        chans = specs.asyncapi_channels(doc)
        self.assertEqual(chans[0]["channel"], "user.signedup")
        self.assertEqual(chans[0]["operations"][0]["action"], "send")
        self.assertEqual(chans[0]["operations"][0]["message"]["fields"], ["id: string"])


class TestLoading(unittest.TestCase):
    def test_yaml_best_effort_and_error_hint(self):
        with TempDir() as tmp:
            p = write(tmp / "openapi.yaml", "openapi: 3.1.0\ninfo:\n  title: Y\npaths:\n  /a:\n    get:\n      operationId: a\n")
            doc = specs.load_spec(p)
            self.assertEqual(specs.openapi_operations(doc)[0]["operationId"], "a")
            bad = write(tmp / "bad.yaml", "openapi: 3.1.0\ninfo: &x\n  title: Y\n")
            with self.assertRaises(specs.SpecError) as ctx:
                specs.load_spec(bad, export_hint="make export-openapi")
            self.assertIn("make export-openapi", str(ctx.exception))
            with self.assertRaises(specs.SpecError):
                specs.load_spec(tmp / "missing.json")

    def test_detect_spec_files(self):
        files = ["api/openapi.json", "docs/asyncapi.yaml", "node_modules/x/openapi.json", "src/swagger-v2.yml", "README.md"]
        self.assertEqual(specs.detect_spec_files(files), {"openapi": ["api/openapi.json", "src/swagger-v2.yml"],
                                                          "asyncapi": ["docs/asyncapi.yaml"]})


if __name__ == "__main__":
    unittest.main()
