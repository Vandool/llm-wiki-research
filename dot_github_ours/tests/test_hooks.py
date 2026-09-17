"""hook_guard.py / stop_gate.py: every hook sample → exactly one JSON object; guard rules with and without WIKI_RUN
(plan §8.4, §10 a/c); stop-gate retry counter, verified marker, stop-gate-failed marker, malformed payloads."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from conftest import FIXTURES, TempDir, commit_all, git, git_out, install_kit, make_repo, read, read_json, run_script, write, write_json  # noqa: F401

SCRIPTS_REL = ".github/skills/wiki-maintain/scripts"
SAMPLES = FIXTURES / "hook-samples"
PHASE_OF = {"session-start": "session-start", "post-tool-read": "post-tool", "post-tool-write": "post-tool", "agent-stop": "stop"}
STOP_PAYLOAD = {"sessionId": "s1", "timestamp": "2026-09-07T10:00:12Z", "cwd": ".", "transcriptPath": "", "stopReason": "end_turn",
                "stop_hook_active": False}


def page(rel: str, title: str, head: str, body: str, owner: str = "agent", ptype: str = "Module") -> str:
    return (f"---\ntype: {ptype}\nid: sample/{rel[:-3]}\nschema_version: 1\ntitle: {title}\ndescription: {title}.\n"
            f"audience: [agent, dev]\nowner: {owner}\nsources:\n  - {{ id: svc, resource: \"repo://src/orders/service.py\" }}\n"
            f"last_verified_commit: {head}\ngenerated: {{ by: \"copilot-cli/test\", at: 2026-09-07T10:00:00Z }}\nstatus: draft\n---\n"
            f"# {title}\n**Read this when:** testing.[^svc]\n\n{body}\n\n[^svc]: `src/orders/service.py`\n")


def now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_json_doc(session: str = "s1", **over) -> dict:
    run = {"run_id": "r-test", "mode": "update", "session_id": None, "started": now_iso(), "timeout_s": None,
           "model": "gpt-5-mini", "checkpoint": "a" * 40, "head": "b" * 40, "wiki_dir": "wiki",
           "work": [{"path": "modules/orders.md", "type": "Module", "action": "update",
                     "reasons": [{"kind": "blob_changed", "path": "src/orders/service.py"}],
                     "sources": [{"resource": "repo://src/orders/service.py", "bytes": 120, "hunks": [], "status": "blob_changed"}],
                     "budget_bytes": 120}],
           "may_create": ["modules/x.md"], "requests": [{"id": 1, "text": "Explain retries"}], "instruction": None,
           "budget": {"max_pages": 8, "max_source_bytes": 200000, "bytes_read": 0, "excerpt_lines_used": 0, "max_excerpt_lines_per_run": 800},
           "over_budget": False, "status": "running"}
    run.update(over)
    return run


class HookHarness(unittest.TestCase):
    """One installed target repository for the whole class; tests restore what they change."""

    tmp: TempDir
    repo: Path
    head: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDir("wikikit-hooks-")
        root = cls.tmp.__enter__()
        cls.repo = make_repo(root)
        write_json(cls.repo / ".github/wiki.config.json", {"repo": {"slug": "group/sample", "id_prefix": "sample"},
                                                            "sources": {"include": ["src", "web"]}})
        r = install_kit(cls.repo, "--hooks", "none")
        assert r.returncode == 0, r.stdout + r.stderr
        cls.head = git_out(cls.repo, "rev-parse", "HEAD")
        write(cls.repo / "wiki/modules/orders.md", page("modules/orders.md", "Orders service", cls.head, "Keeps orders."))
        write(cls.repo / "wiki/runbooks/restart.md", page("runbooks/restart.md", "Restart", cls.head, "Human owned.", owner="human", ptype="Runbook"))
        ov = cls.repo / "wiki/overview.md"
        write(ov, read(ov) + "\n- [Orders service](modules/orders.md)\n- [Restart](runbooks/restart.md)\n")
        for args in (("facts",), ("index", "--write"), ("manifest", "--init")):
            res = run_script(args[0], *args[1:], cwd=cls.repo, scripts=cls.repo / SCRIPTS_REL)
            assert res.returncode == 0, res.stderr
        commit_all(cls.repo, "wiki: install")
        cls.state = cls.repo / ".git/wiki"
        cls.state.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.__exit__(None, None, None)

    def setUp(self) -> None:
        for p in list(self.state.glob("stop-retries.*")) + [self.state / "stop-gate-failed", self.state / "verified", self.state / "run.json"]:
            if p.exists():
                p.unlink()
        git(self.repo, "checkout", "-q", "--", "wiki")
        git(self.repo, "clean", "-fdq", "--", "wiki")

    # -- helpers
    def hook(self, phase: str, payload, wiki: bool = True, env: dict | None = None, raw: str | None = None) -> tuple[dict, int, str]:
        e = {"WIKI_RUN": "1" if wiki else ""}
        if env:
            e.update(env)
        script = "stop_gate" if phase == "stop" else "hook_guard"
        args = () if phase == "stop" else (phase,)
        data = raw if raw is not None else json.dumps(payload)
        res = run_script(script, *args, cwd=self.repo, scripts=self.repo / SCRIPTS_REL, env=e, input=data, timeout=60)
        lines = [l for l in res.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"{script} {phase}: stdout must be exactly one JSON object, got {res.stdout!r} (stderr {res.stderr!r})")
        obj = json.loads(lines[0])
        self.assertIsInstance(obj, dict)
        return obj, res.returncode, res.stderr

    def deny(self, obj: dict, rule: str) -> None:
        self.assertEqual(obj.get("permissionDecision"), "deny", obj)
        self.assertTrue(obj.get("permissionDecisionReason", "").startswith(f"wiki-guard: {rule} — "), obj)

    def with_run(self, **over) -> None:
        write_json(self.state / "run.json", run_json_doc(**over))

    def pre(self, tool: str, args: dict, wiki: bool = True, session: str = "s1", **kw) -> tuple[dict, int]:
        obj, rc, _ = self.hook("pre-tool", {"sessionId": session, "timestamp": "t", "cwd": ".", "toolName": tool, "toolArgs": args}, wiki=wiki, **kw)
        return obj, rc


class SamplesTests(HookHarness):
    def test_every_sample_prints_exactly_one_json_object_in_both_modes(self):
        for wiki in (True, False):
            self.with_run()
            for sample in sorted(SAMPLES.glob("*.json")):
                name = sample.stem
                phase = PHASE_OF.get(name, "post-tool" if name.startswith("post-tool") else "pre-tool")
                raw = read(sample)
                obj, rc, err = self.hook(phase, None, wiki=wiki, raw=raw)
                if name == "malformed":
                    if wiki:
                        self.assertNotEqual(rc, 0, f"malformed payload must exit non-zero in wiki mode ({phase})")
                        if phase == "pre-tool":
                            self.assertEqual(obj.get("permissionDecision"), "deny", obj)
                    else:
                        self.assertEqual(rc, 0)
                        self.assertEqual(obj, {"decision": "allow"} if phase == "stop" else {})
                else:
                    self.assertEqual(rc, 0, f"{name} ({'wiki' if wiki else 'passive'}): rc {rc}, stderr {err}")
                    self.assertNotIn("allow", str(obj.get("permissionDecision", "")), "the guard never emits allow")

    def test_guard_log_records_payload_and_arg_keys(self):
        self.with_run()
        self.pre("write", {"path": "README.md", "content": "x"})
        lines = read(self.state / "guard.log").splitlines()
        last = lines[-1]
        self.assertRegex(last, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z pre-tool deny mode=wiki session=s1 tool=write path=\"README.md\" rule=write-scope keys=cwd,sessionId,timestamp,toolArgs,toolName args=content,path reason=\"")


class PreToolTests(HookHarness):
    def test_contract_10c(self):
        self.with_run()
        obj, rc = self.pre("write", {"path": "README.md", "content": "hello"})
        self.deny(obj, "write-scope")
        self.assertEqual(rc, 0)
        obj, _ = self.pre("write", {"path": "wiki/modules/x.md", "content": "# x"})
        self.assertEqual(obj, {})
        obj, _ = self.pre("edit", {"file_path": "wiki/index.md", "old_string": "a", "new_string": "b"})
        self.deny(obj, "generated")
        obj, _ = self.pre("edit", {"file_path": "wiki/index.md", "old_string": "a", "new_string": "b"}, wiki=False, session="other")
        self.deny(obj, "generated")
        obj, _ = self.pre("write", {"path": "README.md", "content": "hello"}, wiki=False, session="other")
        self.assertEqual(obj, {})
        obj, _ = self.pre("shell", {"command": "python3 .github/skills/wiki-maintain/scripts/excerpt.py src/orders/service.py --symbol OrderService.place"})
        self.assertEqual(obj, {})
        obj, _ = self.pre("shell", {"command": "git commit -am 'oops'"})
        self.deny(obj, "shell-denied")
        obj, _ = self.pre("bash", {"cmd": "ls wiki > out.txt"})
        self.deny(obj, "shell-dangerous")
        obj, _ = self.pre("read", {"filePath": ".env"})
        self.deny(obj, "read-denylist")
        obj, _ = self.pre("some_new_tool", {"x": 1})
        self.assertEqual(obj, {})
        for tool, args in (("shell", {"command": "git commit -am x"}), ("bash", {"cmd": "ls > x"}), ("read", {"filePath": ".env"})):
            obj, _ = self.pre(tool, args, wiki=False, session="other")
            self.assertEqual(obj, {}, f"passive mode must not deny {tool}")

    def test_shell_whitelist_details(self):
        self.with_run()
        for cmd in ("git diff HEAD~1 -- src", "git -C . log --oneline -5", "grep -rn transition src | head -5", "rg -n Outbox src",
                    "sed -n '1,40p' src/orders/service.py", "wc -l src/orders/service.py", "find src -name '*.py'",
                    "python3 .github/skills/wiki-maintain/scripts/lint.py --changed --json"):
            obj, _ = self.pre("shell", {"command": cmd})
            self.assertEqual(obj, {}, cmd)
        for cmd, rule in (("cat src/orders/service.py", "shell-whole-file"), ("git push origin main", "shell-denied"),
                          ("rm -rf wiki", "shell-denied"), ("curl http://x", "shell-denied"), ("git add -A", "shell-denied"),
                          ("sed -i 's/a/b/' wiki/overview.md", "shell-dangerous"), ("python3 -c 'print(1)'", "shell-dangerous"), ("python3 -m unittest", "shell-whitelist"),
                          ("echo hi", "shell-whitelist"), ("git diff && git log", "shell-dangerous"), ("ls $(pwd)", "shell-dangerous"),
                          ("grep x | tee out", "shell-dangerous"), ("python3 scripts/migrate_once.py", "shell-whitelist"),
                          ("git config user.name x", "shell-denied"), ("find . -delete", "shell-dangerous")):
            obj, _ = self.pre("shell", {"command": cmd})
            self.deny(obj, rule)

    def test_write_rules(self):
        self.with_run()
        obj, _ = self.pre("write", {"path": "wiki/modules/y.md", "content": "x"})
        self.deny(obj, "new-file")
        obj, _ = self.pre("edit", {"file_path": "wiki/instructions.md", "old_string": "a", "new_string": "b"})
        self.deny(obj, "protected")
        obj, _ = self.pre("edit", {"file_path": "wiki/runbooks/restart.md", "old_string": "a", "new_string": "b"})
        self.deny(obj, "owner")
        obj, _ = self.pre("edit", {"file_path": "wiki/generated/inventory.md", "old_string": "a", "new_string": "b"})
        self.deny(obj, "generated")
        obj, _ = self.pre("write", {"path": "wiki/../README.md", "content": "x"})
        self.deny(obj, "write-scope")
        obj, _ = self.pre("write", {"path": str(self.repo / "wiki/modules/orders.md"), "content": "x"})
        self.assertEqual(obj, {}, "absolute path inside the wiki passes")
        obj, _ = self.pre("edit", {"file_path": "wiki/modules/orders.md", "old_string": "a", "new_string": "b"})
        self.assertEqual(obj, {})
        obj, _ = self.pre("create_file", {"path": "wiki/modules/z.md", "content": "x"})
        self.deny(obj, "new-file")
        # init mode: instructions.md and new files pass
        self.with_run(mode="init", may_create=[])
        obj, _ = self.pre("edit", {"file_path": "wiki/instructions.md", "old_string": "a", "new_string": "b"})
        self.assertEqual(obj, {})
        obj, _ = self.pre("write", {"path": "wiki/concepts/new.md", "content": "x"})
        self.assertEqual(obj, {})
        # query mode: only analyses/
        self.with_run(mode="query", may_create=[], work=[])
        obj, _ = self.pre("write", {"path": "wiki/analyses/answer.md", "content": "x"})
        self.assertEqual(obj, {})
        obj, _ = self.pre("write", {"path": "wiki/modules/new.md", "content": "x"})
        self.deny(obj, "new-file")
        # symlink escape
        link = self.repo / "wiki/escape"
        try:
            link.symlink_to(self.repo / "src")
            obj, _ = self.pre("write", {"path": "wiki/escape/x.md", "content": "x"})
            self.deny(obj, "write-scope")
        finally:
            link.unlink()

    def test_read_rules(self):
        self.with_run()
        big = self.repo / "big.txt"
        big.write_text("x" * 70000)
        many = self.repo / "many.txt"
        many.write_text("line\n" * 500)
        try:
            obj, _ = self.pre("read", {"path": "big.txt"})
            self.deny(obj, "read-size")
            self.assertIn("excerpt.py", obj["permissionDecisionReason"])
            obj, _ = self.pre("read", {"path": "big.txt", "offset": 1, "limit": 50})
            self.assertEqual(obj, {})
            obj, _ = self.pre("read", {"path": "many.txt"})
            self.deny(obj, "read-lines")
            obj, _ = self.pre("read", {"path": "many.txt", "startLine": 1, "endLine": 40})
            self.assertEqual(obj, {})
            obj, _ = self.pre("read", {"path": "wiki/overview.md"})
            self.assertEqual(obj, {})
            obj, _ = self.pre("read", {"path": ".git/config"})
            self.deny(obj, "read-denylist")
            obj, _ = self.pre("read", {"path": "/etc/hostname"})
            self.deny(obj, "read-scope")
            obj, _ = self.pre("read", {"path": "config/secrets/db.json"})
            self.deny(obj, "read-denylist")
            self.with_run(budget={"max_pages": 8, "max_source_bytes": 100, "bytes_read": 101, "excerpt_lines_used": 0, "max_excerpt_lines_per_run": 800})
            obj, _ = self.pre("read", {"path": "wiki/overview.md"})
            self.deny(obj, "budget-exhausted")
            self.assertIn("run.py defer", obj["permissionDecisionReason"])
        finally:
            big.unlink()
            many.unlink()

    def test_unknown_tool_policy_from_config(self):
        self.with_run()
        cfg_path = self.repo / ".github/wiki.config.json"
        cfg = read_json(cfg_path)
        try:
            cfg["hooks"] = {"unknown_tool": "deny"}
            write_json(cfg_path, cfg)
            obj, _ = self.pre("some_new_tool", {"x": 1})
            self.deny(obj, "unknown-tool")
            obj, _ = self.pre("some_new_tool", {"x": 1}, wiki=False, session="other")
            self.assertEqual(obj, {})
        finally:
            git(self.repo, "checkout", "-q", "--", ".github/wiki.config.json")

    def test_claimed_run_json_turns_a_session_into_wiki_mode_without_the_env_flag(self):
        self.with_run()
        obj, _ = self.pre("write", {"path": "README.md", "content": "x"}, wiki=False, session="s9")
        self.deny(obj, "write-scope")
        self.assertEqual(read_json(self.state / "run.json")["session_id"], "s9")
        obj, _ = self.pre("write", {"path": "README.md", "content": "x"}, wiki=False, session="other")
        self.assertEqual(obj, {}, "a different session stays passive")
        obj, _ = self.pre("write", {"path": "README.md", "content": "x"}, wiki=False, session="s9")
        self.deny(obj, "write-scope")


class StaleRunTests(HookHarness):
    def test_a_stale_unclaimed_run_is_not_claimed_but_a_claimed_one_survives(self):
        self.with_run(started="2026-01-01T00:00:00Z")
        obj, _ = self.pre("write", {"path": "README.md", "content": "x"}, wiki=False, session="s3")
        self.assertEqual(obj, {}, "a passive session never claims a stale run.json")
        self.assertIsNone(read_json(self.state / "run.json")["session_id"])
        self.with_run(started="2026-01-01T00:00:00Z", session_id="s3")
        obj, _ = self.pre("write", {"path": "README.md", "content": "x"}, wiki=False, session="s3")
        self.deny(obj, "write-scope")


class SessionAndPostToolTests(HookHarness):
    def test_session_start_injects_context_and_claims_the_run(self):
        self.with_run()
        payload = {"sessionId": "s1", "timestamp": "t", "cwd": ".", "source": "startup", "initialPrompt": "/wiki-update"}
        obj, rc, _ = self.hook("session-start", payload)
        self.assertEqual(rc, 0)
        ctx = obj["additionalContext"]
        self.assertIn("# Wiki run context", ctx)
        self.assertIn("run_id: r-test", ctx)
        self.assertIn("`wiki/modules/orders.md` (Module, update, 120 bytes)", ctx)
        self.assertIn("## May create", ctx)
        self.assertIn("<<<WIKI-UNTRUSTED id=R1 source=requests.md>>>", ctx)
        self.assertIn("read `wiki/instructions.md` and `wiki/conventions.md` first", ctx)
        self.assertEqual(read_json(self.state / "run.json")["session_id"], "s1")
        obj, rc, _ = self.hook("session-start", dict(payload, sessionId="other"), wiki=False)
        self.assertEqual(obj, {})
        # prefers affected.py's context.md when it belongs to the run
        write(self.state / "context.md", "# Wiki run context\n- mode: update · run_id: r-test · checkpoint..head: a..b · wiki_dir: wiki\nFROM-AFFECTED\n")
        obj, _, _ = self.hook("session-start", payload)
        self.assertIn("FROM-AFFECTED", obj["additionalContext"])
        (self.state / "context.md").unlink()
        # overflow → pointer to run.py status
        cfg_path = self.repo / ".github/wiki.config.json"
        cfg = read_json(cfg_path)
        cfg["budgets"] = {"session_context_kb": 1}
        write_json(cfg_path, cfg)
        try:
            self.with_run(work=[run_json_doc()["work"][0] for _ in range(60)])
            obj, _, _ = self.hook("session-start", payload)
            self.assertIn("run.py status --json", obj["additionalContext"])
            self.assertLess(len(obj["additionalContext"].encode()), 1200)
        finally:
            git(self.repo, "checkout", "-q", "--", ".github/wiki.config.json")
        (self.state / "run.json").unlink()
        obj, rc, _ = self.hook("session-start", payload)
        self.assertEqual(obj, {}, "wiki mode without run.json injects nothing")
        self.assertEqual(rc, 0)

    def test_post_tool_lint_feedback_and_read_metering(self):
        self.with_run()
        bad = "modules/x.md"
        write(self.repo / "wiki" / bad, page(bad, "X module", self.head, "See [gone](missing.md)."))
        payload = {"sessionId": "s1", "timestamp": "t", "cwd": ".", "toolName": "write", "toolArgs": {"path": f"wiki/{bad}"},
                   "toolResult": {"resultType": "success", "textResultForLlm": "written"}}
        obj, rc, _ = self.hook("post-tool", payload)
        self.assertEqual(rc, 0)
        ctx = obj["additionalContext"]
        self.assertTrue(ctx.startswith(f"LINT wiki/{bad}: 1 error(s): L01 "), ctx)
        self.assertTrue(ctx.endswith("Fix before continuing."), ctx)
        self.assertLessEqual(len(ctx.encode()), 10 * 1024)
        write(self.repo / "wiki" / bad, page(bad, "X module", self.head, "Clean."))
        obj, _, _ = self.hook("post-tool", payload)
        self.assertEqual(obj, {})
        obj, _, _ = self.hook("post-tool", dict(payload, sessionId="other"), wiki=False)
        self.assertEqual(obj, {})
        read_payload = {"sessionId": "s1", "timestamp": "t", "cwd": ".", "toolName": "read", "toolArgs": {"path": "src/orders/service.py"},
                        "toolResult": {"resultType": "success", "textResultForLlm": "0123456789" * 4}}
        obj, _, _ = self.hook("post-tool", read_payload)
        self.assertEqual(obj, {})
        self.assertEqual(read_json(self.state / "run.json")["budget"]["bytes_read"], 40)
        self.hook("post-tool", read_payload)
        self.assertEqual(read_json(self.state / "run.json")["budget"]["bytes_read"], 80)


class StopGateTests(HookHarness):
    def stop(self, wiki: bool = True, session: str = "s1", raw: str | None = None) -> tuple[dict, int]:
        obj, rc, _ = self.hook("stop", dict(STOP_PAYLOAD, sessionId=session), wiki=wiki, raw=raw)
        return obj, rc

    def test_clean_wiki_allows_and_writes_verified(self):
        obj, rc = self.stop()
        self.assertEqual((obj, rc), ({"decision": "allow"}, 0))
        self.assertTrue((self.state / "verified").exists())
        self.assertTrue(read(self.state / "verified").startswith("sha256:"))

    def test_dirty_but_clean_page_allows_and_verified_matches_tree(self):
        ov = self.repo / "wiki/overview.md"
        write(ov, read(ov) + "\nMore prose.\n")
        obj, rc = self.stop()
        self.assertEqual(obj, {"decision": "allow"})
        sys.path.insert(0, str(self.repo / SCRIPTS_REL))
        from wikilib import gitio  # noqa: E402
        self.assertEqual(read(self.state / "verified").strip(), gitio.tree_hash(["wiki"], self.repo))

    def test_broken_link_blocks_three_times_then_allows_with_failed_marker(self):
        bad = "modules/x.md"
        write(self.repo / "wiki" / bad, page(bad, "X module", self.head, "See [gone](missing.md)."))
        for k in (1, 2, 3):
            obj, rc = self.stop()
            self.assertEqual(rc, 0)
            self.assertEqual(obj["decision"], "block", obj)
            self.assertIn(f"wiki/{bad}:", obj["reason"])
            self.assertIn("L01", obj["reason"])
            self.assertTrue(obj["reason"].endswith(f"Fix these, then stop again (attempt {k} of 3)."), obj["reason"])
            self.assertEqual(read(self.state / f"stop-retries.s1").strip(), str(k))
            self.assertFalse((self.state / "verified").exists())
        obj, rc = self.stop()
        self.assertEqual(obj, {"decision": "allow"})
        self.assertTrue((self.state / "stop-gate-failed").exists())
        self.assertFalse((self.state / "verified").exists())
        # another session keeps its own counter
        obj, _ = self.stop(session="s2")
        self.assertEqual(obj["decision"], "block")
        self.assertEqual(read(self.state / "stop-retries.s2").strip(), "1")
        # fixing the page clears the counter
        write(self.repo / "wiki" / bad, page(bad, "X module", self.head, "Clean."))
        ov = self.repo / "wiki/overview.md"
        write(ov, read(ov) + "\n- [X module](modules/x.md)\n")
        run_script("index", "--write", cwd=self.repo, scripts=self.repo / SCRIPTS_REL)
        obj, _ = self.stop(session="s2")
        self.assertEqual(obj, {"decision": "allow"})
        self.assertFalse((self.state / "stop-retries.s2").exists())
        self.assertTrue((self.state / "verified").exists())

    def test_index_drift_is_a_finding(self):
        write(self.repo / "wiki/modules/x.md", page("modules/x.md", "X module", self.head, "Clean."))
        ov = self.repo / "wiki/overview.md"
        write(ov, read(ov) + "\n- [X module](modules/x.md)\n")
        obj, _ = self.stop()
        self.assertEqual(obj["decision"], "block")
        self.assertIn("index out of date", obj["reason"])

    def test_passive_and_malformed(self):
        write(self.repo / "wiki/modules/x.md", page("modules/x.md", "X module", self.head, "See [gone](missing.md)."))
        obj, rc = self.stop(wiki=False, session="other")
        self.assertEqual((obj, rc), ({"decision": "allow"}, 0))
        obj, rc = self.stop(raw="not json at all")
        self.assertNotEqual(rc, 0)
        self.assertEqual(obj.get("decision"), "block")
        obj, rc = self.stop(wiki=False, raw="not json at all")
        self.assertEqual((obj, rc), ({"decision": "allow"}, 0))


if __name__ == "__main__":
    unittest.main()
