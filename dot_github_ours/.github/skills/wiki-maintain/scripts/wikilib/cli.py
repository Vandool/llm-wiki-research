"""Common CLI base for every wiki-kit script.

Conventions (plan §8.6): --repo PATH (default toplevel), --config PATH (default
.github/wiki.config.json, env WIKI_CONFIG), --json (exactly one JSON object on stdout, human
text on stderr), --quiet, --now ISO (clock override for tests).

Exit codes: 0 ok · 1 findings/check failed · 2 usage/config · 3 environment (not a repo, lock
held, wiki dirty) · 4 model/subprocess failure.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import KIT_VERSION, SCHEMA_VERSION

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_ENV = 3
EXIT_MODEL = 4


class KitError(Exception):
    """Base class; `code` is the process exit code."""

    code = EXIT_USAGE

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class ConfigError(KitError):
    code = EXIT_USAGE


class EnvError(KitError):
    code = EXIT_ENV


class ModelError(KitError):
    code = EXIT_MODEL


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def iso(dt: _dt.datetime) -> str:
    """`2026-09-07T10:15:00Z` (UTC, second precision)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> _dt.datetime:
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def add_common(p: argparse.ArgumentParser, suppress: bool = False) -> argparse.ArgumentParser:
    """Add the shared options. With `suppress=True` (sub-parsers) unspecified options do not
    overwrite values already parsed by the parent parser."""
    d = argparse.SUPPRESS if suppress else None
    f = argparse.SUPPRESS if suppress else False
    p.add_argument("--repo", default=d, help="repository root (default: git toplevel of cwd)")
    p.add_argument("--config", default=d,
                   help="config path (default .github/wiki.config.json or $WIKI_CONFIG)")
    p.add_argument("--json", action="store_true", default=f, help="print exactly one JSON object on stdout")
    p.add_argument("--quiet", action="store_true", default=f, help="suppress human output on stderr")
    p.add_argument("--now", default=d, help="ISO timestamp overriding the clock (tests)")
    return p


def base_parser(name: str, version: str, description: str, **kw) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"{name}.py", description=description, **kw)
    add_common(p)
    p.set_defaults(_script=name, _version=version)
    return p


def subparsers(p: argparse.ArgumentParser, dest: str = "cmd"):
    """Sub-command container whose sub-parsers also accept the common options after the command."""
    sub = p.add_subparsers(dest=dest, required=True)
    original = sub.add_parser

    def add_parser(name: str, **kw):
        sp = original(name, **kw)
        add_common(sp, suppress=True)
        return sp

    sub.add_parser = add_parser  # type: ignore[assignment]
    return sub


class Emitter:
    """Human text goes to stderr; with --json exactly one object goes to stdout."""

    def __init__(self, script: str, version: str, as_json: bool = False, quiet: bool = False):
        self.script = script
        self.version = version
        self.as_json = as_json
        self.quiet = quiet
        self._emitted = False

    def say(self, *parts: Any) -> None:
        if not self.quiet:
            print(" ".join(str(p) for p in parts), file=sys.stderr)

    def warn(self, msg: str) -> None:
        print(f"{self.script}: warning: {msg}", file=sys.stderr)

    def out(self, text: str) -> None:
        """Human-readable stdout (only when not --json)."""
        if not self.as_json:
            print(text)

    def emit(self, payload: dict, ok: bool = True) -> None:
        """Print the single JSON object (when --json). Adds schema_version/script/ok."""
        if not self.as_json:
            return
        if self._emitted:
            raise RuntimeError("emit() called twice")
        obj = {"schema_version": SCHEMA_VERSION, "script": f"{self.script}/{self.version}", "ok": ok}
        obj.update(payload)
        sys.stdout.write(json.dumps(obj, indent=None, sort_keys=False, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        self._emitted = True

    @property
    def emitted(self) -> bool:
        return self._emitted


class Ctx:
    """Resolved runtime context for a script invocation."""

    def __init__(self, args: argparse.Namespace, need_config: bool = True, need_repo: bool = True):
        from . import gitio, config as _config

        self.args = args
        self.emit = Emitter(args._script, args._version, getattr(args, "json", False),
                            getattr(args, "quiet", False))
        self.now = parse_iso(args.now) if getattr(args, "now", None) else utcnow()
        self.repo: Optional[Path] = None
        self.git_dir: Optional[Path] = None
        if need_repo:
            start = Path(args.repo).resolve() if args.repo else Path.cwd()
            try:
                self.repo = Path(gitio.toplevel(start))
                self.git_dir = Path(gitio.git_dir(self.repo))
            except gitio.GitError as e:
                if args.repo and Path(args.repo).is_dir():
                    self.repo = Path(args.repo).resolve()
                    self.git_dir = None
                else:
                    raise EnvError(f"not a git repository: {start} ({e})")
        self.cfg = None
        if need_config:
            self.cfg = _config.load(self.repo, args.config)
        self.wiki_dir: Optional[Path] = (self.repo / self.cfg.wiki_dir) if (self.cfg and self.repo) else None

    @property
    def state_dir(self) -> Path:
        """`$(git rev-parse --git-dir)/wiki/` — volatile run state, never committed."""
        base = self.git_dir if self.git_dir else (self.repo / ".git")
        d = base / "wiki"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log(self, name: str, message: str) -> None:
        log_to(self.state_dir, name, message)


def log_to(state_dir: Path, name: str, message: str, max_bytes: int = 1_000_000) -> None:
    """Append a timestamped line to `<git-dir>/wiki/<name>.log` with 1 MB rotation."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        p = state_dir / f"{name}.log"
        if p.exists() and p.stat().st_size > max_bytes:
            p.replace(state_dir / f"{name}.log.1")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(f"{iso(utcnow())} {message}\n")
    except OSError:
        pass


def run(main: Callable[[argparse.Namespace], int], parser: argparse.ArgumentParser,
        argv: Optional[list] = None) -> int:
    """Parse, call main(args) -> exit code, map KitError to exit codes; JSON error when --json."""
    args = parser.parse_args(argv)
    try:
        rc = main(args)
        return int(rc or 0)
    except KitError as e:
        if getattr(args, "json", False):
            obj = {"schema_version": SCHEMA_VERSION, "script": f"{args._script}/{args._version}",
                   "ok": False, "error": str(e), "exit": e.code}
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        print(f"{args._script}: error: {e}", file=sys.stderr)
        return e.code


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


__all__ = [
    "EXIT_OK", "EXIT_FINDINGS", "EXIT_USAGE", "EXIT_ENV", "EXIT_MODEL",
    "KitError", "ConfigError", "EnvError", "ModelError",
    "utcnow", "iso", "parse_iso", "base_parser", "add_common", "subparsers", "Emitter", "Ctx", "log_to", "run",
    "env_flag",
    "KIT_VERSION",
]
