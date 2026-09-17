"""Frontmatter handling: split / parse / surgical single-line replace / serialize.

API:
  has_frontmatter(text) -> bool
  split(text) -> (fm_text, body, fm_line_count)      fm_line_count counts both `---` lines
  parse(text) -> (dict, body)                         raises FrontmatterError / yamlmini.YamlError
  replace_key(text, key, value) -> text               top-level scalar keys, or `parent.child` inside
                                                       a one-line flow map / nested block map; never
                                                       re-serialises the block; inserts when missing
  get_key(text, key) -> value | None                  cheap read of one top-level key
  serialize(fm_dict, body) -> text
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import yamlmini

__all__ = ["FrontmatterError", "has_frontmatter", "split", "parse", "replace_key", "get_key", "serialize"]

_DELIM = re.compile(r"^---\s*$")
_END = re.compile(r"^(---|\.\.\.)\s*$")


class FrontmatterError(ValueError):
    def __init__(self, line: int, msg: str):
        self.line = line
        self.msg = msg
        super().__init__(f"line {line}: {msg}")


def has_frontmatter(text: str) -> bool:
    return text.startswith("---") and _DELIM.match(text.split("\n", 1)[0].rstrip("\r")) is not None


def _lines(text: str) -> list[str]:
    return text.split("\n")


def split(text: str) -> tuple[str, str, int]:
    """Return (frontmatter text without delimiters, body, number of lines consumed).

    Without frontmatter → ('', text, 0). Unterminated → FrontmatterError.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    if not has_frontmatter(text):
        return "", text, 0
    lines = _lines(text)
    for i in range(1, len(lines)):
        if _END.match(lines[i].rstrip("\r")):
            fm = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            return fm, body, i + 1
    raise FrontmatterError(1, "unterminated frontmatter (no closing ---)")


def parse(text: str) -> tuple[dict, str]:
    fm, body, n = split(text)
    if n == 0:
        return {}, body
    data = yamlmini.loads(fm)
    if not isinstance(data, dict):
        raise FrontmatterError(1, "frontmatter must be a mapping")
    return data, body


def get_key(text: str, key: str) -> Any:
    """Read one top-level key without parsing the whole block (falls back to full parse)."""
    fm, _, n = split(text)
    if n == 0:
        return None
    prefix = key + ":"
    for line in fm.split("\n"):
        if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] in " \t"):
            try:
                return yamlmini.loads(line).get(key)
            except yamlmini.YamlError:
                break
    try:
        return yamlmini.loads(fm).get(key)
    except yamlmini.YamlError:
        return None


def _top_key_index(fm_lines: list[str], key: str) -> int:
    prefix = key + ":"
    for i, line in enumerate(fm_lines):
        if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] in " \t"):
            return i
    return -1


def _block_end(fm_lines: list[str], start: int) -> int:
    """Index after the last indented line belonging to the block that starts at fm_lines[start]."""
    j = start + 1
    while j < len(fm_lines) and (fm_lines[j].startswith((" ", "\t")) or not fm_lines[j].strip()):
        j += 1
    while j > start + 1 and not fm_lines[j - 1].strip():
        j -= 1
    return j


def replace_key(text: str, key: str, value: Any) -> str:
    """Replace one key's value on its own line, leaving every other byte untouched.

    `key` may be `parent.child`; the parent must be a one-line flow map (`{ by: …, at: … }`) or a
    nested block map. A missing key is inserted at the end of the frontmatter.
    """
    fm, body, n = split(text)
    if n == 0:
        raise FrontmatterError(1, "no frontmatter to edit")
    eol = "\r\n" if "\r\n" in text[: text.find("\n") + 2] else "\n"
    fm_lines = fm.split("\n")
    fm_lines = [l.rstrip("\r") for l in fm_lines]
    parts = key.split(".", 1)
    top = parts[0]
    idx = _top_key_index(fm_lines, top)
    if len(parts) == 1:
        new_line = f"{top}: {yamlmini.dump_scalar(value)}" if not isinstance(value, (dict, list)) \
            else f"{top}: {yamlmini.dump_flow(value)}"
        if idx < 0:
            fm_lines.append(new_line)
        else:
            end = _block_end(fm_lines, idx)
            fm_lines[idx:end] = [new_line]
    else:
        child = parts[1]
        if "." in child:
            raise FrontmatterError(1, "replace_key supports one level of nesting only")
        if idx < 0:
            fm_lines.append(f"{top}: {yamlmini.dump_flow({child: value})}")
        else:
            rest = fm_lines[idx][len(top) + 1:].strip()
            if rest.startswith("{"):
                current = yamlmini.loads(fm_lines[idx]).get(top) or {}
                if not isinstance(current, dict):
                    raise FrontmatterError(idx + 2, f"{top} is not a map")
                current[child] = value
                fm_lines[idx] = f"{top}: {yamlmini.dump_flow(current)}"
            elif rest == "":
                end = _block_end(fm_lines, idx)
                indent = None
                found = -1
                for j in range(idx + 1, end):
                    stripped = fm_lines[j].lstrip(" ")
                    ind = len(fm_lines[j]) - len(stripped)
                    if indent is None and stripped:
                        indent = ind
                    if stripped.startswith(child + ":") and ind == indent:
                        found = j
                        break
                pad = " " * (indent if indent is not None else 2)
                line = f"{pad}{child}: {yamlmini.dump_scalar(value)}"
                if found >= 0:
                    fm_lines[found] = line
                else:
                    fm_lines.insert(end, line)
            else:
                raise FrontmatterError(idx + 2, f"{top} is a scalar, cannot set {key}")
    new_fm = "\n".join(fm_lines)
    head = "---" + eol + new_fm.replace("\n", eol) + eol + "---" + eol
    return head + body


def serialize(fm: dict, body: str) -> str:
    return "---\n" + yamlmini.dumps(fm) + "---\n" + body
