---
id: ADR-07
title: "Standards-based agent knowledge layer: Google Cloud's Open Knowledge Format (OKF) plus the emerging agent-context standards (AGENTS.md, Agent Skills, llms.txt, Copilot instruction files, MCP resources)"
status: candidate        # candidate | recommended | rejected | superseded (changed by decision, not by researcher)
date: 2026-09-02
researcher: researcher-adr-07
fit_score: 7        # overall fit against ../requirements.md, justified in section 12
confidence: medium   # how well the key claims are verified against fetched sources
requirement_ratings: {R1: "✅", R2: "✅", R3: "✅", R4: "🟡", R5: "🟡", R6: "🟡", R7: "✅", R8: "🟡"}   # same symbols as section 5
tags: [standards, okf, agents-md, agent-skills, llms-txt, copilot-instructions, mcp-resources, gitlab-duo, knowledge-layer, file-format-decision]
---

# ADR-07: Standards-based agent knowledge layer: Google Cloud's Open Knowledge Format (OKF) plus the emerging agent-context standards (AGENTS.md, Agent Skills, llms.txt, Copilot instruction files, MCP resources)

<!--
Uniform template for all approach ADRs in llm-wiki/approaches/.
Keep ALL headings, in this order, with these numbers. Add sub-sections freely.
Target length: 250-600 lines. Prefer tables and short paragraphs.
Mark unverified claims with ❓ and say what would verify them.
Never invent product features, URLs, or paper titles; if a search finds nothing, say so.
-->

## 1. Summary

This approach makes the repository's knowledge layer a set of **standardised, tool-agnostic files** that every coding agent can consume: an `AGENTS.md` hierarchy (Agentic AI Foundation / Linux Foundation), Agent Skills `SKILL.md` directories (open spec at agentskills.io), Copilot's own `.github/copilot-instructions.md` and `*.instructions.md`, an `llms.txt` index, ADRs, and the wiki itself stored as a **Google Cloud Open Knowledge Format (OKF)** bundle. OKF is an Apache-2.0 markdown-with-frontmatter spec published 12 June 2026 (v0.1) and 25 July 2026 (v0.2) that explicitly "formalizes the LLM-wiki pattern" from Karpathy's April 2026 gist [S1][S2][S3]. Maturity as of 2026-09: AGENTS.md and Agent Skills are broadly supported (GitHub Copilot, GitLab Duo, Gemini CLI, Claude Code, Codex, Cursor); OKF is eleven weeks old, ~250 GitHub stars, one vendor, no formal governance [S4]. Verdict for us: adopt this as the **file-format decision** for whichever execution model (ADR-01/02/04) wins; it is the best answer to R3 (future agents) and R7 (host-independence), but it does not by itself deliver R4/R5 automation and needs a documented workaround for the JetBrains + Copilot `AGENTS.md` gap.

## 2. Context

The company wants an LLM-maintained repository wiki consumed by agents *and* humans (R1) that serves as the context layer for the whole AI development pipeline (R2), rolled out across many frontend and backend service repositories (R3), maintained by developers via hook-triggered agents (R4) with a form-based retry/instruction channel (R5), under two hard constraints: only GitHub Copilot as the LLM (R6) and GitLab as the host (R7), ideally published with Quartz on GitLab Pages (R8).

The project owner asked whether we should build the wiki on Google Cloud's Open Knowledge Format (OKF) plus the emerging agent-context standards rather than on a bespoke page format. The risk this ADR addresses is **lock-in of the knowledge layer to one agent product**: if the wiki's structure is only understood by a Copilot-specific prompt, the design will not "survive the transition to fully automatic agentic coding systems later" (R3). The standards evaluated here are the ones that at least two independent agent vendors implement today, so an agent swap later changes the *executor*, not the *knowledge*.

Background documents in `../background/` were not yet present at the time of writing (directory empty); this ADR is self-contained and cites primary sources in section 13.

## 3. The approach

### 3.1 Origin and provenance

**Provenance check.** Searches run on 2026-09-02 (Google Cloud blog, the GoogleCloudPlatform GitHub organisation, third-party coverage) confirm that the Google-standardised artefact for agent knowledge is **OKF – Open Knowledge Format** [S1][S2][S3][S5]; no other Google specification competes with it for this role. This ADR evaluates OKF as the Google-standardised component.

| Standard | Originator / steward | First published | Licence | Activity (2026-09) | Notes |
|---|---|---|---|---|---|
| **OKF (Open Knowledge Format)** | Google Cloud Data Cloud team (Sam McVeety, Amir Hormati) | v0.1 2026-06-12, v0.2 2026-07-25 | Apache-2.0 | 246 stars, 9 forks, 9 open issues; canonical repo `GoogleCloudPlatform/open-knowledge-format` (moved out of `knowledge-catalog/okf`) | Single-vendor, "a starting point, not a finished standard"; no foundation, no working group [S1][S2][S3][S4] |
| **AGENTS.md** | OpenAI, donated to the Agentic AI Foundation (Linux Foundation) 2025-12-09 | 2025-08 | Open format, no required fields | 60k+ open-source projects; supported by 25+ agents incl. Copilot, Gemini CLI, Jules, Codex, Claude Code, Cursor, Junie | Google is an AAIF Platinum member but contributed no documentation standard of its own [S6][S7] |
| **Agent Skills (`SKILL.md`)** | Anthropic (originator, per third-party guides [S8]); published as an open spec at agentskills.io | 2025-10 [snippet] | Spec public; `skills-ref` validator | Implemented by GitHub Copilot (CLI, VS Code, coding agent, JetBrains preview), Gemini CLI, GitLab Duo, Claude Code, Codex, Cursor | Progressive disclosure is built in [S9][S10][S11][S12] |
| **llms.txt** | Jeremy Howard / Answer.AI | 2024-09; v2 2026-08 | Open proposal | Thousands of sites; OpenAI, Anthropic, Google publish it for dev docs | Ahrefs (2026-06): 97% of llms.txt files get zero requests [S13][S14] |
| **Copilot instruction files** | GitHub | 2024-2025 | Proprietary convention | `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.github/agents/*.agent.md`, `.github/skills/` | Copilot-only, but VS Code also reads CLAUDE.md, and Copilot reads AGENTS.md/CLAUDE.md/GEMINI.md [S15][S16] |
| **MCP resources** | Anthropic; MCP donated to AAIF | 2024-11; spec rev. 2025-06-18 | Open spec | GitLab ships an MCP server (Free tier, Beta) | Resources are "application-driven": clients decide whether the model sees them [S17][S18] |
| **A2A** (for completeness) | Google, donated to Linux Foundation; v1.0 | 2025-04 | Apache-2.0 | TSC: AWS, Cisco, Google, IBM, Microsoft, Salesforce, SAP, ServiceNow | Agent-to-agent messaging; **nothing to do with documentation or knowledge files** [S19] |

Google's *actual* contributions to agent context are therefore: (a) OKF for knowledge bundles, (b) Gemini CLI reading `GEMINI.md` with `context.fileName` configurable to `["AGENTS.md", ...]` and Agent Skills from `.gemini/skills` or the `.agents/skills` alias, (c) Google Jules listed as an AGENTS.md consumer, (d) AAIF platinum membership, (e) A2A (irrelevant here) [S20][S21][S6][S19].

### 3.2 How it works (architecture)

The knowledge layer is a fixed set of files with a strict division of labour:

| File | Audience | Content rule | Who writes it |
|---|---|---|---|
| `AGENTS.md` (root + one per service/package) | every agent | Short imperative instructions: commands, conventions, "read `docs/wiki/index.md` before planning". No codebase overview (see 3.3 evidence) | humans; agent may propose |
| `.github/copilot-instructions.md` | Copilot surfaces that do not read AGENTS.md (JetBrains Chat, Visual Studio, Eclipse, GitHub.com) | 5-10 lines, delegates to AGENTS.md and the wiki index | humans |
| `.github/instructions/*.instructions.md` | Copilot (VS Code, JetBrains, CLI) | Path-scoped rules via `applyTo` glob, e.g. `api/**` → "consult `docs/wiki/contracts/`" | humans + agent |
| `.agents/skills/<name>/SKILL.md` (+ `scripts/`, `references/`) | Copilot, Gemini CLI, GitLab Duo, Claude Code | Procedures per pipeline stage (wiki-maintain, feature-spec, bugfix-triage, review-checklist, ops-runbook) | humans; agent may propose |
| `docs/wiki/` (OKF bundle) | agents + developers + product owner (via Quartz) | The wiki: one concept per markdown file with `type:` frontmatter, `index.md` per directory, `log.md`, v0.2 trust fields | **agent-maintained**, human-verified |
| `docs/adr/` | developers, agents | MADR-style decisions; also exposed as OKF `type: Decision` concepts | humans |
| `llms.txt` (+ optional `llms-full.txt`) | external/generic LLM tools, Pages site | **Generated** from `docs/wiki/index.md` at build time | CI |
| `.github/agents/wiki-maintainer.agent.md` | Copilot CLI / VS Code / JetBrains | The persona used by the update job (`copilot -p --agent wiki-maintainer`) | humans |

```
                 developer commit / push  (or manual "Run pipeline" form, R5)
                                 |
        +------------------------+-------------------------+
        | execution model: local hook (ADR-01) | CI job (ADR-02) | webhook svc (ADR-04)
        +------------------------+-------------------------+
                                 |
                      copilot -p "..." --agent wiki-maintainer --no-ask-user
                      (auth: COPILOT_GITHUB_TOKEN of a seat holder)   [S22][S23]
                                 |
        reads:  AGENTS.md  ->  .agents/skills/wiki-maintain/SKILL.md  ->  docs/wiki/index.md
                                 |
        writes: docs/wiki/**/*.md (OKF concepts, index.md, log.md)   + proposes AGENTS.md diffs
                                 |
                 CI lint (no LLM): frontmatter `type` present, skills-ref validate,
                 link check, AGENTS.md line budget, stale_after sweep
                                 |
        +------------------------+-------------------------+
        | humans: MR review / Quartz on GitLab Pages (R8) | agents: same files, next task |
        +------------------------+-------------------------+
                                 |
                 llms.txt generated from index.md at Pages build
```

Where the LLM runs: inside GitHub Copilot CLI (programmatic mode) for automation, and inside Copilot in VS Code/JetBrains for interactive use; no model API is called directly (R6). Who authenticates: a human seat holder locally; in CI a token of a seat holder (`COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN` precedence) [S23]. What is committed: only `docs/wiki/**` and `llms.txt`; instruction/skill files change through normal MRs.

### 3.3 Wiki content model it implies

**Direction of derivation (the owner's question).** The wiki (OKF bundle) is the **source**; `AGENTS.md`, instruction files and `llms.txt` are **thin entry points** into it. Evidence for keeping the entry points thin:
- Gloaguen et al. (ETH Zürich SRI Lab, MemAgents@ICLR 2026): context files "do not generally improve task success rates" and raise inference cost "by over 20%"; repository overviews in AGENTS.md were unhelpful; context files are useful for "specifying non-standard coding practices" [S24][S25].
- dos Santos et al. 2026, 100 repos: "Context Bloat" in 42% of AGENTS.md/CLAUDE.md files, "Lint Leakage" 62%, "Skill Leakage" 35% [S26].
- Counter-evidence: Lulla et al. 2026, 10 repos / 124 PRs: AGENTS.md presence associated with 28.64% lower median runtime and 16.58% fewer output tokens at comparable completion [S27]. Reading both: instructions help *efficiency*; knowledge belongs in navigable pages, not in the instruction file.
- Agent Skills spec: metadata ~100 tokens always loaded, body < 5,000 tokens on activation, resources on demand; keep `SKILL.md` under 500 lines [S9].

**OKF concept page (v0.2)** [S3]: YAML frontmatter, `type` is the only required key; recommended `title`, `description`, `resource` (URI), `tags`; trust families `sources[]` (with `resource`, `id`, `author`, `usage_count`, `last_modified`), `generated: {by, at}`, `verified: [{by, at}]` (derived tiers: unverified → machine-confirmed → human-reviewed), lifecycle `status: draft|stable|deprecated`, `stale_after`. Actor convention: `<producer>/<version>`, `human:<id>`, `process:<id>`. Links: bundle-relative (`/services/orders`) recommended; link *kind* is expressed in prose; consumers MUST tolerate broken links and unknown `type` values. Reserved filenames: `index.md` (directory listing, progressive disclosure) and `log.md` (chronology). Optional `okf_version: "0.2"` in the bundle-root `index.md`.

**Our page types** (OKF leaves types to the producer): `Service`, `Endpoint`, `Event`, `Contract`, `Data Model`, `Runbook`, `Decision`, `Glossary`, `Product Capability` (non-technical, for the PO), `Team/Ownership`. Human-facing vs agent-facing: the same pages serve both; the PO reads `Product Capability` and `Glossary` pages through Quartz; agents read everything through `index.md`. Karpathy's `raw/` layer maps to the code itself plus `docs/adr/`; his `schema/CLAUDE.md` maps to `AGENTS.md` + the `wiki-maintain` skill [S28].

### 3.4 Trigger and automation model

The standards say nothing about triggers; they define what is on disk. Options, to be decided in ADR-01/02/04:

| Trigger | Mechanism | Standards-specific notes |
|---|---|---|
| Local git hook (`pre-push`/`post-commit`) | `copilot -p ... --agent wiki-maintainer --allow-tool=... --no-ask-user` on the developer's seat | Copilot CLI does **not** reload changed instruction files in an active session; a fresh process per run avoids that [S15] |
| GitLab CI job on push to default branch | Same command in a `node:` image, `npm install -g @github/copilot`, token in a masked CI variable; commit back with a project access token | Token must belong to a Copilot seat holder; whether a **machine account** may hold a seat is ❓ (see R6) [S22][S23][S29][S30] |
| Manual "Run pipeline" form | GitLab prefilled variables (`description`, `options`) | This is the R5 channel (3.5) [S31] |
| Scheduled lint | CI schedule, no LLM | `stale_after` sweep, orphan pages, broken links |

Loop prevention: the update job commits with `[skip ci]` and a bot identity, and the job rule excludes commits whose author is the bot. Concurrency: `resource_group: wiki-update` in GitLab CI serialises runs per repo. Merge conflicts: the agent only edits `docs/wiki/**`; regeneration is idempotent per concept page (one file per concept keeps diffs local, an OKF design goal: "can touch 15 files in one pass" [S1]).

### 3.5 Human retry / instruction channel ("the form")

GitLab's manual pipeline form with prefilled variables is a verified feature [S31]:

```yaml
variables:
  WIKI_ACTION:
    value: "update"
    options: ["update", "rebuild", "lint-only", "answer-question"]
    description: "What the wiki maintainer should do."
  WIKI_INSTRUCTIONS:
    description: "Free-text instructions for the agent (Markdown ok). Leave empty for a plain re-run."
```

The job passes `$WIKI_INSTRUCTIONS` into the prompt; the `wiki-maintain` skill tells the agent to log the instruction verbatim in `docs/wiki/log.md` with a `process:gitlab-pipeline/<id>` actor. Alternative: an issue template whose creation webhook triggers the pipeline (ADR-04). Neither is part of any standard; the standards only guarantee the agent will find the skill and the wiki.

### 3.6 Multi-repo / microservice fit

- **Per repo**: the file set above. Nested `AGENTS.md` per service directory is supported by Copilot ("nearest AGENTS.md takes precedence" [S16]; Copilot CLI reads root, cwd, intermediate and nested dirs [S15]; VS Code needs the experimental `chat.useNestedAgentsMdFiles` [S32]) and by GitLab Duo (reads `/frontend/AGENTS.md` first when editing there [S33]).
- **Central `platform-knowledge` repo**: an OKF bundle holding cross-repo concepts (`Contract`, `Event`, `Team/Ownership`, environment topology). Each service repo's `AGENTS.md` links to it by URL. OKF links are bundle-relative, so cross-bundle references must be full URLs in `resource:` or in prose ❓ (spec is silent on multi-bundle graphs) [S3].
- **Aggregation for humans**: the Quartz site's CI clones every repo's `docs/wiki/` into `content/<repo>/` (3.7).
- **Ownership**: `Team/Ownership` concept pages with `verified: [{by: human:<lead>}]`; CODEOWNERS on `docs/wiki/**` and `AGENTS.md`.
- **Future autonomous agents**: this is the approach's core strength. AGENTS.md is foundation-governed; Skills are read by Copilot, Gemini CLI, GitLab Duo, Claude Code and Codex; OKF is "format, not platform" and must be consumable "without an integration" [S1]. An agent swap later changes `copilot -p` to another CLI and nothing else.

### 3.7 Publishing / UI

Quartz v5 on GitLab Pages is documented by the Quartz project (`node:24` image, `npx quartz build`, `public/` artifact; Pages are private by default, visibility configurable under Deploy > Pages) [S34]. OKF pages are plain markdown with YAML frontmatter, which Quartz renders; two adjustments are needed: (1) rewrite OKF bundle-relative links (`/services/orders`) to Quartz paths (`<repo>/services/orders`) in a build step ❓ (needs a spike), (2) exclude or render `AGENTS.md`, `SKILL.md` and `*.instructions.md` as an "Agent configuration" section for transparency. `llms.txt` is emitted at the Pages root from the aggregated `index.md` files, following llmstxt.org's H1 / blockquote / H2 link-list layout [S13].

## 4. Concrete implementation sketch for our environment

**Assumptions relied on** (from `../requirements.md`): developers can install Node.js and git hooks; CI runners have outbound internet; a GitLab bot account and project access tokens exist; a Copilot seat for a bot GitHub account is *not* assumed (see R6).

### 4.1 Directory layout (per service repository)

```
AGENTS.md                              # root entry point (<=120 lines)
services/orders/AGENTS.md              # nested, only if the sub-tree has different rules
.github/
  copilot-instructions.md              # shim for Copilot surfaces without AGENTS.md support
  instructions/
    api-contracts.instructions.md      # applyTo: "api/**,contracts/**"
    tests.instructions.md              # applyTo: "**/*_test.py,tests/**"
  agents/
    wiki-maintainer.agent.md           # custom agent for the update job
.agents/skills/                        # canonical skill location (Copilot, Gemini CLI, GitLab user-level)
  wiki-maintain/SKILL.md
  wiki-maintain/scripts/lint_bundle.py
  feature-spec/SKILL.md
  bugfix-triage/SKILL.md
  review-checklist/SKILL.md
  ops-runbook/SKILL.md
skills -> .agents/skills               # symlink for GitLab Duo project-level skills ❓ (Duo reads `skills/` at root [S35]; symlink following unverified)
docs/
  wiki/                                # OKF bundle = the wiki
    index.md                           # okf_version: "0.2", listing of sub-indexes
    log.md
    services/index.md, services/orders.md
    endpoints/index.md, endpoints/post-orders.md
    events/index.md, events/order-created.md
    runbooks/index.md, runbooks/orders-queue-backlog.md
    decisions/index.md                 # generated from docs/adr/
    product/index.md, product/checkout.md   # type: Product Capability (PO audience)
  adr/0001-use-okf-bundle.md
llms.txt                               # generated; do not edit
```

### 4.2 Example `AGENTS.md` (root)

```markdown
# Orders service — agent instructions

## Before any task
- Read `docs/wiki/index.md`, then only the concept pages your task needs (one file per concept).
- Cross-service contracts and events live in https://gitlab.example.com/platform/platform-knowledge/-/tree/main/docs/wiki — never guess a payload, open the `Contract` page.
- If a page has `status: deprecated` or `stale_after` in the past, say so in your answer and do not rely on it.

## Commands
- Install: `uv sync` · Test: `uv run pytest -q` · Lint: `uv run ruff check .` · Type-check: `uv run ty check`
- Run locally: `docker compose up orders`

## Conventions (non-standard, that you would not infer from the code)
- Money is integer minor units; never use float.
- Every outbound event must be added to `docs/wiki/events/` in the same MR (the CI lint fails otherwise).

## After changing behaviour
- Run the `wiki-maintain` skill (`/wiki-maintain`) to update affected concept pages, or leave it to the push hook.
```

(Deliberately no architecture overview: the ETH study found overviews do not help and cost tokens [S24].)

### 4.3 Example `.github/copilot-instructions.md` (shim)

```markdown
Follow the instructions in `AGENTS.md` at the repository root. The project knowledge base is the OKF bundle under `docs/wiki/`; start at `docs/wiki/index.md`. Do not duplicate wiki content into this file.
```

Copilot CLI supports `@` file references in `copilot-instructions.md` and `AGENTS.md` (not in `*.instructions.md`) [S15]; use them sparingly, e.g. `@docs/wiki/index.md`, only if a spike shows they are honoured by the JetBrains plugin too ❓.

### 4.4 Example path-specific instruction file

```markdown
---
applyTo: "api/**,contracts/**"
excludeAgent: "code-review"
---
When touching request/response models, open the matching `docs/wiki/endpoints/<verb>-<path>.md` and the `Contract` page it links to. Update the page's `generated.at` and `description` if the schema changes; leave `verified` untouched (a human re-verifies in review).
```

`applyTo` (comma-separated globs) and `excludeAgent` (`"code-review"` or `"cloud-agent"`) are documented Copilot syntax [S15][S16].

### 4.5 Example `SKILL.md` (`.agents/skills/wiki-maintain/SKILL.md`)

```markdown
---
name: wiki-maintain
description: Update the repository's OKF knowledge bundle under docs/wiki after code changes. Use when asked to update, rebuild, lint or answer questions from the wiki, after a merge, or when a diff touches services/, api/, events/ or runbooks.
license: Proprietary. See LICENSE.
metadata:
  owner: platform-team
  version: "0.3"
---
# Wiki maintenance procedure

1. Read `docs/wiki/index.md`; list concept pages whose `resource:` or `sources[].resource` overlap the changed paths (`git diff --name-only $BASE..HEAD`).
2. For each affected concept: update body and `description`; set `generated: {by: copilot-cli/<model>, at: <now>}`; keep `verified` as is; set `status: draft` if you are unsure.
3. New concept? Create `<dir>/<slug>.md` with `type:` from the allowed list in `references/types.md`; add it to the directory `index.md`.
4. Append one line to `docs/wiki/log.md`: `[update] <ISO time> <actor> <files>`.
5. Run `scripts/lint_bundle.py` and fix what it reports (missing `type`, broken bundle-relative links, pages past `stale_after`).
6. Never edit `AGENTS.md`, `SKILL.md` or `*.instructions.md`; if they are wrong, write the proposed diff to `docs/wiki/log.md` under `[proposal]`.
```

Frontmatter fields and constraints follow the Agent Skills spec (`name` ≤ 64 chars, lowercase/hyphen, equals directory name; `description` ≤ 1,024 chars; optional `license`, `compatibility`, `metadata`, `allowed-tools`) [S9]. Validate with `skills-ref validate .agents/skills/wiki-maintain` [S9].

### 4.6 Example OKF concept page (`docs/wiki/services/orders.md`)

```markdown
---
type: Service
title: Orders service
description: Owns the order lifecycle from cart checkout to fulfilment hand-off; publishes order.* events.
resource: https://gitlab.example.com/shop/orders
tags: [backend, python, checkout]
sources:
  - id: orders-repo
    resource: https://gitlab.example.com/shop/orders/-/tree/main/services/orders
    last_modified: 2026-08-29
generated: { by: copilot-cli/gpt-5.2, at: 2026-09-01T09:12:00Z }
verified:
  - { by: human:a.kaveh, at: 2026-09-01T11:40:00Z }
status: stable
stale_after: 2026-12-31T00:00:00Z
---
# Orders service
Consumes [/events/cart-checked-out](/events/cart-checked-out), exposes [/endpoints/post-orders](/endpoints/post-orders), emits [/events/order-created](/events/order-created). Owner: [/teams/checkout](/teams/checkout).
```

All field names and semantics are taken from SPEC.md v0.2 [S3]. Model identifier in `generated.by` is illustrative ❓ (use whatever `copilot --model` reports).

### 4.7 Example custom agent (`.github/agents/wiki-maintainer.agent.md`)

```markdown
---
name: wiki-maintainer
description: Maintains the OKF wiki bundle in docs/wiki. Non-interactive; edits only docs/wiki/**.
tools: ["read", "edit", "shell"]        # ❓ exact tool identifiers per surface; verify in the CLI's `copilot help`
---
You are the wiki maintainer. Load the `wiki-maintain` skill and follow it exactly. Never modify files outside docs/wiki/. Summarise what you changed at the end.
```

`description` is the only required field; `tools`, `model`, `mcp-servers`, `disable-model-invocation`, `user-invocable` are optional; body max 30,000 characters; supported in VS Code, Copilot CLI, JetBrains (preview) [S36].

### 4.8 Per-pipeline-stage loading rules (R2)

| Stage | Entry point loaded automatically | Skill invoked | Wiki pages pulled by the skill |
|---|---|---|---|
| Feature definition | `AGENTS.md` | `feature-spec` | `product/*`, `glossary/*`, relevant `Service` pages |
| Planning | `AGENTS.md` + nested `AGENTS.md` | `feature-spec` → plan section | `services/*`, `contracts/*` (central bundle), `decisions/*` |
| Implementation | `AGENTS.md`, `*.instructions.md` by `applyTo` | none (instructions suffice) | pages named in the instruction file |
| Testing | `tests.instructions.md` | `review-checklist` (test part) | `runbooks/test-data.md` |
| Bug fixing | `AGENTS.md` | `bugfix-triage` | `runbooks/*`, `events/*`, `log.md` recent entries |
| Review (MR) | `.github/instructions/*` with `excludeAgent` unset | `review-checklist` | `contracts/*`, `decisions/*` |
| Operations | `AGENTS.md` | `ops-runbook` | `runbooks/*`, `Team/Ownership` |
| Wiki upkeep | `AGENTS.md` | `wiki-maintain` | everything touched by the diff |

### 4.9 GitLab CI skeleton

```yaml
stages: [lint, wiki, pages]

wiki-lint:                         # no LLM, runs on every MR
  stage: lint
  image: python:3.13
  script:
    - pip install pyyaml
    - python .agents/skills/wiki-maintain/scripts/lint_bundle.py docs/wiki   # type present, links, stale_after
    - npx --yes skills-ref validate .agents/skills/*                          # ❓ exact package name/invocation of skills-ref
    - test $(wc -l < AGENTS.md) -le 150

wiki-update:
  stage: wiki
  image: node:24
  resource_group: wiki-update
  rules:
    - if: '$CI_COMMIT_AUTHOR =~ /wiki-bot/'
      when: never
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - if: '$CI_PIPELINE_SOURCE == "web"'
  variables:
    WIKI_ACTION: { value: "update", options: ["update","rebuild","lint-only","answer-question"], description: "Action for the wiki maintainer" }
    WIKI_INSTRUCTIONS: { description: "Optional free-text instructions for the agent" }
  script:
    - npm install -g @github/copilot                                # [S22]
    - export COPILOT_GITHUB_TOKEN="$COPILOT_TOKEN"                  # masked CI variable of a seat holder [S23] ❓ licence, see R6
    - copilot -p "Action: $WIKI_ACTION. Instructions: $WIKI_INSTRUCTIONS. Changed files: $(git diff --name-only HEAD~1)" \
        --agent wiki-maintainer --no-ask-user -s \
        --allow-tool=shell --add-dir=docs/wiki --deny-tool=... > wiki-run.md   # ❓ exact tool names for --allow-tool/--deny-tool
    - git add docs/wiki && git -c user.name=wiki-bot commit -m "wiki: auto-update [skip ci]" || true
    - git push "https://oauth2:${WIKI_PUSH_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git" HEAD:$CI_COMMIT_BRANCH
  artifacts: { paths: [wiki-run.md] }

pages:                               # central platform-knowledge repo only
  stage: pages
  image: node:24
  script:
    - for r in $REPOS; do git clone --depth 1 "https://oauth2:${READ_TOKEN}@${CI_SERVER_HOST}/$r.git" tmp/$r && cp -r tmp/$r/docs/wiki content/$(basename $r); done
    - python tools/rewrite_okf_links.py content      # ❓ spike: bundle-relative -> Quartz paths
    - python tools/make_llms_txt.py content > public/llms.txt
    - npx quartz build                                  # [S34]
  artifacts: { paths: [public] }
```

Flags `-p`, `-s`, `--no-ask-user`, `--agent`, `--allow-tool`, `--deny-tool`, `--add-dir`, `--model`, `--share` are documented for Copilot CLI programmatic mode [S22][S37]. GitHub recommends its own "Agentic Workflows" (GitHub Actions) for automation; that product is GitHub-only and does not apply on GitLab [S23].

### 4.10 Bootstrap (one-off)

1. Create the central `platform-knowledge` repo with an empty OKF bundle and the Quartz pipeline.
2. Per repo: add `AGENTS.md` (use Copilot's "Generate Agent Instructions" in JetBrains or VS Code as a *draft*, then cut it to instructions only [S38]), the shim, two instruction files, the five skills (copied from a template repo), the custom agent.
3. Run `copilot -p "Bootstrap docs/wiki from this repository" --agent wiki-maintainer` interactively, in chunks per top-level directory; review; mark reviewed pages `verified`.
4. Enable the CI jobs; enable `chat.useAgentsMdFile` / nested setting in VS Code and "Customizations" in JetBrains for all developers.

## 5. Requirements check

Use exactly these IDs and the legend from `../requirements.md`.

| ID | Requirement (short) | Rating | Evidence / notes |
|----|---------------------|--------|------------------|
| R1 | Dual audience (agents + devs + PO) | ✅ | OKF is "readable by humans and AI agents alike" markdown [S1]; Quartz renders it (3.7); PO audience served by a dedicated `Product Capability` page type, which no standard prescribes (our convention). Instruction/skill files are agent-facing only, by design. |
| R2 | Context layer for whole AI dev pipeline | ✅ | Per-stage skills + `applyTo` instruction files + `index.md` progressive disclosure (4.8); Copilot loads skills automatically "based on your prompt and the skill's description" [S11]. Evidence that overviews in AGENTS.md do not help means the pipeline value must come from the wiki pages, not the instruction file [S24]. |
| R3 | Multi-repo microservices, future autonomous agents | ✅ | AGENTS.md is foundation-governed and read by 25+ agents [S6][S7]; Skills read by Copilot, Gemini CLI, GitLab Duo, Claude Code, Codex [S10][S21][S35]; OKF consumable "without an integration" [S1]. Cross-bundle links not covered by OKF spec ❓ (full URLs as workaround). |
| R4 | Bootstrap once, dev-owned upkeep, hook-triggered auto-update | 🟡 | Standards define files, not triggers. Copilot CLI programmatic mode makes hook/CI runs possible [S22]; Copilot CLI does not reload instruction files mid-session [S15]. Execution model deferred to ADR-01/02/04. |
| R5 | Human retry / instructions via a form | 🟡 | Met via GitLab manual pipeline prefilled variables with `description`/`options` [S31] plus the `wiki-maintain` skill logging instructions; not part of any standard. |
| R6 | Copilot-only (no API keys, no direct model access) | 🟡 | Every file type is read by Copilot CLI/VS Code [S15][S16][S32]; JetBrains: docs matrix says Copilot Chat reads `copilot-instructions.md` and path-specific files but **not** AGENTS.md, while the 2026-03-11 changelog says AGENTS.md/CLAUDE.md are supported [S16][S38] — conflicting, hence the shim in 4.3. Skills in JetBrains are preview [S39]. OKF's reference agent needs a Gemini API key or Vertex AI [S40] → not usable; only the *format* is adopted. CI runs need a seat holder's token; machine accounts are allowed by GitHub ToS [S30] but neither the seat docs nor the 2026 Generative AI Services Terms say whether a machine account may hold a Copilot Business seat ❓ [S29][S41]. |
| R7 | GitLab, not GitHub | ✅ | All files are host-agnostic; `.github/` is just a directory name on GitLab. GitHub staff: Copilot Business works "regardless of where your code lives"; Enterprise-only GitHub.com features do not [S42]. GitLab Duo reads the same AGENTS.md and SKILL.md (Premium/Ultimate, self-managed and SaaS) [S33][S35], so a later GitLab-native agent needs no re-authoring. GitLab MCP server (Free, Beta) works with Copilot in VS Code [S18]. Org-level Copilot instructions and the cloud agent are GitHub.com-only and simply not used [S43]. |
| R8 | UI on GitLab Pages (Quartz) | 🟡 | Quartz v5 on GitLab Pages is documented [S34]; OKF frontmatter is Quartz-compatible; bundle-relative link rewriting and multi-repo aggregation are unverified ❓ (spike in section 11). |

## 6. Pros

- **Vendor independence is the deliverable.** AGENTS.md (AAIF), Skills (five+ implementations) and OKF (Apache-2.0, "format, not platform") mean the knowledge survives an agent swap; this directly answers R3's "fully automatic agentic coding systems later".
- **Progressive disclosure is standardised**, not home-grown: Skills metadata ≈100 tokens, body <5k tokens, resources on demand [S9]; OKF `index.md` per directory [S3]. That is the mechanism by which agents "find what they need without reading the whole codebase" (R2).
- **Trust and staleness are first-class in OKF v0.2** (`generated`, `verified`, `status`, `stale_after`) [S2][S3], giving the human-in-the-loop model R4 asks for a concrete data model: agent writes → human verifies → CI sweeps stale pages.
- **Copilot already supports the whole set** on CLI and VS Code (instructions, AGENTS.md, skills, custom agents, MCP) [S16][S39]; nothing bespoke to build in the model layer.
- **GitLab convergence**: GitLab Duo reads the identical AGENTS.md and SKILL.md files [S33][S35]; the GitLab MCP server exposes GitLab data to Copilot [S18]. Two vendors, one file set.
- **Lintable without an LLM**: `type` present, `skills-ref validate`, link check, `stale_after` sweep — cheap CI guards against drift.
- Plain markdown in git: diffs, MRs, CODEOWNERS and blame apply to knowledge exactly as to code (OKF design goal [S1]).

## 7. Cons and risks

- **OKF is eleven weeks old and single-vendor.** 246 stars, no validator CLI, no governance body, data-catalogue-flavoured examples (BigQuery tables, metrics) [S4][S40]. Risk: abandonment or breaking changes. Mitigation: we only depend on frontmatter conventions we would need anyway; the cost of divergence is a field rename.
- **Instruction files can hurt.** Best available evidence: no success gain, +20% cost, and 42% of real files show context bloat [S24][S26]. Mitigation: hard line budget in CI (4.9), overviews banned from AGENTS.md, knowledge in pages.
- **Copilot support is uneven across surfaces**: JetBrains AGENTS.md documentation is contradictory; skills are preview in JetBrains; VS Code nested AGENTS.md is experimental [S16][S38][S39][S32]. Mitigation: shim file, spike.
- **Skill directory names diverge**: Copilot `.github/skills` / `.claude/skills` / `.agents/skills`; Gemini CLI `.gemini/skills` / `.agents/skills`; GitLab Duo project-level `skills/` at root [S11][S21][S35]. `.agents/skills` is the largest common denominator; GitLab needs a symlink or copy ❓.
- **llms.txt has weak real-world uptake** (97% never requested; Google's Mueller calls it a "temporary crutch" for coding tools) [S14][S44]. We generate it because it is free, but nothing depends on it.
- **MCP resources are application-driven**: in VS Code the user adds them via "Add Context > MCP Resources"; automatic inclusion is not documented [S17][S45]. They are a convenience, not a knowledge-delivery mechanism.
- **Licence question for CI automation** (R6): unresolved whether a machine account may hold a seat; running under a named developer's token bills that person's premium requests [S23] ❓.
- **No standard covers non-technical (PO) content** or cross-repo graphs; both are our conventions on top.

## 8. Known problems reported by practitioners, and fixes

| Problem | Reported by | Fix / mitigation |
|---|---|---|
| Long AGENTS.md with codebase overviews adds cost and steps, no success gain; one model "spent extra steps searching for and re-reading context files that were already loaded" | Gloaguen et al. 2026 [S24]; Upsun write-up [S46] | Start near-empty; add an instruction only after a repeated mistake; ban overviews; enforce line budget in CI |
| Context bloat (42%), lint leakage (62%), skill leakage (35%), conflicting instructions co-occur | dos Santos et al. 2026, 100 repos [S26] | Lint rules belong in linters, procedures in skills, knowledge in the wiki; the `wiki-lint` job checks size, the review checklist checks leakage |
| Copilot CLI ignores edits to instruction files in a running session | GitHub docs [S15] | One process per run in automation; `/memory reload`-style restart interactively |
| Copilot CLI combines user, repo and agent files with no precedence and warns to "avoid conflicting instructions" | GitHub docs [S15] | Single source of truth: the shim only points to AGENTS.md; no rules duplicated |
| `@` file references only work in `copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, not `*.instructions.md` | GitHub docs [S15] | Put references in AGENTS.md; keep instruction files self-contained |
| Instruction files not applied in one IDE but applied in another (JetBrains AGENTS.md) | Docs matrix vs changelog contradiction [S16][S38] | Shim file (4.3) until the spike settles it |
| llms.txt published but never fetched | Ahrefs 2026-06 study [S14] | Treat as generated by-product; do not maintain by hand |
| OKF v0.1 → v0.2 renamed `timestamp` → `generated.at` and body `# Citations` → `sources` | Google Cloud blog [S2] | Pin `okf_version` in root `index.md`; lint script maps legacy fields |
| OKF reference agent requires Gemini/Vertex credentials | OKF README [S40] | Do not use it; the `wiki-maintain` skill under Copilot CLI is our producer |

## 9. Scaling considerations

- **Token budget per task**: with the layout in 4.8 an agent loads AGENTS.md (≤150 lines), skill metadata for all skills (~100 tokens each), one activated skill (<5k tokens), the root `index.md` and a handful of concept pages. The knowledge bundle can grow without growing the per-task prompt, because loading is index-driven, not "read everything" — the same argument Karpathy makes for index.md over embeddings [S28].
- **Many repos**: one bundle per repo plus a central bundle; the Pages job aggregates at build time; no cross-repo runtime dependency. OKF explicitly supports "hostable in any git repo ... subdirectory" [S1].
- **Drift and staleness**: `stale_after` and `status` are queryable; a scheduled CI sweep lists stale pages, and OKF v0.2 trust tiers let consumers "filter by trust tier" [S2]. Lulla et al. suggest instruction files reduce runtime and tokens (28.64% / 16.58%) once present [S27], so upkeep cost is offset by cheaper subsequent tasks — if the instruction file stays small.
- **Incremental vs full regeneration**: OKF's one-file-per-concept makes incremental updates diff-local; a full rebuild is only for schema migrations (`WIKI_ACTION=rebuild`).
- **Concurrency**: `resource_group` in CI serialises wiki writes per repo; interactive developer edits go through MRs like code.
- **Large monorepos**: nested AGENTS.md (Copilot, GitLab Duo) and sub-directory `index.md` (OKF) both scale by locality.

## 10. Effort and cost estimate

| Item | Estimate | Notes |
|------|----------|-------|
| Bootstrap (one-off) | 2-3 person-days for templates (AGENTS.md, shim, 5 skills, custom agent, lint script, Quartz pipeline); then ~0.5 person-day per repo for the interactive bootstrap run and review | Copilot's "Generate Agent Instructions" gives a draft to cut down [S38]. |
| Per-commit / per-MR run | One `copilot -p` invocation ≈ 1 premium request with the default model (Copilot CLI: "one request with default model") [S47]; more with multi-step tool use ❓; wall time minutes | Copilot Business monthly premium-request allowance not on the fetched page; commonly cited 300/user/month ❓ [memory]; overage $0.04/request [S47]. |
| Ongoing maintenance per week | ~1-2 h per team: reviewing wiki MRs, marking pages `verified`, pruning AGENTS.md | The lint job removes most mechanical checking. |
| Infrastructure | GitLab CI runner minutes for lint + update + Pages; no new services | Webhook service only if ADR-04 is chosen. |
| Licensing / seats | Existing Copilot Business seats; **one extra seat for a bot account if licence-compliant ❓** | GitHub ToS permits machine accounts [S30]; Copilot seat docs say seats are "assigned to a unique user account" [S29]; the March 2026 Generative AI Services Terms have no clause on machine accounts [S41]. Needs written confirmation from GitHub. GitLab Duo (Premium/Ultimate) is *not* required. |

## 11. Open questions and spike plan

| # | Question | Smallest experiment |
|---|---|---|
| Q1 | Does Copilot in **JetBrains** (PyCharm) load `AGENTS.md` and nested `AGENTS.md` in Chat and agent mode? Docs say no, changelog says yes [S16][S38]. | Put a distinctive instruction only in AGENTS.md; ask Copilot Chat and agent mode in PyCharm to echo it; repeat with `.github/copilot-instructions.md` removed. |
| Q2 | Are **Agent Skills** picked up by Copilot in JetBrains (preview) and by Copilot CLI from `.agents/skills`? | Add the `wiki-maintain` skill; run `/skills` in the CLI and trigger by description in PyCharm. |
| Q3 | May a **GitHub machine account** hold a Copilot Business seat and be used from GitLab CI via `COPILOT_GITHUB_TOKEN`? | Written question to the GitHub account manager citing the seat doc and ToS §B.3; meanwhile prototype with a named developer's fine-grained PAT ("Copilot Requests" permission) [S23]. |
| Q4 | Does `copilot -p --agent wiki-maintainer --no-ask-user` complete a real wiki update non-interactively inside a `node:24` GitLab runner, and which `--allow-tool` identifiers are needed? | One-repo CI job with `--share` transcript artifact. |
| Q5 | Quartz link rewriting: can OKF bundle-relative links be rendered correctly after aggregation across repos? | Build the Pages site from two repos' `docs/wiki`; check 20 links. |
| Q6 | Does GitLab Duo (if ever licensed) follow a `skills -> .agents/skills` symlink? | Only if Duo is bought; otherwise moot. |
| Q7 | Cross-bundle references in OKF: is there any convention emerging (issue tracker) or do we standardise full URLs in `resource:`? | Read the 9 open issues on the OKF repo; file one if absent. |
| Q8 | Does the Copilot cost per automated run stay ≈1 premium request with tool use? | Measure over 20 runs on the Business plan's usage report. |

## 12. Verdict

**Fit score 7/10.** The approach answers the two questions the other ADRs cannot: what shape the knowledge takes on disk so that *any* agent can use it (R3), and how it stays host-independent (R7). It is fully consumable by Copilot on the CLI and VS Code today, and by GitLab Duo, Gemini CLI, Claude Code and Codex without re-authoring. It loses points because (a) it is a file-format decision, not an execution model — R4 and R5 are only met when combined with ADR-01/02/04 and a GitLab pipeline form; (b) the "Google standard" the owner had in mind is OKF, which is real but very young, single-vendor and data-catalogue-oriented — adopt its frontmatter conventions, not its tooling; (c) Copilot's support is inconsistent on the owner's own IDE (JetBrains) and the CI licence question is open. Confidence is *medium*: all key product claims were read from primary docs, but two are contradictory (JetBrains AGENTS.md) and one is unanswerable from public documents (bot seat).

**Choose this when** the team accepts that the wiki is the source and instruction files are thin entry points, and wants to insure against a future switch from Copilot to autonomous agents or GitLab Duo.

**Combines well with**: ADR-01 (local hook execution) and ADR-02 (CI execution) as the runtime for `copilot -p`; ADR-04 (webhook service) for the issue-based instruction channel; any Karpathy-style LLM-wiki ADR, since OKF is by Google's own description a formalisation of that pattern [S1]. It should be treated as a **cross-cutting recommendation**: whichever approach is chosen, store its pages as an OKF bundle and expose them through AGENTS.md + Skills.

## 13. Sources

1. [S1] "How the Open Knowledge Format can improve data sharing", Sam McVeety & Amir Hormati, Google Cloud Blog, 2026-06-12, https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing — OKF v0.1 definition, design principles, relation to Karpathy's LLM wiki, reference implementations. [fetched]
2. [S2] "OKF v0.2 adds trust signals", McVeety & Hormati, Google Cloud Blog, 2026-07-25, https://cloud.google.com/blog/products/data-analytics/okf-v0-2-adds-trust-signals — v0.2 fields, trust tiers, renames, consumers, no governance body. [fetched]
3. [S3] OKF SPEC.md v0.2, GoogleCloudPlatform, 2026, https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md (raw fetched) — definitions, required/optional fields, linking, conformance, versioning. [fetched]
4. [S4] Repository GoogleCloudPlatform/open-knowledge-format, https://github.com/GoogleCloudPlatform/open-knowledge-format — Apache-2.0, 246 stars, 9 forks, 9 issues, directory layout. [fetched]
5. [S5] Third-party coverage confirming OKF naming: Analytics Vidhya (2026-07), Suganthan, MarkTechPost (2026-06-16), Search Engine Journal, Semrush, MindStudio — https://www.analyticsvidhya.com/blog/2026/07/open-knowledge-format-okf/ , https://www.marktechpost.com/2026/06/16/google-cloud-introduces-open-knowledge-format-okf-a-vendor-neutral-markdown-spec-for-giving-ai-agents-curated-context/ [snippet]
6. [S6] agents.md, Agentic AI Foundation, https://agents.md/ — definition, stewardship, nested precedence, 60k+ projects, supporter list (Copilot, Gemini CLI, Jules, Junie, …). [fetched]
7. [S7] "Linux Foundation Announces the Formation of the Agentic AI Foundation", Linux Foundation, 2025-12-09, https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation — MCP/goose/AGENTS.md donations; Google Platinum member. [fetched]
8. [S8] "Gemini CLI Skills & Plugins Guide (2026)", alirezarezvani.github.io, https://alirezarezvani.github.io/claude-skills/guides/gemini-cli-skills-guide/ — statement that Agent Skills were "initially brought to life by Anthropic". [snippet]
9. [S9] Agent Skills specification, agentskills.io, https://agentskills.io/specification — frontmatter constraints, directory layout, progressive-disclosure token guidance, `skills-ref validate`. [fetched]
10. [S10] "About agent skills", GitHub Docs, https://docs.github.com/en/copilot/concepts/agents/about-agent-skills — open standard; supported surfaces incl. JetBrains agent mode; repo locations. [fetched]
11. [S11] "Adding agent skills for GitHub Copilot CLI", GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills — skill directories, activation, `copilot skill add`, `gh skill`. [fetched]
12. [S12] "Custom skills" (Copilot SDK), GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/skills — `skillDirectories`, SDK languages. [fetched]
13. [S13] llms.txt proposal, Jeremy Howard / Answer.AI, 2024-09, v2 2026-08, https://llmstxt.org/ — format rules, llms-full.txt, adoption. [fetched]
14. [S14] "We Analyzed 137K Sites: 97% of llms.txt Files Never Get Read", Ahrefs, 2026-06-15, https://ahrefs.com/blog/llmstxt-study/ — 28% publish, 97% zero requests. [fetched]
15. [S15] "Adding custom instructions for GitHub Copilot CLI", GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions — files read, nested discovery, `applyTo`, `excludeAgent`, no precedence, no live reload, `@` references. [fetched]
16. [S16] "Custom instructions support" reference matrix and "Adding repository custom instructions", GitHub Docs, https://docs.github.com/en/copilot/reference/custom-instructions-support and https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions — per-surface support table (JetBrains Chat: AGENTS.md ✗), nearest-AGENTS.md precedence, "no longer than 2 pages". [fetched]
17. [S17] MCP specification 2025-06-18, "Resources", https://modelcontextprotocol.io/specification/2025-06-18/server/resources — application-driven model, list/read/templates/subscribe, annotations. [fetched]
18. [S18] "GitLab MCP server", GitLab Docs, https://docs.gitlab.com/user/model_context_protocol/mcp_server/ — Free tier (19.2), Beta, OAuth DCR, Copilot-in-VS-Code setup. [fetched]
19. [S19] A2A Protocol site, https://a2a-protocol.org/latest/ — Google-originated, Linux Foundation, v1.0, unrelated to documentation. [fetched]
20. [S20] "GEMINI.md context files", Gemini CLI docs, https://geminicli.com/docs/cli/gemini-md/ — `context.fileName` may include `AGENTS.md`; `@file` imports. [fetched]
21. [S21] "Agent Skills", Gemini CLI docs, https://geminicli.com/docs/cli/skills/ — `.gemini/skills` / `.agents/skills`, consent-based activation, based on agentskills.io. [fetched]
22. [S22] "Running GitHub Copilot CLI programmatically", GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically — `-p`, `-s`, `--no-ask-user`, `COPILOT_GITHUB_TOKEN`. [fetched]
23. [S23] "Automating tasks with Copilot CLI and GitHub Actions", GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/automate-with-actions — fine-grained PAT with "Copilot Requests", billing to a seat, `npm install -g @github/copilot`, recommendation of Agentic Workflows. [fetched]
24. [S24] Gloaguen, Mündler, Müller, Raychev, Vechev, "Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?", arXiv:2602.11988, 2026-02-12 (rev. 2026-06-23), https://arxiv.org/abs/2602.11988 — no success gain, +20% cost, overviews unhelpful. [fetched]
25. [S25] ETH Zürich SRI Lab publication page for the same paper, MemAgents@ICLR 2026, https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd — affiliation and venue. [fetched]
26. [S26] dos Santos, Costa, Montandon, Silva, Valente, "Configuration Smells in AGENTS.md Files", arXiv:2606.15828, 2026-06-14, https://arxiv.org/abs/2606.15828 — six smells; 62% / 42% / 35% prevalence. [fetched]
27. [S27] Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude, "On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents", arXiv:2601.20404, 2026-01-28, https://arxiv.org/abs/2601.20404 — 28.64% runtime, 16.58% tokens. [fetched]
28. [S28] Andrej Karpathy, "LLM Wiki" gist, 2026-04-04, https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f — raw/wiki/schema layers, index.md, log.md, ingest/query/lint. [fetched]
29. [S29] "GitHub Copilot seat assignment", GitHub Docs, https://docs.github.com/en/copilot/reference/copilot-billing/seat-assignment — "assigned to a unique user account"; silent on machine accounts. [fetched]
30. [S30] GitHub Terms of Service §B.3, https://docs.github.com/en/site-policy/github-terms/github-terms-of-service — bots not permitted; machine accounts permitted for automated tasks; one person per login. [fetched]
31. [S31] "CI/CD pipelines" (run manually, prefill variables, `options`), GitLab Docs, https://docs.gitlab.com/ci/pipelines/ — YAML for `description`/`options`/`value`, trigger tokens. [fetched]
32. [S32] "Use custom instructions in VS Code", VS Code docs, https://code.visualstudio.com/docs/copilot/customization/custom-instructions — `chat.useAgentsMdFile`, `chat.useNestedAgentsMdFiles` (experimental), `chat.useClaudeMdFile`, precedence, links between files. [fetched]
33. [S33] "AGENTS.md", GitLab Duo Agent Platform docs, https://docs.gitlab.com/user/duo_agent_platform/customize/agents_md/ — locations, subdirectory reading, surfaces, Premium/Ultimate, versions 18.7/18.8/18.11. [fetched]
34. [S34] "Hosting", Quartz v5 docs, https://quartz.jzhao.xyz/hosting — GitLab Pages `.gitlab-ci.yml` (`node:24`, `npx quartz build`, `public`), Pages private by default. [fetched]
35. [S35] "Agent Skills", GitLab Duo docs, https://docs.gitlab.com/user/duo_agent_platform/customize/agent_skills/ — supports agentskills.io spec; project-level `skills/<name>/`; user-level `~/.agents/skills`; 18.10+/19.0+. [fetched]
36. [S36] "Custom agents configuration", GitHub Docs, https://docs.github.com/en/copilot/reference/custom-agents-configuration — `.agent.md` fields, 30,000-char body, surfaces. [fetched]
37. [S37] "GitHub Copilot CLI programmatic reference", GitHub Docs, https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference — full flag list and token precedence. [fetched]
38. [S38] "Major agentic capabilities improvements in GitHub Copilot for JetBrains IDEs", GitHub Changelog, 2026-03-11, https://github.blog/changelog/2026-03-11-major-agentic-capabilities-improvements-in-github-copilot-for-jetbrains-ides/ — AGENTS.md/CLAUDE.md support, nested option, Generate Agent Instructions, `/memory`. [fetched]
39. [S39] "Copilot customization cheat sheet", GitHub Docs, https://docs.github.com/en/copilot/reference/customization-cheat-sheet — feature-by-surface table (skills: JetBrains preview), file locations. [fetched]
40. [S40] OKF README, https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/README.md (raw fetched) — reference agent needs `GEMINI_API_KEY` or Vertex AI + BigQuery; no validator; no adopter list. [fetched]
41. [S41] "GitHub Generative AI Services Terms" (effective 2026-03, supersedes Copilot Product Specific Terms), https://github.com/customer-terms/github-generative-ai-services-terms and deprecated https://github.com/customer-terms/github-copilot-product-specific-terms — no clause on machine accounts or automation. [fetched]
42. [S42] "Setting up github copilot on gitlab hosted repositories and pipelines", GitHub Community discussion #66976, staff answer 2024-03-06, https://github.com/orgs/community/discussions/66976 — Business works anywhere; Enterprise features need GitHub-hosted code. [fetched]
43. [S43] "Adding organization custom instructions", GitHub Docs, https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-organization-instructions — GitHub.com-only surfaces. [fetched]
44. [S44] "Google's Mueller Says llms.txt Can't Help LLMs Differentiate Sites", Search Engine Journal, 2026, https://www.searchenginejournal.com/googles-mueller-says-llms-txt-cant-help-llms-differentiate-sites/579304/ — "temporary crutch" quote. [snippet]
45. [S45] "MCP servers in VS Code", VS Code docs, https://code.visualstudio.com/docs/copilot/customization/mcp-servers — "Add Context > MCP Resources", `.vscode/mcp.json`. [fetched]
46. [S46] "The research is in: your AGENTS.md is probably too long", Upsun Developer, 2026, https://developer.upsun.com/posts/ai/agents-md-less-is-more — practical include/skip list, re-reading failure story. [fetched]
47. [S47] "Copilot requests" (premium requests), GitHub Docs, https://docs.github.com/en/copilot/concepts/billing/copilot-requests — CLI = one request with default model; overage $0.04. Business allowance not on page. [fetched]
48. [S48] "Introducing Copilot CLI agent and unified sessions view in GitHub Copilot for JetBrains IDEs", GitHub Changelog, 2026-05-13, https://github.blog/changelog/2026-05-13-introducing-copilot-cli-agent-and-unified-sessions-view-in-github-copilot-for-jetbrains-ides/ — delegation to local Copilot CLI (preview), `~/.copilot/agents`, Business policy gate. [fetched]
49. [S49] "What is OKF?", GitBook Blog, 2026-06-18 (upd. 2026-09-02), https://www.gitbook.com/blog/what-is-okf-open-knowledge-format — vendor positioning; no product implementation. [fetched]
50. [S50] GitLab issue #584017 "Docs: Add AGENTS.md documentation and unified custom instructions overview for GitLab Duo", https://gitlab.com/gitlab-org/gitlab/-/issues/584017 — existence only (HTTP 503 on fetch). [snippet]
51. [S51] MADR (Markdown Any Decision Records) as the ADR template convention, https://adr.github.io/madr/ — used for `docs/adr/` layout. [memory]
52. [S52] Copilot Business premium-request allowance (300/user/month) — widely cited, not on the fetched billing page. [memory] ❓
