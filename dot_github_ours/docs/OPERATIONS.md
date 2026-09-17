# Operating the wiki kit

## How a run works

```
git commit (code)  →  .git/hooks/post-commit (trampoline)  →  .github/skills/wiki-maintain/hooks/post-commit
   guards: WIKI_HOOK_DISABLE · wiki.hook.disable · WIKI_HOOK_RUNNING · trailer "Wiki-Update: auto"
           · mid-rebase · wiki not bootstrapped (no wiki/.manifest.json) · wiki-only commit
   →  nohup python3 .github/skills/wiki-maintain/scripts/run.py worker --trigger post-commit  (background)
        lock .git/wiki/lock · debounce · skip_runs_on branches · dirty wiki ⇒ stop
        facts.py            regenerate generated/, api/, events/, decisions/index.md (no model)
        affected.py         staleness vs the manifest checkpoint + OPEN requests + coverage gaps
          nothing affected  ⇒ commit facts if changed, advance checkpoint, exit (no model call)
          > max_pages       ⇒ commit facts, log "Deferred", exit (run by hand lifts the cap)
        copilot -p … --agent wiki-maintainer --model <models.incremental> -s --no-ask-user   (§8.14)
          hooks: preToolUse guard (writes confined to wiki/) · postToolUse lint · agentStop gate
        judge: diff confined to wiki/ · lint --all clean · backlinks --check clean · .git/wiki/verified
        index.py --write --consumers · manifest.py --touched · requests.py --close · log.py add/rotate
        commit "docs(wiki): update N pages"  trailers Wiki-Update: auto, Wiki-Run: <id>
        manifest.py --advance-checkpoint   (written right before the commit so the tree ends clean)
```

The developer is never blocked: the hook returns in well under a second and the follow-up commit appears
on the same branch a few minutes later. `git push` runs `pre-push`, a deterministic staleness report
(`affected.py --check-only --summary`) that blocks only in strict mode.

Manual runs (same code path, foreground, cap lifted):

```sh
python3 .github/skills/wiki-maintain/scripts/run.py worker --foreground --lift-cap
python3 .github/skills/wiki-maintain/scripts/run.py worker --foreground --no-model     # facts + index + manifest only
copilot --agent wiki-maintainer   then   /wiki-update "focus on the payments router"
```

Notes on the guards: the trailer and wiki-only-commit guards apply to `--trigger post-commit` only, so a manual
`run.py worker --foreground --lift-cap` right after a "Deferred" facts commit still runs. The checkpoint is advanced
inside the update commit (only when the judge says `ok`); advancing afterwards would leave `.manifest.json` dirty and
block the next run. `run.py begin` takes a pid-less interactive lock that a later `begin` reclaims (a session that
quit without `run.py end` never blocks for `lock_ttl_min`); background workers honour it until the TTL.

## State on disk

Committed:

| File | Content |
|---|---|
| `wiki/.manifest.json` | checkpoint commit, per-page source hashes, last run |
| `wiki/.wiki-plan.json` | bootstrap cluster plan and per-cluster status |
| `wiki/log.md`, `wiki/log/*.md` | append-only action log (union merge), rotated archives |
| `wiki/requests.md` | the steering file (OPEN → DONE/SKIPPED/DEFERRED) |
| `.github/wiki.config.json` | config; `kit.files` = sha256 of every kit file |

Volatile, under `$(git rev-parse --git-dir)/wiki/` (never committed, never published):

| File | Content |
|---|---|
| `run.json` | the current run: mode, model, work list, budgets, `bytes_read`, status |
| `lock/` | pid-aware lock directory (`lock_ttl_min` reclaims a dead one) |
| `update.log` | stdout/stderr of hook-started workers (1 MB rotation → `update.log.1`) |
| `guard.log` | every guard decision with the raw payload keys (how the exact tool names were learned) |
| `verified` | tree hash written by the stop gate when lint/backlinks/index were clean |
| `stop-retries.<sessionId>`, `stop-gate-failed` | stop-gate retry counter; marker after 3 failed retries |
| `context.json`, `context.md` | work list and context packs of the last `affected.py` |
| `last-transcript.md`, `last-output.txt` | the CLI session share and output |
| `metrics.jsonl` | one line per run: duration, pages, tokens when available |
| `lint-report.md` | headless `/wiki-lint` findings |
| `bootstrap-<cluster>.log` | driver output per cluster |

`git config wiki.dir` is set by `hooks.py` when the wiki directory is not `wiki`, so the hooks find it
without reading JSON.

## Off switches and knobs

| Switch | Scope | Effect |
|---|---|---|
| `WIKI_HOOK_DISABLE=1` | one command / shell | post-commit, pre-push and pre-commit-lint exit 0 immediately |
| `git config wiki.hook.disable true` | this clone | same, persistent |
| `git commit --no-verify` | one commit | git skips hooks; CI still verifies |
| `WIKI_STRICT=1` or `git config wiki.strict true` | pre-push | a stale wiki blocks the push |
| `branches.skip_runs_on` (config) | branches | no automatic runs on matching branches (`renovate/*`, `release/*`) |
| `max_pages` (config) / `--lift-cap` | run | narrative pages per automatic run; overflow is logged as Deferred |
| `models.incremental` / `models.bootstrap` (config) | run | the pinned models; passed as `--model` |
| `commit_policy: branch-and-mr` (config) | run | commit on `wiki/update-<run_id>` and open an MR with `glab` instead of committing on the current branch |
| `WIKI_PUBLISH: "false"` (CI variable or PROJECT SETTINGS) | CI | verify only, never build or deploy the site |
| `WIKI_VERIFY_SOFT: "true"` | CI | `wiki:verify` warns instead of failing (rollout period) |
| `WIKI_COPILOT_BIN`, `git config wiki.copilot`, `copilot.bin` (config) | run | where the CLI binary is |

## Steering (no tokens, no API keys)

1. **`wiki/requests.md`** — anyone with write access, including a product owner through GitLab's single-file
   editor, adds a line under `## Open`:
   `- [ ] OPEN 2026-09-07 @jane: Explain the retry policy for the PO`
   The next run applies it (only to pages in its work list), marks it `DONE … → run <id> <page>`, `SKIPPED` or
   `DEFERRED`, and logs it. Request text reaches the model inside an untrusted, delimited block: it can say
   what is wanted, it cannot change rules or name files outside the work list.
2. **`/wiki-update "instruction"`** — a developer in `copilot --agent wiki-maintainer`; the instruction is
   passed as data to the same run, with the page cap lifted.
3. **GitLab issue** — install the template with `install.py --issue-template`; a person files a "Wiki request"
   issue; a developer runs `python3 .github/skills/wiki-maintain/scripts/run.py worker --issue 123`, which reads
   the issue with `glab issue view` (the developer's own GitLab login) and comments the result with
   `glab issue note`.

Retry: reopen the request line, or re-run the command. Contradictions are reported, not smoothed over;
if the wiki and the code disagree the page is corrected and a dated line records the superseded statement.

## CI

`.gitlab/ci/wiki.gitlab-ci.yml` (included from `.gitlab-ci.yml` by `/wiki-init`; `ci_integrate.py apply`)
defines, all in stage `.post` with `needs: []`:

| Job | Runs when | Does |
|---|---|---|
| `wiki:verify` | every MR, default/prod/staging branches | `lint.py --all --strict`, `backlinks.py --check`, `facts.py --check`, `index.py --check`, `affected.py --check-only` — fails when the wiki is stale or invalid; no model |
| `wiki:pages` | production branch (`WIKI_PROD_BRANCH`, `""` = default branch) on wiki changes, manual otherwise | Quartz build → site root |
| `wiki:pages:staging` | `WIKI_STAGING_BRANCH`, parallel deployments on | site under `/staging`, `expire_in: never` |
| `wiki:pages:preview` | any other branch / MR, parallel deployments and previews on | site under `/<branch-slug>`, expires after `WIKI_DEV_EXPIRE_IN` |

Everything under `variables:` can be overridden as a project CI/CD variable without editing the file.
`ci_integrate.py detect` lists existing Pages jobs, include form, literal branch variables and suggestions;
`ci_integrate.py check` validates with `glab ci lint` → PyYAML → structural rules and says which one ran;
`ci_integrate.py remove` reverts the include entry byte-for-byte.

Parallel deployments (`pages.path_prefix`) need Premium/Ultimate and GitLab >= 17.9; on Free keep
`WIKI_PARALLEL_DEPLOYMENTS: "false"` (only the production site is published). A preview prefix must not
equal a top-level wiki folder or page name; `detect` warns when a branch slug clashes (`docs` branch vs
`docs/` folder would override that path).

### GitLab 17.4–17.8 variant

The shipped file needs 17.9 (`pages.publish`, user-named Pages jobs need 17.5, `path_prefix` GA 17.9,
`expire_in` from a variable 17.11). On 17.4–17.8 keep the include and add these overrides to
`.gitlab-ci.yml` after it (job overrides merge by name; YAML anchors do not cross the include boundary,
so the paths are written out):

```yaml
include:
  - local: .gitlab/ci/wiki.gitlab-ci.yml

# GitLab 17.4–17.8: legacy `pages` job name, no `publish`, no parallel deployments
wiki:pages:
  rules: [{ when: never }]
wiki:pages:staging:
  rules: [{ when: never }]
wiki:pages:preview:
  rules: [{ when: never }]
pages:
  extends: .wiki_pages
  resource_group: wiki-pages-production
  environment: { name: wiki/production, url: $CI_PAGES_URL }
  rules:
    - if: $WIKI_PUBLISH != "true"
      when: never
    - if: $WIKI_PROD_BRANCH == "" && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      changes: ["wiki/**/*", ".gitlab/ci/wiki.gitlab-ci.yml", ".gitlab/wiki-site/**/*"]
    - if: $WIKI_PROD_BRANCH != "" && $CI_COMMIT_BRANCH == $WIKI_PROD_BRANCH
      changes: ["wiki/**/*", ".gitlab/ci/wiki.gitlab-ci.yml", ".gitlab/wiki-site/**/*"]
    - if: $WIKI_PROD_BRANCH == "" && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: true
```

`public` is already in `artifacts:paths`, which is all the legacy `pages` job needs. On 17.5–17.8 the job
may keep the name `wiki:pages` if you delete the `pages: {publish: public}` block instead. `build.sh`
compensates for `CI_PAGES_URL` lacking the prefix before 17.9.

### Secrets and access

Add GitLab's secret detection next to the wiki include — the wiki is published, and every non-markdown
file under `wiki/` is emitted as-is:

```yaml
include:
  - local: .gitlab/ci/wiki.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
```

`lint.py` also scans for token patterns (L05) and the guard denies reads of `.env*`, keys and secrets
directories, but a server-side scan is the backstop.

Pages access control: Settings → General → Visibility, project features, permissions → Pages →
"Only project members" (available on Free; default `pages.access: members` in the config). On
self-managed the administrator must enable `gitlab_pages['access_control'] = true` first; group owners can
remove the public option for all projects.

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Nothing happens after a commit | `hooks.py status`; `.git/wiki/update.log`; `git log -1 --format=%B` (trailer?); did the commit touch only `wiki/`? | `hooks.py install` in this clone; IDE "run git hooks" setting; `core.hooksPath` → add the printed lines |
| `wiki: python not found` | `python3` on PATH in the hook's environment (IDEs start with a minimal PATH) | install Python, or `--hooks pre-commit` |
| `copilot` not found / auth error in `update.log` | `copilot --version`, `copilot login`; enterprise logins with `-p` (research ADR-01 §8) | `WIKI_COPILOT_BIN=/path/to/copilot`, `git config wiki.copilot …`; token via `COPILOT_GITHUB_TOKEN` from a user-level secret store |
| `wiki: update already running` / lock held | `.git/wiki/lock/` with a live pid? | wait, or remove the directory when the pid is dead (`lock_ttl_min` does it automatically) |
| Run ends with `deferred` | `.git/wiki/context.md`: over `max_pages` or the byte budget | run by hand with `--lift-cap`, raise `budgets.*`, split the change |
| `wiki:verify` red | job log: stale pages, lint findings, drift | locally `copilot` → `/wiki-update`, commit `wiki/`; without Copilot `run.py worker --foreground --no-model` regenerates facts/index/manifest |
| Model wrote outside `wiki/` | `.git/wiki/guard.log` | nothing to do: the worker reverts it and refuses the commit; report the tool name if the guard missed it |
| Pages 404 / links broken under a prefix | job log line `wiki-site: baseUrl=… baseDir=…`; `python3 tests/check_site_links.py public --base /<prefix>` | prefix must equal `pages.path_prefix`; no wiki folder with the branch slug's name |
| External font requests | `build.sh` prints a warning when `fonts.googleapis.com` survives | `fontOrigin: local` is set; check the Quartz version |
| Slow site builds | `WIKI_CONCURRENCY` (default `2` in CI) | raise on larger runners; `.npm/` and `.wiki-build/.quartz/plugins/` are cached per `WIKI_QUARTZ_REF` |
| Merge conflicts in `wiki/log.md` | `.gitattributes` has `merge=union` (installed by the kit) | `git checkout --theirs` is never needed; regenerate `index.md` with `index.py --write` |
| `__pycache__` under `.github/skills/…` after a run | Python bytecode from hook-started scripts | add `__pycache__/` to `.gitignore` (most repositories already have it) |
