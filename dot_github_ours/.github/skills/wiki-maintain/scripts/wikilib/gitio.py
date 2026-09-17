"""Thin git plumbing wrappers (subprocess, no third-party code)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional, Union

PathLike = Union[str, Path]


class GitError(Exception):
    pass


def git(args: Iterable[str], cwd: Optional[PathLike] = None, check: bool = True, text: bool = True,
        input: Optional[Union[str, bytes]] = None, env: Optional[dict] = None) -> Union[str, bytes]:
    """Run `git <args>` and return stdout (stripped when text). Raises GitError when check and rc != 0."""
    cmd = ["git", *[str(a) for a in args]]
    e = dict(os.environ)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    if env:
        e.update(env)
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=text,
                             input=input, env=e)
    except FileNotFoundError:
        raise GitError("git executable not found")
    if check and res.returncode != 0:
        err = res.stderr if text else res.stderr.decode("utf-8", "replace")
        raise GitError(f"git {' '.join(str(a) for a in args)} failed ({res.returncode}): {err.strip()}")
    return res.stdout.strip() if text else res.stdout


def git_rc(args: Iterable[str], cwd: Optional[PathLike] = None) -> int:
    res = subprocess.run(["git", *[str(a) for a in args]], cwd=str(cwd) if cwd else None,
                         capture_output=True, text=True)
    return res.returncode


def toplevel(cwd: Optional[PathLike] = None) -> str:
    return git(["rev-parse", "--show-toplevel"], cwd)


def git_dir(cwd: Optional[PathLike] = None) -> str:
    d = git(["rev-parse", "--git-dir"], cwd)
    p = Path(d)
    if not p.is_absolute():
        p = (Path(cwd) if cwd else Path.cwd()) / p
    return str(p.resolve())


def is_repo(cwd: PathLike) -> bool:
    return git_rc(["rev-parse", "--is-inside-work-tree"], cwd) == 0


def head(cwd: Optional[PathLike] = None) -> Optional[str]:
    """Full HEAD sha or None for an unborn branch."""
    try:
        return git(["rev-parse", "--verify", "HEAD"], cwd)
    except GitError:
        return None


def rev_parse(rev: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    try:
        return git(["rev-parse", "--verify", "--quiet", rev], cwd)
    except GitError:
        return None


def is_ancestor(a: str, b: str, cwd: Optional[PathLike] = None) -> bool:
    return git_rc(["merge-base", "--is-ancestor", a, b], cwd) == 0


def merge_base(a: str, b: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    try:
        return git(["merge-base", a, b], cwd)
    except GitError:
        return None


def ls_files(cwd: Optional[PathLike] = None, paths: Iterable[str] = (), rev: Optional[str] = None) -> list[str]:
    """Tracked files (working tree index) or files in a tree at `rev`."""
    if rev:
        out = git(["ls-tree", "-r", "--name-only", "-z", rev, "--", *paths], cwd, text=False)
    else:
        out = git(["ls-files", "-z", "--", *paths], cwd, text=False)
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def show(rev: str, path: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    """File content at `rev` (text), None if it does not exist there."""
    try:
        return git(["show", f"{rev}:{path}"], cwd, text=False).decode("utf-8", "replace")
    except GitError:
        return None


def show_bytes(rev: str, path: str, cwd: Optional[PathLike] = None) -> Optional[bytes]:
    try:
        return git(["show", f"{rev}:{path}"], cwd, text=False)
    except GitError:
        return None


def blob_sha(rev: str, path: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    return rev_parse(f"{rev}:{path}", cwd)


def diff_name_status(a: str, b: str, cwd: Optional[PathLike] = None, paths: Iterable[str] = ()) -> list[tuple[str, str, Optional[str]]]:
    """`git diff --name-status -M --diff-filter=ACMRD a..b` → [(status, path, new_path_or_None)]."""
    out = git(["diff", "--name-status", "-M", "--diff-filter=ACMRD", "-z", f"{a}", f"{b}", "--", *paths],
              cwd, text=False)
    parts = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0")]
    res: list[tuple[str, str, Optional[str]]] = []
    i = 0
    while i < len(parts):
        st = parts[i]
        if not st:
            i += 1
            continue
        if st[0] in ("R", "C"):
            res.append((st[0], parts[i + 1], parts[i + 2]))
            i += 3
        else:
            res.append((st[0], parts[i + 1], None))
            i += 2
    return res


def diff_text(a: str, b: str, path: str, cwd: Optional[PathLike] = None, context: int = 3) -> str:
    return git(["diff", f"-U{context}", "--no-color", f"{a}", f"{b}", "--", path], cwd)


def diff_tree_files(rev: str = "HEAD", cwd: Optional[PathLike] = None) -> list[str]:
    """Files touched by one commit (empty for merge commits, like the hook)."""
    out = git(["diff-tree", "--no-commit-id", "--name-only", "-r", rev], cwd)
    return [l for l in out.splitlines() if l]


def status_porcelain(cwd: Optional[PathLike] = None, paths: Iterable[str] = ()) -> list[str]:
    out = git(["status", "--porcelain", "--untracked-files=all", "--", *paths], cwd)
    return [l for l in out.splitlines() if l.strip()]


def changed_paths(cwd: Optional[PathLike] = None, paths: Iterable[str] = (), base: Optional[str] = None,
                  staged_only: bool = False) -> list[str]:
    """Repo-relative paths changed in the working tree/index (incl. untracked), plus `base..HEAD` when given."""
    out: set[str] = set()
    if staged_only:
        try:
            txt = git(["diff", "--name-only", "--cached", "-z", "--", *paths], cwd, text=False)
            out.update(p.decode("utf-8", "surrogateescape") for p in txt.split(b"\0") if p)
        except GitError:
            pass
        return sorted(out)
    try:
        txt = git(["status", "--porcelain", "--untracked-files=all", "-z", "--", *paths], cwd, text=False)
        parts = [p.decode("utf-8", "surrogateescape") for p in txt.split(b"\0")]
        i = 0
        while i < len(parts):
            rec = parts[i]
            if not rec:
                i += 1
                continue
            status, path = rec[:2], rec[3:]
            out.add(path)
            if status[0] in ("R", "C") and i + 1 < len(parts):
                i += 1  # the original path follows as its own record
            i += 1
    except GitError:
        pass
    if base:
        try:
            txt = git(["diff", "--name-only", "-z", base, "HEAD", "--", *paths], cwd, text=False)
            out.update(p.decode("utf-8", "surrogateescape") for p in txt.split(b"\0") if p)
        except GitError:
            pass
    return sorted(out)


def log(cwd: Optional[PathLike] = None, n: int = 200, fmt: str = "%H%x00%cI%x00%an%x00%s%x00%b%x1e",
        extra: Iterable[str] = (), rev_range: Optional[str] = None) -> list[dict]:
    args = ["log", f"-n{n}", f"--format={fmt}", *extra]
    if rev_range:
        args.append(rev_range)
    try:
        out = git(args, cwd)
    except GitError:
        return []
    entries = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        f = rec.split("\x00")
        if len(f) < 4:
            continue
        entries.append({"sha": f[0].strip(), "date": f[1].strip(), "author": f[2].strip(), "subject": f[3].strip(),
                        "body": f[4] if len(f) > 4 else ""})
    return entries


def commit_message(rev: str = "HEAD", cwd: Optional[PathLike] = None) -> str:
    try:
        return git(["log", "-1", "--format=%B", rev], cwd)
    except GitError:
        return ""


def committer_date(rev: str = "HEAD", cwd: Optional[PathLike] = None) -> Optional[str]:
    """ISO-8601 committer date (`%cI`) – identical on every machine for the same commit."""
    try:
        return git(["log", "-1", "--format=%cI", rev], cwd)
    except GitError:
        return None


def remote_url(cwd: Optional[PathLike] = None, remote: str = "origin") -> Optional[str]:
    try:
        return git(["remote", "get-url", remote], cwd)
    except GitError:
        return None


def default_branch(cwd: Optional[PathLike] = None, remote: str = "origin") -> Optional[str]:
    """origin/HEAD target, else `init.defaultBranch`, else main/master if present."""
    try:
        ref = git(["symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"], cwd)
        return ref.rsplit("/", 1)[-1]
    except GitError:
        pass
    for cand in ("main", "master"):
        if rev_parse(f"refs/heads/{cand}", cwd):
            return cand
    return current_branch(cwd)


def current_branch(cwd: Optional[PathLike] = None) -> Optional[str]:
    try:
        return git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    except GitError:
        return None


def branches(cwd: Optional[PathLike] = None, remote: bool = True) -> list[str]:
    args = ["for-each-ref", "--format=%(refname:short)", "refs/remotes" if remote else "refs/heads"]
    try:
        out = git(args, cwd)
    except GitError:
        return []
    res = []
    for l in out.splitlines():
        l = l.strip()
        if not l or l.endswith("/HEAD"):
            continue
        res.append(l.split("/", 1)[1] if remote and "/" in l else l)
    return res


def config_get(key: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    try:
        return git(["config", "--get", key], cwd)
    except GitError:
        return None


def config_set(key: str, value: str, cwd: Optional[PathLike] = None) -> None:
    git(["config", key, value], cwd)


def in_progress_rebase_or_merge(cwd: Optional[PathLike] = None) -> bool:
    gd = Path(git_dir(cwd))
    return any((gd / n).exists() for n in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"))


def add(paths: Iterable[str], cwd: Optional[PathLike] = None, all_: bool = False) -> None:
    if all_:
        git(["add", "-A", "--", *paths], cwd)
    else:
        git(["add", "--", *paths], cwd)


def commit(message: str, cwd: Optional[PathLike] = None, trailers: Optional[dict] = None,
           paths: Iterable[str] = (), env: Optional[dict] = None, allow_empty: bool = False) -> str:
    """Commit with trailers written into the message body (works on any git version). Returns sha."""
    body = message.rstrip("\n")
    if trailers:
        body += "\n\n" + "\n".join(f"{k}: {v}" for k, v in trailers.items())
    args = ["commit", "-q", "-F", "-"]
    if allow_empty:
        args.append("--allow-empty")
    if paths:
        args += ["--", *paths]
    e = {"WIKI_HOOK_RUNNING": "1"}
    if env:
        e.update(env)
    git(args, cwd, input=body + "\n", env=e)
    return head(cwd) or ""


def trailer(rev: str, key: str, cwd: Optional[PathLike] = None) -> Optional[str]:
    """Value of a `Key: value` trailer line in the commit message, or None."""
    msg = commit_message(rev, cwd)
    for line in msg.splitlines():
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip()
    return None


def worktree_add(path: PathLike, rev: str = "HEAD", cwd: Optional[PathLike] = None, branch: Optional[str] = None) -> None:
    args = ["worktree", "add", "--detach" if not branch else "-b", *( [branch] if branch else [] ), str(path), rev]
    git(args, cwd)


def worktree_remove(path: PathLike, cwd: Optional[PathLike] = None, force: bool = True) -> None:
    args = ["worktree", "remove"] + (["--force"] if force else []) + [str(path)]
    git(args, cwd, check=False)


def tree_hash(paths: Iterable[str], cwd: Optional[PathLike] = None) -> str:
    """Stable hash of the *working tree* content of `paths` (tracked + untracked), for the verified marker."""
    import hashlib

    h = hashlib.sha256()
    root = Path(toplevel(cwd))
    files: list[str] = []
    for p in paths:
        base = root / p
        if base.is_file():
            files.append(str(base))
        elif base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file() and ".git" not in f.parts:
                    files.append(str(f))
    for f in sorted(files):
        h.update(os.path.relpath(f, root).encode("utf-8") + b"\0")
        try:
            h.update(Path(f).read_bytes())
        except OSError:
            pass
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


__all__ = [n for n in dir() if not n.startswith("_")]
