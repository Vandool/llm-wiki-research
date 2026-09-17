"""Text helpers: hidden-Unicode detection/stripping, sanitising untrusted text, sentence split,
slugify, sha256 helpers, line normalisation.

API:
  find_hidden(text) -> [(line, col, codepoint)]     Cf, Cc (except \\t \\n \\r), U+2028/2029, U+FEFF, tags
  strip_hidden(text) -> str
  sanitize(text, max_chars=None) -> str             hidden/control chars removed, whitespace collapsed
  sentences(text) -> [str]
  word_count(text) -> int
  slugify(text) -> str                              lowercase kebab-case
  sha256_text(s) / sha256_bytes(b) / sha256_lines(lines) -> "sha256:<hex>"
  normalize(text) -> str                            CRLF→LF, trailing whitespace stripped, final newline
  strip_code(body) -> str                           fenced blocks and inline code removed (prose only)
  fenced_line_ranges(body) -> [(a, b)]              1-based inclusive line ranges of fenced code blocks
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable

__all__ = ["find_hidden", "strip_hidden", "sanitize", "sentences", "word_count", "slugify", "sha256_text",
           "sha256_bytes", "sha256_lines", "normalize", "strip_code", "strip_fences", "fenced_line_ranges", "collapse_ws"]

_ALLOWED_CC = {"\t", "\n", "\r"}


def _is_hidden(ch: str) -> bool:
    if ch in _ALLOWED_CC:
        return False
    cat = unicodedata.category(ch)
    if cat in ("Cf", "Cc"):
        return True
    o = ord(ch)
    return o in (0x2028, 0x2029, 0xFEFF) or 0xE0000 <= o <= 0xE007F


def find_hidden(text: str) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    for ln, line in enumerate(text.split("\n"), 1):
        for col, ch in enumerate(line, 1):
            if _is_hidden(ch):
                out.append((ln, col, ord(ch)))
    return out


def strip_hidden(text: str) -> str:
    return "".join(ch for ch in text if not _is_hidden(ch))


_WS = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def sanitize(text: str, max_chars: int | None = None) -> str:
    """Untrusted text → one line: hidden/control characters removed, whitespace collapsed, capped."""
    t = collapse_ws(strip_hidden(text or ""))
    if max_chars is not None and len(t) > max_chars:
        t = t[: max(0, max_chars - 1)].rstrip() + "…"
    return t


_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_END.split(text or "") if p and p.strip()]
    return parts


_WORD = re.compile(r"[A-Za-z0-9_'’-]+")


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "untitled"


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_lines(lines: Iterable[str]) -> str:
    """Hash of lines with trailing whitespace stripped, joined by LF."""
    return sha256_text("\n".join(l.rstrip() for l in lines))


def normalize(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(l.rstrip() for l in t.split("\n"))
    t = t.rstrip("\n") + "\n" if t.strip() else t
    return t


_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def fenced_line_ranges(body: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = None
    fence = None
    for i, line in enumerate(body.split("\n"), 1):
        m = _FENCE.match(line)
        if m:
            if start is None:
                start, fence = i, m.group(1)[0]
            elif m.group(1)[0] == fence:
                ranges.append((start, i))
                start, fence = None, None
    if start is not None:
        ranges.append((start, body.count("\n") + 1))
    return ranges


_INLINE_CODE = re.compile(r"`[^`\n]*`")


def strip_fences(body: str) -> str:
    """Fenced code blocks become empty lines; inline code is kept."""
    lines = body.split("\n")
    for a, b in fenced_line_ranges(body):
        for i in range(a - 1, min(b, len(lines))):
            lines[i] = ""
    return "\n".join(lines)


def strip_code(body: str) -> str:
    """Return the prose of a markdown body: fenced blocks become empty lines, inline code removed."""
    lines = body.split("\n")
    for a, b in fenced_line_ranges(body):
        for i in range(a - 1, min(b, len(lines))):
            lines[i] = ""
    return "\n".join(_INLINE_CODE.sub("", l) for l in lines)
