#!/usr/bin/env python3
"""config.py — read and write `.github/wiki.config.json` for scripts, hooks and shell.

CLI:
  config.py get KEY [--json]                      value of a dotted key (strings raw, else JSON)
  config.py set KEY VALUE [--json]                VALUE parsed as JSON when it parses, else string
  config.py init --from detect.json --answers answers.json [--force] [--json]
  config.py quartz-ignore [--json]                ignore patterns for quartz.config.yaml
  config.py validate [--json]                     load strictly; warnings to stderr; exit 2 on errors
Common: --repo PATH --config PATH --quiet --now ISO. Exit 0 ok · 2 usage/config · 3 not a repo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, config as wconfig  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "config"

QUARTZ_IGNORE = ["private", "templates", ".obsidian", "instructions.md", "requests.md", ".manifest.json",
                 ".wiki-plan.json", ".gitignore", "log/**", "**/.DS_Store"]

# detect.json → config keys (only applied when the config value is still the default/empty)
_DETECT_MAP = {
    "slug": "repo.slug", "gitlab_url": "repo.gitlab_url", "default_branch": "repo.default_branch",
    "team": "repo.team", "roots": "sources.include", "stacks": "stacks",
}


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    sub = cli.subparsers(p)
    g = sub.add_parser("get", help="print one value")
    g.add_argument("key")
    s = sub.add_parser("set", help="set one value and save")
    s.add_argument("key")
    s.add_argument("value")
    i = sub.add_parser("init", help="write the config from detection + answers")
    i.add_argument("--from", dest="detect", default=None, help="detect.py --json output file")
    i.add_argument("--answers", default=None, help="JSON object of answers (dotted or nested keys)")
    i.add_argument("--force", action="store_true", help="overwrite values already set")
    sub.add_parser("quartz-ignore", help="print the Quartz ignorePatterns list")
    sub.add_parser("validate", help="validate the config file")
    return p


def _apply(data: dict, key: str, value: Any, force: bool) -> bool:
    current = wconfig.get_dotted(data, key)
    default = wconfig.get_dotted(wconfig.DEFAULTS, key)
    if force or current in (None, "", [], {}) or current == default:
        wconfig.set_dotted(data, key, value)
        return True
    return False


def cmd_init(ctx: cli.Ctx, args) -> int:
    path = wconfig.find_config(ctx.repo, args.config)
    if path.exists():
        base = wconfig.load(ctx.repo, args.config, warn=False).data
    else:
        base = wconfig.defaults()
    applied: list[str] = []
    if args.detect:
        det = json.loads(Path(args.detect).read_text(encoding="utf-8"))
        for src, dst in _DETECT_MAP.items():
            val = det.get(src)
            if val in (None, "", [], {}):
                continue
            if _apply(base, dst, val, args.force):
                applied.append(dst)
        specs = det.get("specs") or {}
        if isinstance(specs, dict):
            for kind in ("openapi", "asyncapi"):
                if specs.get(kind) and _apply(base, f"api_spec.{kind}", list(specs[kind]), args.force):
                    applied.append(f"api_spec.{kind}")
        br = det.get("branches") or {}
        if isinstance(br, dict):
            if br.get("suggest_staging") and _apply(base, "branches.staging", br["suggest_staging"], args.force):
                applied.append("branches.staging")
        if det.get("name") and not base.get("repo", {}).get("id_prefix"):
            base["repo"]["id_prefix"] = str(det["name"]).rsplit("/", 1)[-1]
            applied.append("repo.id_prefix")
    if args.answers:
        ans = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        if not isinstance(ans, dict):
            raise cli.ConfigError("answers must be a JSON object")

        def _walk(obj: dict, prefix: str) -> None:
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                ref = wconfig.get_dotted(wconfig.DEFAULTS, key)
                if isinstance(v, dict) and isinstance(ref, dict) and key not in ("budgets.max_lines", "kit.files"):
                    _walk(v, key)
                else:
                    wconfig.set_dotted(base, key, v)
                    applied.append(key)

        _walk(ans, "")
    base.setdefault("kit", {})
    base["kit"]["version"] = cli.KIT_VERSION
    if not base["kit"].get("installed_at"):
        base["kit"]["installed_at"] = cli.iso(ctx.now)
    data = wconfig.merge_defaults(base)
    warnings = wconfig.validate(data)
    for w in warnings:
        ctx.emit.warn(w)
    wconfig.save(path, data)
    ctx.emit.say(f"wrote {path} ({len(applied)} keys applied)")
    ctx.emit.emit({"path": str(path), "applied": sorted(set(applied)), "warnings": warnings})
    return 0


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=False, need_repo=True)
    if args.cmd == "init":
        return cmd_init(ctx, args)
    strict = args.cmd == "validate"
    cfg = wconfig.load(ctx.repo, args.config, strict=strict, warn=not args.quiet)
    if args.cmd == "validate":
        ctx.emit.say(f"ok: {cfg.path} ({len(cfg.warnings)} warning(s))")
        ctx.emit.emit({"path": str(cfg.path), "warnings": cfg.warnings})
        return 0
    if args.cmd == "quartz-ignore":
        ctx.emit.out(json.dumps(QUARTZ_IGNORE))
        ctx.emit.emit({"ignore": QUARTZ_IGNORE, "wiki_dir": cfg.wiki_dir})
        return 0
    if args.cmd == "get":
        val = cfg.get(args.key, KeyError)
        if val is KeyError:
            raise cli.ConfigError(f"unknown key {args.key}")
        if args.json:
            ctx.emit.emit({"key": args.key, "value": val})
        else:
            print(val if isinstance(val, str) else json.dumps(val, ensure_ascii=False))
        return 0
    if args.cmd == "set":
        value = wconfig.coerce_value(args.value)
        current = cfg.get(args.key, KeyError)
        if current is KeyError and wconfig.get_dotted(wconfig.DEFAULTS, args.key) is None \
                and not args.key.startswith(("budgets.max_lines.", "kit.files.")):
            ctx.emit.warn(f"unknown key {args.key} (written anyway)")
        cfg.set(args.key, value)
        wconfig.validate(cfg.data)
        cfg.save()
        ctx.emit.say(f"{args.key} = {json.dumps(value)} → {cfg.path}")
        ctx.emit.emit({"key": args.key, "value": value, "path": str(cfg.path)})
        return 0
    raise cli.ConfigError(f"unknown command {args.cmd}")


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
