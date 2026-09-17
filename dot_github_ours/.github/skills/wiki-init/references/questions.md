# wiki-init questions (five screens)

Ask one screen per `ask_user` call, in this order. Show every question with its detected default in
brackets; an empty answer or "ok" keeps the default. "Fills" names the config key
(`.github/wiki.config.json`) or the section of `wiki/instructions.md` the answer goes into. Keep the
answers as `{"Q1": …, …, "Q17": …}` for `config.py init --answers`.

## Screen 1 — Identity

| # | Question | Default / detection | Fills |
|---|---|---|---|
| Q1 | Repository name, canonical service name, aliases, one-sentence purpose? | remote path; `pyproject`/`package.json` name | `repo.slug`, `repo.id_prefix`; instructions §1; glossary seed |
| Q2 | GitLab project URL and default branch (for code links)? | `git remote -v`, `origin/HEAD` | `repo.gitlab_url`, `repo.default_branch` |
| Q3 | Output language? | `en` | `language` |

## Screen 2 — Stack

| # | Question | Default / detection | Fills |
|---|---|---|---|
| Q4 | Confirm detected stack: languages, frameworks, package manager, entry points, test runner, ADR directory, CODEOWNERS? | `detect.py` | `stacks`; instructions §3 notes |
| Q5 | Wiki directory? | `wiki` | `wiki_dir` |
| Q6 | Source roots to document and directories to exclude? | detected roots; default excludes | `sources.include/exclude`; instructions §7 |
| Q7 | OpenAPI/AsyncAPI file path, an export command, or none? | detected `openapi*`, `asyncapi*` | `api_spec.*`; instructions §3 row 6/7 |

## Screen 3 — Content

| # | Question | Default / detection | Fills |
|---|---|---|---|
| Q8 | Audiences: agents and developers always; add the product-owner layer (`product/`)? Who reviews it? | no; CODEOWNERS | `po_layer`, `po.reviewers`; instructions §2 |
| Q9 | Concepts, flows and how-tos that must have a page? | detected modules + "request path entry → response" | instructions §4, §5; plan seeds |
| Q10 | Owning team handle for `team:`? | CODEOWNERS | `repo.team` |

## Screen 4 — Budget

| # | Question | Default / detection | Fills |
|---|---|---|---|
| Q11 | Model for bootstrap, model for incremental runs? | `claude-sonnet-4.6` / `gpt-5-mini` | `models.bootstrap`, `models.incremental` |
| Q12 | Page cap per incremental run and per-run source budget? | 8 / 200 000 bytes | `max_pages`, `budgets.max_source_bytes_per_run` |
| Q13 | Commit policy for automatic runs: commit on the current branch, or branch + merge request? | commit | `commit_policy` |

## Screen 5 — Publish

| # | Question | Default / detection | Fills |
|---|---|---|---|
| Q14 | Production branch, staging branch, dev previews per branch? | default branch; detected `preprod|staging|develop`; yes | `branches.production`, `branches.staging`, `branches.dev_previews` |
| Q15 | GitLab tier: Premium/Ultimate (parallel deployments) or Free (single site)? | ask | `branches.parallel_deployments` |
| Q16 | Pages access: project members only? | yes | `pages.access` |
| Q17 | Integrate the CI jobs now and confirm git hooks? | yes / yes | actions in steps 7 (CI, hooks) of the skill |

## Notes for the asker
- Q5: a directory other than `wiki` also changes the CI include paths (`ci_integrate.py apply --wiki-dir`).
- Q8: ticking product owners enables `product/` pages (`audience: [po]`, PO style rules) and asks for
  reviewer handles; leave it off when nobody will review plain-language pages.
- Q11: the bootstrap model reads far more code than an incremental run; the incremental model should be
  small (cost per run) but must follow negative rules reliably.
- Q13: `branch-and-mr` forces `isolation: worktree` and needs `glab` authenticated on the developer machine.
- Q15: parallel deployments (`pages.path_prefix`) exist only on Premium/Ultimate ≥ 17.9; on Free the
  answer disables staging and preview jobs, the production site still publishes.
- Q17 "no": print the two commands the user can run later
  (`python3 .github/skills/wiki-maintain/scripts/ci_integrate.py apply …`, `… hooks.py install`).
