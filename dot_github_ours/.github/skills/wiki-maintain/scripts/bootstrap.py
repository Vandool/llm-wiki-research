#!/usr/bin/env python3
"""bootstrap.py — the bootstrap driver: one fresh `copilot -p` session per plan cluster (plan §8.6, §8.7.3).

CLI: bootstrap.py [--json] [--resume] [--only ID[,ID]] [--dry-run] [--model M] [--max-failures 2]
                  [--plan wiki/.wiki-plan.json] [--wait-lock SECONDS]

Validates the plan (approved, ids unique, deps resolvable, no cycles; `deps: ["*"]` = after all), orders clusters
leaves first, `--resume` skips `done`, `--only` restricts, `--dry-run` prints the order and commands and spawns nothing.
Per cluster: affected.py --bootstrap-cluster ID (packs) → over budget ⇒ plan split → run.json (mode page, cluster) →
prompts/bootstrap.md → the §8.14 command line with models.bootstrap under bootstrap_timeout_s
(env WIKI_RUN=1 WIKI_WORKER=1 WIKI_PHASE=bootstrap WIKI_CLUSTER=<id> WIKI_RUN_ID=<id>) → judge (diff confined to the
wiki, expected pages exist, lint --all clean, backlinks --check --plan clean, verified marker) → index.py --write,
manifest.py --touched, plan mark done|deferred|failed, log.py add --action Bootstrap, commit `docs(wiki): bootstrap <id>`
with trailers Wiki-Update: auto / Wiki-Run: <id>. A failed attempt keeps lint-clean partial pages (`… (partial)`),
retries once, and the driver stops after --max-failures consecutive failures. At the end: manifest.py --all
--advance-checkpoint (committed) and the review checklist.
Exit codes: 0 all clusters done · 1 some deferred/failed/blocked · 2 invalid plan · 3 lock · 4 stopped by failures.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wikilib import budget as wbudget, cli, config as wconfig, gitio, runner, textnorm  # noqa: E402
import plan as wplan  # noqa: E402

VERSION = cli.KIT_VERSION
NAME = "bootstrap"
MAX_SPLITS = 8


def topo_order(clusters: list[dict]) -> list[str]:
    """Dependency order, leaves first, plan order as the tie-break; `deps: ["*"]` clusters after everything else."""
    live = [c for c in clusters if c.get("status") != "split" and c.get("id")]
    ids = [c["id"] for c in live]
    idset = set(ids)
    deps = {c["id"]: [d for d in (c.get("deps") or []) if d != "*" and d in idset] for c in live}
    star = {c["id"] for c in live if "*" in (c.get("deps") or [])}
    order: list[str] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(n: str) -> None:
        if n in done:
            return
        if n in visiting:
            raise cli.ConfigError(f"dependency cycle through {n}")
        visiting.add(n)
        for d in deps.get(n, []):
            visit(d)
        visiting.discard(n)
        done.add(n)
        order.append(n)

    for n in ids:
        if n not in star:
            visit(n)
    for n in ids:
        if n in star:
            visit(n)
    return order


class Driver:
    def __init__(self, ctx: cli.Ctx, args):
        self.ctx = ctx
        self.args = args
        self.cfg = ctx.cfg
        self.repo: Path = ctx.repo
        self.wd = self.cfg.wiki_dir
        self.wiki: Path = ctx.wiki_dir
        self.state: Path = ctx.state_dir
        self.git_dir: Path = ctx.git_dir or (self.repo / ".git")
        self.plan_path = Path(args.plan) if args.plan else self.wiki / wplan.PLAN_NAME
        if not self.plan_path.is_absolute():
            self.plan_path = self.repo / self.plan_path
        self.plan: dict = {}
        self.lock = runner.Lock(self.state, float(self.cfg.budget("lock_ttl_min") or 60))
        self.model = args.model or str(self.cfg.get("models.bootstrap") or "")
        self.timeout_s = int(self.cfg.budget("bootstrap_timeout_s") or 1800)
        self.summary: dict = {"done": [], "deferred": [], "failed": [], "blocked": [], "skipped": [], "split": []}
        self.splits = 0

    def say(self, msg: str) -> None:
        self.ctx.emit.say(f"{NAME}: {msg}")

    def sh(self, name: str, *args, timeout: int = 900) -> runner.ScriptResult:
        return runner.run_script(self.repo, name, *args, timeout=timeout)

    # -- plan
    def load(self) -> None:
        try:
            self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        except OSError:
            raise cli.EnvError(f"{self.plan_path} not found; run /wiki-init (plan.py build, plan.py commit) first")
        except ValueError as e:
            raise cli.ConfigError(f"{self.plan_path}: invalid JSON: {e}")
        errors = wplan.validate_plan(self.plan, self.wd)
        if not self.plan.get("approved_by"):
            errors.append("plan is not approved (approved_by missing); run plan.py commit --approved-by USER")
        if errors:
            raise cli.ConfigError("invalid plan: " + "; ".join(errors))

    def save(self) -> None:
        self.plan_path.write_text(json.dumps(self.plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def cluster(self, cid: str) -> dict:
        for c in self.plan.get("clusters") or []:
            if c.get("id") == cid:
                return c
        raise cli.ConfigError(f"cluster {cid!r} not in the plan")

    def mark(self, cid: str, status: str, **fields) -> dict:
        c = self.cluster(cid)
        now = cli.iso(cli.utcnow())
        c["status"] = status
        if status == "running":
            c["attempts"] = int(c.get("attempts") or 0) + 1
            c["started"] = now
            c["ended"] = None
        elif status in ("done", "deferred", "failed"):
            c["ended"] = now
            if c.get("started"):
                try:
                    c["duration_s"] = int((cli.parse_iso(now) - cli.parse_iso(c["started"])).total_seconds())
                except ValueError:
                    pass
        for k, v in fields.items():
            if v is not None:
                c[k] = textnorm.sanitize(v, 300) if k == "reason" else v
        self.save()
        return c

    def deps_satisfied(self, c: dict) -> Optional[str]:
        clusters = self.plan.get("clusters") or []
        by_id = {x["id"]: x for x in clusters}
        deps = c.get("deps") or []
        if "*" in deps:
            for o in clusters:
                if o["id"] == c["id"] or "*" in (o.get("deps") or []) or o.get("status") == "split":
                    continue
                if o.get("status") != "done":
                    return o["id"]
            return None
        for d in deps:
            if by_id.get(d, {}).get("status") not in ("done", "split"):
                return d
        return None

    # -- driver
    def run(self) -> int:
        self.load()
        order = topo_order(self.plan["clusters"])
        only = [s.strip() for s in (self.args.only or "").split(",") if s.strip()]
        if only:
            unknown = [o for o in only if o not in {c["id"] for c in self.plan["clusters"]}]
            if unknown:
                raise cli.ConfigError(f"--only: unknown cluster(s) {', '.join(unknown)}")
            order = [c for c in order if c in only]
        if self.args.dry_run:
            return self.dry_run(order, only)
        if self.args.wait_lock:
            if not self.lock.wait(float(self.args.wait_lock), kind="bootstrap"):
                raise cli.EnvError(f"lock still held after {self.args.wait_lock}s ({self.lock.describe()})")
        else:
            ok, info = self.lock.acquire("bootstrap")
            if not ok:
                raise cli.EnvError(f"another wiki run holds the lock ({self.lock.describe(info)})")
        started = time.monotonic()
        try:
            return self.drive(order, only)
        finally:
            self.lock.release()
            self.say(f"finished in {int(time.monotonic() - started)}s: " + ", ".join(f"{k} {len(v)}" for k, v in self.summary.items() if v))

    def dry_run(self, order: list[str], only: list[str]) -> int:
        bin_path = runner.find_copilot(self.cfg, self.repo) or "copilot"
        lines = [f"plan {self.plan_path} ({len(self.plan['clusters'])} clusters, approved by {self.plan.get('approved_by')})", "order:"]
        rows = []
        for cid in order:
            c = self.cluster(cid)
            skip = "skip (done)" if (self.args.resume and c.get("status") == "done") else "run"
            lines.append(f"  {cid:<24} {c.get('status'):<9} deps={','.join(c.get('deps') or []) or '-':<20} pages={len(c.get('pages') or [])} → {skip}")
            rows.append({"id": cid, "status": c.get("status"), "deps": c.get("deps") or [], "pages": [p["path"] for p in c.get("pages") or []], "action": skip})
        prompt = runner.render_prompt("bootstrap.md", {"cluster_id": "<ID>"})
        argv = runner.build_argv(bin_path, prompt, self.model, self.wd, self.state / "last-transcript.md")
        env = runner.cli_env("bootstrap", "<ID>", {"WIKI_CLUSTER": "<ID>"})
        env_show = " ".join(f"{k}={env[k]}" for k in ("WIKI_RUN", "WIKI_WORKER", "WIKI_PHASE", "WIKI_CLUSTER", "WIKI_RUN_ID", "COPILOT_AUTO_UPDATE"))
        lines.append("per cluster: facts.py (once) · affected.py --bootstrap-cluster <ID> --out … · run.json · "
                     f"{env_show} timeout {self.timeout_s}s " + " ".join(_q(a) for a in argv))
        lines.append("then: judge · index.py --write · manifest.py --touched · plan mark · log.py add --action Bootstrap · commit docs(wiki): bootstrap <ID>")
        lines.append("at the end: manifest.py --all --advance-checkpoint · review overview.md, glossary.md, product/")
        if self.ctx.emit.as_json:
            self.ctx.emit.emit({"plan": str(self.plan_path), "order": rows, "argv": argv, "model": self.model, "timeout_s": self.timeout_s, "dry_run": True})
        else:
            print("\n".join(lines))
        return 0

    def drive(self, order: list[str], only: list[str]) -> int:
        head = gitio.head(self.repo)
        if not head:
            raise cli.EnvError("repository has no commits yet")
        if gitio.status_porcelain(self.repo, [self.wd]):
            self.say("wiki has uncommitted changes (plan, instructions): committing them as the bootstrap start")
            runner.commit_wiki(self.repo, self.wd, "docs(wiki): bootstrap start", "bootstrap", extra_paths=(runner.CONSUMERS_REL,))
        queue = list(order)
        failures = 0
        max_failures = int(self.args.max_failures or 2)
        i = 0
        while i < len(queue):
            cid = queue[i]
            i += 1
            c = self.cluster(cid)
            if c.get("status") == "split":
                continue
            if c.get("status") == "done" and (self.args.resume or not only):
                if self.args.resume:
                    self.summary["skipped"].append(cid)
                    self.say(f"{cid}: already done, skipped (--resume)")
                    continue
            blocker = self.deps_satisfied(c)
            if blocker and not only:
                self.summary["blocked"].append(cid)
                self.say(f"{cid}: blocked by {blocker} ({self.cluster(blocker).get('status')})")
                continue
            if blocker and only:
                self.say(f"{cid}: dependency {blocker} is not done; running anyway (--only)")
            outcome = self.run_cluster(cid, queue, i)
            if outcome == "done":
                failures = 0
            elif outcome == "failed":
                failures += 1
                if failures >= max_failures:
                    self.say(f"stopping after {failures} consecutive failed clusters (--max-failures {max_failures})")
                    self.finish()
                    return cli.EXIT_MODEL
        self.finish()
        bad = self.summary["deferred"] + self.summary["failed"] + self.summary["blocked"]
        return cli.EXIT_FINDINGS if bad else 0

    def refresh_facts(self) -> None:
        """facts.py → index.py --write → manifest.py --touched before every cluster: the generated pages embed HEAD,
        so they must be regenerated after each commit for lint --all (L10) to pass; the cluster commit sweeps them in."""
        for name, args in (("facts", ()), ("index", ("--write",)), ("manifest", ("--touched",))):
            r = self.sh(name, *args)
            if not r.ok:
                raise cli.ModelError(f"{name}.py failed: {r.tail() or r.rc}")

    def run_cluster(self, cid: str, queue: list[str], insert_at: int) -> str:
        """Returns done | deferred | failed | split."""
        c = self.cluster(cid)
        expected = [p["path"] for p in c.get("pages") or []]
        for attempt in (1, 2):
            self.mark(cid, "running")
            t0 = time.monotonic()
            self.refresh_facts()
            aff = self.pack(cid)
            if aff.get("over_budget"):
                child_ids = self.split(cid)
                if child_ids:
                    self.summary["split"].append(cid)
                    queue[insert_at:insert_at] = child_ids
                    return "split"
                self.mark(cid, "deferred", reason="over max_source_bytes_per_cluster after one split; raise the budget or narrow the sources")
                self.summary["deferred"].append(cid)
                self.say(f"{cid}: over budget ({aff.get('budget', {}).get('source_bytes')} > {aff.get('budget', {}).get('max_source_bytes')} bytes) and not split again → deferred")
                return "deferred"
            bin_path = runner.find_copilot(self.cfg, self.repo)
            if not bin_path:
                self.mark(cid, "pending")
                raise cli.ModelError("copilot CLI not found (WIKI_COPILOT_BIN, git config wiki.copilot, copilot.bin, PATH)")
            run = self.run_json(cid, aff)
            runner.clear_markers(self.state)
            wbudget.save_run(self.git_dir, run)
            variables = wconfig.scaffold_vars(self.cfg, head=aff.get("head") or "", model=self.model, date=cli.iso(self.ctx.now))
            variables["cluster_id"] = cid
            prompt = runner.render_prompt("bootstrap.md", variables)
            output = self.state / f"bootstrap-{cid}.log"
            try:
                output.write_text("", encoding="utf-8")
            except OSError:
                pass
            self.cluster(cid)["log"] = str(output)
            argv = runner.build_argv(bin_path, prompt, self.model, self.wd, self.state / "last-transcript.md")
            env = runner.cli_env("bootstrap", cid, {"WIKI_CLUSTER": cid})
            before = runner.status_snapshot(self.repo)
            self.say(f"{cid}: attempt {attempt}, {len(expected)} page(s), {aff.get('budget', {}).get('source_bytes', 0)} source bytes, model {self.model}")
            sp = runner.spawn_cli(argv, self.repo, env, self.timeout_s, output, pid_file=self.state / "copilot.pid")
            self.say(f"{cid}: cli exited rc={sp.rc} after {sp.duration_s}s" + (" (TIMED OUT)" if sp.timed_out else ""))
            v = runner.judge(self.repo, self.wd, self.state, before, sp, output, checkpoint=aff.get("checkpoint_commit"),
                             expected=expected, consumers=False, keep_partial=True, log=self.say)
            self.say(f"{cid}: judge {v.summary()}")
            run_now = wbudget.load_run(self.git_dir) or run
            duration = int(time.monotonic() - t0)
            record = {"run_id": cid, "mode": "page", "cluster": cid, "attempt": attempt, "model": self.model,
                      "started": run.get("started"), "duration_s": duration, "cli_duration_s": sp.duration_s,
                      "pages_written": len(v.kept), "bytes_read": (run_now.get("budget") or {}).get("bytes_read"),
                      "tokens": None, "timed_out": sp.timed_out, "result": v.result, "pid": sp.pid}
            self.finish_run(run_now, v.result)
            if v.result == "aborted":
                runner.revert_wiki(self.repo, self.wd)
                self.mark(cid, "failed", reason="; ".join(v.reasons))
                runner.metrics(self.state, record)
                self.say(f"{cid}: ABORTED — files changed outside the wiki: {', '.join(v.outside)}; nothing committed")
                self.summary["failed"].append(cid)
                return "failed"
            plan_status = self.cluster(cid).get("status")  # the model may have marked it
            if v.kept or v.result == "deferred":
                self.sh("manifest", "--touched", "--run-id", cid, "--model", self.model, "--mode", "bootstrap",
                        "--result", v.result, "--duration", str(duration), "--pages-written", str(len(v.kept)))
                self.log_add("Bootstrap", f"cluster {cid}: {len(v.kept)} page(s) {v.result}" + (f" — {'; '.join(v.reasons)}" if v.reasons else ""), cid)
            if v.result == "ok" and not v.missing:
                self.mark(cid, "done", pages_written=len(v.kept), lint_errors=0)
                sha = self.commit(f"docs(wiki): bootstrap {cid}", cid)
                self.mark(cid, "done", commit=sha)
                record["commit"] = sha
                runner.metrics(self.state, record)
                self.summary["done"].append(cid)
                self.say(f"{cid}: done ({len(v.kept)} pages)" + (f", commit {sha[:10]}" if sha else ""))
                return "done"
            if v.result == "deferred" or plan_status == "deferred":
                self.mark(cid, "deferred", reason="; ".join(v.reasons) or "model deferred", pages_written=len(v.kept))
                sha = self.commit(f"docs(wiki): bootstrap {cid} (partial)", cid)
                self.mark(cid, "deferred", commit=sha)
                record["commit"] = sha
                runner.metrics(self.state, record)
                self.summary["deferred"].append(cid)
                self.say(f"{cid}: deferred ({len(v.kept)} clean page(s) kept)")
                return "deferred"
            # partial or failed: keep the clean pages, retry once
            sha = self.commit(f"docs(wiki): bootstrap {cid} (partial)", cid) if v.kept else None
            record["commit"] = sha
            runner.metrics(self.state, record)
            if attempt == 1:
                self.say(f"{cid}: attempt 1 {v.result} ({'; '.join(v.reasons)}); retrying once")
                continue
            self.mark(cid, "failed", reason="; ".join(v.reasons) or v.result, pages_written=len(v.kept), commit=sha)
            self.summary["failed"].append(cid)
            self.say(f"{cid}: failed after 2 attempts")
            return "failed"
        return "failed"

    def pack(self, cid: str) -> dict:
        ctx_json = self.state / "context.json"
        ctx_md = self.state / "context.md"
        r = self.sh("affected", "--bootstrap-cluster", cid, "--out", str(ctx_json), "--md", str(ctx_md), "--run-id", cid)
        if r.rc != 0 and r.data is None:
            raise cli.ModelError(f"affected.py --bootstrap-cluster {cid} failed: {r.tail()}")
        try:
            data = json.loads(ctx_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = r.data or {}
        if "work" not in data:
            raise cli.ModelError(f"affected.py produced no pack for {cid}: {r.tail()}")
        return data

    def is_split_child(self, cid: str) -> bool:
        return any(cid in (c.get("split_into") or []) for c in self.plan.get("clusters") or [])

    def split(self, cid: str) -> list[str]:
        """Re-split once (plan §8.15): a cluster produced by a split is never split again, it is deferred."""
        if self.is_split_child(cid) or self.splits >= MAX_SPLITS:
            return []
        if self.plan_path.resolve() != (self.wiki / wplan.PLAN_NAME).resolve():
            self.say(f"{cid}: over budget; plan.py split needs the default plan path ({wplan.PLAN_NAME})")
            return []
        self.save()
        r = self.sh("plan", "split", cid)
        if not r.ok or not r.data:
            self.say(f"{cid}: over budget and plan.py split failed: {r.tail()}")
            return []
        self.splits += 1
        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        children = [ch["id"] for ch in r.data.get("children") or []]
        self.say(f"{cid}: over budget → split into {', '.join(children)}")
        return children

    def run_json(self, cid: str, aff: dict) -> dict:
        b = aff.get("budget") or {}
        run = runner.base_run(cid, "page", self.cfg, aff.get("head"), aff.get("checkpoint_commit"), self.ctx.now,
                              model=self.model, timeout_s=self.timeout_s)
        run.update({"cluster": cid, "cluster_title": aff.get("cluster_title"), "work": aff.get("work") or [],
                    "may_create": aff.get("may_create") or [], "order": aff.get("order") or [],
                    "dependency_pages": aff.get("dependency_pages") or [], "over_budget": bool(aff.get("over_budget")),
                    "plan": str(self.plan_path), "context_md": str(self.state / "context.md"), "trigger": "bootstrap"})
        run["budget"].update({"max_pages": b.get("max_pages", len(run["work"])), "max_source_bytes": b.get("max_source_bytes", run["budget"]["max_source_bytes"]),
                              "source_bytes": b.get("source_bytes", 0), "bytes_read": int(b.get("bytes_packed") or 0),
                              "bytes_packed": int(b.get("bytes_packed") or 0), "excerpt_lines_used": int(b.get("excerpt_lines_used") or 0)})
        return run

    def finish_run(self, run: dict, status: str) -> None:
        run["status"] = status
        run["ended"] = cli.iso(cli.utcnow())
        try:
            (self.state / "run.last.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            wbudget.run_path(self.git_dir).unlink()
        except OSError:
            pass

    def commit(self, message: str, run_id: str) -> Optional[str]:
        self.sh("index", "--write")
        sha = runner.commit_wiki(self.repo, self.wd, message, run_id, extra_paths=(runner.CONSUMERS_REL,))
        if sha:
            self.say(f"committed {sha[:10]} {message}")
        return sha

    def log_add(self, action: str, text: str, run_id: str) -> None:
        r = self.sh("log", "add", "--action", action, "--text", text, "--run-id", run_id)
        if not r.ok:
            self.say(f"log.py add failed: {r.tail()}")

    def finish(self) -> None:
        self.sh("facts")
        self.sh("index", "--write", "--consumers")
        r = self.sh("manifest", "--all", "--advance-checkpoint")
        if not r.ok:
            self.say(f"manifest.py --all --advance-checkpoint failed: {r.tail()}")
        self.sh("log", "rotate")
        runner.commit_wiki(self.repo, self.wd, "docs(wiki): bootstrap checkpoint", "bootstrap", extra_paths=(runner.CONSUMERS_REL,))
        s = self.summary
        clusters = self.plan.get("clusters") or []
        counts = {}
        for c in clusters:
            counts[c.get("status")] = counts.get(c.get("status"), 0) + 1
        lines = [f"Bootstrap finished: {len(s['done'])} done, {len(s['deferred'])} deferred, {len(s['failed'])} failed, "
                 f"{len(s['blocked'])} blocked, {len(s['skipped'])} skipped; plan status: "
                 + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])))]
        if s["deferred"] or s["failed"] or s["blocked"]:
            lines.append("  rerun with `python3 .github/skills/wiki-maintain/scripts/bootstrap.py --resume` after fixing the plan or the budget "
                         "(deferred clusters: `plan.py split <id>` or a larger max_source_bytes_per_cluster).")
        lines += ["Review before the hook takes over:",
                  f"  1. {self.wd}/overview.md   — what it is, who uses it, how a request flows, where to start",
                  f"  2. {self.wd}/glossary.md   — canonical terms and aliases",
                  f"  3. {self.wd}/product/      — product-owner pages" + ("" if self.cfg.get("po_layer") else " (PO layer disabled: skip)"),
                  "  Then push; the post-commit hook maintains the wiki from now on (`run.py worker --foreground` runs it by hand)."]
        for l in lines:
            self.say(l)
        if self.ctx.emit.as_json:
            self.ctx.emit.emit({"summary": s, "plan_status": counts, "plan": str(self.plan_path), "review": [f"{self.wd}/overview.md", f"{self.wd}/glossary.md", f"{self.wd}/product/"]},
                               ok=not (s["failed"] or s["deferred"] or s["blocked"]))


def _q(a: str) -> str:
    import re
    if len(a) > 80:
        a = a[:77] + "…"
    return json.dumps(a) if re.search(r"[\s'\"()*<>]", a) else a


def build_parser():
    p = cli.base_parser(NAME, VERSION, __doc__.split("\n\n")[0])
    p.add_argument("--resume", action="store_true", help="skip clusters already done")
    p.add_argument("--only", default=None, metavar="ID[,ID]", help="run only these clusters")
    p.add_argument("--dry-run", action="store_true", help="print the order and the commands; spawn nothing")
    p.add_argument("--model", default=None, help="override models.bootstrap")
    p.add_argument("--max-failures", type=int, default=2, help="stop after N consecutive failed clusters")
    p.add_argument("--plan", default=None, help="plan file (default <wiki>/.wiki-plan.json)")
    p.add_argument("--wait-lock", type=float, default=None, metavar="SECONDS", help="wait up to N seconds for the session lock")
    return p


def main(args) -> int:
    ctx = cli.Ctx(args, need_config=True, need_repo=True)
    if ctx.wiki_dir is None or not ctx.wiki_dir.is_dir():
        raise cli.EnvError(f"wiki directory missing: {ctx.wiki_dir}")
    return Driver(ctx, args).run()


if __name__ == "__main__":
    sys.exit(cli.run(main, build_parser()))
