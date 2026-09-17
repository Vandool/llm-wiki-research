"""symbols: Python ast indexer and the conservative regex indexers."""
from __future__ import annotations

import unittest

from conftest import FIXTURES, SCRIPTS  # noqa: F401
from wikilib import symbols

SAMPLE = FIXTURES / "sample-repo"


def _names(idx):
    return [s["name"] for s in idx["symbols"]]


class TestPython(unittest.TestCase):
    def test_routes_with_router_prefix(self):
        idx = symbols.index_file("src/orders/api.py", (SAMPLE / "src/orders/api.py").read_text())
        self.assertEqual(idx["lang"], "python")
        routes = {(r["method"], r["path"]): r["handler"] for r in idx["routes"]}
        self.assertEqual(routes[("POST", "/v1/orders/")], "create_order")
        self.assertEqual(routes[("GET", "/v1/orders/{order_id}")], "get_order")
        self.assertEqual(routes[("POST", "/v1/orders/{order_id}/pay")], "pay_order")
        self.assertIn("router", _names(idx))
        sym = symbols.find_symbol(idx, "get_order")
        self.assertEqual(sym["decorators"], ["router.get('/{order_id}')"])
        self.assertEqual(sym["lines"][0], 23)  # decorator line
        self.assertEqual(sym["signature"], "def get_order(order_id: str) -> dict")

    def test_classes_methods_constants(self):
        idx = symbols.index_file("src/orders/service.py", (SAMPLE / "src/orders/service.py").read_text())
        names = _names(idx)
        self.assertIn("OrderService", names)
        self.assertIn("OrderService.place", names)
        self.assertIn("MAX_LINES_PER_ORDER", names)
        place = symbols.find_symbol(idx, "OrderService.place")
        self.assertEqual(place["kind"], "method")
        self.assertEqual(place["signature"], "def place(self, order_id: str) -> Order")
        self.assertTrue(place["hash"].startswith("sha256:"))
        self.assertLess(place["lines"][0], place["lines"][1])

    def test_hash_ignores_formatting(self):
        a = "def f(x):\n    return x + 1\n"
        b = "def f( x ):\n    return (x + 1)\n"
        c = "def f(x):\n    return x + 2\n"
        self.assertEqual(symbols.symbol_hash(a, "python", "f"), symbols.symbol_hash(b, "python", "f"))
        self.assertNotEqual(symbols.symbol_hash(a, "python", "f"), symbols.symbol_hash(c, "python", "f"))
        self.assertIsNone(symbols.symbol_hash(a, "python", "g"))

    def test_flask_route_and_syntax_error(self):
        src = 'from flask import Blueprint\nbp = Blueprint("x", __name__, url_prefix="/api")\n@bp.route("/items", methods=["GET", "POST"])\ndef items():\n    return []\n'
        idx = symbols.index_python(src)
        self.assertEqual(sorted((r["method"], r["path"]) for r in idx["routes"]), [("GET", "/api/items"), ("POST", "/api/items")])
        bad = symbols.index_python("def (:\n")
        self.assertIn("error", bad)
        self.assertEqual(bad["symbols"], [])


class TestJs(unittest.TestCase):
    def test_express_routes_and_exports(self):
        idx = symbols.index_file("web/src/app.ts", (SAMPLE / "web/src/app.ts").read_text())
        self.assertEqual(idx["lang"], "typescript")
        routes = {(r["method"], r["path"]): r["handler"] for r in idx["routes"]}
        self.assertEqual(routes[("GET", "/health")], "healthHandler")
        self.assertEqual(routes[("POST", "/orders")], "proxyOrder")
        self.assertEqual(routes[("GET", "/orders/:id")], "inline")
        names = _names(idx)
        self.assertIn("healthHandler", names)
        self.assertIn("proxyOrder", names)
        self.assertIn("OrderBody", names)
        fn = symbols.find_symbol(idx, "proxyOrder")
        self.assertEqual(fn["lines"], [14, 20])

    def test_interface_and_const(self):
        idx = symbols.index_file("web/src/config.ts", (SAMPLE / "web/src/config.ts").read_text())
        self.assertEqual([(s["name"], s["kind"]) for s in idx["symbols"]], [("WebConfig", "interface"), ("config", "constant")])

    def test_nestjs(self):
        src = "@Controller('cats')\nexport class CatsController {\n  @Get(':id')\n  findOne(@Param('id') id: string): string {\n    return 'x';\n  }\n  @Post()\n  create() {\n    return 'y';\n  }\n}\n"
        idx = symbols.index_js(src)
        self.assertEqual([(r["method"], r["path"], r["handler"]) for r in idx["routes"]],
                         [("GET", "/cats/:id", "CatsController.findOne"), ("POST", "/cats", "CatsController.create")])
        self.assertIn("CatsController.findOne", _names(idx))

    def test_arrow_function_and_class_method(self):
        src = "export const add = (a: number, b: number): number => {\n  return a + b;\n};\nclass K {\n  run(x) {\n    return x;\n  }\n}\n"
        idx = symbols.index_js(src)
        self.assertEqual(symbols.find_symbol(idx, "add")["lines"], [1, 3])
        self.assertEqual(symbols.find_symbol(idx, "K.run")["kind"], "method")


class TestGoJava(unittest.TestCase):
    def test_go(self):
        src = 'package main\ntype Server struct {\n  x int\n}\nfunc (s *Server) Health(w http.ResponseWriter) {\n  return\n}\nfunc main() {\n  r.HandleFunc("/health", healthHandler)\n  e.GET("/orders", listOrders)\n}\n'
        idx = symbols.index_go(src)
        self.assertEqual(_names(idx), ["Server", "Server.Health", "main"])
        self.assertEqual(symbols.find_symbol(idx, "Server")["kind"], "struct")
        self.assertEqual([(r["method"], r["path"], r["handler"]) for r in idx["routes"]],
                         [("ANY", "/health", "healthHandler"), ("GET", "/orders", "listOrders")])

    def test_java_spring(self):
        src = '@RestController\n@RequestMapping("/api/orders")\npublic class OrderController {\n    @GetMapping("/{id}")\n    public Order get(@PathVariable String id) {\n        return svc.get(id);\n    }\n    @PostMapping\n    public Order create(@RequestBody Order o) {\n        return svc.create(o);\n    }\n}\n'
        idx = symbols.index_java(src)
        self.assertEqual(_names(idx), ["OrderController", "OrderController.get", "OrderController.create"])
        self.assertEqual([(r["method"], r["path"]) for r in idx["routes"]], [("GET", "/api/orders/{id}"), ("POST", "/api/orders")])

    def test_unsupported_language(self):
        self.assertIsNone(symbols.index_file("x.rs", "fn main() {}"))
        self.assertEqual(symbols.language_of("a/b.tsx"), "typescript")
        self.assertIsNone(symbols.language_of("a/b.md"))


if __name__ == "__main__":
    unittest.main()
