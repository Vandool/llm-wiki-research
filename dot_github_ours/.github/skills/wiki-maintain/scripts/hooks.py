#!/usr/bin/env python3
"""hooks.py — per-clone git hook setup for the wiki kit (plan §8.13).

  hooks.py install [--hooks auto|git|pre-commit|none]   write the two trampolines into the git hooks
                                                        directory (existing hooks are kept as <name>.local),
                                                        or print the pre-commit / husky / lefthook lines
  hooks.py uninstall                                    remove our trampolines, restore <name>.local
  hooks.py status [--json]                              what is installed, which mode, off switches

The committed hook bodies live in .github/skills/wiki-maintain/hooks/{post-commit,pre-push,pre-commit-lint};
the trampolines in .git/hooks only chain to them, so a kit upgrade never needs a hook reinstall.
`core.hooksPath` is honoured: when a hook manager owns the hooks directory nothing is written and the
lines to add are printed instead. `git config wiki.dir` is set when the wiki directory is not `wiki`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from wikilib import cli, gitio  # noqa: E402
from wikilib.cli import EXIT_OK, EnvError  # noqa: E402

NAME = "hooks"
VERSION = "1.0.0"
HOOK_NAMES = ("post-commit", "pre-push")
KIT_HOOK_DIR = ".github/skills/wiki-maintain/hooks"
MARK = "wiki-kit trampoline"

# Verbatim from plan §8.13. Regenerated on every `install`; never edited by hand.
TRAMPOLINES = {
    "post-commit": """#!/bin/sh
# wiki-kit trampoline v1 — regenerate with: python3 .github/skills/wiki-maintain/scripts/hooks.py install
d=$(dirname "$0"); [ -x "$d/post-commit.local" ] && "$d/post-commit.local" "$@"
r=$(git rev-parse --show-toplevel 2>/dev/null) && [ -f "$r/.github/skills/wiki-maintain/hooks/post-commit" ] \\
  && sh "$r/.github/skills/wiki-maintain/hooks/post-commit" "$@"
exit 0
""",
    "pre-push": """#!/bin/sh
# wiki-kit trampoline v1 (pre-push; stdin forwarded to both)
d=$(dirname "$0"); r=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
in=$(cat)
if [ -x "$d/pre-push.local" ]; then printf '%s\\n' "$in" | "$d/pre-push.local" "$@" || exit $?; fi
[ -f "$r/.github/skills/wiki-maintain/hooks/pre-push" ] && printf '%s\\n' "$in" | sh "$r/.github/skills/wiki-maintain/hooks/pre-push" "$@"
""",
}

PRE_COMMIT_SNIPPET = """# .pre-commit-config.yaml — add under `repos:` (the hook bodies are committed in this repository)
default_install_hook_types: [pre-commit, post-commit, pre-push]
repos:
  - repo: local
    hooks:
      - id: wiki-post-commit
        name: wiki update (background, Copilot CLI)
        entry: .github/skills/wiki-maintain/hooks/post-commit
        language: script
        always_run: true
        pass_filenames: false
        stages: [post-commit]
      - id: wiki-pre-push
        name: wiki staleness check
        entry: .github/skills/wiki-maintain/hooks/pre-push
        language: script
        always_run: true
        pass_filenames: false
        stages: [pre-push]
      - id: wiki-lint
        name: wiki lint (staged pages)
        entry: .github/skills/wiki-maintain/hooks/pre-commit-lint
        language: script
        pass_filenames: false
        files: ^wiki/
# then: pre-commit install --hook-type pre-commit --hook-type post-commit --hook-type pre-push"""

HUSKY_LINES = f"""# husky (core.hooksPath -> .husky): append to .husky/post-commit and .husky/pre-push
echo 'sh {KIT_HOOK_DIR}/post-commit "$@"' >> .husky/post-commit
echo 'sh {KIT_HOOK_DIR}/pre-push "$@" < /dev/stdin' >> .husky/pre-push"""

LEFTHOOK_LINES = f"""# lefthook.yml: add
post-commit:
  jobs:
    - name: wiki
      run: sh {KIT_HOOK_DIR}/post-commit
pre-push:
  jobs:
    - name: wiki
      run: sh {KIT_HOOK_DIR}/pre-push"""


def hooks_dir(repo: Path, git_dir: Path) -> tuple[Path, Optional[str]]:
    hp = gitio.config_get("core.hooksPath", repo)
    if hp:
        p = Path(os.path.expanduser(hp))
        if not p.is_absolute():
            p = repo / p
        return p, hp
    return git_dir / "hooks", None


def hook_state(path: Path) -> str:
    """absent | ours | foreign"""
    if not path.is_file():
        return "absent"
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
    except OSError:
        return "foreign"
    return "ours" if MARK in head else "foreign"


def _is_exec(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False


def _chmod_x(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def install_trampolines(hdir: Path, emit: cli.Emitter) -> dict:
    hdir.mkdir(parents=True, exist_ok=True)
    actions: dict = {}
    for name, body in TRAMPOLINES.items():
        target = hdir / name
        local = hdir / f"{name}.local"
        st = hook_state(target)
        if st == "foreign":
            if local.exists():
                bak = hdir / f"{name}.local.bak"
                local.replace(bak)
                emit.warn(f"{local.name} already existed; kept as {bak.name}")
            target.replace(local)
            _chmod_x(local)
            actions[name] = f"installed (existing hook kept as {local.name})"
        elif st == "ours" and target.read_text(encoding="utf-8") == body and _is_exec(target):
            actions[name] = "unchanged"
            continue
        else:
            actions[name] = "installed" if st == "absent" else "updated"
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
    return actions


def uninstall_trampolines(hdir: Path) -> dict:
    actions: dict = {}
    for name in HOOK_NAMES:
        target = hdir / name
        local = hdir / f"{name}.local"
        st = hook_state(target)
        if st == "ours":
            target.unlink()
            if local.exists():
                local.replace(target)
                actions[name] = f"removed ({local.name} restored)"
            else:
                actions[name] = "removed"
        elif st == "foreign":
            actions[name] = "left in place (not ours)"
        else:
            actions[name] = "absent"
    return actions


def _pre_commit_info(repo: Path) -> dict:
    cfg = repo / ".pre-commit-config.yaml"
    configured = False
    if cfg.is_file():
        try:
            configured = "wiki-post-commit" in cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            configured = False
    return {"config": cfg.is_file(), "binary": bool(shutil.which("pre-commit")), "configured": configured}


def _manager(repo: Path, hooks_path: Optional[str]) -> str:
    if not hooks_path:
        return "git"
    hp = hooks_path.lower()
    if "husky" in hp or (repo / ".husky").is_dir():
        return "husky"
    if "lefthook" in hp or (repo / "lefthook.yml").is_file() or (repo / ".lefthook.yml").is_file():
        return "lefthook"
    return "hooksPath"


def _sync_wiki_dir(ctx: cli.Ctx) -> dict:
    wd = ctx.cfg.wiki_dir if ctx.cfg else "wiki"
    cur = gitio.config_get("wiki.dir", ctx.repo)
    action = "unchanged"
    if wd != "wiki":
        if cur != wd:
            gitio.config_set("wiki.dir", wd, ctx.repo)
            action = f"set wiki.dir={wd}"
    elif cur:
        gitio.git(["config", "--unset", "wiki.dir"], ctx.repo, check=False)
        action = "unset wiki.dir"
    return {"wiki_dir": wd, "git_config": action}


def status(ctx: cli.Ctx) -> dict:
    repo, git_dir = ctx.repo, ctx.git_dir
    hdir, hp = hooks_dir(repo, git_dir)
    hooks = {}
    for name in HOOK_NAMES:
        p = hdir / name
        hooks[name] = {"path": str(p), "state": hook_state(p), "executable": _is_exec(p),
                       "local": (hdir / f"{name}.local").exists()}
    pc = _pre_commit_info(repo)
    manager = _manager(repo, hp)
    chained = False
    if hp:
        for name in HOOK_NAMES:
            p = hdir / name
            try:
                chained = chained or (p.is_file() and f"{KIT_HOOK_DIR}/{name}" in p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    tramp = all(h["state"] == "ours" for h in hooks.values())
    if tramp:
        mode = "git"
    elif pc["configured"]:
        mode = "pre-commit"
    elif hp and chained:
        mode = manager
    else:
        mode = "none"
    return {
        "mode": mode, "installed": mode != "none", "hooks_dir": str(hdir), "hooks_path": hp, "manager": manager,
        "hooks": hooks, "pre_commit": pc,
        "kit_hooks_present": all((repo / KIT_HOOK_DIR / n).is_file() for n in HOOK_NAMES),
        "wiki_dir": ctx.cfg.wiki_dir if ctx.cfg else "wiki", "wiki_dir_config": gitio.config_get("wiki.dir", repo),
        "disabled": {"env": os.environ.get("WIKI_HOOK_DISABLE") == "1",
                     "git_config": gitio.config_get("wiki.hook.disable", repo) == "true"},
        "strict": os.environ.get("WIKI_STRICT") == "1" or gitio.config_get("wiki.strict", repo) == "true",
    }


def cmd_install(ctx: cli.Ctx, args) -> int:
    em = ctx.emit
    repo, git_dir = ctx.repo, ctx.git_dir
    hdir, hp = hooks_dir(repo, git_dir)
    pc = _pre_commit_info(repo)
    manager = _manager(repo, hp)
    mode = args.hooks
    if mode == "auto":
        mode = "pre-commit" if (pc["config"] and pc["binary"]) else "git"
    res: dict = {"requested": args.hooks, "mode": mode, "hooks_dir": str(hdir), "hooks_path": hp, "manager": manager,
                 "actions": {}, "notes": []}
    if not (repo / KIT_HOOK_DIR / "post-commit").is_file():
        em.warn(f"{KIT_HOOK_DIR}/post-commit not found in this repository; the trampolines will be no-ops "
                f"until the kit files are committed")
    if mode == "none":
        res["notes"].append("no git hooks installed (--hooks none); run.py worker can still be started by hand")
    elif mode == "pre-commit":
        if not pc["binary"]:
            em.warn("pre-commit binary not found; install it (pipx install pre-commit) or use --hooks git")
        if pc["configured"]:
            res["notes"].append(".pre-commit-config.yaml already lists the wiki hooks")
        else:
            res["notes"].append("add the wiki hooks to .pre-commit-config.yaml (snippet below)")
            em.out(PRE_COMMIT_SNIPPET)
        res["notes"].append("run: pre-commit install --hook-type pre-commit --hook-type post-commit --hook-type pre-push")
    elif hp:
        # a hook manager or a personal hooks dir owns core.hooksPath: never write there
        res["mode"] = manager
        res["notes"].append(f"core.hooksPath={hp}: nothing written; add the lines below to that hook set")
        em.warn(f"core.hooksPath is set ({hp}); printing the lines to add instead of writing trampolines")
        if manager == "husky":
            em.out(HUSKY_LINES)
        elif manager == "lefthook":
            em.out(LEFTHOOK_LINES)
        else:
            em.out(f"# {hp}/post-commit and {hp}/pre-push: add\n"
                   f"r=$(git rev-parse --show-toplevel) && sh \"$r/{KIT_HOOK_DIR}/post-commit\" \"$@\"\n"
                   f"r=$(git rev-parse --show-toplevel) && sh \"$r/{KIT_HOOK_DIR}/pre-push\" \"$@\"")
    else:
        res["actions"] = install_trampolines(hdir, em)
        for name, a in res["actions"].items():
            em.say(f"hooks: {hdir / name}: {a}")
    res["wiki_dir"] = _sync_wiki_dir(ctx)
    if res["wiki_dir"]["git_config"] != "unchanged":
        em.say(f"hooks: git config {res['wiki_dir']['git_config']}")
    for n in res["notes"]:
        em.say(f"hooks: {n}")
    em.emit(res, ok=True)
    return EXIT_OK


def cmd_uninstall(ctx: cli.Ctx, args) -> int:
    em = ctx.emit
    hdir, hp = hooks_dir(ctx.repo, ctx.git_dir)
    actions = uninstall_trampolines(hdir)
    for name, a in actions.items():
        em.say(f"hooks: {hdir / name}: {a}")
    if gitio.config_get("wiki.dir", ctx.repo):
        gitio.git(["config", "--unset", "wiki.dir"], ctx.repo, check=False)
    if hp:
        em.say(f"hooks: core.hooksPath={hp}: remove the wiki lines from that hook set by hand")
    if _pre_commit_info(ctx.repo)["configured"]:
        em.say("hooks: .pre-commit-config.yaml still lists the wiki hooks; remove them and run `pre-commit install`")
    em.emit({"hooks_dir": str(hdir), "hooks_path": hp, "actions": actions}, ok=True)
    return EXIT_OK


def cmd_status(ctx: cli.Ctx, args) -> int:
    em = ctx.emit
    st = status(ctx)
    if em.as_json:
        em.emit(st, ok=True)
        return EXIT_OK
    em.out(f"mode:        {st['mode']} ({'installed' if st['installed'] else 'not installed'})")
    em.out(f"hooks dir:   {st['hooks_dir']}" + (f"  (core.hooksPath={st['hooks_path']}, {st['manager']})" if st['hooks_path'] else ""))
    for name, h in st["hooks"].items():
        extra = " +local" if h["local"] else ""
        em.out(f"  {name:12s} {h['state']}{' (not executable)' if h['state'] != 'absent' and not h['executable'] else ''}{extra}")
    pc = st["pre_commit"]
    em.out(f"pre-commit:  config={'yes' if pc['config'] else 'no'} binary={'yes' if pc['binary'] else 'no'} wiki hooks configured={'yes' if pc['configured'] else 'no'}")
    em.out(f"wiki dir:    {st['wiki_dir']}" + (f" (git config wiki.dir={st['wiki_dir_config']})" if st['wiki_dir_config'] else ""))
    d = st["disabled"]
    if d["env"] or d["git_config"]:
        em.out(f"disabled:    {'WIKI_HOOK_DISABLE=1 ' if d['env'] else ''}{'git config wiki.hook.disable=true' if d['git_config'] else ''}".rstrip())
    if st["strict"]:
        em.out("strict:      pre-push blocks on stale pages")
    if not st["kit_hooks_present"]:
        em.out(f"note:        {KIT_HOOK_DIR}/* missing in this checkout (kit not installed or not committed)")
    return EXIT_OK


def _add_common(sp: argparse.ArgumentParser) -> None:
    S = argparse.SUPPRESS
    sp.add_argument("--repo", default=S)
    sp.add_argument("--config", default=S)
    sp.add_argument("--json", action="store_true", default=S)
    sp.add_argument("--quiet", action="store_true", default=S)
    sp.add_argument("--now", default=S)


def build_parser() -> argparse.ArgumentParser:
    p = cli.base_parser(NAME, VERSION, "Install, remove or inspect the wiki-kit git hook trampolines.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="install|uninstall|status")
    sp = sub.add_parser("install", help="write the trampolines (or print the hook-manager lines)")
    sp.add_argument("--hooks", choices=["auto", "git", "pre-commit", "none"], default="auto")
    _add_common(sp)
    sp = sub.add_parser("uninstall", help="remove the trampolines, restore <name>.local")
    _add_common(sp)
    sp = sub.add_parser("status", help="show what is installed")
    _add_common(sp)
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if ctx.git_dir is None:
        raise EnvError(f"not a git repository: {ctx.repo}")
    return {"install": cmd_install, "uninstall": cmd_uninstall, "status": cmd_status}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
