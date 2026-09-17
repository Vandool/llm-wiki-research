"""Symbol indexers: Python via `ast` (signatures with `ast.unparse`, line spans, decorators,
`@router.get("/p")` routes incl. `APIRouter(prefix=…)`), conservative regex indexers for
JS/TS/Go/Java incl. Express/NestJS/Spring routes.

Index shape per file (plan §8.6):
  {"lang": "python", "symbols": [{"name", "kind", "lines": [a, b], "signature", "hash", "decorators": []}],
   "routes": [{"method", "path", "handler", "lines": [a, b]}]}

API:
  LANG_BY_EXT, CODE_EXTS, language_of(path)
  index_file(path, text) -> dict | None            None for unsupported languages
  index_python(text) / index_js(text) / index_go(text) / index_java(text)
  find_symbol(file_index, name) -> symbol dict | None
  symbol_hash(text, lang, name) -> str | None     hash of one symbol in a file's text
  symbol_text(text, lang, name) -> (a, b, snippet) | None
"""
from __future__ import annotations

import ast
import re
from typing import Any, Optional

from .textnorm import sha256_text

__all__ = ["LANG_BY_EXT", "CODE_EXTS", "language_of", "index_file", "index_python", "index_js", "index_go",
           "index_java", "find_symbol", "symbol_hash", "symbol_text"]

LANG_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go",
    ".java": "java", ".kt": "kotlin",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".scala": "scala", ".swift": "swift",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
}
CODE_EXTS = set(LANG_BY_EXT)
_INDEXED = {"python", "javascript", "typescript", "go", "java"}
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "websocket", "trace")


def language_of(path: str) -> Optional[str]:
    p = str(path).lower()
    for ext, lang in LANG_BY_EXT.items():
        if p.endswith(ext):
            return lang
    return None


def index_file(path: str, text: str) -> Optional[dict]:
    lang = language_of(path)
    if lang not in _INDEXED:
        return None
    if lang == "python":
        return index_python(text)
    if lang in ("javascript", "typescript"):
        d = index_js(text)
        d["lang"] = lang
        return d
    if lang == "go":
        return index_go(text)
    return index_java(text)


def find_symbol(file_index: Optional[dict], name: str) -> Optional[dict]:
    if not file_index:
        return None
    for s in file_index.get("symbols", []):
        if s.get("name") == name:
            return s
    return None


def _collapsed_hash(snippet: str) -> str:
    return sha256_text(re.sub(r"\s+", " ", snippet).strip())


def symbol_text(text: str, lang: str, name: str) -> Optional[tuple[int, int, str]]:
    idx = index_file("x." + {"python": "py", "javascript": "js", "typescript": "ts", "go": "go", "java": "java"}.get(lang, "py"), text)
    s = find_symbol(idx, name)
    if not s:
        return None
    a, b = s["lines"]
    lines = text.split("\n")
    return a, b, "\n".join(lines[a - 1:b])


def symbol_hash(text: str, lang: str, name: str) -> Optional[str]:
    idx = index_file("x." + {"python": "py", "javascript": "js", "typescript": "ts", "go": "go", "java": "java"}.get(lang, "py"), text)
    s = find_symbol(idx, name)
    return s.get("hash") if s else None


# ---------------------------------------------------------------- python

def _py_signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    return ast.unparse(node).split("\n", 1)[0][:200]


def _py_start(node: ast.AST) -> int:
    decos = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decos])


def _py_const(kw: list, name: str) -> Optional[str]:
    for k in kw:
        if k.arg == name and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
            return k.value.value
    return None


def _py_first_str(call: ast.Call) -> Optional[str]:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return _py_const(call.keywords, "path")


def _join_route(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path or path == "/":
        return prefix + ("/" if path == "/" else "")
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def index_python(text: str) -> dict:
    out: dict = {"lang": "python", "symbols": [], "routes": []}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        out["error"] = f"syntax error: {e}"
        return out
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if fname in ("APIRouter", "Blueprint", "Router"):
                prefix = _py_const(node.value.keywords, "prefix") or _py_const(node.value.keywords, "url_prefix") or ""
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        prefixes[t.id] = prefix

    def add_symbol(node: ast.AST, name: str, kind: str) -> dict:
        decos = [ast.unparse(d) for d in getattr(node, "decorator_list", []) or []]
        sym = {"name": name, "kind": kind, "lines": [_py_start(node), getattr(node, "end_lineno", node.lineno)],
               "signature": _py_signature(node), "hash": sha256_text(ast.unparse(node)), "decorators": decos}
        out["symbols"].append(sym)
        return sym

    def routes_of(node: ast.AST, handler: str) -> None:
        for d in getattr(node, "decorator_list", []) or []:
            if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
                continue
            attr = d.func.attr.lower()
            owner = d.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else (owner.attr if isinstance(owner, ast.Attribute) else "")
            path = _py_first_str(d)
            if path is None:
                continue
            methods: list[str] = []
            if attr in HTTP_METHODS:
                methods = [attr.upper()]
            elif attr in ("route", "api_route"):
                for k in d.keywords:
                    if k.arg == "methods" and isinstance(k.value, (ast.List, ast.Tuple)):
                        methods = [str(e.value).upper() for e in k.value.elts if isinstance(e, ast.Constant)]
                methods = methods or ["GET"]
            else:
                continue
            full = _join_route(prefixes.get(owner_name, ""), path)
            for m in methods:
                out["routes"].append({"method": m, "path": full, "handler": handler,
                                      "lines": [_py_start(node), getattr(node, "end_lineno", node.lineno)]})

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_symbol(node, node.name, "function")
            routes_of(node, node.name)
        elif isinstance(node, ast.ClassDef):
            add_symbol(node, node.name, "class")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = f"{node.name}.{sub.name}"
                    add_symbol(sub, qual, "method")
                    routes_of(sub, qual)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and (t.id.isupper() or t.id in prefixes):
                    kind = "router" if t.id in prefixes else "constant"
                    add_symbol(node, t.id, kind)
    out["symbols"].sort(key=lambda s: (s["lines"][0], s["name"]))
    out["routes"].sort(key=lambda r: (r["lines"][0], r["method"], r["path"]))
    return out


# ---------------------------------------------------------------- brace-language helpers

def _strip_strings_and_comments(line: str) -> str:
    """Rough removal of string literals and // comments so braces inside them are not counted."""
    line = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", '""', line)
    return re.sub(r"//.*$", "", line)


def _block_end(lines: list[str], start: int) -> int:
    """End line (1-based) of a `{…}` block whose opening brace is on/after line `start`."""
    depth = 0
    opened = False
    for i in range(start - 1, len(lines)):
        seg = _strip_strings_and_comments(lines[i])
        for ch in seg:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth <= 0:
                    return i + 1
        if not opened and (seg.rstrip().endswith(";") or i - (start - 1) >= 2):
            return i + 1
    return len(lines)


def _add(out: dict, lines: list[str], name: str, kind: str, start: int, end: int, sig: str, decos: list) -> None:
    snippet = "\n".join(lines[start - 1:end])
    out["symbols"].append({"name": name, "kind": kind, "lines": [start, end], "signature": sig.strip()[:200],
                           "hash": _collapsed_hash(snippet), "decorators": decos})


_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(")
_JS_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
_JS_ARROW = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>")
_JS_EXPORT_CONST = re.compile(r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)")
_JS_TYPE = re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(interface|type|enum)\s+([A-Za-z_$][\w$]*)")
_JS_METHOD = re.compile(r"^\s{2,}(?:(?:public|private|protected|static|async|readonly|override)\s+)*(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\((?:[^()]|\([^()]*\))*\)\s*(?::\s*[^{;=]+)?\{")
_JS_ROUTE = re.compile(r"\b([A-Za-z_$][\w$]*)\.(get|post|put|patch|delete|all|head|options)\(\s*(['\"`])([^'\"`]+)\3\s*(?:,\s*([A-Za-z_$][\w$.]*))?")
_NEST_CTRL = re.compile(r"@Controller\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)")
_NEST_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete|Head|Options|All)\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)")
_JS_DECO = re.compile(r"^\s*@([A-Za-z_$][\w$]*)(\([^)]*\))?")
_JS_RESERVED = {"if", "for", "while", "switch", "catch", "function", "return", "constructor", "else", "do", "try"}


def index_js(text: str) -> dict:
    out: dict = {"lang": "javascript", "symbols": [], "routes": []}
    lines = text.split("\n")
    current_class: Optional[str] = None
    class_end = 0
    nest_prefix = ""
    pending_deco: list[str] = []
    pending_route: Optional[tuple[str, str]] = None
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if i > class_end:
            current_class = None
        dm = _JS_DECO.match(line)
        if dm:
            pending_deco.append(line.strip())
            cm = _NEST_CTRL.search(line)
            if cm:
                nest_prefix = cm.group(1) or ""
            rm = _NEST_ROUTE.search(line)
            if rm:
                pending_route = (rm.group(1).upper(), rm.group(2) or "")
            if line.strip().endswith(")") or "(" not in line:
                continue
        m = _JS_CLASS.match(line)
        if m:
            end = _block_end(lines, i)
            _add(out, lines, m.group(1), "class", i, end, line, pending_deco)
            current_class, class_end = m.group(1), end
            pending_deco = []
            continue
        m = _JS_FUNC.match(line)
        if m:
            end = _block_end(lines, i)
            _add(out, lines, m.group(1), "function", i, end, line, pending_deco)
            pending_deco = []
            continue
        m = _JS_ARROW.match(line)
        if m:
            end = _block_end(lines, i) if "{" in _strip_strings_and_comments(line) else i
            _add(out, lines, m.group(1), "function", i, end, line, pending_deco)
            pending_deco = []
            continue
        m = _JS_TYPE.match(line)
        if m:
            end = _block_end(lines, i) if "{" in line else i
            _add(out, lines, m.group(2), m.group(1), i, end, line, pending_deco)
            pending_deco = []
            continue
        m = _JS_EXPORT_CONST.match(line)
        if m:
            end = _block_end(lines, i) if "{" in _strip_strings_and_comments(line) and not line.rstrip().endswith(";") else i
            _add(out, lines, m.group(1), "constant", i, end, line, pending_deco)
            pending_deco = []
            continue
        if current_class:
            m = _JS_METHOD.match(line)
            if m and m.group(1) not in _JS_RESERVED:
                end = _block_end(lines, i)
                qual = f"{current_class}.{m.group(1)}"
                _add(out, lines, qual, "method", i, end, line, pending_deco)
                if pending_route:
                    method, path = pending_route
                    out["routes"].append({"method": method, "path": _join_route("/" + nest_prefix.strip("/") if nest_prefix else "", path),
                                          "handler": qual, "lines": [i, end]})
                pending_deco = []
                pending_route = None
                continue
        for rm in _JS_ROUTE.finditer(line):
            obj, method, _, path, handler = rm.groups()
            if obj in ("axios", "http", "https", "fetch", "client", "api", "request", "got", "superagent"):
                continue
            end = _block_end(lines, i) if line.rstrip().endswith("{") or line.rstrip().endswith("=> {") else i
            out["routes"].append({"method": method.upper(), "path": path, "handler": handler or "inline",
                                  "lines": [i, end]})
        if line.strip():
            pending_deco = []
    out["symbols"].sort(key=lambda s: (s["lines"][0], s["name"]))
    out["routes"].sort(key=lambda r: (r["lines"][0], r["method"], r["path"]))
    return out


# ---------------------------------------------------------------- go

_GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w+\s+\*?(\w+)\s*\)\s+)?(\w+)\s*\(")
_GO_TYPE = re.compile(r"^type\s+(\w+)\s+(struct|interface|func|\w+)")
_GO_VAR = re.compile(r"^(?:var|const)\s+(\w+)\b")
_GO_ROUTE = re.compile(r"\b(\w+)\.(GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete|HandleFunc|Handle|Methods)\(\s*\"([^\"]+)\"\s*,\s*([\w.]+)")


def index_go(text: str) -> dict:
    out: dict = {"lang": "go", "symbols": [], "routes": []}
    lines = text.split("\n")
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        m = _GO_FUNC.match(line)
        if m:
            name = f"{m.group(1)}.{m.group(2)}" if m.group(1) else m.group(2)
            end = _block_end(lines, i) if "{" in line else i
            _add(out, lines, name, "method" if m.group(1) else "function", i, end, line, [])
        else:
            m = _GO_TYPE.match(line)
            if m:
                end = _block_end(lines, i) if "{" in line else i
                _add(out, lines, m.group(1), m.group(2) if m.group(2) in ("struct", "interface") else "type", i, end, line, [])
            else:
                m = _GO_VAR.match(line)
                if m:
                    _add(out, lines, m.group(1), "constant", i, i, line, [])
        for rm in _GO_ROUTE.finditer(line):
            method = rm.group(2).upper()
            if method in ("HANDLEFUNC", "HANDLE", "METHODS"):
                method = "ANY"
            out["routes"].append({"method": method, "path": rm.group(3), "handler": rm.group(4), "lines": [i, i]})
    out["symbols"].sort(key=lambda s: (s["lines"][0], s["name"]))
    out["routes"].sort(key=lambda r: (r["lines"][0], r["method"], r["path"]))
    return out


# ---------------------------------------------------------------- java

_JAVA_TYPE = re.compile(r"^\s*(?:(?:public|protected|private|abstract|static|final|sealed)\s+)*(class|interface|enum|record)\s+(\w+)")
_JAVA_METHOD = re.compile(r"^\s+(?:(?:public|protected|private|static|final|synchronized|abstract|default|native)\s+)*(?:<[^>]+>\s+)?[\w<>\[\],.?]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w., ]+)?\s*\{")
_JAVA_ANNOT = re.compile(r"^\s*@(\w+)(\([^)]*\))?")
_SPRING_CLASS = re.compile(r"@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"")
_SPRING_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?(?:\"([^\"]*)\")?)?")
_JAXRS_PATH = re.compile(r"@Path\(\s*\"([^\"]*)\"\s*\)")
_JAXRS_METHOD = re.compile(r"^\s*@(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")


def index_java(text: str) -> dict:
    out: dict = {"lang": "java", "symbols": [], "routes": []}
    lines = text.split("\n")
    current_class: Optional[str] = None
    class_end = 0
    prefix = ""
    pending: list[str] = []
    route: Optional[tuple[str, str]] = None
    jax_method: Optional[str] = None
    jax_path: Optional[str] = None
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if i > class_end:
            current_class = None
        am = _JAVA_ANNOT.match(line)
        if am:
            pending.append(line.strip())
            sm = _SPRING_ROUTE.search(line)
            if sm:
                route = (sm.group(1).upper() if sm.group(1) != "Request" else "ANY", sm.group(2) or "")
            jm = _JAXRS_METHOD.match(line)
            if jm:
                jax_method = jm.group(1)
            pm = _JAXRS_PATH.search(line)
            if pm:
                jax_path = pm.group(1)
            if "class " not in line and "interface " not in line:
                continue
        m = _JAVA_TYPE.match(line)
        if m:
            end = _block_end(lines, i)
            _add(out, lines, m.group(2), m.group(1), i, end, line, pending)
            current_class, class_end = m.group(2), end
            cls_prefix = next((_SPRING_CLASS.search(a) for a in pending if _SPRING_CLASS.search(a)), None)
            prefix = cls_prefix.group(1) if cls_prefix else (jax_path or "")
            pending, route, jax_method, jax_path = [], None, None, None
            continue
        if current_class:
            m = _JAVA_METHOD.match(line)
            if m and m.group(1) not in ("if", "for", "while", "switch", "catch", "synchronized"):
                end = _block_end(lines, i)
                qual = f"{current_class}.{m.group(1)}"
                _add(out, lines, qual, "method", i, end, line, pending)
                if route:
                    out["routes"].append({"method": route[0], "path": _join_route(prefix, route[1]), "handler": qual, "lines": [i, end]})
                elif jax_method:
                    out["routes"].append({"method": jax_method, "path": _join_route(prefix, jax_path or ""), "handler": qual, "lines": [i, end]})
                pending, route, jax_method, jax_path = [], None, None, None
                continue
        if line.strip():
            pending, route, jax_method, jax_path = [], None, None, None
    out["symbols"].sort(key=lambda s: (s["lines"][0], s["name"]))
    out["routes"].sort(key=lambda r: (r["lines"][0], r["method"], r["path"]))
    return out
