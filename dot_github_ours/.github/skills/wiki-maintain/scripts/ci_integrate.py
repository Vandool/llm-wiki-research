#!/usr/bin/env python3
"""ci_integrate.py — wire the wiki CI include into a project's `.gitlab-ci.yml` (plan §8.12).

Subcommands
  detect [--json]
      Pipeline facts: include form (none|list|scalar|mapping|flow), whether our include is present,
      existing Pages jobs, stages, literal branch variables, default/remote branches, suggested
      production/staging branches, remote host, available validators, warnings.
  apply [--prod-branch B] [--staging-branch B] [--previews BOOL] [--parallel BOOL] [--publish BOOL]
        [--expire-in T] [--verify-soft BOOL] [--wiki-dir D] [--yes] [--dry-run]
      Exactly two edits: (1) values in the PROJECT SETTINGS block of .gitlab/ci/wiki.gitlab-ci.yml,
      (2) one include entry in .gitlab-ci.yml, touching nothing else. Prints a unified diff; writes
      only with --yes. Records kit.ci_include_form in .github/wiki.config.json.
  check [--json] [--validator glab|pyyaml|structural]
      glab ci lint → PyYAML → structural (no tabs, unique top-level keys, one include, our entry
      present once, include file intact). Reports which validator ran.
  remove [--yes] [--dry-run]
      Reverts edit (2) using the recorded include form (a list we created is turned back).

Python API (used by detect.py): `detect(repo: Path, cfg=None) -> dict`.
The whole file is text-based on purpose: the remainder of .gitlab-ci.yml stays byte-identical.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from wikilib import cli, config as wconfig, gitio  # noqa: E402
from wikilib.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, EnvError, KitError  # noqa: E402

NAME = "ci_integrate"
VERSION = "1.0.0"

GITLAB_CI = ".gitlab-ci.yml"
INCLUDE_PATH = ".gitlab/ci/wiki.gitlab-ci.yml"
INCLUDE_ITEM = f"- local: {INCLUDE_PATH}"
FLOW_ITEM = '{local: "' + INCLUDE_PATH + '"}'

PROJECT_KEYS = ("WIKI_PROD_BRANCH", "WIKI_STAGING_BRANCH", "WIKI_PUBLISH", "WIKI_PARALLEL_DEPLOYMENTS",
                "WIKI_DEV_PREVIEWS", "WIKI_DEV_EXPIRE_IN", "WIKI_VERIFY_SOFT")
PROJECT_MARK = "# ---- PROJECT SETTINGS"
TOOLCHAIN_MARK = "# ---- TOOLCHAIN"
REQUIRED_JOBS = ("wiki:verify", "wiki:pages", "wiki:pages:staging", "wiki:pages:preview")

PROD_VARS = ("BRANCH_PROD", "PROD_BRANCH", "PRODUCTION_BRANCH")
STAGING_VARS = ("BRANCH_PREPROD", "PREPROD_BRANCH", "STAGING_BRANCH", "BRANCH_STAGING")
BRANCH_VAR_RE = re.compile(r"^\s+(" + "|".join(PROD_VARS + STAGING_VARS) + r")\s*:\s*(.*?)\s*$")
STAGING_CANDIDATES = ("staging", "preprod", "pre-prod", "stage", "develop", "dev", "development")
BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

TOP_KEY_RE = re.compile(r"""^([A-Za-z0-9_.\-:]+|"[^"]*"|'[^']*')\s*:(?:\s|$)""")
INCLUDE_LINE_RE = re.compile(r"^include\s*:(.*)$")
SETTINGS_RE = re.compile(r'^(\s{2}(WIKI_[A-Z_]+):\s*)"([^"]*)"(.*)$')
ANCHOR_RE = re.compile(r'^(\s+-\s+")([^"/]+)(/\*\*/\*"\s*)$')
OUR_ITEM_RE = re.compile(r"""^(\s*)-\s*(?:local:\s*)?["']?/?""" + re.escape(INCLUDE_PATH) + r"""["']?\s*(?:#.*)?$""")
OUR_FLOW_RE = re.compile(r"""\{\s*local:\s*["']?/?""" + re.escape(INCLUDE_PATH) + r"""["']?\s*\}""")


# ----------------------------------------------------------------------------------------------
# line helpers (every function keeps the original bytes of untouched lines, CRLF included)
# ----------------------------------------------------------------------------------------------
def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _body(line: str) -> str:
    return line.rstrip("\r\n")


def _eol(line: str) -> str:
    return line[len(_body(line)):]


def _file_eol(lines: list[str]) -> str:
    for l in lines:
        e = _eol(l)
        if e:
            return e
    return "\n"


def _blank(b: str) -> bool:
    return not b.strip()


def _comment(b: str) -> bool:
    return b.lstrip().startswith("#")


def _indent(b: str) -> int:
    return len(b) - len(b.lstrip(" "))


def _strip_comment(s: str) -> str:
    """Drop a trailing ` # comment` that is outside quotes."""
    out: list[str] = []
    q: Optional[str] = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
            out.append(ch)
            continue
        if ch in "\"'":
            q = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _top_key(b: str) -> Optional[str]:
    if _blank(b) or _comment(b) or _indent(b) or b.startswith("-"):
        return None
    m = TOP_KEY_RE.match(b)
    return m.group(1).strip("\"'") if m else None


def _delete_line(lines: list[str], idx: int) -> None:
    """Delete a line; keep the 'last line has no newline' property of the original file."""
    had_eol = bool(_eol(lines[idx]))
    del lines[idx]
    if not had_eol and idx - 1 >= 0 and idx == len(lines):
        lines[idx - 1] = _body(lines[idx - 1])


def _insert_after(lines: list[str], idx: int, body: str, eol: str) -> None:
    """Insert `body` as a new line after index idx-1 (i.e. at position idx)."""
    if idx > 0 and idx == len(lines) and not _eol(lines[idx - 1]):
        lines[idx - 1] = lines[idx - 1] + eol
        lines.insert(idx, body)
    else:
        lines.insert(idx, body + eol)


# ----------------------------------------------------------------------------------------------
# include block model
# ----------------------------------------------------------------------------------------------
@dataclass
class IncludeBlock:
    layout: str                     # none | inline | flow | list | block-mapping | empty
    line: int = -1                  # index of the `include:` line (insertion index for `none`)
    rest: str = ""                  # text after `include:` (inline)
    item_indent: int = 2
    start: int = 0                  # first line of the value block (list / mapping)
    end: int = 0                    # index after the last non-blank, non-comment block line
    flow_open: tuple = (0, 0)
    flow_close: tuple = (0, 0)

    @property
    def form(self) -> str:
        if self.layout in ("none",):
            return "none"
        if self.layout == "list":
            return "list"
        if self.layout == "empty":
            return "empty"              # `include:` with a null value; strip keeps the key
        if self.layout == "flow":
            return "flow"
        if self.layout == "block-mapping":
            return "mapping"
        if self.layout == "inline":
            return "mapping" if _strip_comment(self.rest).strip().startswith("{") else "scalar"
        return self.layout


def _find_flow_end(lines: list[str], li: int, ci: int) -> tuple:
    depth = 0
    q: Optional[str] = None
    i, j = li, ci
    while i < len(lines):
        b = _body(lines[i])
        while j < len(b):
            ch = b[j]
            if q:
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
            elif ch == "#" and (j == 0 or b[j - 1] in " \t"):
                break
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    return (i, j)
            j += 1
        i += 1
        j = 0
    raise KitError(f"{GITLAB_CI}: unterminated flow sequence after `include:`")


def find_include(lines: list[str]) -> IncludeBlock:
    for i, line in enumerate(lines):
        b = _body(line)
        if _indent(b):
            continue
        m = INCLUDE_LINE_RE.match(b)
        if not m:
            continue
        rest = m.group(1)
        value = _strip_comment(rest).strip()
        if value.startswith("["):
            pos = b.index("[", len("include"))
            return IncludeBlock("flow", line=i, rest=rest, flow_open=(i, pos), flow_close=_find_flow_end(lines, i, pos))
        if value:
            return IncludeBlock("inline", line=i, rest=rest)
        j = i + 1
        while j < len(lines) and (_blank(_body(lines[j])) or _comment(_body(lines[j]))):
            j += 1
        if j >= len(lines):
            return IncludeBlock("empty", line=i, start=i + 1, end=i + 1, item_indent=2)
        bj = _body(lines[j])
        ind = _indent(bj)
        s = bj.lstrip()
        if s.startswith("- ") or s == "-":
            k, last = j, j
            while k < len(lines):
                bk = _body(lines[k])
                if _blank(bk) or _comment(bk):
                    k += 1
                    continue
                ik = _indent(bk)
                if (ik == ind and bk.lstrip().startswith("-")) or ik > ind:
                    last = k
                    k += 1
                    continue
                break
            return IncludeBlock("list", line=i, item_indent=ind, start=j, end=last + 1)
        if ind > 0:
            k, last = j, j
            while k < len(lines):
                bk = _body(lines[k])
                if _blank(bk) or _comment(bk):
                    k += 1
                    continue
                if _indent(bk) >= ind:
                    last = k
                    k += 1
                    continue
                break
            return IncludeBlock("block-mapping", line=i, item_indent=ind, start=j, end=last + 1)
        return IncludeBlock("empty", line=i, start=i + 1, end=i + 1, item_indent=2)
    # no include: insertion point after leading comments / document marker
    idx = 0
    while idx < len(lines):
        b = _body(lines[idx])
        if _blank(b) or _comment(b) or b.strip() in ("---", "..."):
            idx += 1
            continue
        break
    return IncludeBlock("none", line=idx)


def include_form(text: str) -> str:
    """Reported form: none|list|scalar|mapping|flow (a null `include:` counts as an empty list)."""
    f = find_include(_lines(text)).form
    return "list" if f == "empty" else f


def already_included(text: str) -> bool:
    for l in _lines(text):
        b = _body(l)
        if _comment(b):
            continue
        if INCLUDE_PATH in _strip_comment(b):
            return True
    return False


def _flow_inner(lines: list[str], open_pos: tuple, close_pos: tuple) -> str:
    (oi, oj), (ci, cj) = open_pos, close_pos
    if oi == ci:
        return _body(lines[oi])[oj + 1:cj]
    parts = [_body(lines[oi])[oj + 1:]]
    for k in range(oi + 1, ci):
        parts.append(_body(lines[k]))
    parts.append(_body(lines[ci])[:cj])
    return "".join(parts)


def insert_include(text: str) -> tuple[str, str]:
    """Return (new_text, original_form). Idempotent: an already included file is returned unchanged."""
    lines = _lines(text)
    eol = _file_eol(lines)
    blk = find_include(lines)
    if already_included(text):
        return text, blk.form
    if blk.layout == "none":
        idx = blk.line
        at_end = idx >= len(lines)
        new = list(lines)
        if at_end:
            _insert_after(new, len(new), "include:", eol)
            _insert_after(new, len(new), "  " + INCLUDE_ITEM, eol)
        else:
            new[idx:idx] = ["include:" + eol, "  " + INCLUDE_ITEM + eol, eol]
        return "".join(new), "none"
    if blk.layout in ("list", "empty"):
        new = list(lines)
        _insert_after(new, blk.end, " " * blk.item_indent + INCLUDE_ITEM, eol)
        return "".join(new), blk.form
    if blk.layout == "inline":
        line = lines[blk.line]
        e = _eol(line)
        new = list(lines)
        new[blk.line:blk.line + 1] = ["include:" + (e or eol), "  -" + blk.rest + (e or eol),
                                      "  " + INCLUDE_ITEM + e]
        return "".join(new), blk.form
    if blk.layout == "block-mapping":
        ind = blk.item_indent
        new = list(lines)
        first = True
        for k in range(blk.start, blk.end):
            b, e = _body(new[k]), _eol(new[k])
            if _blank(b) or _indent(b) < ind:
                continue
            if first:
                new[k] = " " * ind + "- " + b[ind:] + e
                first = False
            else:
                new[k] = "  " + b + e
        _insert_after(new, blk.end, " " * ind + INCLUDE_ITEM, eol)
        return "".join(new), "mapping"
    if blk.layout == "flow":
        inner = _flow_inner(lines, blk.flow_open, blk.flow_close).strip()
        if inner == "":
            ins = FLOW_ITEM
        elif inner.endswith(","):
            ins = FLOW_ITEM + ","           # keep the caller's trailing comma: `[a,{ours},]`
        else:
            ins = ", " + FLOW_ITEM
        li, cj = blk.flow_close
        new = list(lines)
        b, e = _body(new[li]), _eol(new[li])
        new[li] = b[:cj] + ins + b[cj:] + e
        return "".join(new), "flow"
    raise KitError(f"unsupported include layout: {blk.layout}")


def _list_items(lines: list[str], blk: IncludeBlock) -> list[int]:
    return [k for k in range(blk.start, blk.end)
            if _indent(_body(lines[k])) == blk.item_indent and _body(lines[k]).lstrip().startswith("-")]


def strip_include(text: str, form: Optional[str] = None) -> str:
    """Revert insert_include(). `form` is the recorded original form (kit.ci_include_form) or None."""
    lines = _lines(text)
    blk = find_include(lines)
    if blk.layout == "none":
        return text
    if blk.layout == "flow":
        (oi, oj), (ci, cj) = blk.flow_open, blk.flow_close
        start = len("".join(lines[:oi])) + oj
        stop = len("".join(lines[:ci])) + cj + 1
        head, seg, tail = text[:start], text[start:stop], text[stop:]
        ours = OUR_FLOW_RE.pattern
        # exact inverses of insert_include first, then hand-written placements
        for pat in (ours + r",\s*", r", " + ours, r" " + ours, ours):
            new_seg, n = re.subn(pat, "", seg, count=1)
            if n:
                return head + new_seg + tail
        return text
    if blk.layout not in ("list", "empty"):
        return text
    ours = [k for k in range(blk.start, blk.end) if OUR_ITEM_RE.match(_body(lines[k]))]
    if not ours:
        return text
    new = list(lines)
    _delete_line(new, ours[0])
    blk2 = find_include(new)
    items = _list_items(new, blk2) if blk2.layout in ("list", "empty") else []
    if not items:
        if form == "empty":
            return "".join(new)         # the key was there before us (null value); leave it
        # nothing left under `include:` (we created the block, or it only ever held our entry):
        # drop the header and the one blank separator insert_include() adds when a line follows
        hdr = blk2.line
        _delete_line(new, hdr)
        if hdr < len(new) and _blank(_body(new[hdr])):
            _delete_line(new, hdr)
        return "".join(new)
    if len(items) == 1 and form in ("scalar", "mapping"):
        k = items[0]
        single = (blk2.end == k + 1)
        if single:
            b, e = _body(new[k]), _eol(new[k])
            rest = b[b.index("-") + 1:]
            new[blk2.line:k + 1] = ["include:" + rest + e]
            return "".join(new)
        if form == "mapping":
            ind = blk2.item_indent
            b, e = _body(new[k]), _eol(new[k])
            new[k] = " " * ind + b[ind + 2:] + e
            for m in range(k + 1, blk2.end):
                b, e = _body(new[m]), _eol(new[m])
                if not _blank(b) and _indent(b) >= ind + 2:
                    new[m] = b[2:] + e
            return "".join(new)
    return "".join(new)


# ----------------------------------------------------------------------------------------------
# include file (.gitlab/ci/wiki.gitlab-ci.yml) settings
# ----------------------------------------------------------------------------------------------
def _settings_range(lines: list[str]) -> tuple[int, int]:
    a = b = -1
    for i, l in enumerate(lines):
        if PROJECT_MARK in l and a < 0:
            a = i
        elif TOOLCHAIN_MARK in l and a >= 0:
            b = i
            break
    if a < 0:
        return (-1, -1)
    return (a, b if b >= 0 else len(lines))


def read_project_settings(text: str) -> dict:
    lines = _lines(text)
    a, b = _settings_range(lines)
    out: dict = {}
    for l in lines[a + 1:b] if a >= 0 else []:
        m = SETTINGS_RE.match(_body(l))
        if m:
            out[m.group(2)] = m.group(3)
    return out


def set_project_settings(text: str, values: dict) -> str:
    lines = _lines(text)
    a, b = _settings_range(lines)
    if a < 0:
        raise KitError(f"{INCLUDE_PATH}: PROJECT SETTINGS block not found (file replaced?)")
    for i in range(a + 1, b):
        m = SETTINGS_RE.match(_body(lines[i]))
        if m and m.group(2) in values:
            v = str(values[m.group(2)])
            if '"' in v or "\n" in v:
                raise KitError(f"{m.group(2)}: value must not contain quotes or newlines")
            tail = m.group(4)
            if tail.strip().startswith("#"):        # keep the trailing comment in its column
                col = len(m.group(1)) + len(m.group(3)) + 2 + (len(tail) - len(tail.lstrip()))
                pad = max(1, col - (len(m.group(1)) + len(v) + 2))
                tail = " " * pad + tail.lstrip()
            lines[i] = f'{m.group(1)}"{v}"{tail}' + _eol(lines[i])
    return "".join(lines)


def read_wiki_dir(text: str) -> str:
    for l in _lines(text):
        m = SETTINGS_RE.match(_body(l))
        if m and m.group(2) == "WIKI_DIR":
            return m.group(3)
    return "wiki"


def set_wiki_dir(text: str, wiki_dir: str) -> str:
    old = read_wiki_dir(text)
    wiki_dir = wiki_dir.strip("/")
    if not wiki_dir or wiki_dir == old:
        return text
    lines = _lines(text)
    for i, l in enumerate(lines):
        b, e = _body(l), _eol(l)
        m = SETTINGS_RE.match(b)
        if m and m.group(2) == "WIKI_DIR":
            lines[i] = f'{m.group(1)}"{wiki_dir}"{m.group(4)}' + e
            continue
        m2 = ANCHOR_RE.match(b)
        if m2 and m2.group(2) == old:
            lines[i] = f"{m2.group(1)}{wiki_dir}{m2.group(3)}" + e
    return "".join(lines)


# ----------------------------------------------------------------------------------------------
# detection
# ----------------------------------------------------------------------------------------------
def ci_slug(name: str) -> str:
    """GitLab CI_COMMIT_REF_SLUG: lowercase, [^a-z0-9] -> '-', no leading/trailing '-', <= 63 bytes."""
    s = re.sub(r"[^a-z0-9]", "-", name.lower())[:63]
    return s.strip("-")


def _parse_remote(url: Optional[str]) -> dict:
    if not url:
        return {"remote_url": None, "remote_host": None, "remote_path": None}
    host = path = None
    m = re.match(r"^(?:ssh://)?(?:[^@/]+@)?([^:/]+)[:/](.+?)(?:\.git)?/?$", url) if "://" not in url or url.startswith("ssh://") else None
    if m:
        host, path = m.group(1), m.group(2)
    else:
        m = re.match(r"^[a-z+]+://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
        if m:
            host, path = m.group(1), m.group(2)
    return {"remote_url": url, "remote_host": host, "remote_path": path}


def _scan_ci(text: str) -> dict:
    """Top-level keys, stages, branch vars, pages jobs, duplicate keys, tabs."""
    lines = _lines(text)
    top_keys: list[str] = []
    stages: list[str] = []
    branch_vars: dict = {}
    pages_jobs: list[dict] = []
    tabs = 0
    current: Optional[str] = None
    seen_names: set = set()
    for i, l in enumerate(lines):
        b = _body(l)
        if b.startswith("\t") or re.match(r"^ *\t", b):
            tabs += 1
        k = _top_key(b)
        if k is not None:
            current = k
            top_keys.append(k)
            if k == "pages":
                pages_jobs.append({"name": "pages", "kind": "job", "line": i + 1})
                seen_names.add("pages")
            elif (k.startswith("pages-") or k.startswith("pages:")) and not k.startswith("wiki:"):
                pages_jobs.append({"name": k, "kind": "name", "line": i + 1})
                seen_names.add(k)
            # inline stages / flow
            if k == "stages":
                v = _strip_comment(b.split(":", 1)[1]).strip()
                if v.startswith("["):
                    stages = [_unquote(x) for x in v.strip("[]").split(",") if x.strip()]
            continue
        if current == "stages" and re.match(r"^\s*-\s+", b):
            stages.append(_unquote(_strip_comment(b).split("-", 1)[1]))
        elif current == "variables":
            m = BRANCH_VAR_RE.match(b)
            if m:
                v = _unquote(_strip_comment(m.group(2)))
                if v and not v.startswith("$"):
                    branch_vars[m.group(1)] = v
        elif current and _indent(b) and re.match(r"^\s+pages\s*:", b) and not _comment(b):
            if current not in seen_names and not current.startswith((".wiki_", "wiki:")):
                pages_jobs.append({"name": current, "kind": "pages-key", "line": i + 1})
                seen_names.add(current)
        m = re.search(r"""template\s*:\s*["']?(Pages/[^"'\s]+)""", b)
        if m and not _comment(b):
            pages_jobs.append({"name": m.group(1), "kind": "template", "line": i + 1})
    dups = sorted({k for k in top_keys if top_keys.count(k) > 1})
    return {"top_keys": top_keys, "stages": stages, "branch_vars": branch_vars, "pages_jobs": pages_jobs,
            "duplicate_keys": dups, "tabs": tabs}


def _glab_status() -> dict:
    exe = shutil.which("glab")
    if not exe:
        return {"available": False, "authenticated": False}
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=15)
        return {"available": True, "authenticated": r.returncode == 0}
    except (OSError, subprocess.SubprocessError):
        return {"available": True, "authenticated": False}


def _pyyaml_available() -> bool:
    try:
        return importlib.util.find_spec("yaml") is not None
    except (ImportError, ValueError):
        return False


def detect(repo: Path, cfg=None, probe_tools: bool = True) -> dict:
    """Pipeline facts for /wiki-init and detect.py. Never raises for a missing .gitlab-ci.yml."""
    repo = Path(repo)
    if cfg is None:
        cfg = wconfig.load(repo, warn=False)
    ci_path = repo / GITLAB_CI
    warnings: list[str] = []
    text = ci_path.read_text(encoding="utf-8", errors="replace") if ci_path.is_file() else None
    scan = _scan_ci(text) if text is not None else _scan_ci("")
    form = include_form(text) if text is not None else "none"
    included = already_included(text) if text is not None else False
    is_repo = gitio.is_repo(repo)
    default_branch = gitio.default_branch(repo) if is_repo else None
    remote_branches = gitio.branches(repo, remote=True) if is_repo else []
    local_branches = gitio.branches(repo, remote=False) if is_repo else []
    remote = _parse_remote(gitio.remote_url(repo) if is_repo else None)
    all_branches = list(dict.fromkeys(remote_branches + local_branches))

    prod = cfg.get("branches.production") or ""
    if not prod:
        for k in PROD_VARS:
            if scan["branch_vars"].get(k):
                prod = scan["branch_vars"][k]
                break
    if not prod:
        prod = default_branch or "main"
    staging = cfg.get("branches.staging") or ""
    if not staging:
        for k in STAGING_VARS:
            if scan["branch_vars"].get(k):
                staging = scan["branch_vars"][k]
                break
    if not staging:
        lower = {b.lower(): b for b in all_branches}
        for cand in STAGING_CANDIDATES:
            if cand in lower:
                staging = lower[cand]
                break
    if staging == prod:
        staging = ""

    if text is None:
        warnings.append(f"no {GITLAB_CI}: `apply` creates one containing only the include")
    if included:
        warnings.append(f"{INCLUDE_PATH} is already included")
    if scan["pages_jobs"]:
        names = ", ".join(j["name"] for j in scan["pages_jobs"])
        warnings.append(f"existing Pages job(s): {names} — /wiki-init asks whether to replace it with the wiki site, "
                        f"keep it (WIKI_PUBLISH \"false\") or stop")
    if scan["duplicate_keys"]:
        warnings.append(f"duplicate top-level keys in {GITLAB_CI}: {', '.join(scan['duplicate_keys'])}")
    if scan["tabs"]:
        warnings.append(f"{GITLAB_CI} contains tab indentation ({scan['tabs']} line(s)); YAML forbids tabs")
    if scan["top_keys"].count("include") > 1:
        warnings.append(f"{GITLAB_CI} has more than one top-level `include` key")
    wiki_root = repo / cfg.wiki_dir
    folders = sorted(d.name for d in wiki_root.iterdir() if d.is_dir() and not d.name.startswith(".")) \
        if wiki_root.is_dir() else []
    root_pages = sorted(p.stem for p in wiki_root.glob("*.md")) if wiki_root.is_dir() else []
    for br in all_branches:
        slug = ci_slug(br)
        if slug in folders:
            warnings.append(f"branch '{br}' has slug '{slug}' equal to wiki folder '{slug}/': a preview deployment "
                            f"(pages.path_prefix) would override that path — rename the branch or disable previews")
        elif slug in root_pages:
            warnings.append(f"branch '{br}' has slug '{slug}' equal to wiki page '{slug}.md'")
    if not is_repo:
        warnings.append("not a git repository: branches unknown")
    validators = {"glab": False, "glab_available": False, "pyyaml": False, "structural": True}
    if probe_tools:
        g = _glab_status()
        validators.update({"glab": g["available"] and g["authenticated"], "glab_available": g["available"],
                           "pyyaml": _pyyaml_available()})
    return {
        "gitlab_ci": GITLAB_CI if text is not None else None,
        "include_form": form,
        "already_included": included,
        "pages_jobs": scan["pages_jobs"],
        "stages": scan["stages"],
        "branch_vars": scan["branch_vars"],
        "default_branch": default_branch,
        "remote_branches": remote_branches,
        "local_branches": local_branches,
        "suggest": {"prod": prod, "staging": staging},
        "remote_host": remote["remote_host"],
        "remote_url": remote["remote_url"],
        "remote_path": remote["remote_path"],
        "include_path": INCLUDE_PATH,
        "include_file_present": (repo / INCLUDE_PATH).is_file(),
        "validators": validators,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------------------------------
# validation
# ----------------------------------------------------------------------------------------------
def structural_check(ci_text: Optional[str], inc_text: Optional[str], form: Optional[str] = None) -> tuple[list, list]:
    errors: list[str] = []
    warnings: list[str] = []
    if ci_text is None:
        errors.append(f"{GITLAB_CI} missing")
    else:
        scan = _scan_ci(ci_text)
        if scan["tabs"]:
            errors.append(f"{GITLAB_CI}: tab indentation on {scan['tabs']} line(s)")
        if scan["duplicate_keys"]:
            errors.append(f"{GITLAB_CI}: duplicate top-level keys: {', '.join(scan['duplicate_keys'])}")
        n_inc = scan["top_keys"].count("include")
        if n_inc > 1:
            errors.append(f"{GITLAB_CI}: {n_inc} top-level `include` keys")
        hits = sum(1 for l in _lines(ci_text) if not _comment(_body(l)) and INCLUDE_PATH in _strip_comment(_body(l)))
        if hits == 0:
            errors.append(f"{GITLAB_CI}: include entry for {INCLUDE_PATH} missing (run `ci_integrate.py apply`)")
        elif hits > 1:
            errors.append(f"{GITLAB_CI}: include entry for {INCLUDE_PATH} appears {hits} times")
        else:
            try:
                stripped = strip_include(ci_text, form)
                re_ins, _ = insert_include(stripped)
                if re_ins != ci_text:
                    warnings.append(f"{GITLAB_CI}: include entry is not in the position `apply` would choose "
                                    f"(hand-edited?); `remove` still works")
            except KitError as e:
                warnings.append(str(e))
        if scan["pages_jobs"] and inc_text and read_project_settings(inc_text).get("WIKI_PUBLISH", "true") == "true":
            names = ", ".join(j["name"] for j in scan["pages_jobs"])
            warnings.append(f"{GITLAB_CI}: Pages job(s) {names} coexist with wiki:pages; both would deploy to the "
                            f"site root — set WIKI_PUBLISH \"false\" or remove the other job")
    if inc_text is None:
        errors.append(f"{INCLUDE_PATH} missing (run install.py)")
    else:
        if any(_body(l).startswith("\t") for l in _lines(inc_text)):
            errors.append(f"{INCLUDE_PATH}: tab indentation")
        inc_scan = _scan_ci(inc_text)
        for job in REQUIRED_JOBS:
            if job not in inc_scan["top_keys"]:
                errors.append(f"{INCLUDE_PATH}: job `{job}` missing")
        if "stages" in inc_scan["top_keys"]:
            errors.append(f"{INCLUDE_PATH}: must not define `stages` (include cannot merge them)")
        settings = read_project_settings(inc_text)
        for k in PROJECT_KEYS:
            if k not in settings:
                errors.append(f"{INCLUDE_PATH}: PROJECT SETTINGS key {k} missing or not double-quoted")
        for k in ("WIKI_PUBLISH", "WIKI_PARALLEL_DEPLOYMENTS", "WIKI_DEV_PREVIEWS", "WIKI_VERIFY_SOFT"):
            if k in settings and settings[k] not in ("true", "false"):
                errors.append(f"{INCLUDE_PATH}: {k} must be \"true\" or \"false\", got \"{settings[k]}\"")
        for k in ("WIKI_PROD_BRANCH", "WIKI_STAGING_BRANCH"):
            v = settings.get(k, "")
            if v and not BRANCH_NAME_RE.match(v):
                errors.append(f"{INCLUDE_PATH}: {k} is not a literal branch name: \"{v}\"")
        if settings.get("WIKI_STAGING_BRANCH") and settings.get("WIKI_PARALLEL_DEPLOYMENTS") != "true":
            warnings.append(f"{INCLUDE_PATH}: WIKI_STAGING_BRANCH is set but parallel deployments are off; "
                            f"wiki:pages:staging never runs")
    return errors, warnings


def _pyyaml_check(ci_text: str, inc_text: str) -> list[str]:
    import yaml  # type: ignore

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    errors: list[str] = []
    for name, text in ((GITLAB_CI, ci_text), (INCLUDE_PATH, inc_text)):
        try:
            data = yaml.load(text, Loader=Loader)
        except yaml.YAMLError as e:  # type: ignore[attr-defined]
            errors.append(f"{name}: YAML error: {e}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{name}: top level is not a mapping")
            continue
        if name == GITLAB_CI:
            inc = data.get("include")
            items = inc if isinstance(inc, list) else [inc]
            found = any((isinstance(x, dict) and x.get("local", "").lstrip("/") == INCLUDE_PATH)
                        or (isinstance(x, str) and x.lstrip("/") == INCLUDE_PATH) for x in items if x is not None)
            if not found:
                errors.append(f"{GITLAB_CI}: parsed `include` does not reference {INCLUDE_PATH}")
    return errors


def _glab_check(repo: Path) -> tuple[Optional[bool], str]:
    """(verdict or None when inconclusive, output)."""
    exe = shutil.which("glab")
    if not exe:
        return None, "glab not installed"
    try:
        r = subprocess.run([exe, "ci", "lint"], cwd=str(repo), capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"glab ci lint failed to run: {e}"
    out = (r.stdout + "\n" + r.stderr).strip()
    if r.returncode == 0:
        return True, out
    low = out.lower()
    if INCLUDE_PATH in out and any(s in low for s in ("not found", "does not exist", "could not be found", "not exist")):
        return None, "glab ci lint: the include file is not on the server yet (push it first): " + out
    if any(s in low for s in ("not authenticated", "login", "401", "403", "no token")):
        return None, "glab ci lint: not authenticated: " + out
    return False, out


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------
def _bool(v: str) -> bool:
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n"):
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {v!r}")


def _add_common(sp: argparse.ArgumentParser) -> None:
    S = argparse.SUPPRESS
    sp.add_argument("--repo", default=S)
    sp.add_argument("--config", default=S)
    sp.add_argument("--json", action="store_true", default=S)
    sp.add_argument("--quiet", action="store_true", default=S)
    sp.add_argument("--now", default=S)


def build_parser() -> argparse.ArgumentParser:
    p = cli.base_parser(NAME, VERSION, "Integrate the wiki CI include into .gitlab-ci.yml (detect/apply/check/remove).")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="detect|apply|check|remove")
    sp = sub.add_parser("detect", help="pipeline facts (include form, Pages jobs, branches, validators)")
    _add_common(sp)
    sp = sub.add_parser("apply", help="rewrite PROJECT SETTINGS and insert the include (two edits)")
    sp.add_argument("--prod-branch", default=None, help='literal branch name; "" or "default" = $CI_DEFAULT_BRANCH')
    sp.add_argument("--staging-branch", default=None, help='literal branch name; "" = off')
    sp.add_argument("--previews", type=_bool, default=None, help="per-branch previews (true/false)")
    sp.add_argument("--parallel", type=_bool, default=None, help="parallel deployments, Premium/Ultimate (true/false)")
    sp.add_argument("--publish", type=_bool, default=None, help="build and deploy the site (true/false)")
    sp.add_argument("--expire-in", default=None, help='preview lifetime, e.g. "1 week"')
    sp.add_argument("--verify-soft", type=_bool, default=None, help="wiki:verify warns instead of failing")
    sp.add_argument("--wiki-dir", default=None, help="wiki directory when not `wiki` (rewrites WIKI_DIR and the changes anchor)")
    sp.add_argument("--yes", action="store_true", help="write the files (otherwise only the diff is shown)")
    sp.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    _add_common(sp)
    sp = sub.add_parser("check", help="validate: glab ci lint -> PyYAML -> structural")
    sp.add_argument("--validator", choices=["glab", "pyyaml", "structural"], default=None, help="force one validator")
    _add_common(sp)
    sp = sub.add_parser("remove", help="revert the include entry in .gitlab-ci.yml")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    _add_common(sp)
    return p


def _udiff(old: str, new: str, path: str) -> str:
    if old == new:
        return ""
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}"))


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _save_cfg(ctx: cli.Ctx, updates: dict, files: Optional[dict] = None) -> bool:
    """Apply dotted-key updates (and kit.files entries, whose keys contain dots) to the config file."""
    cfg = ctx.cfg
    if not cfg or not cfg.path or not cfg.path.exists():
        ctx.emit.warn("config not found; settings not recorded (run install.py first)")
        return False
    raw = json.loads(cfg.path.read_text(encoding="utf-8"))
    for k, v in updates.items():
        wconfig.set_dotted(raw, k, v)
    if files:
        kit = raw.setdefault("kit", {})
        if not isinstance(kit.get("files"), dict):
            kit["files"] = {}
        kit["files"].update(files)
    wconfig.save(cfg.path, raw)
    return True


def cmd_detect(ctx: cli.Ctx, args) -> int:
    det = detect(ctx.repo, ctx.cfg)
    em = ctx.emit
    if em.as_json:
        em.emit(det, ok=True)
        return EXIT_OK
    em.out(f"gitlab_ci:        {det['gitlab_ci'] or '(none)'}")
    em.out(f"include_form:     {det['include_form']}   already_included: {det['already_included']}")
    em.out(f"pages_jobs:       {', '.join(j['name'] + ' (' + j['kind'] + ')' for j in det['pages_jobs']) or '(none)'}")
    em.out(f"stages:           {', '.join(det['stages']) or '(none)'}")
    em.out(f"branch_vars:      {det['branch_vars'] or '{}'}")
    em.out(f"default_branch:   {det['default_branch']}   remote_branches: {', '.join(det['remote_branches']) or '(none)'}")
    em.out(f"suggest:          prod={det['suggest']['prod']!r} staging={det['suggest']['staging']!r}")
    em.out(f"remote_host:      {det['remote_host']}")
    v = det["validators"]
    em.out(f"validators:       glab={'yes' if v['glab'] else 'no'} pyyaml={'yes' if v['pyyaml'] else 'no'} structural=yes")
    for w in det["warnings"]:
        em.out(f"warning:          {w}")
    return EXIT_OK


def cmd_apply(ctx: cli.Ctx, args) -> int:
    repo, cfg, em = ctx.repo, ctx.cfg, ctx.emit
    det = detect(repo, cfg, probe_tools=False)
    inc_path = repo / INCLUDE_PATH
    if not inc_path.is_file():
        raise EnvError(f"{INCLUDE_PATH} not found — run install.py first (it copies the include template)")
    wiki_dir = (args.wiki_dir or cfg.wiki_dir).strip("/")

    prod = args.prod_branch if args.prod_branch is not None else (cfg.get("branches.production") or det["suggest"]["prod"] or "")
    if prod in ("default", "$CI_DEFAULT_BRANCH"):
        prod = ""
    staging = args.staging_branch if args.staging_branch is not None else (cfg.get("branches.staging") or "")
    for label, v in (("--prod-branch", prod), ("--staging-branch", staging)):
        if v and not BRANCH_NAME_RE.match(v):
            raise KitError(f"{label}: not a literal branch name: {v!r}")
    if staging and staging == prod:
        raise KitError("staging branch must differ from the production branch")
    publish = args.publish if args.publish is not None else bool(cfg.get("pages.enabled", True))
    parallel = args.parallel if args.parallel is not None else bool(cfg.get("branches.parallel_deployments", False))
    previews = args.previews if args.previews is not None else bool(cfg.get("branches.dev_previews", True))
    expire = args.expire_in if args.expire_in is not None else (cfg.get("branches.dev_expire_in") or "1 week")
    verify_soft = bool(args.verify_soft) if args.verify_soft is not None else False
    values = {
        "WIKI_PROD_BRANCH": prod, "WIKI_STAGING_BRANCH": staging,
        "WIKI_PUBLISH": "true" if publish else "false",
        "WIKI_PARALLEL_DEPLOYMENTS": "true" if parallel else "false",
        "WIKI_DEV_PREVIEWS": "true" if previews else "false",
        "WIKI_DEV_EXPIRE_IN": expire, "WIKI_VERIFY_SOFT": "true" if verify_soft else "false",
    }
    warnings: list[str] = []
    if det["pages_jobs"] and publish and args.publish is None:
        warnings.append("existing Pages job(s) " + ", ".join(j["name"] for j in det["pages_jobs"]) +
                        " — both would deploy to the site root; pass --publish false to keep the other job, "
                        "or remove it")
    if staging and not parallel:
        warnings.append("staging branch set but parallel deployments off: wiki:pages:staging stays inactive (Premium/Ultimate only)")
    if previews and not parallel:
        warnings.append("dev previews need parallel deployments (Premium/Ultimate >= 17.9); they stay inactive")

    inc_old = inc_path.read_text(encoding="utf-8")
    inc_new = set_project_settings(inc_old, values)
    inc_new = set_wiki_dir(inc_new, wiki_dir)
    ci_path = repo / GITLAB_CI
    ci_old = ci_path.read_text(encoding="utf-8") if ci_path.is_file() else ""
    ci_new, form = insert_include(ci_old)
    inserted = ci_new != ci_old
    if inserted and strip_include(ci_new, form) != ci_old:
        raise KitError("internal: the include edit is not reversible for this file layout; refusing to write")
    diff = _udiff(inc_old, inc_new, INCLUDE_PATH) + _udiff(ci_old, ci_new, GITLAB_CI)
    changed = bool(diff)

    payload = {"settings": values, "include_form": form, "inserted": inserted, "changed": changed,
               "already_included": det["already_included"], "wiki_dir": wiki_dir, "diff": diff,
               "warnings": warnings, "written": False}
    for w in warnings:
        em.warn(w)
    if not changed:
        em.say("ci_integrate: nothing to change")
    else:
        em.out(diff.rstrip("\n"))
    if args.dry_run:
        em.say("ci_integrate: dry run, nothing written")
        em.emit(payload, ok=True)
        return EXIT_OK
    if not args.yes:
        em.say("ci_integrate: re-run with --yes to write these changes")
        em.emit(payload, ok=False)
        return EXIT_USAGE if changed else EXIT_OK
    if inc_new != inc_old:
        inc_path.write_text(inc_new, encoding="utf-8")
    if ci_new != ci_old:
        ci_path.write_text(ci_new, encoding="utf-8")
    updates = {"branches.production": prod, "branches.staging": staging, "branches.dev_previews": previews,
               "branches.parallel_deployments": parallel, "branches.dev_expire_in": expire, "pages.enabled": publish}
    if inserted:
        updates["kit.ci_include_form"] = form
    files_update = {}
    if cfg.path and cfg.path.exists():
        raw = json.loads(cfg.path.read_text(encoding="utf-8"))
        files = wconfig.get_dotted(raw, "kit.files") or {}
        if INCLUDE_PATH in files or inc_new != inc_old:
            files_update[INCLUDE_PATH] = _sha(inc_new)     # install.py --upgrade treats it as unmodified
    payload["recorded"] = _save_cfg(ctx, updates, files_update)
    payload["written"] = True
    em.say(f"ci_integrate: {'include inserted (' + form + ' form)' if inserted else 'include already present'}; "
           f"settings written to {INCLUDE_PATH}")
    em.emit(payload, ok=True)
    return EXIT_OK


def cmd_check(ctx: cli.Ctx, args) -> int:
    repo, cfg, em = ctx.repo, ctx.cfg, ctx.emit
    ci_path, inc_path = repo / GITLAB_CI, repo / INCLUDE_PATH
    ci_text = ci_path.read_text(encoding="utf-8") if ci_path.is_file() else None
    inc_text = inc_path.read_text(encoding="utf-8") if inc_path.is_file() else None
    form = cfg.get("kit.ci_include_form") or None
    errors: list[str] = []
    warnings: list[str] = []
    tried: list[str] = []
    validator = None
    order = [args.validator] if args.validator else ["glab", "pyyaml", "structural"]
    for v in order:
        if v == "glab":
            if not ci_text:
                continue
            verdict, out = _glab_check(repo)
            tried.append("glab")
            if verdict is None:
                warnings.append(out)
                if args.validator:
                    errors.append("glab was inconclusive")
                continue
            validator = "glab"
            if not verdict:
                errors.append("glab ci lint: " + out)
            break
        if v == "pyyaml":
            if not _pyyaml_available() or ci_text is None or inc_text is None:
                if args.validator:
                    errors.append("PyYAML not importable")
                continue
            tried.append("pyyaml")
            errors.extend(_pyyaml_check(ci_text, inc_text))
            validator = "pyyaml"
            break
        if v == "structural":
            tried.append("structural")
            validator = "structural"
            break
    s_err, s_warn = structural_check(ci_text, inc_text, form)
    if validator != "structural":
        tried.append("structural")
    errors.extend(e for e in s_err if e not in errors)
    warnings.extend(w for w in s_warn if w not in warnings)
    ok = not errors
    for e in errors:
        em.say(f"error: {e}")
    for w in warnings:
        em.say(f"warning: {w}")
    em.say(f"ci_integrate check: {'OK' if ok else 'FAILED'} (validator: {validator or 'none'}; ran: {', '.join(tried)})")
    em.emit({"validator": validator, "validators_run": tried, "errors": errors, "warnings": warnings,
             "included": bool(ci_text) and already_included(ci_text or "")}, ok=ok)
    return EXIT_OK if ok else EXIT_FINDINGS


def cmd_remove(ctx: cli.Ctx, args) -> int:
    repo, cfg, em = ctx.repo, ctx.cfg, ctx.emit
    ci_path = repo / GITLAB_CI
    if not ci_path.is_file():
        em.say(f"ci_integrate: no {GITLAB_CI}; nothing to remove")
        em.emit({"changed": False, "diff": ""}, ok=True)
        return EXIT_OK
    form = cfg.get("kit.ci_include_form") or None
    old = ci_path.read_text(encoding="utf-8")
    new = strip_include(old, form)
    diff = _udiff(old, new, GITLAB_CI)
    payload = {"changed": new != old, "form": form, "diff": diff, "written": False}
    if new == old:
        em.say("ci_integrate: include entry not present; nothing to remove")
        em.emit(payload, ok=True)
        return EXIT_OK
    em.out(diff.rstrip("\n"))
    if args.dry_run:
        em.emit(payload, ok=True)
        return EXIT_OK
    if not args.yes:
        em.say("ci_integrate: re-run with --yes to write")
        em.emit(payload, ok=False)
        return EXIT_USAGE
    ci_path.write_text(new, encoding="utf-8")
    payload["written"] = True
    if cfg.path and cfg.path.exists():
        _save_cfg(ctx, {"kit.ci_include_form": ""})
    em.say(f"ci_integrate: include entry removed from {GITLAB_CI}")
    em.emit(payload, ok=True)
    return EXIT_OK


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    return {"detect": cmd_detect, "apply": cmd_apply, "check": cmd_check, "remove": cmd_remove}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
