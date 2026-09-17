"""`.github/wiki.config.json`: defaults, load/validate, dotted access, scaffold placeholders.

Rules (plan §8.1): unknown keys warn, wrong types error (exit 2), keys starting with `_` are
comments. Written by install.py (defaults + detection) and /wiki-init (answers).
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from . import KIT_VERSION, SCHEMA_VERSION
from .cli import ConfigError

CONFIG_REL_PATH = ".github/wiki.config.json"

# Verbatim defaults from plan §8.1. Order is preserved when written.
DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "kit": {"version": KIT_VERSION, "installed_at": "", "ci_include_form": "", "files": {}},
    "wiki_dir": "wiki",
    "repo": {"slug": "", "id_prefix": "", "gitlab_url": "", "default_branch": "main", "team": ""},
    "language": "en",
    "models": {"bootstrap": "claude-sonnet-4.6", "incremental": "gpt-5-mini"},
    "copilot": {"bin": None},
    "max_pages": 8,
    "budgets": {
        "max_source_bytes_per_run": 200000, "max_source_bytes_per_cluster": 120000,
        "max_pages_per_cluster": 6,
        "max_excerpt_lines": 120, "max_excerpt_lines_per_run": 800, "read_max_bytes": 65536,
        "run_timeout_s": 1200, "bootstrap_timeout_s": 1800, "max_requests_per_run": 5,
        "max_request_chars": 500,
        "debounce_s": 120, "lock_ttl_min": 60, "lint_sample_pages": 10, "session_context_kb": 30,
        "max_lines": {
            "Overview": 150, "Architecture": 200, "Module": 200, "Concept": 120, "How-to": 120,
            "Contract": 400, "Contract Guide": 150, "Runbook": 150, "Glossary": 300, "Feature": 80,
            "Capability Map": 150, "Release Notes": 200, "What Changed": 60, "Analysis": 200,
            "Generated": 400, "Conventions": 150, "Requests": 400, "Instructions": 300,
        },
        "index_root_lines": 120, "index_folder_lines": 200, "log_entries": 200,
    },
    "sources": {
        "include": ["src", "app", "lib", "services", "cmd", "pkg"],
        "exclude": ["**/node_modules/**", "**/.venv/**", "**/dist/**", "**/build/**", "**/*.min.js",
                    "**/vendor/**", "**/__snapshots__/**", "**/*.lock"],
    },
    "coverage": {"depth": 2, "min_files": 3, "ignore_tests": True},
    "api_spec": {"openapi": [], "asyncapi": [], "export_hint": ""},
    "branches": {"production": "", "staging": "", "dev_previews": True, "parallel_deployments": False,
                 "dev_expire_in": "1 week", "skip_runs_on": ["renovate/*", "release/*"]},
    "pages": {"enabled": True, "site_title": "", "access": "members"},
    "commit_policy": "commit",
    "isolation": "in-place",
    "po_layer": False,
    "po": {"reviewers": [], "max_sentence_words": 25,
           "forbidden_words": ["endpoint", "repository", "MR", "merge request", "JSON", "null", "exception",
                               "refactor", "schema", "payload", "identifier", "identifiers", "stack trace",
                               "commit"]},
    "stacks": [],
    "hooks": {"write_tools": ["edit", "write", "create", "multi_edit", "apply_patch", "str_replace_editor"],
              "shell_tools": ["shell", "bash", "execute", "run_in_terminal"],
              "read_tools": ["read", "view"], "unknown_tool": "pass"},
    "secrets_denylist": [],
}

ENUMS = {
    "commit_policy": ("commit", "branch-and-mr"),
    "isolation": ("in-place", "worktree"),
    "pages.access": ("members", "public"),
    "hooks.unknown_tool": ("pass", "deny"),
}


def find_config(repo: Path, explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit) if Path(explicit).is_absolute() else (Path(repo) / explicit)
    env = os.environ.get("WIKI_CONFIG")
    if env:
        return Path(env) if Path(env).is_absolute() else (Path(repo) / env)
    return Path(repo) / CONFIG_REL_PATH


def _strip_comments(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    return obj


def merge_defaults(user: dict, defaults: Optional[dict] = None) -> dict:
    """Deep-merge user values over defaults (dicts merge, everything else replaces)."""
    base = copy.deepcopy(DEFAULTS if defaults is None else defaults)

    def _merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = copy.deepcopy(v)
        return dst

    return _merge(base, _strip_comments(user))


def _type_name(v: Any) -> str:
    return {bool: "boolean", int: "integer", float: "number", str: "string", list: "list",
            dict: "object", type(None): "null"}.get(type(v), type(v).__name__)


def validate(data: dict, defaults: Optional[dict] = None) -> list[str]:
    """Return warnings; raise ConfigError on wrong types or bad enum values."""
    warnings: list[str] = []
    ref = DEFAULTS if defaults is None else defaults

    def _walk(d: Any, r: Any, path: str) -> None:
        if isinstance(r, dict) and isinstance(d, dict):
            for k, v in d.items():
                if str(k).startswith("_"):
                    continue
                if k not in r:
                    if path in ("budgets.max_lines", "kit.files"):
                        continue  # open maps
                    warnings.append(f"unknown key {path + '.' if path else ''}{k}")
                    continue
                _walk(v, r[k], f"{path}.{k}" if path else k)
            return
        if r is None:
            return  # any type allowed (e.g. copilot.bin)
        if isinstance(r, bool) or isinstance(d, bool):
            if not (isinstance(d, bool) and isinstance(r, bool)):
                raise ConfigError(f"config key {path}: expected {_type_name(r)}, got {_type_name(d)}")
            return
        if isinstance(r, (int, float)):
            if not isinstance(d, (int, float)):
                raise ConfigError(f"config key {path}: expected number, got {_type_name(d)}")
            return
        if isinstance(r, str) and d is None and path in ("kit.installed_at",):
            return
        if type(d) is not type(r):
            raise ConfigError(f"config key {path}: expected {_type_name(r)}, got {_type_name(d)}")
        if isinstance(r, list) and r and all(isinstance(x, str) for x in r):
            for x in d:
                if not isinstance(x, str):
                    raise ConfigError(f"config key {path}: list items must be strings")

    _walk(data, ref, "")
    for key, allowed in ENUMS.items():
        val = get_dotted(data, key)
        if val is not None and val not in allowed:
            raise ConfigError(f"config key {key}: {val!r} not in {list(allowed)}")
    if data.get("commit_policy") == "branch-and-mr" and data.get("isolation") != "worktree":
        warnings.append("commit_policy branch-and-mr forces isolation=worktree")
        data["isolation"] = "worktree"
    wd = str(data.get("wiki_dir", "wiki"))
    if not wd or wd.startswith("/") or ".." in wd.split("/"):
        raise ConfigError(f"wiki_dir must be a relative path inside the repository: {wd!r}")
    return warnings


def get_dotted(data: dict, key: str, default: Any = None) -> Any:
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_dotted(data: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def coerce_value(text: str) -> Any:
    """Parse a CLI value: JSON when it parses, else the raw string."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


class Config:
    """Loaded configuration with dotted access."""

    def __init__(self, data: dict, path: Optional[Path], repo: Optional[Path], warnings: Iterable[str] = ()):
        self.data = data
        self.path = path
        self.repo = repo
        self.warnings = list(warnings)

    def get(self, key: str, default: Any = None) -> Any:
        return get_dotted(self.data, key, default)

    def set(self, key: str, value: Any) -> None:
        set_dotted(self.data, key, value)

    def __getitem__(self, key: str) -> Any:
        v = get_dotted(self.data, key, KeyError)
        if v is KeyError:
            raise KeyError(key)
        return v

    @property
    def wiki_dir(self) -> str:
        return str(self.data.get("wiki_dir", "wiki")).strip("/") or "wiki"

    @property
    def wiki_path(self) -> Path:
        return (self.repo or Path(".")) / self.wiki_dir

    @property
    def id_prefix(self) -> str:
        p = self.get("repo.id_prefix") or ""
        if not p:
            slug = self.get("repo.slug") or ""
            p = slug.rsplit("/", 1)[-1] if slug else (self.repo.name if self.repo else "wiki")
        return p

    def budget(self, key: str) -> Any:
        return get_dotted(self.data, f"budgets.{key}", get_dotted(DEFAULTS, f"budgets.{key}"))

    def max_lines(self, page_type: str) -> Optional[int]:
        return get_dotted(self.data, "budgets.max_lines", {}).get(page_type)

    def save(self, path: Optional[Path] = None) -> Path:
        p = Path(path or self.path)
        return save(p, self.data)


def load(repo: Optional[Path] = None, path: Optional[str] = None, strict: bool = False,
         warn: bool = True) -> Config:
    """Load + validate; a missing file yields the defaults (with a warning unless strict)."""
    import sys

    repo = Path(repo) if repo else Path.cwd()
    cfg_path = find_config(repo, path)
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ConfigError(f"{cfg_path}: invalid JSON: {e}")
        if not isinstance(raw, dict):
            raise ConfigError(f"{cfg_path}: top level must be an object")
        data = merge_defaults(raw)
        warnings = validate(data)
    else:
        if strict:
            raise ConfigError(f"config not found: {cfg_path}")
        data = copy.deepcopy(DEFAULTS)
        warnings = [f"config not found at {cfg_path}; using defaults"]
    if warn:
        for w in warnings:
            print(f"wiki.config: warning: {w}", file=sys.stderr)
    return Config(data, cfg_path, repo, warnings)


def save(path: Path, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}")


def scaffold(text: str, variables: dict) -> str:
    """Substitute `{{name}}` placeholders; unknown placeholders are left untouched."""

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in variables and variables[key] is not None:
            return str(variables[key])
        return m.group(0)

    return _PLACEHOLDER.sub(_sub, text)


def scaffold_vars(cfg: Config, *, head: str = "", user: str = "", model: str = "", date: str = "") -> dict:
    """Standard placeholder set (plan §8.8)."""
    slug = cfg.get("repo.slug") or (cfg.repo.name if cfg.repo else "project")
    return {
        "repo_slug": slug,
        "id_prefix": cfg.id_prefix,
        "site_title": cfg.get("pages.site_title") or f"{slug.rsplit('/', 1)[-1]} wiki",
        "date": date,
        "head": head,
        "model": model or cfg.get("models.bootstrap"),
        "user": user,
        "team": (cfg.get("repo.team") or "").lstrip("@"),
        "wiki_dir": cfg.wiki_dir,
        "gitlab_url": cfg.get("repo.gitlab_url") or "",
        "default_branch": cfg.get("repo.default_branch") or "main",
    }


__all__ = ["CONFIG_REL_PATH", "DEFAULTS", "ENUMS", "Config", "ConfigError", "find_config", "merge_defaults",
           "validate", "get_dotted", "set_dotted", "coerce_value", "load", "save", "defaults", "scaffold",
           "scaffold_vars"]
