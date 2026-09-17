"""Read-budget metering into `<git-dir>/wiki/run.json` (plan §8.7.4, §8.15).

API:
  run_path(git_dir) -> Path
  load_run(git_dir) -> dict | None                 None when no run.json exists / unreadable
  save_run(git_dir, run) -> Path                   atomic write
  add_bytes(git_dir, n) -> (total, exhausted)      meters `budget.bytes_read`; (0, False) without a run
  add_excerpt_lines(git_dir, n) -> (total, exhausted)
  is_exhausted(run) -> bool
  update_run(git_dir, **fields) -> dict | None     merge top-level fields
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

__all__ = ["run_path", "load_run", "save_run", "add_bytes", "add_excerpt_lines", "is_exhausted", "update_run"]


def run_path(git_dir: Path) -> Path:
    return Path(git_dir) / "wiki" / "run.json"


def load_run(git_dir: Path) -> Optional[dict]:
    p = run_path(git_dir)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_run(git_dir: Path, run: dict) -> Path:
    p = run_path(git_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".run-", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def is_exhausted(run: Optional[dict]) -> bool:
    if not run:
        return False
    b = run.get("budget") or {}
    limit = b.get("max_source_bytes")
    used = b.get("bytes_read", 0) or 0
    lines_limit = b.get("max_excerpt_lines_per_run")
    lines_used = b.get("excerpt_lines_used", 0) or 0
    if isinstance(limit, (int, float)) and limit > 0 and used > limit:
        return True
    if isinstance(lines_limit, (int, float)) and lines_limit > 0 and lines_used > lines_limit:
        return True
    return bool(run.get("over_budget"))


def _add(git_dir: Path, key: str, n: int) -> tuple[int, bool]:
    run = load_run(git_dir)
    if run is None:
        return 0, False
    b = run.setdefault("budget", {})
    b[key] = int(b.get(key, 0) or 0) + int(n)
    exhausted = is_exhausted(run)
    if exhausted:
        run["over_budget"] = True
    try:
        save_run(git_dir, run)
    except OSError:
        pass
    return b[key], exhausted


def add_bytes(git_dir: Path, n: int) -> tuple[int, bool]:
    return _add(git_dir, "bytes_read", n)


def add_excerpt_lines(git_dir: Path, n: int) -> tuple[int, bool]:
    return _add(git_dir, "excerpt_lines_used", n)


def update_run(git_dir: Path, **fields) -> Optional[dict]:
    run = load_run(git_dir)
    if run is None:
        return None
    run.update(fields)
    save_run(git_dir, run)
    return run
