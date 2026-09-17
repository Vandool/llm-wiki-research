---
name: wiki-maintain
description: >-
  Reference for the wiki maintenance scripts and page templates; load when a wiki skill needs a
  script's flags or a page template.
allowed-tools: [read, edit, search, execute]
user-invocable: false
---
# wiki-maintain — script and template reference

Every script lives in `.github/skills/wiki-maintain/scripts/` and is run as
`python3 .github/skills/wiki-maintain/scripts/<name>.py …` from the repository root (the only shell
form the guard hook allows). Shared flags: `--help`, `--repo PATH`, `--config PATH` (default
`.github/wiki.config.json`), `--json` (exactly one JSON object on stdout, human text on stderr),
`--quiet`. Exit codes: 0 ok · 1 findings or check failed · 2 usage/config · 3 environment (lock held,
wiki dirty, not a repo) · 4 model/subprocess failure. JSON outputs carry
`{"schema_version":1,"script":"<name>/<ver>","ok":bool,…}`.

| Script | CLI | Output (`--json`) |
|---|---|---|
| `affected.py` | `[--json] [--check-only] [--summary] [--full] [--instruction TEXT] [--issue N] [--lift-cap] [--max-pages N] [--out FILE] [--md FILE] [--run-id ID] [--bootstrap-cluster ID]` | work list + context packs: `{run_id, checkpoint_commit, head, changed_files[], stale[{page,type,owner,status,reasons[]}], gaps[], requests[], instruction, untrusted_block, cap{max_pages,selected,lifted,deferred[]}, order[], packs{page:{template,headings[],sources[{id,resource,status,excerpt,symbols[]}]}}, may_create[], noop}`; `--check-only` prints the staleness table, exit 1 when stale |
| `facts.py` | `[--json] [--only inventory,symbols,deps,changelog,decisions,owners,openapi,asyncapi,catalog] [--check] [--detect-stacks] [--seed-catalog] [--shard-lines 400]` | `{generated[], counts{}, stacks[]}`; writes `generated/**`, `api/<router>.md`, `events/<channel>.md`, `decisions/index.md`; `--check` exit 1 on drift |
| `lint.py` | `(--file PATH \| --changed \| --staged \| --all) [--json] [--fix] [--strict] [--base SHA] [--full] [--anchors]` | `{errors[{rule,code,severity,file,line,message,fix}], warnings[], summary{}}`; exit 1 on errors |
| `backlinks.py` | `(--changed \| --all) [--json] [--check] [--suggest] [--plan FILE] [--graph OUT]` | `{orphans[], suggestions{}}`; `--plan` accepts planned pages as link targets |
| `index.py` | `[--json] [--check] [--write] [--consumers]` | `{written[], drift[]}`; regenerates every `index.md` except `decisions/`, `api/`, `events/` |
| `manifest.py` | `[--json] (--init \| --touched \| --pages P… \| --all) [--run-id ID] [--model M] [--advance-checkpoint] [--prune]` | `{pages_updated[], checkpoint}`; scripts only, never called by a skill |
| `requests.py` | `[--json] (--parse \| --close N… --run-id ID --result PATH \| --skip N --reason TEXT \| --defer N --reason TEXT) [--lint]` | `{open[{n,line,date,user,text}], block}` |
| `log.py` | `[--json] add --action A --text T [--page P] [--run-id ID] \| rotate \| check` | actions: Bootstrap, Creation, Update, Deprecation, Lint, Query, Instruction, Deferred |
| `excerpt.py` | `PATH [--hunks] [--symbol NAME] [--lines a-b] [--max-lines N] [--json]` | text, or `{path, range, text, bytes}`; meters bytes into the run budget; exit 3 = budget exhausted |
| `plan.py` | `build [--json] \| commit [--approved-by USER] \| show ID --json \| mark ID done\|deferred\|failed [--reason TEXT] \| split ID \| next --json \| estimate [--json] \| status` | cluster plan in `wiki/.wiki-plan.json`; `show` returns `{id,title,kind,deps[],pages[{path,type,audience,owner,sources[],notes}],estimate{},status}` |
| `detect.py` | `--json` | `{stacks[], evidence{}, roots[], specs[], adr_dir, codeowners, remote, default_branch, branches{suggest_prod,suggest_staging}, ci{…}}` |
| `template.py` | `TYPE [--json] [--vars k=v…]` | the page template for `TYPE` from `references/templates/` with `{{placeholders}}` substituted |
| `config.py` | `get KEY \| set KEY VALUE \| init --from F --answers F \| quartz-ignore --json \| validate` | dotted keys, e.g. `config.py get models.incremental` |
| `run.py` | `begin --mode init\|update\|query\|lint [--instruction TEXT] [--force] \| status --json \| prompt \| defer --reason TEXT \| end \| bootstrap --detach` (`worker …` is for hooks and humans, not for the model) | `status` returns `.git/wiki/run.json`: `{run_id, mode, model, checkpoint, head, wiki_dir, cluster, work[], may_create[], requests[], instruction, budget{}, over_budget, status}` |
| `ci_integrate.py` | `detect [--json] \| apply --prod-branch B [--staging-branch B] [--previews bool] [--parallel bool] [--publish bool] [--wiki-dir D] [--yes] [--dry-run] \| check [--json] \| remove` | `detect`: `{gitlab_ci, include_form, already_included, pages_jobs[], branch_vars{}, suggest{prod,staging}, validators{}}`; `apply` prints a unified diff |
| `hooks.py` | `install [--hooks auto\|git\|pre-commit\|none] \| uninstall \| status [--json]` | git hook trampolines |
| `bootstrap.py` | `[--json] [--resume] [--only ID[,ID]] [--dry-run] [--model M] [--max-failures 2] [--plan FILE] [--wait-lock SECONDS]` | the driver; run by a human or `run.py bootstrap --detach`, never from inside a session |
| `hook_guard.py`, `stop_gate.py` | `session-start \| pre-tool \| post-tool` / none | Copilot hooks; one JSON object each |

Page templates: `references/templates/<type>.md` (`module`, `concept`, `howto`, `runbook`,
`architecture`, `contract-guide`, `feature`, `analysis`, `conventions`); `template.py <Type>` renders
them with `--vars`. Context and read budgets: `references/budgets.md`. Frontmatter keys, enumerations
and the YAML subset the scripts parse: `references/frontmatter-schema.md`. Versioned headless prompts:
`prompts/update.md`, `prompts/bootstrap.md`.
