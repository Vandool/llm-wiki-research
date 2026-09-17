# Design notes

This file is the complete design record of the kit: the accepted design in summary, the decisions taken
while turning it into one installable kit, and the assumptions that still need confirmation. It stands on
its own; nothing outside this repository is required to understand or change the kit.

## The accepted design in summary

**Requirements.** Dual audience (coding agents, developers, optionally product owners); the wiki is the
context layer for the whole AI development pipeline; it must survive fully autonomous agents; bootstrap
once, then automatic upkeep triggered by git hooks; humans steer through a form-like channel rather than
editing; only GitHub Copilot, no API keys; GitLab hosting; Quartz on GitLab Pages. The model runs only on a
developer machine through the Copilot CLI or IDE under that developer's login; shared runners run
deterministic jobs only. Manual upkeep is not an option: automation maintains, humans steer.

**Execution model.** A `post-commit` git hook starts, in the background, `copilot -p … --agent
wiki-maintainer --model <pinned> -s --no-ask-user --add-dir wiki`; the developer is never blocked. Loop
guards: an environment flag on the worker, the HEAD trailer `Wiki-Update: auto`, commits touching only
`wiki/`, a pid-aware lock, a debounce. The CLI's exit codes are undocumented, so success is judged by
evidence: working-tree diff confined to the wiki, lint and backlinks clean, the stop gate's `verified`
marker, and the model's final `WIKI-RUN-RESULT:` line. Known CLI quirks handled: `COPILOT_AUTO_UPDATE=false`,
detached process group with `killpg` on timeout, transcript captured with `--share`.

**Facts versus narrative.** Scripts generate every factual page (inventory, symbol index, dependency
manifests, git changelog, ADR index, CODEOWNERS, API and event contracts from OpenAPI/AsyncAPI, every
`index.md`, the log). The model writes only narrative pages listed by `affected.py`, from declared sources
and diff hunks read through `excerpt.py` under a byte budget, one section at a time with a minimal diff.
Every page declares `sources[]` and `last_verified_commit`, so staleness is a git query against the
committed manifest: blob, line-range and symbol hashes per source, checkpoint commit advanced only after a
successful run. Nothing affected means no model call. Verification happens in-session through hooks
(deny, lint feedback, stop gate with three retries) and again in CI without a model (`wiki:verify`: facts
regenerate and diff, lint, backlinks, index drift, staleness, secrets) as the backstop for bypassed hooks.

**Frontmatter contract.** Required keys `type, title, description, id, schema_version, audience, owner,
generated{by,at}`; agent- and process-owned pages also carry `sources[]` and `last_verified_commit`.
Source resources use the schemes `repo://path[#La-Lb|::Symbol]`, `api://`, `event://`, `adr://`,
`changelog://`, `flag://`, `https://`. Actors are `copilot-cli/<model>`, `process:<script>/<ver>`,
`human:<user>`. `id` is `<id_prefix>/<path-without-.md>`. Quartz-semantic keys (`date, created, modified,
updated, lastmod, published, image, cover, permalink, draft`) are never used for other meanings; shared
keys are `title, description, tags, aliases`. Closed enumerations for `type`, `status`, `audience`,
`owner`, log actions, request states and stale reasons; a change bumps `schema_version`.

**Content model.** Fixed layout `wiki/{index.md, log.md, log/, conventions.md, requests.md,
instructions.md, overview.md, glossary.md, catalog.yaml, .manifest.json, architecture/, api/, events/,
modules/, concepts/, howto/, runbooks/, analyses/, decisions/, generated/, product/}`, lowercase
kebab-case names, a distinct-titled `index.md` per folder generated from frontmatter and never model-edited.
Page types with line caps (Overview 150, Architecture 200, Module 200, Concept 120, How-to 120, Contract
400, Contract Guide 150, Runbook 150, Glossary 300, Feature 80, Analysis 200, …), a fixed heading order per
type, a `**Read this when:**` lede, footnotes keyed by `sources[].id`, inline citations
`path/file.py::Symbol`, markdown links only (file-relative with `.md`, no wikilinks). Agent navigation:
root index, at most two folder indexes, at most five pages, then follow `sources` into the code; the log is
never read except when debugging. The product-owner layer (`product/`) has its own vocabulary rules. Lint
rules L01–L17 cover broken links, orphans, staleness, size caps, secrets, the frontmatter schema, PO
leakage, link form, ownership, index and log integrity, coverage gaps, citation coverage, hidden Unicode,
duplicated headings, the trust gate and a churn guard; all deterministic (contradiction detection by a
model is optional and never gates).

**Design rules that shaped the kit.** A frontmatter contract; CI re-runs every deterministic check; loop
prevention; generated indexes and a union-merged log; no model call when nothing is stale; section edits
only; read-only human and process pages; managed blocks in shared files; instruction files under 200 lines
with knowledge in the wiki; every claim cites code, never another wiki page; `draft` on creation with no
automatic promotion; diff plus code only, untrusted input in delimited blocks, hidden Unicode stripped; no
deploy secrets or egress, explicit tool deny lists, never `--allow-all`; secret scan and access-controlled
Pages; budgets and debounce; runtime and token logging; a pinned model and versioned prompts. Empirical
lessons: instructions are followed, overviews are not; negative constraints beat positive style directives;
record why each rule exists; a stale wiki is worse than none; agents cannot detect their own staleness, so
lint must be deterministic; dependency-ordered generation (leaves before overviews) raises truthfulness.

**Adopted practices.** Per-page `sources` plus `last_verified_commit`; the citation microformat; licensed
refusal ("the wiki contains no established statement on this", never synthesised from weak matches, never
filed back); contradictions as first-class artifacts (replace the statement and record what was superseded);
a two-phase bootstrap with an explicit stop, the negative-space question (what deliberately gets no page)
and the three least-understood places; "librarian, not developer"; anti-slop rules (150–400 words per
module page, code blocks of at most ten lines, empty sections omitted, only affected sections touched);
query write-back only on approval; lint closers (three repairs with the best effort-to-value ratio, three
questions the wiki cannot answer). From the OpenWiki pattern: a brief compiled into `conventions.md`
(glossary table, fixed heading order per type) before any page is written, the **Needs confirmation** token
("never infer topic, caller, authorization, ordering or idempotency from naming alone"), grounded Mermaid
with a one-line caption only, a per-page manifest with hashes, partial progress committed on failure, and
GitLab parallel deployments (`pages.path_prefix` per branch, expiring dev previews, environment URLs).

**Publishing.** Quartz v5 is fetched at a pinned ref (core is not on npm), dependencies come from the
upstream lockfile, plugins from a committed `quartz.lock.json`, the wiki is copied into `content/`, and
`build.sh` runs identically in CI and locally. Known sub-path caveats are handled by `--baseDir` plus a
rewritten `baseUrl`, verified by the link checker in the test-suite. Pages access control ("only project
members") is available on the Free tier; parallel deployments need Premium or Ultimate.

## Decisions

### Taken with the owner (2026-09-07)

| Topic | Decision |
|---|---|
| Publishing scope | Per-repo only. Each repo publishes its own `wiki/` with Quartz v5 to its own GitLab Pages, per branch. Stay hub-compatible (frontmatter, `catalog.yaml`, relative links) but build no hub. |
| Project instructions | `wiki/instructions.md`: a well-designed, project-agnostic default that covers every angle, clearly sectioned so a user can adjust it (must-include concepts, flows, audiences, exclusions). Excluded from the published site. |
| Bootstrap execution | Plan interactively, populate in fresh sessions. `/wiki-init` does Q&A + confirmations, writes `wiki/instructions.md` + a cluster plan, gets approval. Population runs one cluster per fresh `copilot -p --no-ask-user` session via a driver script: bounded context, lint-verified, committed per cluster, resumable. |
| Fact generators | Generic baseline: inventory/module tree, symbol index (Python `ast`; JS/TS/Go/Java regex), dependency manifests, git changelog, ADR/decisions index, CODEOWNERS, API/event pages from OpenAPI/AsyncAPI when configured. Everything else is narrative. |
| Folder | `dot_github_ours/` at the Research repo root = the future agent repository root. |

### Taken during design

| Topic | Decision | Why |
|---|---|---|
| Scripts home | ONE directory: `.github/skills/wiki-maintain/{scripts,references,hooks}/`. `wiki-maintain/SKILL.md` is a toolbox reference (`user-invocable: false`). User skills `wiki-init`, `wiki-update`, `wiki-page`, `wiki-query`, `wiki-lint` are thin procedures calling those scripts. | Stdlib scripts importing each other need one home; skill dirs are auto-discovered by Copilot. |
| Config | JSON at fixed path `.github/wiki.config.json` (`wiki_dir` inside it). | Stdlib has no YAML; `tomllib` is read-only and 3.11+; hooks/CI must find config before knowing `wiki_dir`; nothing new at repo root. |
| Volatile run state | `$(git rev-parse --git-dir)/wiki/` (`run.json`, lock, logs, guard log, stop-retry counters). Committed state: `wiki/.manifest.json`, `wiki/.wiki-plan.json` (plan + per-cluster status). | Never published, never in `git status`, resumable across machines via the committed plan. |
| Who commits | Scripts (`run.py`, `bootstrap.py`) commit after the stop gate passes. The model is denied every git write command. | The original design had the agent commit; committing from the scripts lets the stop gate run before the commit. |
| Guard semantics | Two modes. Wiki mode (`WIKI_RUN=1` or a claimed `run.json`): confine writes to the wiki dir, whitelist shell, meter reads, gate the stop. Passive mode (any other Copilot session in the repo): deny only hand-edits of process-generated wiki files. Pass = `{}`; never emit `allow`. Unhandled error: exit 2 (deny) in wiki mode, `{}` in passive. | Hooks fire in every session in the repo; auto-approving developers' tool calls is unacceptable. |
| Success judgement | Working-tree diff confined to `wiki/` + `lint --all` clean + `backlinks --check` clean + marker `.git/wiki/verified` written by `stop_gate.py` + the model's final line `WIKI-RUN-RESULT: {…}`. Never the exit code. | CLI exit codes are undocumented. |
| Quartz install | Pinned git fetch of `jackyzha0/quartz` at `WIKI_QUARTZ_REF` (default `v5.0.0`; release process pins a tested SHA), `npm ci` on upstream lockfile, committed `quartz.lock.json` for plugins. Site files in `.gitlab/wiki-site/`; build dir `.wiki-build/` gitignored; `wiki/` copied into `content/`. | Quartz core is not on npm (404 verified). Content dir is fixed to `<project>/content`. |
| CI include | `.gitlab/ci/wiki.gitlab-ci.yml`, jobs in stage `.post` with `needs: []`; `pages:` keyword with `publish`; `path_prefix` only on staging/preview jobs; literals for branch settings; `expire_in: never` for staging. Minimum GitLab 17.9 (17.11 for variable expiry). | `include` cannot merge `stages`; `.post` exists everywhere; Free tier never sees Premium keys. |
| Python | ≥3.10 stdlib only; PyYAML optional (CI check only). | Runs on any dev machine and CI image. |
| Agent auto-selection | `disable-model-invocation: true`; explicit `--agent`/`/agent` or skills. Description still carries use/do-not-use triggers. | Wiki write sessions need run context and a pinned model. |
| Model pin | Not in frontmatter; `models.bootstrap` / `models.incremental` in config, passed with `--model` by every launcher. | Per-repo, per-phase pins. |

### Installer and CI integration specifics (this track)

| Topic | Decision | Why |
|---|---|---|
| `.gitlab-ci.yml` edits | Text-level, never re-serialised: one entry added in whatever include form the file already uses (`none`, `list`, `scalar`, `mapping`, `flow`); the form is recorded in `kit.ci_include_form`; `remove` reverts byte-for-byte; `apply` refuses to write when its own edit is not reversible. | No YAML library in the stdlib; a reformatted pipeline file is unreviewable. |
| Kit-file ownership | sha256 per installed kit file in `kit.files`; `--upgrade` replaces only files whose sha still matches; `ci_integrate.py apply` re-records the CI file it rewrites. | Distinguish "kit changed" from "user changed" without a VCS of our own. |
| Hooks | Trampolines in `.git/hooks` chain a pre-existing hook (`<name>.local`) and the committed body under `.github/skills/wiki-maintain/hooks/`; nothing is written when `core.hooksPath` is set. | Kit upgrades never need a hook reinstall; hook managers keep ownership of their directory. |
| Uninstall | Removes what the sha record proves is ours; keeps `wiki/` and the config answers. | An uninstall must never destroy the wiki or the init answers. |

## Assumptions and open items (confirm during the manual Copilot checks)

1. Exact `toolName` values and whether `{}` counts as "no decision" for `preToolUse`: learned from README check (2); until then no `matcher`.
2. Whether `/wiki-page <id>` inside `-p` text invokes the skill; prompts also name the skill in prose.
3. `stop_hook_active` semantics (set on retry vs every stop); the counter file makes the gate correct either way.
4. `--output-format=json` usage fields are undocumented; token metrics are best-effort (`null` when absent).
5. `npx quartz plugin install` honouring a committed `quartz.lock.json` exactly; plugin names/options verified only by the build test (fix against `quartz.config.default.yaml` if needed).
6. `.post` + `needs: []` starts immediately (documented for `needs: []` generally); worst case is timing.
7. Windows: `nohup … &` detachment from an MSYS hook and winget install path unverified.
8. `GIT_DEPTH: 0` costs a full clone on big repos; alternative is making `facts.py --check` tolerate shallow history.
9. The changelog page carries sanitised commit subjects (`audience: [dev]`, never in context packs); tighten to hashes+dates if the owner wants it airtight.
10. In-place runs read the developer's working tree while staleness is computed against HEAD; `isolation: worktree` is the fix (default for `branch-and-mr`).
11. `git commit --trailer` needs git ≥2.32 (fallback: trailer in the message file — what `wikilib.gitio.commit` does).
12. `path_prefix` must not equal an existing site folder (e.g. a `docs` branch vs a `docs/` folder): `ci_integrate.py detect` warns when a remote branch slug equals a top-level wiki folder.
13. (this track) `glab ci lint` posts the pipeline to the server, which resolves `include: local` against the pushed repository: before the include file is pushed the server-side lint is inconclusive and `check` falls through to PyYAML/structural.
14. (this track) GitLab accepts a plain string item in an `include` list (the `scalar` form is converted to `- <original scalar>` plus our entry rather than guessing `local:`/`remote:`).
