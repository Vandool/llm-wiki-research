"""Minimal YAML subset reader/writer for page frontmatter (stdlib only).

Supported: `key: scalar`, single/double-quoted strings, unquoted scalars (int, float, true/false,
null; ISO dates and timestamps stay strings), block lists (`- item`, `- { flow map }`, `- key: v`
mapping items), flow lists `[a, b, "c"]`, flow maps `{ id: x, resource: "repo://…" }` (nested),
nested block maps by indentation, `#` comments, empty values (null).

Not supported (loud `YamlError` with the line number): anchors/aliases (`&`, `*`), tags (`!`),
multi-line block scalars (`|`, `>`), multi-line flow collections, tabs for indentation,
duplicate keys.

API: `loads(text) -> dict`, `dumps(obj) -> str` (stable: flow style for short lists/maps, block
otherwise), `dump_scalar(value) -> str`, `dump_flow(value) -> str`, `YamlError(line, msg)`.
"""
from __future__ import annotations

import re
from typing import Any, Optional

__all__ = ["YamlError", "loads", "dumps", "dump_scalar", "dump_flow", "is_timestamp"]


class YamlError(ValueError):
    def __init__(self, line: int, msg: str):
        self.line = line
        self.msg = msg
        super().__init__(f"line {line}: {msg}")


_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[-+]\d{2}:?\d{2})?)?$")
_KEY_PLAIN_RE = re.compile(r"^([^\s'\"{\[#&*!|>][^:#]*?)\s*:(\s+|$)")
_NULLS = ("", "~", "null", "Null", "NULL")
_TRUE = ("true", "True", "TRUE")
_FALSE = ("false", "False", "FALSE")


def is_timestamp(text: str) -> bool:
    return bool(_TS_RE.match(text))


# ---------------------------------------------------------------- scanning helpers

class _Line:
    __slots__ = ("no", "indent", "text")

    def __init__(self, no: int, indent: int, text: str):
        self.no = no
        self.indent = indent
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover
        return f"_Line({self.no}, {self.indent}, {self.text!r})"


def _strip_comment(text: str, lineno: int) -> str:
    """Remove a trailing `# comment` that is outside quotes (must be at start or after whitespace)."""
    quote: Optional[str] = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2
                continue
            if c == quote:
                if quote == "'" and i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        else:
            if c in ("'", '"') and (i == 0 or text[i - 1] in " \t:,[{-"):
                quote = c
            elif c == "#" and (i == 0 or text[i - 1] in " \t"):
                return text[:i].rstrip()
        i += 1
    return text.rstrip()


def _scan(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for no, raw in enumerate(text.splitlines(), 1):
        raw = raw.rstrip("\r")
        stripped = raw.lstrip(" ")
        if stripped.startswith("\t"):
            raise YamlError(no, "tabs are not allowed for indentation")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        content = _strip_comment(stripped, no)
        if not content:
            continue
        lines.append(_Line(no, len(raw) - len(stripped), content))
    return lines


# ---------------------------------------------------------------- scalars

def _to_scalar(text: str) -> Any:
    t = text.strip()
    if t in _NULLS:
        return None
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    if _INT_RE.match(t):
        try:
            return int(t)
        except ValueError:
            return t
    if _FLOAT_RE.match(t) and any(ch in t for ch in ".eE"):
        try:
            return float(t)
        except ValueError:
            return t
    return t


def _parse_quoted(s: str, pos: int, lineno: int) -> tuple[str, int]:
    """Parse a quoted string starting at s[pos] (a quote char). Returns (value, position after quote)."""
    q = s[pos]
    i = pos + 1
    out: list[str] = []
    n = len(s)
    while i < n:
        c = s[i]
        if q == "'":
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            out.append(c)
            i += 1
            continue
        # double quoted
        if c == "\\":
            if i + 1 >= n:
                raise YamlError(lineno, "dangling escape in double-quoted string")
            e = s[i + 1]
            simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0",
                      "b": "\b", "f": "\f", " ": " "}
            if e in simple:
                out.append(simple[e])
                i += 2
                continue
            if e == "u" and i + 5 < n + 1:
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                except ValueError:
                    raise YamlError(lineno, "bad \\u escape")
                i += 6
                continue
            if e == "x":
                try:
                    out.append(chr(int(s[i + 2:i + 4], 16)))
                except ValueError:
                    raise YamlError(lineno, "bad \\x escape")
                i += 4
                continue
            raise YamlError(lineno, f"unsupported escape \\{e}")
        if c == '"':
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise YamlError(lineno, "unterminated quoted string")


def _skip_ws(s: str, pos: int) -> int:
    n = len(s)
    while pos < n and s[pos] in " \t":
        pos += 1
    return pos


def _parse_flow(s: str, pos: int, lineno: int, depth: int = 0) -> tuple[Any, int]:
    """Parse a flow value at s[pos]; returns (value, position after it)."""
    if depth > 32:
        raise YamlError(lineno, "flow nesting too deep")
    pos = _skip_ws(s, pos)
    if pos >= len(s):
        raise YamlError(lineno, "unexpected end of flow value")
    c = s[pos]
    if c == "{":
        return _parse_flow_map(s, pos + 1, lineno, depth)
    if c == "[":
        return _parse_flow_list(s, pos + 1, lineno, depth)
    if c in ("'", '"'):
        val, pos = _parse_quoted(s, pos, lineno)
        return val, pos
    if c in ("&", "*", "!"):
        raise YamlError(lineno, f"anchors, aliases and tags are not supported ({c!r})")
    if c in ("|", ">"):
        raise YamlError(lineno, "multi-line block scalars (| and >) are not supported")
    # plain scalar until a terminator
    start = pos
    n = len(s)
    while pos < n and s[pos] not in ",]}":
        pos += 1
    return _to_scalar(s[start:pos]), pos


def _parse_flow_key(s: str, pos: int, lineno: int) -> tuple[str, int]:
    pos = _skip_ws(s, pos)
    if pos < len(s) and s[pos] in ("'", '"'):
        key, pos = _parse_quoted(s, pos, lineno)
    else:
        start = pos
        while pos < len(s) and s[pos] not in ":,}":
            pos += 1
        key = s[start:pos].strip()
    pos = _skip_ws(s, pos)
    if pos >= len(s) or s[pos] != ":":
        raise YamlError(lineno, f"expected ':' after flow map key {key!r}")
    return key, pos + 1


def _parse_flow_map(s: str, pos: int, lineno: int, depth: int) -> tuple[dict, int]:
    out: dict = {}
    while True:
        pos = _skip_ws(s, pos)
        if pos >= len(s):
            raise YamlError(lineno, "unterminated flow map (multi-line flow collections are not supported)")
        if s[pos] == "}":
            return out, pos + 1
        key, pos = _parse_flow_key(s, pos, lineno)
        pos = _skip_ws(s, pos)
        if pos < len(s) and s[pos] in ",}":
            val: Any = None
        else:
            val, pos = _parse_flow(s, pos, lineno, depth + 1)
        if key in out:
            raise YamlError(lineno, f"duplicate key {key!r}")
        out[key] = val
        pos = _skip_ws(s, pos)
        if pos >= len(s):
            raise YamlError(lineno, "unterminated flow map")
        if s[pos] == ",":
            pos += 1
            continue
        if s[pos] == "}":
            return out, pos + 1
        raise YamlError(lineno, f"unexpected {s[pos]!r} in flow map")


def _parse_flow_list(s: str, pos: int, lineno: int, depth: int) -> tuple[list, int]:
    out: list = []
    while True:
        pos = _skip_ws(s, pos)
        if pos >= len(s):
            raise YamlError(lineno, "unterminated flow list (multi-line flow collections are not supported)")
        if s[pos] == "]":
            return out, pos + 1
        val, pos = _parse_flow(s, pos, lineno, depth + 1)
        out.append(val)
        pos = _skip_ws(s, pos)
        if pos >= len(s):
            raise YamlError(lineno, "unterminated flow list")
        if s[pos] == ",":
            pos += 1
            continue
        if s[pos] == "]":
            return out, pos + 1
        raise YamlError(lineno, f"unexpected {s[pos]!r} in flow list")


def _parse_inline_value(text: str, lineno: int) -> Any:
    """Value written on the same line as its key (or list dash)."""
    t = text.strip()
    if not t:
        return None
    c = t[0]
    if c in ("{", "["):
        val, pos = _parse_flow(t, 0, lineno)
        rest = t[pos:].strip()
        if rest:
            raise YamlError(lineno, f"trailing text after flow collection: {rest!r}")
        return val
    if c in ("'", '"'):
        val, pos = _parse_quoted(t, 0, lineno)
        rest = t[pos:].strip()
        if rest:
            raise YamlError(lineno, f"trailing text after quoted string: {rest!r}")
        return val
    if c in ("|", ">"):
        raise YamlError(lineno, "multi-line block scalars (| and >) are not supported")
    if c in ("&", "*", "!"):
        raise YamlError(lineno, f"anchors, aliases and tags are not supported ({c!r})")
    return _to_scalar(t)


# ---------------------------------------------------------------- block structure

class _Parser:
    def __init__(self, lines: list[_Line]):
        self.lines = lines
        self.i = 0

    def peek(self) -> Optional[_Line]:
        return self.lines[self.i] if self.i < len(self.lines) else None

    def parse_block(self, indent: int) -> Any:
        ln = self.peek()
        if ln is None:
            return None
        if ln.indent != indent:
            raise YamlError(ln.no, f"bad indentation (expected {indent}, got {ln.indent})")
        if _is_seq_item(ln.text):
            return self.parse_seq(indent)
        return self.parse_map(indent)

    def parse_map(self, indent: int) -> dict:
        out: dict = {}
        while True:
            ln = self.peek()
            if ln is None or ln.indent < indent:
                return out
            if ln.indent > indent:
                raise YamlError(ln.no, "unexpected indentation")
            if _is_seq_item(ln.text):
                raise YamlError(ln.no, "list item where a mapping key was expected")
            key, rest = self._split_key(ln)
            if key in out:
                raise YamlError(ln.no, f"duplicate key {key!r}")
            self.i += 1
            if rest.strip():
                out[key] = _parse_inline_value(rest, ln.no)
                nxt = self.peek()
                if nxt is not None and nxt.indent > indent:
                    raise YamlError(nxt.no, "unexpected indentation after a scalar value")
                continue
            nxt = self.peek()
            if nxt is None or nxt.indent < indent:
                out[key] = None
            elif nxt.indent > indent:
                out[key] = self.parse_block(nxt.indent)
            elif _is_seq_item(nxt.text):
                out[key] = self.parse_seq(indent)  # `key:` followed by `- item` at the same indent
            else:
                out[key] = None

    def parse_seq(self, indent: int) -> list:
        out: list = []
        while True:
            ln = self.peek()
            if ln is None or ln.indent < indent:
                return out
            if ln.indent > indent:
                raise YamlError(ln.no, "unexpected indentation")
            if not _is_seq_item(ln.text):
                return out
            item = ln.text[1:]
            if item.startswith(" "):
                item = item[1:]
            item_indent = indent + 2 + (len(item) - len(item.lstrip(" ")))
            item = item.lstrip(" ")
            if not item:
                self.i += 1
                nxt = self.peek()
                if nxt is not None and nxt.indent > indent:
                    out.append(self.parse_block(nxt.indent))
                else:
                    out.append(None)
                continue
            if _looks_like_key(item):
                # `- key: value` → mapping item; re-inject the remainder as a line at item_indent
                self.lines[self.i] = _Line(ln.no, item_indent, item)
                out.append(self.parse_map(item_indent))
                continue
            self.i += 1
            out.append(_parse_inline_value(item, ln.no))
            nxt = self.peek()
            if nxt is not None and nxt.indent > indent:
                raise YamlError(nxt.no, "unexpected indentation after a list item")

    @staticmethod
    def _split_key(ln: _Line) -> tuple[str, str]:
        text = ln.text
        if text[0] in ("'", '"'):
            key, pos = _parse_quoted(text, 0, ln.no)
            rest = text[pos:].lstrip()
            if not rest.startswith(":"):
                raise YamlError(ln.no, "expected ':' after quoted key")
            rest = rest[1:]
            if rest and not rest[0] in " \t":
                raise YamlError(ln.no, "expected space after ':'")
            return key, rest
        m = _KEY_PLAIN_RE.match(text)
        if not m:
            if text[0] in ("&", "*", "!"):
                raise YamlError(ln.no, "anchors, aliases and tags are not supported")
            raise YamlError(ln.no, f"expected `key: value`, got {text!r}")
        return m.group(1).strip(), text[m.end():]


def _is_seq_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _looks_like_key(text: str) -> bool:
    if text[0] in ("'", '"'):
        return False  # quoted scalars in list items are never keys here
    if text[0] in ("{", "["):
        return False
    m = _KEY_PLAIN_RE.match(text)
    return bool(m) and "://" not in m.group(1)


def loads(text: str) -> dict:
    """Parse the YAML subset; the top level must be a mapping (empty text → {})."""
    lines = _scan(text or "")
    if not lines:
        return {}
    p = _Parser(lines)
    first = p.peek()
    if first is not None and first.indent != 0:
        raise YamlError(first.no, "top level must not be indented")
    if first is not None and _is_seq_item(first.text):
        raise YamlError(first.no, "top level must be a mapping")
    val = p.parse_map(0)
    rest = p.peek()
    if rest is not None:
        raise YamlError(rest.no, "unparsed trailing content")
    return val


# ---------------------------------------------------------------- writer

_NEEDS_QUOTE_START = set("-?:,[]{}#&*!|>'\"%@`")


def _needs_quote(s: str, flow: bool = False) -> bool:
    if s == "":
        return True
    if s != s.strip() or "\n" in s or "\r" in s or "\t" in s:
        return True
    if s[0] in _NEEDS_QUOTE_START:
        return True
    if s.endswith(":"):
        return True
    if ": " in s or " #" in s:
        return True
    if ":" in s and not is_timestamp(s):
        return True
    if s in _NULLS or s in _TRUE or s in _FALSE:
        return True
    if s.lower() in ("yes", "no", "on", "off", "y", "n"):
        return True
    if _INT_RE.match(s) or _FLOAT_RE.match(s):
        return True
    if flow and any(ch in s for ch in ",]}"):
        return True
    return False


def dump_scalar(v: Any, flow: bool = False) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)
    if _needs_quote(s, flow):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'
    return s


def _dump_key(k: Any) -> str:
    s = str(k)
    if s == "" or _KEY_PLAIN_RE.match(s + ":") is None or s != s.strip() or "#" in s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def dump_flow(v: Any) -> str:
    """Single-line flow form of any value (used by frontmatter.replace_key)."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{ " + ", ".join(f"{_dump_key(k)}: {dump_flow(x)}" for k, x in v.items()) + " }"
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        return "[" + ", ".join(dump_flow(x) for x in v) + "]"
    return dump_scalar(v, flow=True)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _short_flow(v: Any, limit: int = 120) -> Optional[str]:
    """Flow form when the collection is shallow and short, else None."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        if len(v) > 5 or not all(_is_scalar(x) for x in v.values()):
            return None
    elif isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        if not all(_is_scalar(x) for x in v):
            return None
    else:
        return None
    s = dump_flow(v)
    return s if len(s) <= limit else None


def _dump_lines(v: Any, indent: int, out: list[str]) -> None:
    pad = " " * indent
    if isinstance(v, dict):
        for k, x in v.items():
            key = _dump_key(k)
            if _is_scalar(x):
                out.append(f"{pad}{key}: {dump_scalar(x)}")
                continue
            flow = _short_flow(x)
            if flow is not None:
                out.append(f"{pad}{key}: {flow}")
                continue
            out.append(f"{pad}{key}:")
            _dump_lines(x, indent + 2, out)
        return
    if isinstance(v, (list, tuple)):
        for x in v:
            if _is_scalar(x):
                out.append(f"{pad}- {dump_scalar(x)}")
                continue
            flow = _short_flow(x)
            if flow is not None:
                out.append(f"{pad}- {flow}")
                continue
            if isinstance(x, dict) and x:
                sub: list[str] = []
                _dump_lines(x, indent + 2, sub)
                sub[0] = f"{pad}- " + sub[0][indent + 2:]
                out.extend(sub)
            elif isinstance(x, (list, tuple)):
                out.append(f"{pad}-")
                _dump_lines(x, indent + 2, out)
            else:
                out.append(f"{pad}- {dump_flow(x)}")
        return
    out.append(f"{pad}{dump_scalar(v)}")


def dumps(obj: Any) -> str:
    """Serialise a mapping (or list) in the subset; always ends with a newline (empty → '')."""
    if obj is None or obj == {} or obj == []:
        return ""
    out: list[str] = []
    _dump_lines(obj, 0, out)
    return "\n".join(out) + "\n"
