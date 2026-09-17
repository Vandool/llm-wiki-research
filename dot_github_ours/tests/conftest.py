"""Shared test helpers. Importable under both `python3 -m unittest discover -s tests` and pytest.

Usage in a test module:
    from conftest import KIT, SCRIPTS, FIXTURES, make_repo, run_script, git, TempDir
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

KIT = Path(__file__).resolve().parent.parent
SCRIPTS = KIT / ".github" / "skills" / "wiki-maintain" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_COPILOT = Path(__file__).resolve().parent / "fake_copilot.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test User", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2026-09-07T10:00:00+00:00", "GIT_COMMITTER_DATE": "2026-09-07T10:00:00+00:00",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": tempfile.gettempdir(),
    "WIKI_HOOK_DISABLE": "1",
}


def env_with(extra: Optional[dict] = None, **kw) -> dict:
    e = dict(os.environ)
    e.update(GIT_ENV)
    e.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if extra:
        e.update(extra)
    e.update(kw)
    return e


def git(repo: Path, *args: str, check: bool = True, input: Optional[str] = None,
        env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=check,
                          input=input, env=env_with(env))


def git_out(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.strip()


class TempDir:
    """Context manager around tempfile.mkdtemp (unittest-friendly)."""

    def __init__(self, prefix: str = "wikikit-"):
        self.prefix = prefix
        self.path: Optional[Path] = None

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix=self.prefix))
        return self.path

    def __exit__(self, *exc) -> None:
        if self.path and not os.environ.get("WIKIKIT_KEEP_TMP"):
            shutil.rmtree(self.path, ignore_errors=True)


def make_repo(tmp: Path, fixture: str = "sample-repo", commit: bool = True, name: str = "repo",
              branch: str = "main") -> Path:
    """git init a copy of a fixture (default sample-repo) under tmp/<name>; one initial commit."""
    repo = tmp / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", branch)
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    if fixture:
        src = FIXTURES / fixture
        shutil.copytree(src, repo, dirs_exist_ok=True)
    if commit:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fixture")
    return repo


def commit_all(repo: Path, message: str = "change", env: Optional[dict] = None) -> str:
    git(repo, "add", "-A", env=env)
    git(repo, "commit", "-q", "-m", message, env=env)
    return git_out(repo, "rev-parse", "HEAD")


def run_script(name: str, *args: str, cwd: Optional[Path] = None, env: Optional[dict] = None,
               input: Optional[str] = None, check: bool = False, timeout: int = 120,
               scripts: Path = SCRIPTS) -> subprocess.CompletedProcess:
    """Run `python3 <scripts>/<name>.py <args>` in `cwd`; returns CompletedProcess (text)."""
    script = scripts / (name if name.endswith(".py") else f"{name}.py")
    return subprocess.run([sys.executable, str(script), *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, input=input, env=env_with(env), check=check,
                          timeout=timeout)


def run_json(name: str, *args: str, **kw) -> dict:
    """Run a script with --json and parse the single JSON object on stdout."""
    if "--json" not in args:
        args = (*args, "--json")
    res = run_script(name, *args, **kw)
    out = res.stdout.strip()
    assert out, f"{name}: no stdout (stderr: {res.stderr})"
    try:
        obj = json.loads(out)
    except ValueError as e:
        raise AssertionError(f"{name}: stdout is not one JSON object: {e}\n{out}\nstderr: {res.stderr}")
    obj["_rc"] = res.returncode
    obj["_stderr"] = res.stderr
    return obj


def read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj: dict) -> Path:
    return write(path, json.dumps(obj, indent=2) + "\n")


def install_kit(repo: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run the kit installer against `repo` (non-interactive)."""
    return subprocess.run([sys.executable, str(KIT / "install.py"), str(repo), "--yes", *args],
                          capture_output=True, text=True, env=env_with(env))


# ---- pytest fixtures (only when pytest is the runner) ----
try:  # pragma: no cover
    import pytest  # type: ignore

    @pytest.fixture
    def tmp_repo(tmp_path):
        return make_repo(tmp_path)
except Exception:  # pragma: no cover
    pass
