#!/usr/bin/env python3
"""install.py — install, upgrade, check or remove the wiki kit in a target repository (plan §8.13).

  python3 install.py TARGET [--wiki-dir wiki] [--hooks auto|git|pre-commit|none] [--upgrade] [--uninstall]
                            [--force] [--dry-run] [--check] [--no-ci] [--no-site] [--issue-template] [--yes]
                            [--json] [--quiet] [--now ISO]

Policies:
  kit       owned by the kit: copied on install; on --upgrade overwritten unless the recorded sha256
            differs from the file on disk (locally modified -> skipped with a warning; --force overwrites)
  scaffold  created only if missing (`{{placeholders}}` substituted); never overwritten
  block     managed block between <!-- WIKI-AGENT:START --> / <!-- WIKI-AGENT:END --> in
            .github/copilot-instructions.md, replaced on upgrade; file created with a two-line header
  lines     exact lines under a `# wiki-kit` comment in .gitattributes / .gitignore
  hook      .git/hooks trampolines via hooks.py install
  record    kit.version / kit.installed_at / kit.files (sha256 per kit file) in .github/wiki.config.json

Stdlib only; Python >= 3.10. The kit directory is the directory of this file.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional

KIT = Path(__file__).resolve().parent
SCRIPTS_REL = ".github/skills/wiki-maintain/scripts"
KIT_SCRIPTS = KIT / SCRIPTS_REL
if str(KIT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(KIT_SCRIPTS))

try:
    from wikilib import cli as wcli, config as wconfig, gitio  # noqa: E402
    import ci_integrate  # noqa: E402
except ImportError as e:  # pragma: no cover
    print(f"install.py: kit incomplete ({e}); expected {KIT_SCRIPTS}/wikilib", file=sys.stderr)
    sys.exit(2)

CONFIG_REL = ".github/wiki.config.json"
BLOCK_TEMPLATE_REL = "templates/copilot-instructions.block.md"
BLOCK_TARGET_REL = ".github/copilot-instructions.md"
BLOCK_START = "<!-- WIKI-AGENT:START"
BLOCK_END = "<!-- WIKI-AGENT:END -->"
LINES_MARK = "# wiki-kit"
CI_TEMPLATE_REL = "templates/ci/wiki.gitlab-ci.yml"
CI_TARGET_REL = ".gitlab/ci/wiki.gitlab-ci.yml"
SITE_TEMPLATE_DIR = "templates/quartz"
SITE_TARGET_DIR = ".gitlab/wiki-site"
WIKI_TEMPLATE_DIR = "templates/wiki"
ISSUE_TEMPLATE_REL = "templates/issue_templates/Wiki request.md"
ISSUE_TARGET_REL = ".gitlab/issue_templates/Wiki request.md"
KIT_EXCLUDE_REL = {BLOCK_TARGET_REL, CONFIG_REL, ".github/instructions/wiki-consumers.instructions.md"}
KIT_EXCLUDE_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache"}
SUB_ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")     # never leave __pycache__ in the target
NEXT_STEPS = ("1) copilot login (once)  2) cd {repo} && WIKI_RUN=1 copilot --agent wiki-maintainer "
              "--model {model}  3) /wiki-init")
TEAMMATES = "python3 .github/skills/wiki-maintain/scripts/hooks.py install"


def kit_version() -> str:
    try:
        return (KIT / "VERSION").read_text(encoding="utf-8").strip() or wcli.KIT_VERSION
    except OSError:
        return wcli.KIT_VERSION


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Out:
    """Human text to stdout (stderr under --json); one JSON object at the end under --json."""

    def __init__(self, as_json: bool, quiet: bool):
        self.as_json, self.quiet = as_json, quiet
        self.warnings: list[str] = []

    def say(self, msg: str = "") -> None:
        if self.quiet and not msg.startswith(("wiki-kit", "error")):
            return
        print(msg, file=sys.stderr if self.as_json else sys.stdout)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"install.py: warning: {msg}", file=sys.stderr)


class Action:
    def __init__(self, policy: str, path: str, op: str, reason: str = "", diff: str = "",
                 data: Optional[bytes] = None, mode: Optional[int] = None, record: bool = False):
        self.policy, self.path, self.op, self.reason, self.diff = policy, path, op, reason, diff
        self.data, self.mode, self.record = data, mode, record

    def as_dict(self) -> dict:
        return {"policy": self.policy, "path": self.path, "op": self.op, "reason": self.reason}

    @property
    def changes(self) -> bool:
        return self.op in ("create", "update", "remove")


# ----------------------------------------------------------------------------------------------
# enumeration of kit sources
# ----------------------------------------------------------------------------------------------
def kit_file_map(opts) -> list[tuple[Path, str]]:
    """[(kit source, target relative path)] for policy `kit`."""
    out: list[tuple[Path, str]] = []
    root = KIT / ".github"
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix == ".pyc":
            continue
        if any(part in KIT_EXCLUDE_NAMES for part in p.relative_to(KIT).parts):
            continue
        rel = p.relative_to(KIT).as_posix()
        if rel in KIT_EXCLUDE_REL:
            continue
        out.append((p, rel))
    if not opts.no_ci and (KIT / CI_TEMPLATE_REL).is_file():
        out.append((KIT / CI_TEMPLATE_REL, CI_TARGET_REL))
    if not opts.no_site and (KIT / SITE_TEMPLATE_DIR).is_dir():
        for p in sorted((KIT / SITE_TEMPLATE_DIR).iterdir()):
            if p.is_file() and p.name not in KIT_EXCLUDE_NAMES:
                out.append((p, f"{SITE_TARGET_DIR}/{p.name}"))
    return out



def actor_user(repo) -> str:
    """`human:<user>` needs a token without spaces: login name first, then git user.email's local part,
    then a slug of git user.name (plan §8.9 actors, example `human:akaveh`)."""
    import getpass
    import re as _re
    cands = []
    try:
        cands.append(getpass.getuser())
    except Exception:
        pass
    cands += [os.environ.get("USER"), os.environ.get("USERNAME")]
    if repo is not None:
        email = gitio.config_get("user.email", repo) or ""
        if "@" in email:
            cands.append(email.split("@", 1)[0])
        cands.append(gitio.config_get("user.name", repo))
    for c in cands:
        if not c:
            continue
        tok = _re.sub(r"[^A-Za-z0-9._@-]+", "-", c.strip()).strip("-").lower()
        if tok:
            return tok
    return "unknown"

def scaffold_file_map(opts, wiki_dir: str) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    base = KIT / WIKI_TEMPLATE_DIR
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if p.is_file() and not any(part in KIT_EXCLUDE_NAMES for part in p.relative_to(base).parts):
                out.append((p, f"{wiki_dir}/{p.relative_to(base).as_posix()}"))
    if opts.issue_template and (KIT / ISSUE_TEMPLATE_REL).is_file():
        out.append((KIT / ISSUE_TEMPLATE_REL, ISSUE_TARGET_REL))
    return out


# ----------------------------------------------------------------------------------------------
# text transforms
# ----------------------------------------------------------------------------------------------
def _is_text(data: bytes) -> bool:
    return b"\0" not in data[:8192]


def upsert_block(existing: Optional[str], block: str, repo_name: str) -> tuple[str, str]:
    block = block.strip("\n") + "\n"
    if existing is None:
        header = (f"# Copilot instructions for {repo_name}\n"
                  f"<!-- Repository-wide guidance for GitHub Copilot. The wiki kit manages only the block between the WIKI-AGENT markers. -->\n\n")
        return header + block, "create"
    s, e = existing.find(BLOCK_START), existing.find(BLOCK_END)
    if s >= 0 and e > s:
        end = e + len(BLOCK_END)
        if existing[end:end + 1] == "\n":
            end += 1
        if existing[s:end] == block:
            return existing, "unchanged"
        return existing[:s] + block + existing[end:], "update"
    if not existing.strip():
        sep = ""
    elif existing.endswith("\n\n"):
        sep = ""
    elif existing.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return existing + sep + block, "update"


def remove_block(existing: str) -> Optional[str]:
    """Text without the managed block; None when only our header (or nothing) remains."""
    s, e = existing.find(BLOCK_START), existing.find(BLOCK_END)
    if s < 0 or e < s:
        return existing
    end = e + len(BLOCK_END)
    if existing[end:end + 1] == "\n":
        end += 1
    rest = existing[:s].rstrip("\n") + ("\n" if existing[:s].strip() else "") + existing[end:].lstrip("\n")
    lines = [l for l in rest.splitlines() if l.strip()]
    ours = [l for l in lines if l.startswith("# Copilot instructions for ") or "The wiki kit manages only the block" in l]
    if not lines or len(ours) == len(lines):
        return None
    return rest if rest.endswith("\n") or not rest else rest + "\n"


def ensure_lines(existing: Optional[str], wanted: list[str]) -> tuple[str, str]:
    text = existing or ""
    have = {l.rstrip("\r\n") for l in text.splitlines()}
    missing = [l for l in wanted if l not in have]
    if not missing:
        return text, "unchanged"
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in text else "\n"
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += eol
    marker = next((i for i, l in enumerate(lines) if l.rstrip("\r\n") == LINES_MARK), None)
    if marker is None:
        if lines and lines[-1].strip():
            lines.append(eol)
        lines.append(LINES_MARK + eol)
        insert_at = len(lines)
    else:
        insert_at = marker + 1
        while insert_at < len(lines) and lines[insert_at].strip() and not lines[insert_at].startswith("#"):
            insert_at += 1
    lines[insert_at:insert_at] = [l + eol for l in missing]
    return "".join(lines), "create" if existing is None else "update"


def drop_lines(existing: str, wanted: list[str]) -> Optional[str]:
    lines = existing.splitlines(keepends=True)
    keep = [l for l in lines if l.rstrip("\r\n") not in wanted]
    idx = [i for i, l in enumerate(keep) if l.rstrip("\r\n") == LINES_MARK]
    for i in reversed(idx):
        nxt = keep[i + 1].strip() if i + 1 < len(keep) else ""
        if not nxt or nxt.startswith("#"):
            del keep[i]
            if i - 1 >= 0 and not keep[i - 1].strip() and (i >= len(keep) or not keep[i].strip()):
                del keep[i - 1]
    text = "".join(keep)
    return text if text.strip() else None


def _lines_for(rel: str, wiki_dir: str) -> list[str]:
    src = KIT / "templates" / rel
    if not src.is_file():
        return []
    out = []
    for l in src.read_text(encoding="utf-8").splitlines():
        l = l.rstrip()
        if not l or l == LINES_MARK:
            continue
        if wiki_dir != "wiki" and l.startswith("wiki/"):
            l = wiki_dir + l[len("wiki"):]
        out.append(l)
    return out


def _udiff(old: bytes, new: bytes, path: str) -> str:
    if old == new or not (_is_text(old) and _is_text(new)):
        return "" if old == new else f"(binary change: {path})\n"
    return "".join(difflib.unified_diff(old.decode("utf-8", "replace").splitlines(True),
                                        new.decode("utf-8", "replace").splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}"))


# ----------------------------------------------------------------------------------------------
# detection prefill (fresh install only)
# ----------------------------------------------------------------------------------------------
def _pick(d: dict, *keys):
    for k in keys:
        v = wconfig.get_dotted(d, k)
        if v not in (None, "", [], {}):
            return v
    return None


def _first_owner_from_codeowners(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts and parts[0] == "*" and len(parts) > 1 and parts[1].startswith("@"):
                return parts[1]
    except OSError:
        pass
    return ""


def prefill_from_detection(target: Path, data: dict, out: Out) -> None:
    cfg = wconfig.Config(data, None, target)
    try:
        det = ci_integrate.detect(target, cfg, probe_tools=False)
    except Exception as e:  # pragma: no cover
        out.warn(f"ci detection failed: {e}")
        det = {}
    host, path = det.get("remote_host"), det.get("remote_path")
    if path:
        data["repo"]["slug"] = path
        data["repo"]["id_prefix"] = path.rsplit("/", 1)[-1]
        if host:
            data["repo"]["gitlab_url"] = f"https://{host}/{path}"
    if det.get("default_branch"):
        data["repo"]["default_branch"] = det["default_branch"]
    sug = det.get("suggest") or {}
    if sug.get("prod") and sug["prod"] != data["repo"]["default_branch"]:
        data["branches"]["production"] = sug["prod"]
    if sug.get("staging"):
        data["branches"]["staging"] = sug["staging"]
    for w in det.get("warnings", []):
        if "already included" not in w and "no .gitlab-ci.yml" not in w:
            out.warn(w)

    detect_py = KIT_SCRIPTS / "detect.py"
    d: dict = {}
    if detect_py.is_file():
        try:
            r = subprocess.run([sys.executable, str(detect_py), "--json", "--repo", str(target)],
                               capture_output=True, text=True, timeout=120, cwd=str(target), env=SUB_ENV)
            line = next((l for l in reversed(r.stdout.strip().splitlines()) if l.startswith("{")), "")
            d = json.loads(line) if line else {}
            if not isinstance(d, dict):
                d = {}
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            out.warn(f"detect.py unusable ({e}); config prefilled from git only")
            d = {}
    else:
        out.say("note: detect.py not present in this kit; config prefilled from git only")
    if not d:
        co = target / "CODEOWNERS"
        for cand in (co, target / ".gitlab" / "CODEOWNERS", target / "docs" / "CODEOWNERS"):
            if cand.is_file():
                data["repo"]["team"] = _first_owner_from_codeowners(cand)
                break
        return
    slug = _pick(d, "repo.slug", "remote.slug", "remote.path", "slug", "remote_path")
    if isinstance(slug, str) and not data["repo"]["slug"]:
        data["repo"]["slug"] = slug
        data["repo"]["id_prefix"] = slug.rsplit("/", 1)[-1]
    url = _pick(d, "repo.gitlab_url", "remote.web_url", "gitlab_url", "remote.url", "remote_url")
    if isinstance(url, str) and not data["repo"]["gitlab_url"]:
        m = re.match(r"^(?:ssh://)?(?:[^@/]+@)?([^:/]+)[:/](.+?)(?:\.git)?/?$", url) if "://" not in url or url.startswith("ssh://") else \
            re.match(r"^[a-z+]+://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
        data["repo"]["gitlab_url"] = f"https://{m.group(1)}/{m.group(2)}" if m else url
    db = _pick(d, "repo.default_branch", "default_branch", "branches.default")
    if isinstance(db, str):
        data["repo"]["default_branch"] = db
    team = _pick(d, "repo.team", "codeowners.default_owner", "codeowners.owner", "team", "owners.default")
    if isinstance(team, str) and team.startswith("@"):
        data["repo"]["team"] = team
    else:
        co = _pick(d, "codeowners", "codeowners.path")
        if isinstance(co, str) and (target / co).is_file():
            data["repo"]["team"] = _first_owner_from_codeowners(target / co)
    roots = _pick(d, "roots", "sources.include", "source_roots")
    if isinstance(roots, list):
        vals = [r if isinstance(r, str) else (r.get("path") or r.get("root")) for r in roots]
        vals = [v.strip("/") for v in vals if isinstance(v, str) and v.strip("/")]
        if vals:
            data["sources"]["include"] = vals
    specs = _pick(d, "specs", "api_spec")
    if isinstance(specs, dict):
        for k in ("openapi", "asyncapi"):
            v = specs.get(k)
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                data["api_spec"][k] = v
    elif isinstance(specs, list):
        for s in specs:
            p = s if isinstance(s, str) else (s.get("path") or "")
            kind = (s.get("kind") or s.get("type") or "") if isinstance(s, dict) else ""
            low = (kind + " " + p).lower()
            if "asyncapi" in low:
                data["api_spec"]["asyncapi"].append(p)
            elif "openapi" in low or "swagger" in low:
                data["api_spec"]["openapi"].append(p)
    stacks = _pick(d, "stacks")
    if isinstance(stacks, list):
        names = [s if isinstance(s, str) else (s.get("name") or s.get("id")) for s in stacks]
        data["stacks"] = [n for n in names if isinstance(n, str)]
    sp = _pick(d, "branches.suggest_prod", "ci.suggest.prod")
    if isinstance(sp, str) and sp != data["repo"]["default_branch"] and not data["branches"]["production"]:
        data["branches"]["production"] = sp
    ss = _pick(d, "branches.suggest_staging", "ci.suggest.staging")
    if isinstance(ss, str) and not data["branches"]["staging"]:
        data["branches"]["staging"] = ss


# ----------------------------------------------------------------------------------------------
# planning
# ----------------------------------------------------------------------------------------------
class Installer:
    def __init__(self, opts, out: Out):
        self.opts = opts
        self.out = out
        self.target = Path(opts.target).resolve()
        self.version = kit_version()
        self.now = wcli.parse_iso(opts.now) if opts.now else wcli.utcnow()
        self.is_repo = gitio.is_repo(self.target) if self.target.is_dir() else False
        self.cfg_path = self.target / CONFIG_REL
        self.existing_cfg: Optional[dict] = None
        self.data: dict = {}
        self.actions: list[Action] = []
        self.pending_upgrade: list[str] = []
        self.wiki_dir = "wiki"

    # -- config ---------------------------------------------------------------------------------
    def load_config(self) -> None:
        if self.cfg_path.is_file():
            try:
                raw = json.loads(self.cfg_path.read_text(encoding="utf-8"))
            except ValueError as e:
                raise wcli.ConfigError(f"{self.cfg_path}: invalid JSON: {e}")
            if not isinstance(raw, dict):
                raise wcli.ConfigError(f"{self.cfg_path}: top level must be an object")
            self.existing_cfg = raw
            data = wconfig.merge_defaults(raw)
            for w in wconfig.validate(data):
                self.out.warn(f"config: {w}")
            if self.opts.wiki_dir and self.opts.wiki_dir.strip("/") != data["wiki_dir"]:
                self.out.warn(f"config has wiki_dir={data['wiki_dir']!r}; --wiki-dir {self.opts.wiki_dir!r} ignored "
                              f"(edit {CONFIG_REL} to move the wiki)")
        else:
            data = wconfig.defaults()
            data["wiki_dir"] = (self.opts.wiki_dir or "wiki").strip("/") or "wiki"
            if not self.opts.uninstall:
                prefill_from_detection(self.target, data, self.out)
            wconfig.validate(data)
        self.data = data
        self.wiki_dir = data["wiki_dir"]

    def _record(self) -> dict:
        return dict((self.data.get("kit") or {}).get("files") or {})

    # -- kit files ------------------------------------------------------------------------------
    def _kit_content(self, src: Path, rel: str, current: Optional[bytes]) -> bytes:
        data = src.read_bytes()
        if rel == CI_TARGET_REL and _is_text(data):
            text = data.decode("utf-8")
            if self.wiki_dir != "wiki":
                text = ci_integrate.set_wiki_dir(text, self.wiki_dir)
            if current is not None and _is_text(current):
                try:
                    old_settings = ci_integrate.read_project_settings(current.decode("utf-8"))
                    if old_settings:
                        text = ci_integrate.set_project_settings(text, old_settings)
                        # the old file's wiki dir wins when the config did not say otherwise
                        old_wd = ci_integrate.read_wiki_dir(current.decode("utf-8"))
                        if old_wd != ci_integrate.read_wiki_dir(text) and self.wiki_dir == "wiki":
                            text = ci_integrate.set_wiki_dir(text, old_wd)
                except wcli.KitError:
                    pass
            data = text.encode("utf-8")
        return data

    def plan_kit_files(self) -> None:
        record = self._record()
        for src, rel in kit_file_map(self.opts):
            dst = self.target / rel
            mode = src.stat().st_mode & 0o777
            current = dst.read_bytes() if dst.is_file() else None
            new = self._kit_content(src, rel, current)
            if current is None:
                self.actions.append(Action("kit", rel, "create", data=new, mode=mode, record=True))
                continue
            if current == new:
                self.actions.append(Action("kit", rel, "unchanged", data=new, mode=mode, record=True))
                continue
            cur_sha = sha(current)
            rec = record.get(rel)
            diff = _udiff(current, new, rel)
            if self.opts.force:
                self.actions.append(Action("kit", rel, "update", "forced", diff, new, mode, record=True))
            elif self.opts.upgrade or self.opts.check:
                if rec and cur_sha == rec:
                    self.actions.append(Action("kit", rel, "update", "kit version changed", diff, new, mode, record=True))
                else:
                    why = "locally modified (sha differs from the recorded one)" if rec else "no recorded sha (installed by hand?)"
                    self.actions.append(Action("kit", rel, "skip", why + "; use --force to overwrite", diff, new, mode))
                    if not self.opts.check:
                        self.out.warn(f"{rel}: {why}; kept as is (--force overwrites)")
            elif rec and rec == sha(new):
                # the kit did not change since the install: the user edited this file on purpose
                self.actions.append(Action("kit", rel, "unchanged", "locally modified; kept"))
            else:
                self.actions.append(Action("kit", rel, "skip", "differs from this kit version; run --upgrade", diff, new, mode))
                self.pending_upgrade.append(rel)

    # -- scaffold -------------------------------------------------------------------------------
    def plan_scaffold(self) -> None:
        cfg = wconfig.Config(self.data, self.cfg_path, self.target)
        head = gitio.head(self.target) if self.is_repo else None
        user = actor_user(self.target if self.is_repo else None)
        variables = wconfig.scaffold_vars(cfg, head=head or "", user=user, date=wcli.iso(self.now))
        for src, rel in scaffold_file_map(self.opts, self.wiki_dir):
            dst = self.target / rel
            if dst.exists():
                self.actions.append(Action("scaffold", rel, "unchanged", "exists (never overwritten)"))
                continue
            raw = src.read_bytes()
            if _is_text(raw):
                raw = wconfig.scaffold(raw.decode("utf-8"), variables).encode("utf-8")
            self.actions.append(Action("scaffold", rel, "create", data=raw, mode=src.stat().st_mode & 0o777))
        if not (KIT / WIKI_TEMPLATE_DIR).is_dir():
            self.out.warn(f"{WIKI_TEMPLATE_DIR}/ missing in this kit: no wiki scaffold written")

    # -- block ----------------------------------------------------------------------------------
    def plan_block(self) -> None:
        src = KIT / BLOCK_TEMPLATE_REL
        if not src.is_file():
            self.out.warn(f"{BLOCK_TEMPLATE_REL} missing in this kit: {BLOCK_TARGET_REL} not managed")
            return
        block = src.read_text(encoding="utf-8")
        if self.wiki_dir != "wiki":
            block = re.sub(r"(?<=[`\s(])wiki/", self.wiki_dir + "/", block)
        dst = self.target / BLOCK_TARGET_REL
        existing = dst.read_text(encoding="utf-8") if dst.is_file() else None
        new, op = upsert_block(existing, block, self.target.name)
        if op == "update" and existing is not None and BLOCK_START in existing and \
                not (self.opts.upgrade or self.opts.force):
            self.actions.append(Action("block", BLOCK_TARGET_REL, "skip", "managed block differs; run --upgrade",
                                       _udiff(existing.encode(), new.encode(), BLOCK_TARGET_REL)))
            self.pending_upgrade.append(BLOCK_TARGET_REL)
            return
        diff = _udiff((existing or "").encode("utf-8"), new.encode("utf-8"), BLOCK_TARGET_REL) if op != "unchanged" else ""
        self.actions.append(Action("block", BLOCK_TARGET_REL, op, "", diff, new.encode("utf-8"), 0o644))

    # -- lines ----------------------------------------------------------------------------------
    def plan_lines(self) -> None:
        for name in ("gitattributes", "gitignore"):
            wanted = _lines_for(name, self.wiki_dir)
            if not wanted:
                continue
            rel = "." + name
            dst = self.target / rel
            existing = dst.read_text(encoding="utf-8") if dst.is_file() else None
            new, op = ensure_lines(existing, wanted)
            diff = _udiff((existing or "").encode("utf-8"), new.encode("utf-8"), rel) if op != "unchanged" else ""
            self.actions.append(Action("lines", rel, op, "", diff, new.encode("utf-8"), 0o644))

    # -- record ---------------------------------------------------------------------------------
    def plan_record(self) -> None:
        files = {}
        old_files = self._record()
        for a in self.actions:
            if a.policy == "kit" and a.record and a.data is not None:
                files[a.path] = sha(a.data)
            elif a.policy == "kit" and a.path in old_files:
                files[a.path] = old_files[a.path]     # keep the record of a modified file untouched
        kit = self.data.setdefault("kit", {})
        other_changes = any(a.changes for a in self.actions)
        new_kit = {"version": self.version, "installed_at": kit.get("installed_at") or "",
                   "ci_include_form": kit.get("ci_include_form") or "", "files": files}
        candidate = dict(self.data)
        candidate["kit"] = new_kit
        existing_text = json.dumps(self.existing_cfg, indent=2, ensure_ascii=False) + "\n" if self.existing_cfg is not None else None
        new_text = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
        if existing_text is None:
            new_kit["installed_at"] = wcli.iso(self.now)
            new_text = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
            self.actions.append(Action("record", CONFIG_REL, "create", data=new_text.encode("utf-8"), mode=0o644))
        elif new_text != existing_text or other_changes:
            if other_changes or new_kit["version"] != kit.get("version"):
                new_kit["installed_at"] = wcli.iso(self.now)
                new_text = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
            if new_text != existing_text:
                self.actions.append(Action("record", CONFIG_REL, "update", "kit record / new keys",
                                           _udiff(existing_text.encode("utf-8"), new_text.encode("utf-8"), CONFIG_REL),
                                           new_text.encode("utf-8"), 0o644))
            else:
                self.actions.append(Action("record", CONFIG_REL, "unchanged"))
        else:
            self.actions.append(Action("record", CONFIG_REL, "unchanged"))
        self.data = candidate

    def plan(self) -> None:
        self.plan_kit_files()
        self.plan_scaffold()
        self.plan_block()
        self.plan_lines()
        self.plan_record()

    # -- execution ------------------------------------------------------------------------------
    def execute(self) -> None:
        for a in self.actions:
            if a.op not in ("create", "update") or a.data is None:
                continue
            dst = self.target / a.path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(a.data)
            if a.mode is not None:
                try:
                    dst.chmod((dst.stat().st_mode & ~0o777) | a.mode)
                except OSError:
                    pass

    def run_hooks(self, mode: str) -> Optional[dict]:
        script = self.target / SCRIPTS_REL / "hooks.py"
        if mode == "none" or not script.is_file() or not self.is_repo:
            return None
        cmd = [sys.executable, str(script), "install", "--hooks", mode, "--repo", str(self.target), "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.target), env=SUB_ENV)
        for line in r.stderr.strip().splitlines():
            self.out.say(f"  {line}")
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
        except ValueError:
            res = None
        if r.returncode != 0:
            self.out.warn(f"hooks.py install failed ({r.returncode}); run it by hand: {TEAMMATES}")
        return res

    # -- uninstall ------------------------------------------------------------------------------
    def plan_uninstall(self) -> None:
        record = self._record()
        current_map = {rel: src for src, rel in kit_file_map(self.opts)}
        rels = sorted(set(record) | set(current_map))
        for rel in rels:
            dst = self.target / rel
            if not dst.is_file():
                continue
            cur = dst.read_bytes()
            matches = (record.get(rel) == sha(cur)) or (rel in current_map and current_map[rel].read_bytes() == cur)
            if not matches and rel == CI_TARGET_REL and rel in current_map and _is_text(cur):
                # settings written by ci_integrate.py apply are ours too
                try:
                    kit_text = current_map[rel].read_text(encoding="utf-8")
                    norm = ci_integrate.set_project_settings(cur.decode("utf-8"),
                                                             ci_integrate.read_project_settings(kit_text))
                    matches = norm == kit_text or norm == ci_integrate.set_wiki_dir(kit_text, self.wiki_dir)
                except (wcli.KitError, UnicodeDecodeError):
                    matches = False
            if matches or self.opts.force:
                self.actions.append(Action("kit", rel, "remove"))
            else:
                self.actions.append(Action("kit", rel, "keep", "modified locally; kept (--force removes)"))
        dst = self.target / BLOCK_TARGET_REL
        if dst.is_file():
            existing = dst.read_text(encoding="utf-8")
            if BLOCK_START in existing:
                new = remove_block(existing)
                if new is None:
                    self.actions.append(Action("block", BLOCK_TARGET_REL, "remove", "only the managed block and header"))
                else:
                    self.actions.append(Action("block", BLOCK_TARGET_REL, "update", "managed block removed",
                                               _udiff(existing.encode(), new.encode(), BLOCK_TARGET_REL), new.encode("utf-8"), 0o644))
        for name in ("gitattributes", "gitignore"):
            rel = "." + name
            dst = self.target / rel
            wanted = _lines_for(name, self.wiki_dir)
            if not dst.is_file() or not wanted:
                continue
            existing = dst.read_text(encoding="utf-8")
            new = drop_lines(existing, wanted)
            if new is None:
                self.actions.append(Action("lines", rel, "remove", "only wiki-kit lines"))
            elif new != existing:
                self.actions.append(Action("lines", rel, "update", "wiki-kit lines removed",
                                           _udiff(existing.encode(), new.encode(), rel), new.encode("utf-8"), 0o644))
        if self.cfg_path.is_file():
            kit = self.data.setdefault("kit", {})
            kit["installed_at"] = ""
            kit["files"] = {}
            text = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
            self.actions.append(Action("record", CONFIG_REL, "update", "kit record cleared (answers kept)",
                                       data=text.encode("utf-8"), mode=0o644))

    def execute_uninstall(self) -> None:
        scripts = self.target / SCRIPTS_REL
        if (scripts / "ci_integrate.py").is_file():
            r = subprocess.run([sys.executable, str(scripts / "ci_integrate.py"), "remove", "--yes", "--repo", str(self.target)],
                               capture_output=True, text=True, cwd=str(self.target), env=SUB_ENV)
            self.out.say(f"  ci_integrate remove: {(r.stderr.strip().splitlines() or ['done'])[-1]}")
        if (scripts / "hooks.py").is_file() and self.is_repo:
            r = subprocess.run([sys.executable, str(scripts / "hooks.py"), "uninstall", "--repo", str(self.target)],
                               capture_output=True, text=True, cwd=str(self.target), env=SUB_ENV)
            for line in r.stderr.strip().splitlines():
                self.out.say(f"  {line}")
        for a in self.actions:
            dst = self.target / a.path
            if a.op == "remove" and dst.exists():
                dst.unlink()
            elif a.op == "update" and a.data is not None:
                dst.write_bytes(a.data)
        for d in (".github/skills/wiki-maintain/scripts/wikilib", ".github/skills/wiki-maintain/scripts",
                  ".github/skills/wiki-maintain/hooks", ".github/skills/wiki-maintain/references",
                  ".github/skills/wiki-maintain/prompts", ".github/skills/wiki-maintain",
                  ".github/skills/wiki-init/references", ".github/skills/wiki-init", ".github/skills/wiki-update",
                  ".github/skills/wiki-page", ".github/skills/wiki-query", ".github/skills/wiki-lint",
                  ".github/skills", ".github/agents", ".github/hooks", ".github/instructions", ".github/prompts",
                  ".github", ".gitlab/ci", ".gitlab/wiki-site", ".gitlab/issue_templates", ".gitlab"):
            p = self.target / d
            try:
                if p.is_dir():
                    for junk in p.rglob("__pycache__"):
                        shutil.rmtree(junk, ignore_errors=True)
                    if not any(p.iterdir()):
                        p.rmdir()
            except OSError:
                pass


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="install.py", description="Install the wiki kit into a repository.")
    p.add_argument("target", help="repository root")
    p.add_argument("--wiki-dir", default=None, help="wiki directory (default wiki; recorded in the config)")
    p.add_argument("--hooks", choices=["auto", "git", "pre-commit", "none"], default="auto")
    p.add_argument("--upgrade", action="store_true", help="overwrite unmodified kit files with this kit version")
    p.add_argument("--uninstall", action="store_true", help="remove kit files, block, lines, hooks and include; keep wiki/")
    p.add_argument("--force", action="store_true", help="overwrite (or remove) locally modified kit files too")
    p.add_argument("--dry-run", action="store_true", help="print actions and diffs; write nothing")
    p.add_argument("--check", action="store_true", help="report the installation state; exit 1 if anything is off")
    p.add_argument("--no-ci", action="store_true", help="skip .gitlab/ci/wiki.gitlab-ci.yml")
    p.add_argument("--no-site", action="store_true", help="skip .gitlab/wiki-site/")
    p.add_argument("--issue-template", action="store_true", help="also install .gitlab/issue_templates/Wiki request.md")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--json", action="store_true", help="one JSON object on stdout")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--now", default=None, help="ISO timestamp overriding the clock (tests)")
    return p


def _confirm(opts, question: str) -> bool:
    if opts.yes or not sys.stdin.isatty():
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _print_actions(inst: Installer, out: Out, show_diffs: bool) -> None:
    for a in inst.actions:
        if a.op == "unchanged" and not inst.opts.check:
            continue
        line = f"  {a.op:9s} {a.policy:8s} {a.path}"
        if a.reason:
            line += f"  ({a.reason})"
        out.say(line)
        if show_diffs and a.diff:
            out.say(a.diff.rstrip("\n"))


def main(argv: Optional[list] = None) -> int:
    opts = build_parser().parse_args(argv)
    out = Out(opts.json, opts.quiet)
    target = Path(opts.target)
    result: dict = {"schema_version": 1, "script": "install/" + kit_version(), "ok": True, "version": kit_version(),
                    "target": str(target.resolve()) if target.exists() else str(target), "actions": [], "warnings": out.warnings}

    def finish(rc: int, **extra) -> int:
        result.update(extra)
        result["ok"] = rc == 0
        if opts.json:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return rc

    if not target.is_dir():
        out.say(f"error: target is not a directory: {target}")
        return finish(2)
    try:
        inst = Installer(opts, out)
        if not inst.is_repo and opts.hooks != "none":
            out.say(f"error: {inst.target} is not a git repository (use --hooks none to install without git hooks)")
            return finish(3)
        inst.load_config()
    except wcli.KitError as e:
        out.say(f"error: {e}")
        return finish(e.code)

    mode = "uninstall" if opts.uninstall else "check" if opts.check else "upgrade" if opts.upgrade else "install"
    result["mode"] = mode

    if opts.uninstall:
        inst.plan_uninstall()
        result["actions"] = [a.as_dict() for a in inst.actions]
        out.say(f"wiki-kit {inst.version}: uninstall from {inst.target}")
        _print_actions(inst, out, show_diffs=opts.dry_run)
        if opts.dry_run:
            out.say("dry run: nothing changed")
            return finish(0, dry_run=True)
        if not _confirm(opts, "Remove the wiki kit (wiki/ stays)?"):
            out.say("aborted")
            return finish(1)
        inst.execute_uninstall()
        out.say(f"wiki-kit {inst.version}: removed; {inst.wiki_dir}/ and {CONFIG_REL} (answers) were left in place")
        return finish(0)

    inst.plan()
    result["actions"] = [a.as_dict() for a in inst.actions]
    changes = [a for a in inst.actions if a.changes]
    pending = inst.pending_upgrade
    up_to_date = not changes and not pending

    if opts.check:
        out.say(f"wiki-kit {inst.version}: check {inst.target}")
        _print_actions(inst, out, show_diffs=False)
        hooks_ok = True
        script = inst.target / SCRIPTS_REL / "hooks.py"
        if inst.is_repo and script.is_file() and opts.hooks != "none":
            r = subprocess.run([sys.executable, str(script), "status", "--json", "--repo", str(inst.target)],
                               capture_output=True, text=True, cwd=str(inst.target), env=SUB_ENV)
            try:
                st = json.loads(r.stdout.strip().splitlines()[-1])
                hooks_ok = bool(st.get("installed"))
                result["hooks"] = st
                out.say(f"  hooks: {st.get('mode')} ({'installed' if hooks_ok else 'not installed: ' + TEAMMATES})")
            except (ValueError, IndexError):
                hooks_ok = False
        bad = [a for a in inst.actions if a.op in ("create", "update", "skip")]
        rc = 0 if (not bad and hooks_ok) else 1
        out.say(f"wiki-kit {inst.version}: {'installed and up to date' if rc == 0 else str(len(bad)) + ' item(s) need attention'}")
        return finish(rc, up_to_date=(rc == 0))

    if up_to_date:
        out.say(f"wiki-kit {inst.version}: up to date ({inst.target})")
        hooks_res = None if opts.dry_run else inst.run_hooks(opts.hooks)
        return finish(0, up_to_date=True, hooks=hooks_res)

    out.say(f"wiki-kit {inst.version}: {mode} into {inst.target} (wiki dir: {inst.wiki_dir})")
    _print_actions(inst, out, show_diffs=opts.dry_run)
    if pending and not changes:
        out.say(f"{len(pending)} kit item(s) differ from this kit version; run with --upgrade to update them")
        hooks_res = None if opts.dry_run else inst.run_hooks(opts.hooks)
        return finish(0, up_to_date=False, pending_upgrade=pending, hooks=hooks_res)
    if opts.dry_run:
        out.say(f"dry run: {len(changes)} change(s) not written; would run: {SCRIPTS_REL}/hooks.py install --hooks {opts.hooks}")
        return finish(0, dry_run=True, up_to_date=False)
    if not _confirm(opts, f"Write {len(changes)} change(s) into {inst.target}?"):
        out.say("aborted")
        return finish(1)
    inst.execute()
    hooks_res = inst.run_hooks(opts.hooks)
    if pending:
        out.say(f"{len(pending)} kit item(s) differ from this kit version; run with --upgrade to update them")
    model = inst.data.get("models", {}).get("bootstrap", "claude-sonnet-4.6")
    out.say("")
    out.say(f"wiki-kit {inst.version}: {len(changes)} change(s) written")
    out.say("Next steps:")
    out.say("  " + NEXT_STEPS.format(repo=inst.target, model=model))
    out.say(f"Teammates (each clone): {TEAMMATES}")
    if opts.hooks == "none":
        out.say("No git hooks installed (--hooks none): start runs with run.py worker --foreground")
    return finish(0, up_to_date=False, pending_upgrade=pending, hooks=hooks_res, written=len(changes))


if __name__ == "__main__":
    sys.exit(main())
