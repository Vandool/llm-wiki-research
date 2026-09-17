---
id: ADR-06
title: "OpenWiki (LangChain's open-source LLM-wiki implementation) as the wiki engine"
status: candidate        # candidate | recommended | rejected | superseded (changed by decision, not by researcher)
date: 2026-09-02
researcher: researcher-adr-06
fit_score: 6        # overall fit against ../requirements.md, justified in section 12
confidence: medium   # how well the key claims are verified against fetched sources
requirement_ratings: {R1: "🟡", R2: "🟡", R3: "🟡", R4: "🟡", R5: "🟡", R6: "🟡", R7: "🟡", R8: "🟡"}   # same symbols as section 5
tags: [openwiki, langchain, deep-agents, okf, grounded-claims, copilot-provider, copilot-cli-host, gitlab-ci, generator, resumable-page-jobs, licence-question]
---

# ADR-06: OpenWiki (LangChain's open-source LLM-wiki implementation) as the wiki engine

<!--
Uniform template for all approach ADRs in llm-wiki/approaches/.
Keep ALL headings, in this order, with these numbers. Add sub-sections freely.
Target length: 250-600 lines. Prefer tables and short paragraphs.
Mark unverified claims with ❓ and say what would verify them.
Never invent product features, URLs, or paper titles; if a search finds nothing, say so.
-->

## 1. Summary

OpenWiki is LangChain's MIT-licensed CLI (`npm install -g openwiki`, v0.5.0 on 2026-09-01) that reads a code repository and writes and maintains an `openwiki/` directory of Markdown pages in Google's Open Knowledge Format v0.2, each factual page backed by "grounded Claims" that cite exact code ranges (`repo://src/server.ts#L40-L82`) and are re-checked on `--update` [S1][S2][S5]. It is built on LangChain's Deep Agents harness, ships thirteen model providers including a `copilot` provider that calls `https://api.githubcopilot.com` with the OAuth token of a `gh auth login` session (no API key), and ships a GitLab CI example that runs `openwiki code --update --print` and opens an MR [S1][S6][S9]. Maturity as of 2026-09: 16k stars, first public release July 2026, weekly releases, one visible core maintainer, open issues on unbounded cost variance and monorepo support [S8][S22][S24]. **Verdict for us:** the most complete off-the-shelf generator for the code-repository variant of Karpathy's pattern, and the only one with both a Copilot provider and a GitLab example; but its Copilot path is a *third-party client* on GitHub's Copilot inference API whose licence status GitHub's current terms neither permit nor forbid explicitly (❓, must be confirmed in writing), the licence-clean alternative (driving OpenWiki's MCP lifecycle from Copilot CLI) is an unshipped adapter, and code mode still hard-codes GitHub Actions artefacts on GitLab repositories. Fit 6/10; worth a two-spike evaluation, not a straight adoption.

## 2. Context

The company wants an LLM-maintained repository wiki for agents and humans (R1) that serves as the context layer for the whole AI pipeline (R2) across many frontend and backend repositories (R3), bootstrapped once and then kept current by hook- or push-triggered agents that commit their result (R4), with a form-based retry/instruction channel (R5), under two hard constraints: only GitHub Copilot as the model, no API keys (R6), and GitLab as the host (R7); a Quartz site on GitLab Pages is a nice-to-have (R8).

OpenWiki is on the table because the landscape survey identified it as "the only generator found that lists GitHub Copilot as a provider *and* ships a GitLab CI example" (`../background/landscape.md` §4–§5) and because it implements several design rules from `../background/problems-and-fixes.md` out of the box: evidence-based refresh (P01), citations to code (P02/D12), managed blocks in AGENTS.md (P04/D10), deterministic `index.md` (P05/D06), no-op detection before model calls (P08/D07), resumable page jobs (P17). The questions this ADR answers are the ones the survey left open: how exactly the Copilot provider authenticates and what GitHub's terms say about it; whether it can run from GitLab CI end to end; and how far it goes on multi-repo, PO-facing content and the instruction channel.

## 3. The approach

### 3.1 Origin and provenance

| Item | Verified fact | Src |
|---|---|---|
| Project | `langchain-ai/openwiki` — "The self-maintaining wiki. Built for agents, explored by humans." npm package `openwiki`, bin `openwiki`, Node ≥ 22 | [S1][S7] |
| Owner / maintainer | LangChain (GitHub org `langchain-ai`); the Copilot provider PR was reviewed and merged by Colin Francis (`colifran`) on 2026-07-27 | [S1][S15] |
| Licence | MIT (package.json `license: MIT`; LICENSE "Copyright (c) 2026") | [S7][BG-L] |
| Dependencies | `deepagents` 1.12.0 (Deep Agents JS, MIT, "works with tool-calling chat models"), `langchain` ^1.5, `@langchain/openai`/`anthropic`/`aws`/`google`/`openrouter`, `@langchain/langgraph-checkpoint-sqlite`, `@modelcontextprotocol/sdk`, `langsmith`. No tree-sitter, no simple-git | [S7][S31] |
| First appearance | Hacker News 2026-07-01, 96 points; the LangChain blog URL (`langchain.com/blog/openwiki`, also via `blog.langchain.com/openwiki`) returns 404, so the official announcement post could not be opened ❓ | [S23][S32] |
| Releases | v0.2.5 (2026-07-31, `.openwikiignore`), v0.3.0 (08-04, link validation), v0.3.3 (08-14, custom MCP connector, LEDGER benchmark), **v0.4.0 (08-25, OKF v0.2 + grounded claims + resumable page-job lifecycle)**, **v0.5.0 (09-01, durable page-level resumability across local/CI/host runs, Cursor integration, "GitHub Copilot streaming for non-GPT-5 models" fix)** | [S8] |
| Size / activity | 16,000+ stars, 1.2k forks; ~30 issues/PRs touching Copilot, GitLab, cost and monorepos opened between July and September 2026; many community PRs wait for one maintainer's review | [S1][S21][S22][S24] |
| Name collisions | `dcouple/openwiki` (Dcouple, Inc.): a Docker/SSH/tmux setup in which Claude Code agents curate a private Obsidian-style vault and publish a public Astro site; licence "TBD", 0 stars, unrelated to LangChain [S33]. `barvhaim/pi-openwiki`: a port of LangChain's OpenWiki as an extension for the Pi coding-agent harness; MIT, 8 stars, 6 commits [S34]. |

### 3.2 How it works (architecture)

**Components.** A TypeScript CLI (`src/cli`), a Deep Agents agent with code-mode prompts (`src/agent`), a repository ingestion layer (`src/ingestion`), a page-job engine (`src/generation`: `page-jobs.ts`, `page-manifest.ts`, `run-state.ts`), claims and OKF modules (`src/claims`, `src/okf`), a Mermaid validator, a wiki-link validator, an MCP server that exposes the same page-job lifecycle to *host* coding agents (`src/integrations/mcp`), and a graph visualiser [S29].

**Inputs read from a code repository** (code mode): the filesystem tree and files, filtered by `.openwikiignore` (which "filters filesystem discovery and restricts shell execute so ignored paths stay out of the run"); git commit messages and history (the CI examples set `GIT_DEPTH: "0"` because a shallow clone hides "the commit it last documented"); tests "as behavioral evidence"; the README; and the existing wiki [S3][S9][S30]. There is no parser/AST layer; the agent reads files with tools. The code-mode prompt forbids inventing "files, modules, APIs, business rules, or behavior" and requires grounding "every important claim in source files, tests, existing docs, or git evidence" [S14].

**Page-job lifecycle** (since v0.4.0): `begin → submit_plan → next_page → submit_page … → finish`. `openwiki/.run.json` checkpoints the ordered page queue during a run; `openwiki/.page-manifest.json` records per-page progress and source checkpoints; a clean finish deletes `.run.json`; an interrupted run resumes [S3][S9]. Since PR #688 the author fans out to sub-agents per page and the plan is validated mechanically at submit time (internal reward metric 0.40 vs 0.19 for v0.3.0) [S24].

**Grounded Claims.** Each factual page has a sidecar in `openwiki/.claims/` listing "material propositions" with evidence URIs and the evidence version observed. A page receives `verified: {by: openwiki/<version>, at: …}` "only after a successful page submission reconciles a non-empty complete Claims set". `--update` is evidence-based: stale claims force work even if the planner omits a page; a clean update "skips model work and leaves wiki content untouched while refreshing `.last-update.json`" [S3][S9][BG-L].

**Where the LLM runs / who authenticates.** OpenWiki itself calls the provider (OpenAI-compatible HTTP for Copilot) with credentials from env vars or `~/.openwiki/.env`; in *host-driven* runs (Codex, Claude Code, OpenCode, Cursor) the host agent's own model and session do the writing and OpenWiki only validates and persists through MCP tools ("use the agent's authenticated session") [S4][S6][S27].

```
 developer push / schedule / "Run pipeline" form (R5)
            │
            ▼
 GitLab CI job  (node:22, npm i -g openwiki)
            │
   ┌────────┴─────────────────────────────────────────┐
   │ Route A: openwiki code --update --print          │  provider=copilot
   │   Deep Agents loop ──HTTP──► api.githubcopilot.com│  token = gho_… from `gh auth login`
   │                                                   │
   │ Route B: copilot -p "<skill prompt>"              │  Copilot CLI = model runtime
   │   Copilot CLI ──MCP(stdio)──► openwiki mcp --host │  auth = COPILOT_GITHUB_TOKEN
   └────────┬─────────────────────────────────────────┘
            ▼
 writes openwiki/**  (OKF v0.2 pages, .claims/, .page-manifest.json, index.md)
 refreshes <!-- OPENWIKI:START/END --> block in AGENTS.md / CLAUDE.md
            │
            ▼
 branch openwiki/update-<pipeline> ──► MR (REST API) ──► human review ──► merge
            │
            ▼
 wiki-hub project: collect openwiki/ of every repo ──► Quartz ──► GitLab Pages (R8)
```

### 3.3 Wiki content model it implies

| Element | OpenWiki behaviour | Src |
|---|---|---|
| Directory | `openwiki/` at repo root; pages such as quickstart, architecture/overview, source map, operations; sub-directories allowed, each with a generated `index.md` | [S3][S14][S28] |
| Front matter | OKF v0.2: `type` required; `title`, `description`, `resource`, `tags` recommended; `generated: {by: openwiki/<version>, at}` stamped by the tool (agent must not author it); `sources` reconciled from claims while "preserving independently authored sources"; `verified` after claim reconciliation; optional `status`, `stale_after`; root `index.md` carries `okf_version: "0.2"` | [S3][S14][S28] |
| Index / log | `index.md` per directory is "generated deterministically after the run" from `title`/`description` (agent is told "Do not create or edit them yourself") — this is D06 as shipped; `log.md` is reserved scaffolding, excluded from indexing | [S14][S28] |
| Claims | `openwiki/.claims/` sidecars; evidence `repo://path#Lx-Ly` plus version; cover "behavior, responsibilities, architecture, data flow, invariants, failure semantics, configuration, and security boundaries" | [S3] |
| Human-owned | `openwiki/INSTRUCTIONS.md` — "User-authored brief for scope and priorities. OpenWiki reads it on init and update", never rewritten by routine runs; everything outside the managed block in `AGENTS.md`/`CLAUDE.md` | [S3][S14] |
| Agent pointer | `<!-- OPENWIKI:START --> … <!-- OPENWIKI:END -->` block in `AGENTS.md` and `CLAUDE.md` "that tells coding agents when to consult the wiki"; Copilot reads both files (landscape §8) | [S3][BG-L] |
| Audience | README: primary audience is agents; the code-mode prompt says "for both humans and future agents"; no PO/non-technical track exists — it must be requested through `INSTRUCTIONS.md` (P14, D20) | [S1][S14][BG-P] |
| Diagrams | Mermaid where it "clarif[ies] a concept better than prose"; invalid diagrams are downgraded to a `text` fence and repaired on a later `--update` (needs `mermaid` + `jsdom` installed) | [S3] |
| Links | Internal links validated after generation (v0.3.0); prompt emits relative links since PR #608 | [S8][S24] |
| Languages | `--language <BCP-47>` (e.g. `ko`, `pt-BR`) | [S4] |

### 3.4 Trigger and automation model

| Trigger | Shipped? | Notes | Src |
|---|---|---|---|
| Manual CLI | ✅ `openwiki --init`, `openwiki --update`, `openwiki code --update --print` (non-TTY runs are routed through the print path since PR #153) | Also interactive chat and `-p "<question>"` one-shot | [S4][S22][S30] |
| GitHub Actions | ✅ `examples/openwiki-update.yml` (cron + manual dispatch, PR via `peter-evans/create-pull-request`) | — | [S9][BG-L] |
| **GitLab CI** | ✅ `examples/openwiki-update.gitlab-ci.yml`: `image: node:22`, `rules` on `schedule` or `web`, `npm install --global openwiki mermaid@11.16.0 jsdom@29.1.1`, `openwiki code --update --print`, `git diff --quiet` no-op exit, branch `openwiki/update-${CI_PIPELINE_ID}`, push with `oauth2:${OPENWIKI_GITLAB_TOKEN}` in the URL, MR via `${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests`; provider OpenRouter by default | Token-in-URL flagged as a secret-leak risk (issue #600, open). Note the example `git add`s `.github/workflows/openwiki-update.yml` — see 3.4 "GitHub hard-coding" | [S9][S21] |
| Bitbucket | ✅ example | — | [S9] |
| Git hooks | ❌ none shipped | A `post-commit`/`pre-push` hook can call the CLI, but D02 says hooks must not call the model; use hooks only to enqueue (section 4) | [BG-P] |
| Scheduling | CI cron; macOS `launchd` cron only for *personal-mode connectors* (`openwiki cron …`), Windows Task Scheduler backend in an open PR | Not relevant to code mode | [S4][S21] |
| Host-driven | ✅ for Codex, Claude Code, OpenCode, Cursor via `openwiki integrations install <host>`; ❌ no Copilot host | See 4.3 for the Copilot adapter | [S6][S27] |

**GitHub hard-coding on GitLab (issue #341, open; fix PR #342 unmerged).** `ensureCodeModeRepoSetup()` "unconditionally writes `.github/workflows/openwiki-update.yml` on every run, even for non-GitHub repos", and the managed block says "The scheduled OpenWiki **GitHub Actions workflow** refreshes the repository wiki"; on GitLab the `.github` directory "reappear[s] after every `openwiki code --update` run" and manual corrections are reverted [S19]. Workaround: delete the file before committing and accept the wrong sentence, or carry PR #342.

**Loop prevention / concurrency / conflicts.** Not addressed by OpenWiki; the example relies on schedule/web triggers so a bot push never starts another run. For push-triggered runs apply D04 (`[skip ci]`/`-o ci.skip`, bot-exclusion `workflow: rules`) and `resource_group` to serialise. The bot never touches the default branch (D05) — the example already opens an MR. Because `index.md` is generated and pages are one-concept-per-file, merge conflicts are limited to pages whose evidence changed (P05).

### 3.5 Human retry / instruction channel ("the form")

OpenWiki has two user-facing instruction inputs: the durable `openwiki/INSTRUCTIONS.md` scope brief (read on every init/update, editable "yourself, or ask OpenWiki in chat to change it") and the one-shot chat/`-p` message [S3][S4]. Neither is a form. The form is GitLab's: a manual pipeline with prefilled variables (`description`, `options`, `value`) renders as a dropdown/text form on **Build › Pipelines › New pipeline** (no tier requirement stated) [S37]. The job appends the free text to `INSTRUCTIONS.md` under a dated "Operator instructions" heading and runs `--update`; a plain re-run with empty text is the "retry" (section 4.4). ❓ Whether `openwiki code --update --message "<text>"` (the `--message` option exists on `openwiki code` in `commands.ts`) injects a one-shot instruction into an update run was not verified; the `INSTRUCTIONS.md` append is the documented path [S30].

### 3.6 Multi-repo / microservice fit

- **Per repository** only. Code mode documents "the current repository"; the prompt forbids "broad commands that search outside the target repository" [S14]. Nothing federates wikis across repos; `openwiki visualize` serves one wiki at a time [S5].
- **Monorepos**: issue #162 (8 reactions) and PR #439 ("tree of wikis", nested `<subproject>/openwiki/`, auto-detects pnpm/npm/yarn workspaces, Cargo, `go.work`, uv, Gradle, Maven, .NET, Bazel; "Updates do not cascade across subprojects") are open, not merged; the PR "addresses monorepos only, not multi-repository scenarios" [S20].
- **Cross-repo knowledge (P23)**: has to be built around OpenWiki — a hub project that collects every repo's `openwiki/` and adds contract/event/ownership pages built deterministically from OpenAPI/AsyncAPI files and CODEOWNERS (D06), optionally by running OpenWiki over a `platform-contracts` repository that holds those files. OKF claims can only cite `repo://` inside one repository, so cross-repo claims have no evidence link ❓ (OKF spec is silent on multi-bundle graphs, landscape §6).
- **Future autonomous agents (R3)**: strong. Output is OKF (readable by any OKF consumer, see ADR-07), every claim has a code citation and version, and the lifecycle is exposed as MCP tools so a future agent platform can be the host [S27][S28].

### 3.7 Publishing / UI

- `openwiki/` is plain Markdown with YAML front matter and relative links, which Quartz renders; the hub site aggregates all repos (identical Quartz-on-GitLab-Pages recipe to ADR-07/08/10: `image: node:24`, `npx quartz plugin install`, `npx quartz build`, artifact `public`; Pages available on Free/Premium/Ultimate and GitLab.com/Self-Managed/Dedicated, with access control for private sites) [S35][S36]. Exclude `openwiki/.claims/**`, `.page-manifest.json`, `.last-update.json`, `.run.json` from the Quartz content (`ignorePatterns`) ❓ syntax to verify in the spike.
- Alternative: `openwiki visualize --export <dir>` produces `index.html, client.js, client-lib.js, styles.css, graph.json` — a graph + reader UI — but "loads its graph, Markdown, and diagram libraries from a public CDN, so an internet connection is required"; usable as a per-repo Pages artefact, not as the aggregate site [S5].

## 4. Concrete implementation sketch for our environment

Assumptions relied on (from `../requirements.md`): developers can install Node 22 and `gh`; CI runners have outbound internet; a GitLab bot account with project/group access tokens exists; a GitHub account with a Copilot seat can be assigned to a bot **only if licence terms allow it** (unverified — section 11).

### 4.1 Directory layout (per service repository) and hub

```
service-repo/
├── AGENTS.md                      # human-owned rules + <!-- OPENWIKI:START/END --> block (D10, D11)
├── CLAUDE.md                      # same block (optional; Copilot reads either)
├── .openwikiignore                # vendored/, generated/, fixtures/**, *.pem, .env*, *.pptx, media (P10, issue #335)
├── .gitlab-ci.yml                 # include: project: platform/wiki-ci, file: openwiki.gitlab-ci.yml (D18)
├── .github/mcp.json               # Route B only: OpenWiki MCP server for Copilot CLI (4.3)
├── .agents/skills/openwiki/       # Route B only: SKILL.md written by `openwiki integrations install codex --project .`
└── openwiki/
    ├── INSTRUCTIONS.md            # human-owned scope brief + appended operator instructions (R5)
    ├── index.md                   # generated per directory; root carries okf_version: "0.2"
    ├── log.md
    ├── quickstart.md, architecture.md, ...   # OKF v0.2 concept pages
    ├── .claims/                   # evidence sidecars — commit them
    ├── .page-manifest.json        # commit — resumability across CI runs (v0.5.0)
    ├── .last-update.json          # commit — no-op detection
    └── .run.json                  # only present while a run is interrupted

platform-wiki-hub/
├── .gitlab-ci.yml                 # nightly + trigger: fetch openwiki/ of each repo → content/<repo>/ → quartz build → pages
├── quartz.config.ts               # ignorePatterns for .claims/ and dot-files ❓
└── content/
    ├── index.md                   # human-owned landing page; PO pages (owner: human, D20)
    └── contracts/, events/, owners/   # deterministic cross-repo pages (D06, P23)
```

`git add openwiki` (as in the shipped example) stages the dot-files too, which is what makes v0.5.0's cross-run resumability work on ephemeral runners [S9][S3].

### 4.2 Route A — OpenWiki's native `copilot` provider from GitLab CI

What the provider does (verified in source): `OPENWIKI_PROVIDER=copilot`; base URL `https://api.githubcopilot.com` (override `COPILOT_BASE_URL`; the `gh` hostname is derived from it, "falling back to github.com when unset"); GPT-5-family models go to `/responses`, all others to `/chat/completions`; auth method `external-cli` → adapter `github-cli` runs `gh auth token --hostname <host>` on every run ("The token itself never leaves the CLI's own credential store"); tokens matching `^(ghp_|github_pat_)` are rejected with *"The GitHub Copilot API does not accept Personal Access Tokens. Authenticate with 'gh auth login' using a Copilot-enabled account, or set COPILOT_API_KEY to a GitHub OAuth token."*; in CI, `COPILOT_API_KEY` holds the OAuth token [S6][S13][S15][S16][S17]. Model catalogue in `constants.ts`: `gpt-5.6-terra|luna|sol`, `gpt-5.5`, `gpt-5.4-mini`, `claude-opus-5`, `claude-opus-4.8`, `claude-sonnet-5`, `claude-sonnet-4.6`, `claude-haiku-4.5`, `claude-fable-5`, `gemini-2.5-pro` [S17]. ❓ I did not locate where request headers (e.g. an integration id) are set; a token-exchange call is not in the auth adapter.

```yaml
# platform/wiki-ci/openwiki.gitlab-ci.yml  (included by every service repo)
openwiki_update:
  image: node:22
  stage: docs
  resource_group: openwiki-$CI_PROJECT_ID          # one run at a time per repo
  rules:
    - if: '$GITLAB_USER_LOGIN == "wiki-bot"'
      when: never                                  # D04: bot commits never re-trigger
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
    - if: '$CI_PIPELINE_SOURCE == "web"'           # R5 form (4.4)
  variables:
    GIT_DEPTH: "0"                                 # full history, as in the shipped example
    OPENWIKI_PROVIDER: copilot
    OPENWIKI_MODEL_ID: gpt-5.4-mini                # pin (D21); must be enabled by the org "Copilot Features & Models" policy
    COPILOT_API_KEY: $WIKI_COPILOT_OAUTH_TOKEN     # masked+protected CI var: gho_… from `gh auth token` — licence ❓ (section 11)
    OPENWIKI_TELEMETRY_DISABLED: "1"
    # deliberately NOT set: LANGCHAIN_TRACING_V2 / LANGSMITH_API_KEY (third-party SaaS, R6)
  before_script:
    - npm install --global openwiki@0.5.0 mermaid@11.16.0 jsdom@29.1.1
    - git config user.name "wiki-bot" && git config user.email "wiki-bot@example.com"
  script:
    - |
      if [ -n "$WIKI_INSTRUCTIONS" ]; then
        printf '\n## Operator instructions (%s, pipeline %s)\n\n%s\n' "$(date -I)" "$CI_PIPELINE_ID" "$WIKI_INSTRUCTIONS" >> openwiki/INSTRUCTIONS.md
      fi
    - openwiki code --update --print
    - rm -f .github/workflows/openwiki-update.yml   # issue #341 workaround (GitHub file written unconditionally)
    - if git diff --quiet -- openwiki AGENTS.md CLAUDE.md; then echo "wiki up to date"; exit 0; fi
    - scripts/wiki-guard.sh                         # D09: fail if the diff touches anything outside openwiki/, AGENTS.md, CLAUDE.md
    - git checkout -b "openwiki/update-${CI_PIPELINE_ID}"
    - git add openwiki AGENTS.md CLAUDE.md
    - git commit -m "docs(wiki): update OpenWiki [skip ci]"
    - git -c credential.helper='!f(){ echo username=oauth2; echo password=$OPENWIKI_GITLAB_TOKEN; }; f' push -o ci.skip origin "openwiki/update-${CI_PIPELINE_ID}"   # no token in URL (issue #600)
    - |
      curl --fail --request POST --header "PRIVATE-TOKEN: ${OPENWIKI_GITLAB_TOKEN}" \
        --form "source_branch=openwiki/update-${CI_PIPELINE_ID}" --form "target_branch=${CI_DEFAULT_BRANCH}" \
        --form "title=docs(wiki): update OpenWiki" --form "remove_source_branch=true" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests"
```

Everything above except `resource_group`, the `workflow`-style bot rule, the `INSTRUCTIONS.md` append, the guard script and the credential helper is taken from the shipped example [S9]. ❓ `OPENWIKI_GITLAB_TOKEN` scopes are not documented; `api` + `write_repository` on a project access token is the obvious choice. ❓ Whether `[skip ci]` plus a REST-created MR still yields an MR pipeline for the docs-only diff depends on the repo's MR-pipeline config (fine either way, D03).

### 4.3 Route B — Copilot CLI as the *host* (adapter needed)

OpenWiki's host mode is the licence-cleanest way to satisfy R6, because the only thing that talks to GitHub is GitHub's own Copilot CLI. The lifecycle is exposed by `openwiki mcp --host <id>` (internal subcommand; `--host` accepts "1-64 lowercase letters, digits, or hyphens") with tools `openwiki_begin{root, mode: init|update, language?, force?}`, `openwiki_submit_plan{runId, pages, deletePages?}`, `openwiki_next_page{runId}`, `openwiki_inspect_page_claims{runId, jobId}`, `openwiki_submit_page{runId, jobId, claims?, confirmedClaimIds?, retractedClaimIds?}`, `openwiki_finish` [S26][S27][S30]. The bundled `SKILL.md` (agentskills.io format, `name: openwiki`) walks the host through `git rev-parse --show-toplevel` → begin → plan → page loop → finish and requires OKF front matter and `repo://…#Lx-Ly` claims per page [S25]. The registry knows only `codex`, `claude`, `opencode`, `cursor` — no Copilot host [S27]. The adapter is therefore configuration, not code:

```bash
# one-off per repo (commit the results)
openwiki integrations install codex --project .      # writes .agents/skills/openwiki/SKILL.md (+ .codex/config.toml, unused)
cat > .github/mcp.json <<'JSON'
{ "openwiki": { "type": "local", "command": "openwiki", "args": ["mcp", "--host", "copilot"], "tools": ["*"] } }
JSON
```

Copilot CLI reads skills from `.agents/skills/` and MCP servers from `.github/mcp.json` / `.mcp.json` / `~/.copilot/mcp-config.json` [S38][BG-L §8]. The CI job then replaces the `openwiki code --update --print` line with:

```bash
export COPILOT_GITHUB_TOKEN="$WIKI_COPILOT_TOKEN"     # fine-grained PAT ("Copilot Requests", personal account) of the bot seat, or a GitHub App installation token (4.5)
npm install --global @github/copilot
copilot -p "Update this repository's OpenWiki for changes since its last successful run. Follow the openwiki skill exactly and stop only after openwiki_finish returns complete." \
  --model gpt-5.4-mini --no-ask-user -s \
  --allow-tool='openwiki' --allow-tool='write' --allow-tool='shell(git log)' --allow-tool='shell(git rev-parse)' \
  --deny-tool='shell(git push)' --deny-tool='shell(rm)'                 # D15  ❓ exact --allow-tool grammar for MCP tools
```

Flags `-p`, `--allow-tool`, `--deny-tool`, `--allow-all-tools`, `--agent`, `--model`, `--no-ask-user`, `-s`, `--add-dir` and env `COPILOT_GITHUB_TOKEN`/`COPILOT_MODEL` are documented [S39]. ❓ Open points for the spike: (a) whether `openwiki mcp --host copilot` accepts an unregistered host id or needs a one-line registry addition (upstream PR); (b) whether the MCP server needs any provider credential of its own in host mode (the code suggests not [S26]); (c) whether Copilot CLI's agent completes the multi-page loop reliably — the same lifecycle failed on Copilot-served `claude-sonnet-4.6` in Route A until v0.5.0 forced streaming (issue #731 → PR #744) [S18][S8].

### 4.4 The R5 form

```yaml
# in the included template
variables:
  WIKI_ACTION:
    value: "update"
    options: ["update", "rebuild", "instruct-only"]
    description: "update = incremental; rebuild = openwiki --init --force (re-plans every page, expensive); instruct-only = append instructions, no model run"
  WIKI_INSTRUCTIONS:
    value: ""
    description: "Free text for the wiki agent (Markdown). Appended to openwiki/INSTRUCTIONS.md with date and pipeline id. Leave empty for a plain re-run."
```

Prefilled variables with `description`/`options`/`value` render on the New pipeline form [S37]. The append is idempotent per pipeline id; the PO can use it for "explain the checkout flow for non-developers" (P14). ❓ `--init --force` semantics for a full rebuild are inferred from the `force?` field of `openwiki_begin`; verify.

### 4.5 Authentication options for R6, compared

| Option | Mechanism | Licence/billing status | Src |
|---|---|---|---|
| A1 developer-local | Each developer runs `openwiki code --update` before pushing; provider reuses their own `gh auth login` session and Copilot seat | Third-party client on the Copilot API (see 5/R6); billed to the developer's seat; no shared credential | [S6][S15] |
| A2 bot OAuth token in CI | `gh auth login` on a **machine account** with a Copilot Business seat; `gh auth token` stored as `COPILOT_API_KEY` | Machine accounts are permitted by the ToS; whether a machine account may hold a seat is ❓ (same open question as ADR-07/08); a *human's* `gho_` token in CI would violate "a single login may not be shared by multiple people" | [S10][S16] |
| B1 bot fine-grained PAT for Copilot CLI | `COPILOT_GITHUB_TOKEN` = fine-grained PAT that "Must be owned by your personal account (not an organization) with the Copilot Requests account permission"; classic PATs "Not supported" | Documented, first-party; credits "drawn from that user's Copilot seat entitlements"; GitHub warns PAT automation poses "operational and security risks for organizations" | [S11][S12] |
| B2 GitHub App installation token | Copilot SDK docs: for "Other CI Systems" create a GitHub App with Copilot permissions, install it on the org, mint installation tokens (`copilot_requests: write`, "requires All repositories access", expire after one hour), pass via `COPILOT_GITHUB_TOKEN`; "Usage is attributed and billed to the account that owns the GitHub App installation"; needs the org policy "Allow use of Copilot CLI billed to the organization" | Documented for Copilot CLI/SDK; **no seat needed** — organisation-billed; ❓ not verified on docs.github.com, and plan availability not stated | [S40] |

B2 is the only path that removes the bot-seat question entirely; it works only with Route B (Copilot CLI), not with OpenWiki's direct provider (installation tokens are not `gho_` OAuth tokens; acceptance by `api.githubcopilot.com` for a third-party client is ❓ and, per PR #192's finding on PATs, unlikely [S15]).

### 4.6 Local hooks and developer workflow (R4)

- `pre-push` hook (D02/D03): no model call; compare `openwiki/.last-update.json` and `.page-manifest.json` checkpoints with `HEAD` and print "wiki is N commits behind; run `openwiki code --update` or let CI do it". The CI job is the source of truth.
- Developers who want the wiki in their own MR run A1 locally (their seat, their diff visible in the MR). Route B locally is `copilot` interactive with the skill.
- Onboarding a repo (P16): add the `include:`, create `.openwikiignore`, write `openwiki/INSTRUCTIONS.md` (scope, PO section request, forbidden dirs), run the bootstrap pipeline manually with `WIKI_ACTION=rebuild`, review the MR (`confidence: unreviewed` semantics via OKF `status: draft` until reviewed, D13).

## 5. Requirements check

| ID | Requirement (short) | Rating | Evidence / notes |
|----|---------------------|--------|------------------|
| R1 | Dual audience (agents + devs + PO) | 🟡 | Pages are Markdown "for both humans and future agents" [S14] with quickstart/architecture/operations content and validated Mermaid [S3]; the README states agents are the primary audience [S1]; no PO track — must be requested via `INSTRUCTIONS.md` and kept human-owned (P14/D20). |
| R2 | Context layer for whole AI dev pipeline | 🟡 | AGENTS.md/CLAUDE.md managed block points every agent at the wiki (P12) [S3]; claims give verifiable citations (D12); but there is no retrieval/search tool for consumers (the MCP server exposes only the *authoring* lifecycle [S26]), pages are agent-planned rather than task-shaped, and `openwiki -p` answers questions only for humans at a terminal [S4]. |
| R3 | Multi-repo microservices, future autonomous agents | 🟡 | Per-repo only; monorepo support is an unmerged PR and explicitly not multi-repo [S20]; cross-repo pages must be built outside OpenWiki (3.6). Future-proofing is good: OKF v0.2 output, versioned claims, MCP lifecycle [S27][S28]. |
| R4 | Bootstrap once, dev-owned upkeep, hook-triggered auto-update | 🟡 | `--init`/`--update` with resumable page jobs and no-op detection [S3][S9]; push-triggered GitLab job + MR is a small change to the shipped example [S9]; no git hooks shipped and hooks must not call the model anyway (D02); `INSTRUCTIONS.md` is the developer-ownership handle. |
| R5 | Human retry / instructions via a form | 🟡 | GitLab prefilled-variable form [S37] feeding `INSTRUCTIONS.md` (documented input) [S3]; not a native OpenWiki feature; `--message` semantics ❓. |
| R6 | Copilot-only (no API keys, no direct model access) | 🟡 | Route A needs **no API key** and sends prompts only to GitHub's Copilot API [S6][S15], but it is a third-party client: GitHub's API already refuses PATs "for third-party integrations" [S15], the governing Generative AI Services Terms, ToS and AUP contain no clause permitting or prohibiting such clients ❓ [S10][S41][S42], and the AUP's "excessive automated bulk activity" clause plus documented abuse-detection warnings against automated third-party use [S42][S43][S44] make it a written-confirmation item (D22). Route B (Copilot CLI host) is first-party but requires an unverified adapter (4.3). Both LangSmith tracing and telemetry must be switched off. |
| R7 | GitLab, not GitHub | 🟡 | GitLab CI example works on GitLab.com and self-managed (uses `CI_SERVER_HOST`, REST v4) [S9]; but code mode writes `.github/workflows/openwiki-update.yml` unconditionally and the managed block claims a "GitHub Actions workflow" (issue #341 open) [S19]; token-in-URL push (issue #600) [S21]. Workarounds are one-liners. |
| R8 | UI on GitLab Pages (Quartz) | 🟡 | Output is Quartz-renderable Markdown with relative links; Quartz's GitLab Pages recipe and Pages availability on all tiers are documented [S35][S36]; aggregation and `.claims/` exclusion are ours to build; `visualize --export` depends on a public CDN [S5]. |

## 6. Pros

- **Most complete open implementation of the pattern for code**: grounded claims with versioned evidence, evidence-driven `--update`, deterministic per-directory `index.md`, managed AGENTS.md block, `.openwikiignore`, Mermaid and link validation, resumable page jobs that survive CI job limits (v0.5.0) [S3][S8][S28]. It implements D06, D07, D10, D12 and the P17 fix without custom code.
- **OKF v0.2 output** makes the wiki readable by any future OKF consumer and aligns with ADR-07 [S3][S28].
- **Copilot provider exists and is maintained** (PR #192 merged, streaming fix in v0.5.0, model-availability PR pending) [S15][S8][S18]; **GitLab CI example exists** [S9].
- **Keyless operation possible** in two ways (gh OAuth session; host-driven MCP lifecycle) [S6][S25].
- **Repository content is treated as untrusted evidence, not instructions** in the host protocol [S26] (P09 awareness); `.openwikiignore` also restricts shell execution to non-ignored paths [S3].
- MIT, TypeScript, small surface; forkable if LangChain loses interest.

## 7. Cons and risks

- **Licence grey zone for Route A (R6, P20)**: a third-party client on `api.githubcopilot.com`; GitHub's own docs describe Copilot CLI/SDK as the programmatic surfaces [S11][S40]; abuse-detection suspensions are reported by the community for automated third-party use [S43]. A negative answer from GitHub kills Route A outright.
- **Bot-seat question unchanged** (A2/B1) — same blocker as ADR-07/08; only B2 (GitHub App installation token) avoids it and B2 is ❓ and Route-B-only [S40].
- **Unbounded, non-deterministic cost**: 12× cost and 4.5× wall-time variance between identical `--init` runs (issue #51: $0.10 typical vs $10.71 worst path on a 390-file subproject); 10.1M tokens on a 47-file repo with `claude-sonnet-4-6` without completing (issue #696); no `--max-iterations`/budget flag [S22][S24] (P08, P19).
- **Copilot model policy interplay**: the hard-coded model list ignores org-disabled models until PR #763 lands; Business plans may not expose every listed model [S18][S17].
- **GitHub-centric code paths on GitLab** (issue #341) and secret-in-URL example (issue #600) [S19][S21].
- **Single-repo scope**: no multi-repo, monorepo PR unmerged [S20] (P23).
- **Single-maintainer bottleneck**: many substantive community PRs (#342, #439, #551, #608, #763) sit unreviewed [S20][S21][S24].
- **Wedged runs**: binary files poison the SQLite checkpoint so retries fail identically (issue #335); truncated tool calls end runs silently (issue #458) [S24].
- **Third-party SaaS creep**: LangSmith tracing is on in the shipped CI examples (`LANGCHAIN_TRACING_V2: "true"`) and telemetry is on by default — both must be disabled for R6 [S9][S13].
- **No PO track, no search tool, no evaluation harness** beyond an internal LEDGER benchmark [S8] (P14, P12, P15).

## 8. Known problems reported by practitioners, and fixes

| Problem (source) | Maps to | Fix / mitigation |
|---|---|---|
| "repeated `openwiki --init` runs vary ~12× in cost and ~4.5× in wall-time" because the agent picks delegate vs self-read strategies (issue #51, open, no maintainer reply) [S22] | P08, P19 | Pin a cheap model for routine updates (D21); set `OPENWIKI_MAX_OUTPUT_TOKENS`; separate bootstrap budget (D17); watch the Copilot cost-centre budget; consider carrying a `--max-iterations` patch. |
| ~10.1M tokens, two partial runs, credits exhausted on a 47-file repo (issue #696) [S24] | P08, P17 | Same as above; smaller `.openwikiignore`-scoped runs; enable prompt caching when upstream lands it. |
| Copilot-served `claude-sonnet-4.6` "exited without submit_plan" (issue #731) → fixed by forcing streaming for non-GPT-5 models (PR #744, v0.5.0) [S18][S8] | — | Use ≥ v0.5.0; prefer GPT-5-family ids on Copilot until Claude ids are re-validated. |
| Selected model not entitled / disabled by org policy (issues #490, #763) [S18] | P20 | Pick a model visible in the org's "Copilot Features & Models" policy; carry PR #763. |
| `.github/workflows/openwiki-update.yml` re-created on every run on GitLab; managed block says "GitHub Actions workflow" (issue #341) [S19] | P04, P11 | `rm -f` before commit (4.2); carry PR #342; do not hand-edit the block. |
| GitLab example pushes with the token in the URL (issue #600) [S21] | P21 | Credential helper (4.2). |
| Binary files (`.pptx`, media) poison the checkpoint; "run permanently wedged" (issue #335) [S24] | P17 | Ignore media in `.openwikiignore`; delete `openwiki/.run.json` and the SQLite checkpoint to recover. |
| Truncated tool calls end runs without error (issue #458); context overflow on 131k-context local models (issue #648) [S24] | P19 | Use 200k+ context Copilot models; set `OPENWIKI_MAX_OUTPUT_TOKENS`; check the MR for missing pages. |
| Run plan deleted on completion (issue #607) [S24] | P15 | Keep the MR description listing pages touched (from `git diff --stat`). |
| CI `npm install --global openwiki` invisible to Renovate (issue #775) [S21] | P16 | Pin the version in the shared template; bump via MR. |
| HN: "could have been a SKILL … mostly a thin … wrapper around the prompts"; wikis "get stale too quick"; "verbose, duplicated, incorrect, outdated or incomplete docs often leads to worse performance for AI" (no LangChain reply) [S23] | P12, P22, P24 | Keep the wiki on the workflow path (D19 evaluation set); rely on claims-based staleness rather than prose; measure agent runtime with/without the pointer. |
| OAuth/ngrok fetches without deadlines hang the CLI (issue #541) [S24] | P07 | Personal-mode connectors only; not used in code mode. |

## 9. Scaling considerations

- **Bootstrap on large repos (P17)**: page-by-page jobs with checkpoints mean a failed CI job resumes instead of restarting, and partial progress can be committed [S3][S9]. But cost is unbounded (section 8) and the plan is agent-made; DocAgent/MemDocAgent-style dependency ordering is not implemented (landscape §7 P2, P4). Start with `.openwikiignore` covering generated and vendored code and a tight `INSTRUCTIONS.md`.
- **Incremental updates (P01)**: claims are refreshed when their evidence version changes; a clean update makes no model call [S3]. This is evidence-keyed rather than commit-keyed, so semantic drift outside cited ranges still needs a periodic full re-plan (`WIKI_ACTION=rebuild`) — schedule monthly, budget separately.
- **Token budget per run on Copilot**: AI credits are metered per model usage with a shared enterprise pool (Business 1,900 / Enterprise 3,900 credits per user per month; overage $0.01 per credit; budgets per user/cost-centre) [S45]; the credit-per-token rate is not published in the pages opened ❓. Anchor from the issues: a mid-size repo bootstrap can be 1–10M tokens; an incremental update touching a few pages is typically ≤ 1M ❓.
- **Many repos (P11/P16)**: one included CI template and one `.openwikiignore` convention; no batch tooling like AutoWiki's "batch refresh" (BG-P P16) — schedule runs staggered to protect the shared credit pool (D17).
- **Index size (P03)**: per-directory generated `index.md` avoids the flat-index limit; no search tool is provided — add BM25/grep at the hub (BG-P P03 fixes).
- **Staleness is worse than nothing** (landscape P27): OKF `verified`/`generated` stamps let the Quartz site show freshness per page; enforce `status: draft` for unreviewed bootstrap pages (D13).
- **Non-determinism (P19)**: unchanged evidence → no rewrite is enforced by the no-op check; pages whose evidence changed are rewritten wholesale by the model (not section edits, D08 ❓ partially met — "Sparse Claims reconciliation preserving unaffected statements" in v0.5.0 [S8]).

## 10. Effort and cost estimate

| Item | Estimate | Notes |
|------|----------|-------|
| Bootstrap (one-off) | 3–5 person-days for the shared CI template, guard script, R5 form, Quartz hub and Route-B adapter spike; then ~0.5 person-day per repo (INSTRUCTIONS.md, ignore file, review of the bootstrap MR). Model cost per repo bootstrap: 1–10M tokens ❓ (issues #51/#696 anchors) | Route B adds 1–2 days if the host id needs an upstream patch. |
| Per-commit / per-MR run | No-op: seconds, zero credits. Typical update: 3–15 min, ≤ 1M tokens ❓; outliers 10× (issue #51) | Debounce to one run per default-branch push (D17). |
| Ongoing maintenance per week | ~2 h: review wiki MRs across repos, prune `INSTRUCTIONS.md`, bump the pinned `openwiki` version, re-check Copilot model policy | Plus a monthly rebuild review. |
| Infrastructure | GitLab runners with Node 22 and internet; hub project with Pages; no servers | Runner must not hold deploy secrets (D15). |
| Licensing / seats | Existing Copilot Business seats for A1; one machine-account seat for A2/B1 **if permitted ❓**; zero extra seats for B2 (org-billed installation token) **if verified ❓** | Business $19/seat/1,900 credits; Enterprise $39/seat/3,900 credits [S45][S46]. |

## 11. Open questions and spike plan

| # | Question | Smallest experiment / verification |
|---|---|---|
| Q1 | May a third-party tool call `api.githubcopilot.com` with a Copilot Business user's OAuth token under the GitHub Generative AI Services Terms and AUP? | Written question to the GitHub account manager quoting OpenWiki PR #192's "third-party integrations" finding [S15] and the AUP bulk-activity clause [S42]; ask for a yes/no in writing (D22). Until answered, Route A is for local developer use only. |
| Q2 | May a machine account hold a Copilot Business seat and be used headlessly from GitLab CI? | Same letter; in parallel assign a seat, run `gh auth login` + `gh auth token`, run `openwiki code --update --print` in a GitLab job on a sample repo (0.5 day). |
| Q3 | Does Route B work: `openwiki mcp --host copilot` + `.github/mcp.json` + skill + `copilot -p` completing `openwiki_finish`? | 1-day spike on one repo; if the host id is rejected, add `copilot` to `registry.ts` and open an upstream PR. |
| Q4 | Does a GitHub App installation token (B2) authenticate Copilot CLI from a GitLab runner, and is it billed to the org without a seat? | Create the app per the SDK doc [S40], mint a token in the job, run `copilot -p "echo ok"`; check the org usage report (0.5 day). |
| Q5 | Real cost per bootstrap and per update in AI credits on a representative service repo | Run Q2/Q3 twice each with `gpt-5.4-mini` and one larger model; read the Copilot usage report; record variance. |
| Q6 | GitLab self-managed specifics: MR API, protected-branch push by the bot token, `[skip ci]` behaviour, `resource_group` | Part of Q2 on the self-managed instance if one exists. |
| Q7 | Quartz rendering of OKF pages, `.claims/` exclusion, relative links, Mermaid | Build the hub from two repos' `openwiki/`; check 20 links and 5 diagrams (0.5 day). |
| Q8 | Can `INSTRUCTIONS.md` reliably produce a PO-readable overview page that stays put across updates? | Add the request, run three updates, have the PO read it (P14). |
| Q9 | Does `openwiki code --update --message` inject a one-shot instruction? Does `--init` with `force` re-plan everything? | 30-minute CLI test. |

## 12. Verdict

**Fit score 6/10.** OpenWiki gives us, today, the strongest open implementation of the code-wiki pattern — claims with versioned evidence, OKF output, resumable CI runs, a managed agent pointer, deterministic indexes — and it is the only generator that already knows about both Copilot and GitLab. It loses points where our hard constraints bite: its Copilot provider is a third-party client on GitHub's inference API whose compliance nobody has confirmed (R6 ❓), the clean alternative is an adapter we would have to prove (Q3), GitLab support has open rough edges (#341, #600), and it is single-repo with unbounded cost variance. All eight requirements land on 🟡.

**Choose it when** Q1 or Q3/Q4 come back positive and the team prefers adopting a maintained generator over building the LLM half of ADR-08 themselves. **Do not choose it** as the sole engine if GitHub answers Q1 negatively and Q3 fails, or if a fixed per-run credit budget is mandatory.

**Combines well with:** ADR-07 (OpenWiki is the reference producer of OKF v0.2; the standards layer there is exactly what OpenWiki emits), ADR-08 (use OpenWiki for the narrative layer on top of the deterministic backbone and the hub; the backbone covers R3 cross-repo pages that OpenWiki cannot), and ADR-10 as the benchmark for what a vendor-native trigger model looks like. Route B (Copilot CLI host) also makes OpenWiki compatible with any future Copilot-CLI-based execution model chosen elsewhere.

## 13. Sources

Tags: `[fetched]` = opened in this session; `[snippet]` = search-result excerpt only; `[memory]` = not verified online. `BG-L` / `BG-P` = the local background files `../background/landscape.md` and `../background/problems-and-fixes.md`, both read in full; facts attributed to them were verified by the survey researchers, not re-opened here.

1. [S1] langchain-ai/openwiki README — LangChain — 2026 — https://github.com/langchain-ai/openwiki — tagline, commands, providers, output layout, OKF, CI examples, MIT, 16k★/1.2k forks. `[fetched]`
2. [S2] OpenWiki overview — LangChain docs — https://docs.langchain.com/oss/openwiki/overview — modes, Deep Agents/LangSmith, feature list, doc navigation. `[fetched]`
3. [S3] OpenWiki code mode — LangChain docs — https://docs.langchain.com/oss/openwiki/code-mode — inputs, `.openwikiignore`, page-job queue, claims, `verified`, `.last-update.json`, INSTRUCTIONS.md, OKF fields, managed block, Mermaid. `[fetched]`
4. [S4] OpenWiki CLI reference — LangChain docs — https://docs.langchain.com/oss/openwiki/cli-reference — commands, flags, config locations, `--language`, `-p`. `[fetched]`
5. [S5] OpenWiki visualize — LangChain docs — https://docs.langchain.com/oss/openwiki/visualize — `--export` output files, CDN dependency, single wiki. `[fetched]`
6. [S6] OpenWiki model providers — LangChain docs — https://docs.langchain.com/oss/openwiki/providers — provider table, Copilot env vars, "Personal Access Tokens … are rejected by the Copilot API for third-party integrations", ChatGPT OAuth provider. `[fetched]`
7. [S7] openwiki package.json (main) — https://raw.githubusercontent.com/langchain-ai/openwiki/main/package.json — v0.5.0, MIT, Node ≥22, dependencies. `[fetched]`
8. [S8] OpenWiki releases — https://github.com/langchain-ai/openwiki/releases — v0.2.5…v0.5.0 notes. `[fetched]`
9. [S9] OpenWiki GitLab CI example — https://raw.githubusercontent.com/langchain-ai/openwiki/main/examples/openwiki-update.gitlab-ci.yml — full job YAML; and "Automate updates" — https://docs.langchain.com/oss/openwiki/automate-updates — credentials, resumability on ephemeral runners, telemetry flag. `[fetched]`
10. [S10] GitHub Terms of Service (effective 2026-04-27) — https://docs.github.com/en/site-policy/github-terms/github-terms-of-service — one person per login, machine accounts permitted, API abuse clause, Section J AI Features. `[fetched]`
11. [S11] Authenticate Copilot CLI — GitHub Docs — https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli — token precedence, fine-grained PAT "Copilot Requests" on a personal account, classic PAT not supported, ghe.com hosts. `[fetched]`
12. [S12] About using Copilot CLI in GitHub Actions — GitHub Docs — https://docs.github.com/en/copilot/concepts/agents/copilot-cli/copilot-cli-in-github-actions — PAT billed to the user's seat and "operational and security risks", GITHUB_TOKEN recommended, org CLI policy separate from licensing. `[fetched]`
13. [S13] OpenWiki README (raw) — https://raw.githubusercontent.com/langchain-ai/openwiki/main/README.md — "routes inference through the OpenAI-compatible Copilot API (`https://api.githubcopilot.com`)", gh session reuse, Node 22, telemetry scope and opt-out. `[fetched]`
14. [S14] OpenWiki code-mode prompt — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/agent/prompts/code.ts — audience, grounding rules, reserved index/log, INSTRUCTIONS.md, AGENTS.md rule, OKF front matter, repo-scope rule. `[fetched]`
15. [S15] PR #192 "feat: add github copilot as a model provider for inference" — https://github.com/langchain-ai/openwiki/pull/192 — external-cli auth, hostname from COPILOT_BASE_URL, "The Copilot API refuses PATs for third-party integrations regardless of permissions (verified empirically; only the first-party Copilot CLI flow accepts them)", Responses vs chat completions routing, merged 2026-07-27 by colifran. `[fetched]`
16. [S16] OpenWiki `src/auth/external-cli-auth.ts` — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/auth/external-cli-auth.ts — `gh auth token --hostname`, PAT regex and error string, no token exchange in this file. `[fetched]`
17. [S17] OpenWiki `src/config/constants.ts` — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/config/constants.ts — base URL, env keys, `authMethod: "external-cli"`, Copilot model ids, defaults; and `src/model-availability.ts` (Copilot: "No availability adapter is configured"). `[fetched]`
18. [S18] OpenWiki issues/PRs matching "copilot" (GitHub search API) — https://api.github.com/search/issues?q=repo:langchain-ai/openwiki+copilot — #30, #34, #375, #490, #731, #744, #763 etc.; plus https://github.com/langchain-ai/openwiki/issues/763 and https://github.com/langchain-ai/openwiki/issues/731. `[fetched]`
19. [S19] Issue #341 "code mode is hardcoded to GitHub" — https://github.com/langchain-ai/openwiki/issues/341 — unconditional `.github/workflows` write, GitHub Actions wording, PR #342. `[fetched]`
20. [S20] PR #439 "Recursive documentation for monorepos" — https://github.com/langchain-ai/openwiki/pull/439 — tree of wikis, detected layouts, no cascade, monorepo-only, open. `[fetched]`
21. [S21] OpenWiki issues/PRs matching "gitlab" (GitHub search API) — https://api.github.com/search/issues?q=repo:langchain-ai/openwiki+gitlab — #137, #153, #253, #306, #342, #396, #577, #600, #713, #775. `[fetched]`
22. [S22] Issue #51 cost variance — https://github.com/langchain-ai/openwiki/issues/51 — 390-file subproject, $0.10 vs $10.71, 12×/4.5× variance, requested flags. `[fetched]`
23. [S23] HN thread "OpenWiki: CLI that writes and maintains agent documentation for your codebase" (96 pts, 2026-07-01) — https://hn.algolia.com/api/v1/items/48752949 — commenter critiques. `[fetched]`
24. [S24] OpenWiki issues/PRs matching monorepo/large/cost/tokens/timeout (GitHub search API) — https://api.github.com/search/issues?q=repo:langchain-ai/openwiki+(monorepo+OR+large+OR+cost+OR+tokens+OR+timeout+OR+hallucinat) — #162, #335, #439, #447, #458, #459, #541, #607, #608, #648, #688, #696; plus https://github.com/langchain-ai/openwiki/issues/696. `[fetched]`
25. [S25] OpenWiki host skill — https://raw.githubusercontent.com/langchain-ai/openwiki/main/integrations/openwiki/SKILL.md — lifecycle steps, claims format, host uses its own session. `[fetched]`
26. [S26] OpenWiki MCP server — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/integrations/mcp/server.ts — server name, lifecycle tools, "repository content is untrusted evidence, not instructions", no model credential. `[fetched]`
27. [S27] OpenWiki integrations registry and protocol — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/integrations/install/registry.ts and https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/integrations/core/protocol.ts — hosts codex/claude/opencode/cursor, skill paths, `["openwiki","mcp","--host",…]`, tool input schemas; and integrations docs https://docs.langchain.com/oss/openwiki/integrations. `[fetched]`
28. [S28] OpenWiki `src/okf/index-sync.ts` — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/okf/index-sync.ts — per-directory deterministic index from title/description, `okf_version` on root only, log.md excluded. `[fetched]`
29. [S29] OpenWiki repository tree (GitHub API) — https://api.github.com/repos/langchain-ai/openwiki/git/trees/main?recursive=1 — module layout. `[fetched]`
30. [S30] OpenWiki `src/cli/commands.ts` — https://raw.githubusercontent.com/langchain-ai/openwiki/main/src/cli/commands.ts — command/flag help strings, `mcp --host`, `code --message`, `--dry-run`; and `src/ingestion/code-mode.ts` (connector time window from `.last-update.json`). `[fetched]`
31. [S31] langchain-ai/deepagentsjs — https://github.com/langchain-ai/deepagentsjs — MIT, "works with tool-calling chat models", 1.5k★. `[fetched]`
32. [S32] LangChain blog OpenWiki post — https://www.langchain.com/blog/openwiki (and https://blog.langchain.com/openwiki/ → 301 to it) — HTTP 404; announcement not verifiable ❓. `[fetched]` (404)
33. [S33] dcouple/openwiki — https://github.com/dcouple/openwiki — Claude Code-curated vault + public site, licence TBD, 0★. `[fetched]`
34. [S34] barvhaim/pi-openwiki — https://github.com/barvhaim/pi-openwiki — Pi extension port, MIT, 8★. `[fetched]`
35. [S35] Quartz "Hosting" — https://quartz.jzhao.xyz/hosting — GitLab Pages `.gitlab-ci.yml` (node:24, `npx quartz build`, `public`), private by default. `[fetched]`
36. [S36] GitLab Pages — GitLab Docs — https://docs.gitlab.com/user/project/pages/ — Free/Premium/Ultimate, all offerings, access control, `pages: true`. `[fetched]`
37. [S37] CI/CD pipelines (run manually, prefill variables, `options`) — GitLab Docs — https://docs.gitlab.com/ci/pipelines/. `[fetched]`
38. [S38] Add MCP servers to Copilot CLI — GitHub Docs — https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers — `~/.copilot/mcp-config.json`, `.mcp.json`, `.github/mcp.json`, stdio JSON shape, `/mcp add`, org registry/allowlist policy. `[fetched]`
39. [S39] Copilot CLI programmatic reference — GitHub Docs — https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference — `-p`, `--allow-tool`, `--deny-tool`, `--allow-all-tools`, `--agent`, `--model`, `--no-ask-user`, `-s`, `--add-dir`, `COPILOT_GITHUB_TOKEN`, `COPILOT_MODEL`. `[fetched]`
40. [S40] GitHub Copilot SDK — https://github.com/github/copilot-sdk (GA, MIT, JSON-RPC to Copilot CLI server mode, "subscription is required … unless you are using BYOK"); docs/auth/README.md, docs/auth/authenticate.md (gho_/ghu_/github_pat_ accepted, ghp_ not), docs/auth/server-to-server-tokens.md (GitHub App installation tokens for "Other CI Systems", `copilot_requests: write`, All-repositories access, 1-hour expiry, billed to installation owner, org policy "Allow use of Copilot CLI billed to the organization"). `[fetched]`
41. [S41] GitHub Generative AI Services Terms (Version March 2026; replaces Product Specific Terms before 2026-03-05) — https://github.com/customer-terms/github-generative-ai-services-terms — §1.A applicability, §5.A acceptable use, §3 no training, no clause on third-party clients or seats; index at https://github.com/customer-terms; archived Copilot Product Specific Terms https://github.com/customer-terms/github-copilot-product-specific-terms (Oct 2024, deprecated 2026-03-05); Terms for Additional Products and Features https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features (updated 2026-04-27). `[fetched]`
42. [S42] GitHub Acceptable Use Policies — https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies — "excessive automated bulk activity", "undue burden on our servers through automated means". `[fetched]`. GitHub AI Code of Conduct: two guessed URLs returned 404; not read ❓.
43. [S43] ericc-ch/copilot-api (reverse-engineered Copilot proxy, MIT, 4.1k★) — https://github.com/ericc-ch/copilot-api — warning that "Excessive automated or scripted use of Copilot (including rapid or bulk requests, such as via automated tools) may trigger GitHub's abuse-detection systems … could result in temporary suspension of your Copilot access". `[fetched]`
44. [S44] Usage limits for GitHub Copilot — GitHub Docs — https://docs.github.com/en/copilot/concepts/usage-limits — rate limits, "If you're making frequent or automated requests … consider adjusting your usage pattern". `[fetched]`
45. [S45] About billing for GitHub Copilot in organizations and enterprises — GitHub Docs — https://docs.github.com/en/copilot/concepts/billing/organizations-and-enterprises — 1,900 / 3,900 credits, shared pool, $0.01 overage, budgets, +10% data-resident multiplier. `[fetched]`
46. [S46] Plans for GitHub Copilot — GitHub Docs — https://docs.github.com/en/copilot/get-started/plans — prices, credits, "All plans include Copilot CLI", org policies on Business/Enterprise. `[fetched]`
47. [S47] Manage policies for Copilot in your organization — GitHub Docs — https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-for-organization/manage-policies — "Copilot Features & Models" policy, MCP policy, third-party coding agents. `[fetched]`
48. [S48] OpenCode providers (GitHub Copilot section) — https://opencode.ai/docs/providers/ — device-flow login; "Some models might need a Pro+ subscription". `[fetched]`
49. [S49] OpenWiki quickstart — https://docs.langchain.com/oss/openwiki/quickstart — init prompts, outputs, chat/`-p`, `~/.openwiki/.env`. `[fetched]`
50. [BG-L] ../background/landscape.md — researcher-landscape — 2026-09-02 — §2, §4, §5 (OpenWiki facts, LICENSE, GitHub Actions example), §6 (OKF), §7 (papers P2, P4, P13, P25, P27), §8 (Copilot reads AGENTS.md/CLAUDE.md, skills from `.agents/skills/`). `[fetched]` (local file)
51. [BG-P] ../background/problems-and-fixes.md — researcher-problems — 2026-09-02 — P01–P24, D01–D22, GitLab job-token/`[ci skip]` facts, Copilot billing facts. `[fetched]` (local file)
