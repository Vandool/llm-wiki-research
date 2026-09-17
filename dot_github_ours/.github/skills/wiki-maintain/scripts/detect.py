#!/usr/bin/env python3
"""detect.py — stack detection for /wiki-init and install.py (thin CLI over wikilib + ci_integrate.detect).

CLI: detect.py [--json] [--repo PATH] [--config PATH]
Output (--json): {name, stacks[], languages{}, frameworks[], package_manager, entry_points[], test_runner,
  evidence{}, roots[], excludes[], specs{openapi[], asyncapi[]}, adr_dir, codeowners, team, remote{url, host,
  slug, https_url}, slug, gitlab_url, default_branch, branches{local[], remote[], suggest_prod, suggest_staging,
  ci_vars{}}, ci{…from ci_integrate.detect…}, validators{}}
Importable: detect(repo, cfg) -> dict, detect_stacks(files, repo) -> (stacks, evidence).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import cli, gitio, specs as wspecs, symbols  # noqa: E402
from wikilib.pages import is_excluded, is_test_path  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "detect"

_NON_ROOT_DIRS = {"tests", "test", "docs", "doc", "scripts", "script", "examples", "example", "node_modules", "vendor",
                  "build", "dist", "target", "out", "bin", "obj", ".venv", "venv", "env", "migrations", "fixtures",
                  "tools", "ci", "deploy", "infra", "public", "static", "assets", "wiki", "coverage"}
_ENTRY_NAMES = {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "server.py", "__main__.py", "index.ts",
                "index.js", "server.ts", "server.js", "app.ts", "app.js", "main.go", "main.ts", "main.js", "Program.cs",
                "Application.java", "main.rs"}
_ADR_DIRS = ("docs/adr", "docs/decisions", "adr", "doc/adr", "architecture/decisions", "docs/architecture/decisions")
_CODEOWNERS = ("CODEOWNERS", ".gitlab/CODEOWNERS", "docs/CODEOWNERS", ".github/CODEOWNERS")
_STAGING_NAMES = ("preprod", "staging", "stage", "develop", "dev", "development", "uat", "qa")
_BRANCH_VAR_RE = re.compile(r"^\s*(BRANCH_PROD|PROD_BRANCH|PRODUCTION_BRANCH|BRANCH_PREPROD|PREPROD_BRANCH|STAGING_BRANCH|BRANCH_STAGING)\s*:\s*[\"']?([\w./-]+)[\"']?\s*$", re.M)
_PY_FRAMEWORKS = ("fastapi", "flask", "django", "starlette", "aiohttp", "sanic", "litestar", "tornado", "celery", "sqlalchemy", "pydantic")
_JS_FRAMEWORKS = {"express": "express", "@nestjs/core": "nestjs", "next": "next", "react": "react", "vue": "vue",
                  "fastify": "fastify", "koa": "koa", "@angular/core": "angular", "svelte": "svelte", "hono": "hono"}
_GO_FRAMEWORKS = {"github.com/gin-gonic/gin": "gin", "github.com/labstack/echo": "echo", "github.com/go-chi/chi": "chi",
                  "github.com/gofiber/fiber": "fiber", "github.com/gorilla/mux": "gorilla-mux"}


def _read(repo: Path, rel: str, limit: int = 200_000) -> str:
    try:
        return (repo / rel).read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def tracked_files(repo: Path) -> list[str]:
    try:
        files = gitio.ls_files(repo)
        if files:
            return files
    except gitio.GitError:
        pass
    out: list[str] = []
    for p in sorted(Path(repo).rglob("*")):
        if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts:
            out.append(p.relative_to(repo).as_posix())
    return out


def detect_stacks(files: Iterable[str], repo: Path) -> tuple[list[dict], dict]:
    """[{name, frameworks[], package_manager, manifest}] and evidence {stack: [files]}."""
    files = list(files)
    fs = set(files)
    stacks: list[dict] = []
    evidence: dict[str, list[str]] = {}

    def has(name: str) -> bool:
        return name in fs

    py_manifest = next((f for f in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile") if has(f)), None)
    py_files = [f for f in files if f.endswith(".py")]
    if py_manifest or len(py_files) >= 3:
        text = (_read(repo, "pyproject.toml") + "\n" + _read(repo, "requirements.txt") + "\n" + _read(repo, "setup.py")
                + "\n" + _read(repo, "Pipfile")).lower()
        fw = [f for f in _PY_FRAMEWORKS if re.search(r"\b" + re.escape(f) + r"\b", text)]
        pm = "uv" if has("uv.lock") else "poetry" if has("poetry.lock") else "pipenv" if has("Pipfile.lock") or has("Pipfile") \
            else "pdm" if has("pdm.lock") else "pip"
        stacks.append({"name": "python", "frameworks": fw, "package_manager": pm, "manifest": py_manifest})
        evidence["python"] = [f for f in (py_manifest, "requirements.txt", "uv.lock", "poetry.lock") if f and has(f)][:4] or py_files[:3]
    if has("package.json"):
        try:
            pkg = json.loads(_read(repo, "package.json") or "{}")
        except ValueError:
            pkg = {}
        deps = {}
        for k in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(pkg.get(k), dict):
                deps.update(pkg[k])
        fw = sorted({v for k, v in _JS_FRAMEWORKS.items() if k in deps})
        if "typescript" in deps or any(f.endswith((".ts", ".tsx")) for f in files):
            fw.append("typescript")
        pm = "pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "bun" if has("bun.lockb") or has("bun.lock") else "npm"
        stacks.append({"name": "node", "frameworks": fw, "package_manager": pm, "manifest": "package.json",
                       "scripts": sorted((pkg.get("scripts") or {}).keys())[:10]})
        evidence["node"] = ["package.json"] + [f for f in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json") if has(f)]
    if has("go.mod"):
        text = _read(repo, "go.mod")
        fw = sorted({v for k, v in _GO_FRAMEWORKS.items() if k in text})
        stacks.append({"name": "go", "frameworks": fw, "package_manager": "go", "manifest": "go.mod"})
        evidence["go"] = ["go.mod"]
    jm = next((f for f in ("pom.xml", "build.gradle", "build.gradle.kts") if has(f)), None)
    if jm:
        text = _read(repo, jm)
        fw = [f for f in ("spring", "quarkus", "micronaut", "jakarta") if f in text.lower()]
        stacks.append({"name": "java", "frameworks": fw, "package_manager": "maven" if jm == "pom.xml" else "gradle", "manifest": jm})
        evidence["java"] = [jm]
    if has("Cargo.toml"):
        stacks.append({"name": "rust", "frameworks": [], "package_manager": "cargo", "manifest": "Cargo.toml"})
        evidence["rust"] = ["Cargo.toml"]
    if any(f.endswith(".csproj") or f.endswith(".sln") for f in files):
        stacks.append({"name": "dotnet", "frameworks": [], "package_manager": "nuget",
                       "manifest": next(f for f in files if f.endswith((".csproj", ".sln")))})
        evidence["dotnet"] = [stacks[-1]["manifest"]]
    return stacks, evidence


def _languages(files: Iterable[str], excludes: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in files:
        if is_excluded(f, excludes):
            continue
        lang = symbols.language_of(f)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _roots(files: Iterable[str], excludes: Iterable[str]) -> tuple[list[str], dict]:
    per_dir: dict[str, dict] = {}
    for f in files:
        if is_excluded(f, excludes) or "/" not in f:
            continue
        top = f.split("/", 1)[0]
        if top.startswith(".") or top in _NON_ROOT_DIRS or is_test_path(f):
            continue
        lang = symbols.language_of(f)
        if not lang:
            continue
        d = per_dir.setdefault(top, {"files": 0, "languages": {}})
        d["files"] += 1
        d["languages"][lang] = d["languages"].get(lang, 0) + 1
    roots = sorted(per_dir, key=lambda k: (-per_dir[k]["files"], k))
    return roots, {r: per_dir[r] for r in roots}


def _entry_points(files: Iterable[str], repo: Path) -> list[str]:
    out = []
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name in _ENTRY_NAMES and not is_test_path(f) and "node_modules" not in f:
            out.append(f)
        elif re.match(r"^cmd/[^/]+/main\.go$", f):
            out.append(f)
    try:
        pkg = json.loads(_read(repo, "package.json") or "{}")
        for key in ("main", "module"):
            if isinstance(pkg.get(key), str):
                out.append(pkg[key])
        if isinstance(pkg.get("bin"), dict):
            out.extend(str(v) for v in pkg["bin"].values())
    except ValueError:
        pass
    text = _read(repo, "pyproject.toml")
    m = re.search(r"\[project\.scripts\]\s*(.*?)(?:\n\[|\Z)", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if "=" in line:
                out.append(line.split("=", 1)[1].strip().strip("\"'"))
    return sorted(dict.fromkeys(out))[:12]


def _test_runner(files: Iterable[str], repo: Path, stacks: list[dict]) -> Optional[str]:
    fs = set(files)
    names = {s["name"] for s in stacks}
    py = _read(repo, "pyproject.toml")
    if "python" in names:
        if "[tool.pytest" in py or "pytest" in py or any(f.startswith(("tests/", "test/")) and f.endswith(".py") for f in fs):
            return "pytest"
    if "node" in names:
        try:
            pkg = json.loads(_read(repo, "package.json") or "{}")
        except ValueError:
            pkg = {}
        deps = {**(pkg.get("devDependencies") or {}), **(pkg.get("dependencies") or {})}
        test = str((pkg.get("scripts") or {}).get("test", ""))
        for cand in ("vitest", "jest", "mocha", "ava", "playwright", "cypress"):
            if cand in deps or cand in test:
                return cand
    if "go" in names:
        return "go test"
    if "java" in names:
        return "junit"
    if "rust" in names:
        return "cargo test"
    return None


def _adr_dir(files: Iterable[str]) -> Optional[str]:
    fs = list(files)
    for d in _ADR_DIRS:
        if any(f.startswith(d + "/") and f.endswith(".md") for f in fs):
            return d
    for f in fs:
        if re.search(r"(^|/)ADR-[^/]*\.md$", f, re.I):
            return f.rsplit("/", 1)[0] if "/" in f else "."
    return None


def _codeowners(files: Iterable[str], repo: Path) -> tuple[Optional[str], Optional[str]]:
    fs = set(files)
    for c in _CODEOWNERS:
        if c in fs:
            team = None
            for line in _read(repo, c).splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("["):
                    continue
                parts = line.split()
                if parts[0] == "*" and len(parts) > 1:
                    team = parts[1]
                    break
            if team is None:
                for line in _read(repo, c).splitlines():
                    parts = line.strip().split()
                    if len(parts) > 1 and not line.startswith("#") and parts[1].startswith("@"):
                        team = parts[1]
                        break
            return c, team
    return None, None


def parse_remote(url: Optional[str]) -> dict:
    out = {"url": url, "host": None, "slug": None, "https_url": None}
    if not url:
        return out
    m = re.match(r"^(?:ssh://)?(?:[\w.-]+@)?([\w.-]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url) if "://" not in url or url.startswith("ssh://") else None
    if m is None:
        m = re.match(r"^[a-z+]+://(?:[^@/]+@)?([\w.-]+)(?::\d+)?/(.+?)(?:\.git)?/?$", url)
    if m:
        out["host"] = m.group(1)
        out["slug"] = m.group(2)
        out["https_url"] = f"https://{m.group(1)}/{m.group(2)}"
    return out


def _branches(repo: Path, default: Optional[str]) -> dict:
    local = gitio.branches(repo, remote=False)
    remote = gitio.branches(repo, remote=True)
    names = list(dict.fromkeys(local + remote))
    ci_vars: dict[str, str] = {}
    for m in _BRANCH_VAR_RE.finditer(_read(repo, ".gitlab-ci.yml")):
        ci_vars[m.group(1)] = m.group(2)
    prod = next((v for k, v in ci_vars.items() if "PROD" in k and "PREPROD" not in k), None) or default
    staging = next((v for k, v in ci_vars.items() if "PREPROD" in k or "STAGING" in k), None)
    if not staging:
        staging = next((n for n in _STAGING_NAMES if n in names), None)
    return {"local": local, "remote": remote, "suggest_prod": prod, "suggest_staging": staging, "ci_vars": ci_vars}


def _validators() -> dict:
    out = {name: bool(shutil.which(name)) for name in ("glab", "copilot", "node", "npm", "git", "pre-commit")}
    try:
        import yaml  # type: ignore  # noqa: F401
        out["pyyaml"] = True
    except Exception:
        out["pyyaml"] = False
    out["python"] = ".".join(str(x) for x in sys.version_info[:3])
    return out


def _name(repo: Path, files: Iterable[str], remote: dict) -> str:
    text = _read(repo, "pyproject.toml")
    m = re.search(r"^\s*name\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
    if m:
        return m.group(1)
    try:
        pkg = json.loads(_read(repo, "package.json") or "{}")
        if isinstance(pkg.get("name"), str):
            return pkg["name"].split("/")[-1]
    except ValueError:
        pass
    if remote.get("slug"):
        return remote["slug"].rsplit("/", 1)[-1]
    return Path(repo).name


def detect(repo: Path, cfg) -> dict:
    repo = Path(repo)
    files = tracked_files(repo)
    excludes = list(cfg.get("sources.exclude") or []) if cfg else []
    stacks, evidence = detect_stacks(files, repo)
    roots, root_evidence = _roots(files, excludes)
    for r, ev in root_evidence.items():
        evidence[f"root:{r}"] = ev
    remote = parse_remote(gitio.remote_url(repo) if gitio.is_repo(repo) else None)
    default_branch = gitio.default_branch(repo) if gitio.is_repo(repo) else None
    adr_dir = _adr_dir(files)
    codeowners, team = _codeowners(files, repo)
    present_excludes = sorted({d for d in ("vendor", "node_modules", "dist", "build", ".venv", "target") if any(f.startswith(d + "/") for f in files)})
    result = {
        "name": _name(repo, files, remote),
        "stacks": stacks,
        "languages": _languages(files, excludes),
        "frameworks": sorted({f for s in stacks for f in s.get("frameworks", [])}),
        "package_manager": ", ".join(s["package_manager"] for s in stacks) or None,
        "entry_points": _entry_points(files, repo),
        "test_runner": _test_runner(files, repo, stacks),
        "evidence": evidence,
        "roots": roots,
        "excludes": present_excludes,
        "specs": wspecs.detect_spec_files(files),
        "adr_dir": adr_dir,
        "codeowners": codeowners,
        "team": team,
        "remote": remote,
        "slug": remote.get("slug"),
        "gitlab_url": remote.get("https_url"),
        "default_branch": default_branch,
        "branches": _branches(repo, default_branch) if gitio.is_repo(repo) else {"local": [], "remote": [], "suggest_prod": None, "suggest_staging": None, "ci_vars": {}},
        "ci": {},
        "validators": _validators(),
        "file_count": len(files),
    }
    try:
        import ci_integrate  # type: ignore
        result["ci"] = ci_integrate.detect(repo, cfg) or {}
    except ImportError:
        result["ci"] = {"gitlab_ci": ".gitlab-ci.yml" if (repo / ".gitlab-ci.yml").exists() else None}
    except Exception as e:  # pragma: no cover - never fail detection because of CI parsing
        result["ci"] = {"error": str(e)}
    return result


def build_parser():
    return cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    res = detect(ctx.repo, ctx.cfg)
    if not args.json:
        ctx.emit.out(f"name: {res['name']}")
        ctx.emit.out("stacks: " + (", ".join(f"{s['name']}({', '.join(s['frameworks']) or '-'}; {s['package_manager']})" for s in res["stacks"]) or "none"))
        ctx.emit.out("languages: " + ", ".join(f"{k}={v}" for k, v in res["languages"].items()))
        ctx.emit.out(f"roots: {', '.join(res['roots']) or '-'}   excludes present: {', '.join(res['excludes']) or '-'}")
        ctx.emit.out(f"entry points: {', '.join(res['entry_points']) or '-'}   test runner: {res['test_runner'] or '-'}")
        ctx.emit.out(f"specs: openapi={res['specs']['openapi'] or '-'} asyncapi={res['specs']['asyncapi'] or '-'}")
        ctx.emit.out(f"adr dir: {res['adr_dir'] or '-'}   codeowners: {res['codeowners'] or '-'} (team {res['team'] or '-'})")
        ctx.emit.out(f"remote: {res['remote']['url'] or '-'} → slug {res['slug'] or '-'}   default branch: {res['default_branch'] or '-'}")
        b = res["branches"]
        ctx.emit.out(f"branches: prod={b['suggest_prod'] or '-'} staging={b['suggest_staging'] or '-'} (ci vars {b['ci_vars'] or '-'})")
        ctx.emit.out("validators: " + ", ".join(f"{k}={v}" for k, v in res["validators"].items()))
    ctx.emit.emit(res)
    return 0


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
