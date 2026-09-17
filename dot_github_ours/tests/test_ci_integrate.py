"""ci_integrate.py: every include form, byte-identical remainder, conflict detection, branch suggestions."""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

from conftest import FIXTURES, KIT, SCRIPTS, TempDir, git, make_repo, read, read_json, run_json, run_script, write

sys.path.insert(0, str(SCRIPTS))
import ci_integrate as ci  # noqa: E402
from wikilib import config as wconfig  # noqa: E402

CI_FIXTURES = FIXTURES / "gitlab-ci"
INCLUDE_TEMPLATE = KIT / "templates" / "ci" / "wiki.gitlab-ci.yml"
FORMS = {"none": "none", "list": "list", "scalar": "scalar", "mapping": "mapping", "flow": "flow",
         "existing-pages": "none", "already-included": "list"}


def repo_with_ci(tmp: Path, fixture: str, name: str = "repo") -> Path:
    """sample-repo + a .gitlab-ci.yml from tests/fixtures/gitlab-ci + the include template + a config."""
    repo = make_repo(tmp, commit=False, name=name)
    shutil.copyfile(CI_FIXTURES / f"{fixture}.yml", repo / ".gitlab-ci.yml")
    (repo / ".gitlab" / "ci").mkdir(parents=True)
    shutil.copyfile(INCLUDE_TEMPLATE, repo / ".gitlab" / "ci" / "wiki.gitlab-ci.yml")
    wconfig.save(repo / ".github" / "wiki.config.json", wconfig.defaults())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    return repo


def count_include_lines(text: str) -> int:
    return sum(1 for l in text.splitlines() if ci.INCLUDE_PATH in l and not l.lstrip().startswith("#"))


class DetectTests(unittest.TestCase):
    def test_include_form_for_every_fixture(self):
        with TempDir() as tmp:
            for fixture, form in FORMS.items():
                repo = repo_with_ci(tmp, fixture, name=f"r-{fixture}")
                d = run_json("ci_integrate", "detect", cwd=repo)
                self.assertEqual(d["_rc"], 0, d.get("_stderr"))
                self.assertEqual(d["include_form"], form, fixture)
                self.assertEqual(d["already_included"], fixture == "already-included", fixture)
                self.assertEqual(d["gitlab_ci"], ".gitlab-ci.yml")
                self.assertTrue(d["include_file_present"])
                for key in ("pages_jobs", "stages", "branch_vars", "default_branch", "remote_branches", "suggest",
                            "remote_host", "validators", "warnings"):
                    self.assertIn(key, d, fixture)
                self.assertTrue(d["validators"]["structural"])

    def test_conflict_detection(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "existing-pages")
            d = run_json("ci_integrate", "detect", cwd=repo)
            self.assertEqual([j["name"] for j in d["pages_jobs"]], ["pages"])
            self.assertEqual(d["pages_jobs"][0]["kind"], "job")
            self.assertTrue(any("Pages job" in w for w in d["warnings"]))
            self.assertEqual(d["stages"], ["build", "deploy"])

    def test_pages_key_and_template_detection(self):
        text = ("include:\n  - template: Pages/Jekyll.gitlab-ci.yml\n\n.lib:\n  pages:\n    path_prefix: x\n\n"
                "site:\n  extends: .lib\n  script: [echo]\n")
        scan = ci._scan_ci(text)
        names = {(j["name"], j["kind"]) for j in scan["pages_jobs"]}
        self.assertIn(("Pages/Jekyll.gitlab-ci.yml", "template"), names)
        self.assertIn((".lib", "pages-key"), names)

    def test_branch_suggestions_from_variables(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)          # sample-repo: BRANCH_PROD "main", BRANCH_PREPROD "preprod"
            d = run_json("ci_integrate", "detect", cwd=repo)
            self.assertEqual(d["branch_vars"], {"BRANCH_PROD": "main", "BRANCH_PREPROD": "preprod"})
            self.assertEqual(d["suggest"], {"prod": "main", "staging": "preprod"})
            self.assertEqual(d["default_branch"], "main")
            self.assertEqual(d["include_form"], "none")

    def test_branch_suggestions_from_branches_and_list_fixture(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "list")       # PROD_BRANCH "production", STAGING_BRANCH "staging"
            d = ci.detect(repo, probe_tools=False)
            self.assertEqual(d["suggest"], {"prod": "production", "staging": "staging"})
            repo2 = repo_with_ci(tmp, "none", name="r2")
            git(repo2, "branch", "develop")
            git(repo2, "update-ref", "refs/remotes/origin/develop", "HEAD")
            d2 = ci.detect(repo2, probe_tools=False)
            self.assertEqual(d2["suggest"]["prod"], "main")
            self.assertEqual(d2["suggest"]["staging"], "develop")
            self.assertIn("develop", d2["remote_branches"])

    def test_python_api_without_gitlab_ci(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            (repo / ".gitlab-ci.yml").unlink()
            d = ci.detect(repo, probe_tools=False)
            self.assertIsNone(d["gitlab_ci"])
            self.assertEqual(d["include_form"], "none")
            self.assertTrue(any("no .gitlab-ci.yml" in w for w in d["warnings"]))

    def test_slug_equal_to_wiki_folder_warns(self):
        with TempDir() as tmp:
            repo = make_repo(tmp)
            (repo / "wiki" / "modules").mkdir(parents=True)
            git(repo, "update-ref", "refs/remotes/origin/Modules", "HEAD")
            d = ci.detect(repo, probe_tools=False)
            self.assertTrue(any("slug 'modules'" in w and "wiki folder" in w for w in d["warnings"]), d["warnings"])

    def test_remote_parsing(self):
        self.assertEqual(ci._parse_remote("git@gitlab.example.com:group/sub/project.git"),
                         {"remote_url": "git@gitlab.example.com:group/sub/project.git",
                          "remote_host": "gitlab.example.com", "remote_path": "group/sub/project"})
        self.assertEqual(ci._parse_remote("https://gitlab.com/g/p.git")["remote_path"], "g/p")
        self.assertEqual(ci._parse_remote("ssh://git@gitlab.com:2222/g/p")["remote_host"], "gitlab.com")
        self.assertEqual(ci.ci_slug("feature/Big Thing!"), "feature-big-thing")


class ApplyTests(unittest.TestCase):
    def test_every_form_byte_identical_remainder_and_reversible(self):
        with TempDir() as tmp:
            for fixture, form in FORMS.items():
                if fixture == "already-included":
                    continue
                repo = repo_with_ci(tmp, fixture, name=f"r-{fixture}")
                original = read(repo / ".gitlab-ci.yml")
                res = run_json("ci_integrate", "apply", "--prod-branch", "main", "--staging-branch", "preprod",
                               "--parallel", "true", "--yes", cwd=repo)
                self.assertEqual(res["_rc"], 0, res.get("_stderr"))
                self.assertTrue(res["inserted"], fixture)
                self.assertEqual(res["include_form"], form, fixture)
                new = read(repo / ".gitlab-ci.yml")
                self.assertEqual(count_include_lines(new), 1, fixture)
                # the remainder is byte-identical: stripping our entry gives the original back
                self.assertEqual(ci.strip_include(new, form), original, fixture)
                self.assertEqual(read_json(repo / ".github" / "wiki.config.json")["kit"]["ci_include_form"], form)
                d = run_json("ci_integrate", "detect", cwd=repo)
                self.assertTrue(d["already_included"], fixture)
                chk = run_json("ci_integrate", "check", cwd=repo)
                self.assertEqual(chk["_rc"], 0, (fixture, chk))
                self.assertTrue(chk["ok"])
                self.assertEqual(chk["validator"], "structural")    # no glab / PyYAML on this machine
                self.assertIn("structural", chk["validators_run"])
                # idempotent
                res2 = run_json("ci_integrate", "apply", "--prod-branch", "main", "--staging-branch", "preprod",
                                "--parallel", "true", "--yes", cwd=repo)
                self.assertFalse(res2["inserted"])
                self.assertEqual(read(repo / ".gitlab-ci.yml"), new)
                # remove reverts to the original bytes
                rem = run_json("ci_integrate", "remove", "--yes", cwd=repo)
                self.assertEqual(rem["_rc"], 0, rem.get("_stderr"))
                self.assertEqual(read(repo / ".gitlab-ci.yml"), original, fixture)
                self.assertEqual(read_json(repo / ".github" / "wiki.config.json")["kit"]["ci_include_form"], "")

    def test_settings_block_rewritten_and_recorded(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            res = run_json("ci_integrate", "apply", "--prod-branch", "prod", "--staging-branch", "staging",
                           "--parallel", "true", "--previews", "false", "--publish", "true",
                           "--expire-in", "2 weeks", "--verify-soft", "true", "--yes", cwd=repo)
            self.assertEqual(res["_rc"], 0, res.get("_stderr"))
            inc = read(repo / ".gitlab" / "ci" / "wiki.gitlab-ci.yml")
            settings = ci.read_project_settings(inc)
            self.assertEqual(settings, {"WIKI_PROD_BRANCH": "prod", "WIKI_STAGING_BRANCH": "staging",
                                        "WIKI_PUBLISH": "true", "WIKI_PARALLEL_DEPLOYMENTS": "true",
                                        "WIKI_DEV_PREVIEWS": "false", "WIKI_DEV_EXPIRE_IN": "2 weeks",
                                        "WIKI_VERIFY_SOFT": "true"})
            # only the PROJECT SETTINGS values changed in the include file
            template = read(INCLUDE_TEMPLATE)
            self.assertEqual(ci.set_project_settings(inc, ci.read_project_settings(template)), template)
            cfg = read_json(repo / ".github" / "wiki.config.json")
            self.assertEqual(cfg["branches"]["production"], "prod")
            self.assertEqual(cfg["branches"]["staging"], "staging")
            self.assertTrue(cfg["branches"]["parallel_deployments"])
            self.assertFalse(cfg["branches"]["dev_previews"])
            self.assertIn(".gitlab/ci/wiki.gitlab-ci.yml", cfg["kit"]["files"])

    def test_apply_requires_yes_and_dry_run_writes_nothing(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "list")
            before = read(repo / ".gitlab-ci.yml")
            r = run_script("ci_integrate", "apply", "--prod-branch", "main", cwd=repo)
            self.assertEqual(r.returncode, 2)
            self.assertIn("--- a/.gitlab-ci.yml", r.stdout)
            self.assertEqual(read(repo / ".gitlab-ci.yml"), before)
            r = run_script("ci_integrate", "apply", "--prod-branch", "main", "--dry-run", cwd=repo)
            self.assertEqual(r.returncode, 0)
            self.assertIn("+  - local: .gitlab/ci/wiki.gitlab-ci.yml", r.stdout)
            self.assertEqual(read(repo / ".gitlab-ci.yml"), before)

    def test_conflict_warning_on_existing_pages_job(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "existing-pages")
            res = run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            self.assertTrue(any("Pages job" in w for w in res["warnings"]), res["warnings"])
            chk = run_json("ci_integrate", "check", cwd=repo)
            self.assertTrue(chk["ok"])
            self.assertTrue(any("coexist" in w for w in chk["warnings"]))
            res2 = run_json("ci_integrate", "apply", "--publish", "false", "--yes", cwd=repo)
            self.assertFalse(any("Pages job" in w for w in res2["warnings"]))
            self.assertEqual(ci.read_project_settings(read(repo / ".gitlab/ci/wiki.gitlab-ci.yml"))["WIKI_PUBLISH"], "false")

    def test_already_included_leaves_pipeline_untouched(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "already-included")
            before = read(repo / ".gitlab-ci.yml")
            res = run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            self.assertFalse(res["inserted"])
            self.assertTrue(res["already_included"])
            self.assertEqual(read(repo / ".gitlab-ci.yml"), before)
            self.assertEqual(ci.read_project_settings(read(repo / ".gitlab/ci/wiki.gitlab-ci.yml"))["WIKI_PROD_BRANCH"], "main")

    def test_missing_gitlab_ci_is_created(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            (repo / ".gitlab-ci.yml").unlink()
            res = run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            self.assertEqual(res["_rc"], 0, res.get("_stderr"))
            self.assertEqual(read(repo / ".gitlab-ci.yml"), "include:\n  - local: .gitlab/ci/wiki.gitlab-ci.yml\n")
            run_json("ci_integrate", "remove", "--yes", cwd=repo)
            self.assertEqual(read(repo / ".gitlab-ci.yml"), "")

    def test_wiki_dir_rewrites_anchor_and_variable(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            res = run_json("ci_integrate", "apply", "--prod-branch", "main", "--wiki-dir", "docs/wiki", "--yes", cwd=repo)
            self.assertEqual(res["_rc"], 0, res.get("_stderr"))
            inc = read(repo / ".gitlab/ci/wiki.gitlab-ci.yml")
            self.assertIn('WIKI_DIR: "docs/wiki"', inc)
            self.assertIn('- "docs/wiki/**/*"', inc)
            self.assertNotIn('- "wiki/**/*"', inc)
            self.assertEqual(ci.read_wiki_dir(inc), "docs/wiki")

    def test_missing_include_file_is_an_environment_error(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            (repo / ".gitlab/ci/wiki.gitlab-ci.yml").unlink()
            r = run_script("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            self.assertEqual(r.returncode, 3)
            self.assertIn("install.py", r.stderr)

    def test_bad_branch_name_rejected(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            r = run_script("ci_integrate", "apply", "--prod-branch", 'ma"in', "--yes", cwd=repo)
            self.assertEqual(r.returncode, 2)


class CheckTests(unittest.TestCase):
    def test_structural_check_reports_missing_include_and_tabs(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "none")
            chk = run_json("ci_integrate", "check", cwd=repo)
            self.assertEqual(chk["_rc"], 1)
            self.assertFalse(chk["ok"])
            self.assertTrue(any("include entry" in e for e in chk["errors"]))
            run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            write(repo / ".gitlab-ci.yml", read(repo / ".gitlab-ci.yml") + "bad:\n\tscript: [x]\n")
            chk = run_json("ci_integrate", "check", cwd=repo)
            self.assertEqual(chk["_rc"], 1)
            self.assertTrue(any("tab" in e for e in chk["errors"]), chk["errors"])

    def test_structural_check_validates_include_file(self):
        errors, _ = ci.structural_check("include:\n  - local: .gitlab/ci/wiki.gitlab-ci.yml\n", "stages: [x]\n", "none")
        self.assertTrue(any("wiki:verify" in e for e in errors))
        self.assertTrue(any("must not define `stages`" in e for e in errors))
        errors, warnings = ci.structural_check("include:\n  - local: .gitlab/ci/wiki.gitlab-ci.yml\n",
                                               read(INCLUDE_TEMPLATE), "none")
        self.assertEqual(errors, [])
        dup = "include:\n  - local: .gitlab/ci/wiki.gitlab-ci.yml\nstages: [a]\nstages: [b]\n"
        errors, _ = ci.structural_check(dup, read(INCLUDE_TEMPLATE), "none")
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_forced_validator_unavailable_fails(self):
        with TempDir() as tmp:
            repo = repo_with_ci(tmp, "list")
            run_json("ci_integrate", "apply", "--prod-branch", "main", "--yes", cwd=repo)
            chk = run_json("ci_integrate", "check", "--validator", "structural", cwd=repo)
            self.assertTrue(chk["ok"])
            self.assertEqual(chk["validators_run"], ["structural"])


class TextEditTests(unittest.TestCase):
    """Pure-function edge cases (CRLF, no trailing newline, flow lists, null include)."""

    CASES = {
        "crlf-none": "# c\r\nstages:\r\n  - test\r\n",
        "crlf-list": "include:\r\n  - local: a.yml\r\n\r\nstages:\r\n  - test\r\n",
        "no-trailing-newline-list": "include:\n  - local: a.yml",
        "no-trailing-newline-none": "stages: [test]",
        "scalar-last-line": "stages: [test]\ninclude: a.yml",
        "scalar-with-comment": "include: a.yml  # lint\nstages: [test]\n",
        "inline-mapping": "include: {project: g/p, file: x.yml}\nstages: [test]\n",
        "flow-empty": "include: []\nstages: [test]\n",
        "flow-multiline": "include: [\n  {local: a.yml},\n  {template: b.yml},\n]\nstages: [test]\n",
        "flow-trailing-comma": "include: [{local: a.yml},]\nstages: [test]\n",
        "list-indent-0": "include:\n- local: a.yml\n- local: b.yml\nstages: [test]\n",
        "mapping-nested": "include:\n  project: g/p\n  ref: main\n  file:\n    - a.yml\n    - b.yml\n\nstages: [test]\n",
        "null-include": "include:\n\nstages: [test]\n",
        "doc-start": "---\n# hdr\n\nstages: [test]\n",
        "empty": "",
        "comments-only-no-newline": "# just a comment",
    }

    def test_round_trip_every_layout(self):
        for name, text in self.CASES.items():
            new, form = ci.insert_include(text)
            self.assertTrue(ci.already_included(new), name)
            self.assertEqual(ci.insert_include(new)[0], new, f"{name}: not idempotent")
            self.assertEqual(ci.strip_include(new, form), text, f"{name}: strip did not restore the original")
            self.assertFalse(ci.already_included(ci.strip_include(new, None)), f"{name}: strip without form")

    def test_mapping_is_wrapped_as_list_item(self):
        new, form = ci.insert_include(self.CASES["mapping-nested"])
        self.assertEqual(form, "mapping")
        self.assertEqual(new, "include:\n  - project: g/p\n    ref: main\n    file:\n      - a.yml\n      - b.yml\n"
                              "  - local: .gitlab/ci/wiki.gitlab-ci.yml\n\nstages: [test]\n")

    def test_flow_gets_inline_item(self):
        new, form = ci.insert_include('include: [{local: "a.yml"}]\n')
        self.assertEqual(form, "flow")
        self.assertEqual(new, 'include: [{local: "a.yml"}, {local: ".gitlab/ci/wiki.gitlab-ci.yml"}]\n')


if __name__ == "__main__":
    unittest.main()
