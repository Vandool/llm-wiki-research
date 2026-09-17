---
id: ADR-10
title: GitLab-native alternative: GitLab Wiki plus GitLab Duo Agent Platform (flows and agents) as the maintainer
status: rejected        # 2026-09-02: fails hard constraint R6 (GitLab Duo is not GitHub Copilot)
date: 2026-09-02
researcher: researcher-adr-10
fit_score: 3        # overall fit against ../requirements.md, justified in section 12
confidence: medium   # how well the key claims are verified against fetched sources
requirement_ratings: {R1: "✅", R2: "✅", R3: "🟡", R4: "🟡", R5: "✅", R6: "❌", R7: "✅", R8: "✅"}   # same symbols as section 5
tags: [gitlab-duo, agent-platform, flows, custom-agents, gitlab-wiki, gitlab-pages, quartz, benchmark, violates-R6, future-option]
---

# ADR-10: GitLab-native alternative: GitLab Wiki plus GitLab Duo Agent Platform (flows and agents) as the maintainer

<!--
Uniform template for all approach ADRs in llm-wiki/approaches/.
Keep ALL headings, in this order, with these numbers. Add sub-sections freely.
Target length: 250-600 lines. Prefer tables and short paragraphs.
Mark unverified claims with ❓ and say what would verify them.
Never invent product features, URLs, or paper titles; if a search finds nothing, say so.
-->

## 1. Summary

This ADR evaluates the path the platform vendor itself offers: keep the LLM-maintained repository wiki as Markdown (in-repo `wiki/` directory, optionally mirrored into the git-backed GitLab Wiki), let **GitLab Duo Agent Platform** (custom flows, custom agents, event triggers, Duo CLI) do the maintenance, and publish it with Quartz on GitLab Pages. The idea is Karpathy's "LLM Wiki" pattern (gist, April 2026: raw sources, an LLM-owned wiki, a schema file, `index.md` + `log.md`, ingest/query/lint operations [59]) applied to code repositories, executed by GitLab's own agents. Maturity as of 2026-09: Agent Platform GA since GitLab 18.8 (2026-01-15), custom flows GA since 19.2 (2026-07-16), event triggers expanded through 19.1–19.4, self-hosted models GA for self-managed, usage billed in GitLab Credits. **Verdict for us: technically the most integrated option on the table and a good benchmark, but it fails the hard constraint R6 today** — Duo routes prompts through GitLab's AI Gateway to Anthropic/Google/OpenAI models (or to a self-hosted model, which R6 also excludes) and it is not GitHub Copilot. It also has no push/commit trigger, so R4 needs a workaround. Keep it as the documented "plan B / future option" and design the Copilot-based approach so its artefacts carry over.

## 2. Context

The owner has asked for an LLM-maintained wiki that serves coding agents and humans (R1), acts as the context layer for the whole AI pipeline (R2), works across many frontend and backend repositories (R3), is bootstrapped once and then updated by hook-triggered agents (R4), can be re-triggered or instructed through a form (R5), and is served on GitLab Pages (R8). Two hard constraints shape everything: only GitHub Copilot may be used as the LLM (R6), and the code lives on GitLab, not GitHub (R7).

ADR-10 exists because R7 makes GitLab's own AI the "obvious" candidate, and because the product owner should see what a native path would look like, what it costs, and exactly which policy would have to change. It is deliberately evaluated as (a) a benchmark against which the Copilot-based approaches (ADR-01/02/03) can be judged, and (b) a migration target if the R6 policy is ever amended. No background docs exist yet in `../background/` at the time of writing; the Karpathy gist is cited directly [59].

## 3. The approach

### 3.1 Origin and provenance

| Item | Detail | Source |
|------|--------|--------|
| Wiki pattern | Andrej Karpathy, "LLM Wiki" gist, created 2026-04-04, still being updated (last 2026-09-02). Three layers (raw sources, LLM-owned wiki, schema file such as `CLAUDE.md`/`AGENTS.md`), three operations (ingest, query, lint), two navigation files (`index.md`, `log.md`). Explicitly abstract; no licence stated on the gist. | [59] |
| Maintainer | GitLab Duo Agent Platform (formerly "Duo Workflow"). GA in GitLab 18.8 on 2026-01-15; Premium and Ultimate; GitLab.com, Self-Managed, Dedicated. | [1][39] |
| Flow engine | Flow Registry v1 specification, open documentation in the `ai-assist` repo (GitLab's AI Gateway / Duo Workflow service). | [5] |
| Store | GitLab Wiki (each wiki is a separate Git repository; project wikis Free+, group wikis Premium/Ultimate) or plain Markdown in the code repository. | [33][34] |
| UI | GitLab Pages (Free+) with Quartz (documented `.gitlab-ci.yml` on the Quartz site). | [37][38] |
| Activity | Monthly GitLab releases 18.8 → 19.3 each added Agent Platform features (triggers, custom flows GA, Duo CLI GA, Flow Creator agent, credits usage caps). Vendor-driven, high activity. | [39]-[43] |
| Spin-offs | Community: `satomic/gitlab-copilot-coding-agent` (Copilot CLI inside GitLab CI, 42 stars) is the closest "Copilot on GitLab" bridge and matters for the migration story in section 4.6. | [58] |

### 3.2 How it works (architecture)

Components and data flow:

- **Trigger** (GitLab-side event: mention/assign of a service account, MR created/ready/approved/conflict, pipeline state, work item created/status changed) starts a **flow session**. [7]
- **Flow definition** (YAML, flow registry v1) lives in the **AI Catalog** (project-managed, semver-versioned, visibility Private/Restricted/Public) or, for external agents only, at a **configuration path** in the repo such as `.gitlab/duo/flows/claude.yaml` (behind flag `ai_catalog_create_third_party_flows`). [3][7][10][12]
- **Execution**: flows started from the GitLab UI or by a trigger run **as a CI/CD job** ("workloads") on GitLab-hosted runners (GitLab.com, on by default) or on your own instance/group runner tagged `gitlab--duo` with a docker/kubernetes executor (shell executor not supported). The job clones the repo (`coding_environment: full`) and runs the agent loop, calling the **GitLab AI Gateway** (cloud.gitlab.com for GitLab-managed models, or a local AI Gateway for self-hosted models). Flows started in the IDE run locally. [6][4][24]
- **Identity**: every flow acts under a **composite identity** = service account `ai-<flow>-<group>` (Developer role) + the triggering human; commits show the service account "on behalf of" the human; access is the intersection of both. [11]
- **Output**: the agent reads/writes files in the checkout, creates commits/MRs/notes via tools (`create_commit`, `create_merge_request`, `create_merge_request_note`, ...). Agent branches follow `^duo/(fix|feature|refactor|docs)/.*` and may need branch rules. [5][10][46]
- **Models**: GitLab-managed models via the AI Gateway; default for agentic chat/custom agents "Claude Sonnet 4.6", selectable per top-level group by an Owner (Claude 4.x/5, Gemini 3.x Flash, GPT-5.x). Data goes to sub-processors Anthropic, Google (Gemini Enterprise Agent Platform), OpenAI, Fireworks (Codestral); no training; some models have limited vendor-side retention. [13][31]
- **Billing**: GitLab Credits ($1 list per credit); non-human subjects (the flow's service account) get no included credits and draw from the Monthly Commitment Pool / On-Demand. [28]

```
  developer                   GitLab (SaaS or self-managed)                       LLM side
 ──────────                 ───────────────────────────────                   ───────────────
 push / merge MR ──► pipeline ──► [Trigger: Pipeline=Passed | MR=Approved] ─┐
 @ai-wiki-flow "re-run" ─► [Trigger: Mention/Assign] ──────────────────────┤
 issue form ──────────────► [Trigger: Work item created] ──────────────────┤
                                                                            ▼
                                  flow session (composite identity: ai-wiki-flow-<group> + human)
                                                                            │
                                  CI job "workloads" on runner tag gitlab--duo (or hosted)
                                  ├─ clone repo (coding_environment: full)
                                  ├─ AgentComponent loop: read_file/list_dir/find_files/edit_file ...
                                  │      prompts ◄── AGENTS.md, .gitlab/duo/chat-rules.md, skills/  ──► AI Gateway ──► Anthropic / Google / OpenAI
                                  │                                                                     (or local AI Gateway ──► vLLM / Bedrock / Azure)
                                  └─ create_commit + create_merge_request (branch duo/docs/wiki-...)
                                                                            │
                          wiki/*.md, index.md, log.md updated ──► MR ──► merge ──► Pages pipeline (Quartz) ──► https://<group>.gitlab.io/<wiki-site>
```

### 3.3 Wiki content model it implies

The Karpathy pattern maps onto a repository like this (per repo, tool-agnostic Markdown so that Duo, Copilot, and humans all read the same files):

| Layer | Location | Purpose |
|-------|----------|---------|
| Schema | `AGENTS.md` (root, nested allowed), `.gitlab/duo/chat-rules.md`, `skills/<name>/SKILL.md` | Tells any agent (Duo honours all three; Copilot honours `AGENTS.md`) how the wiki is structured and when to update it. GitLab supports the AGENTS.md spec in Chat (18.7) and flows (18.8), project-level skills since 18.10, custom rules since 18.2. [17][18][19] |
| Wiki | `wiki/` with `index.md` (catalog, one line per page), `log.md` (append-only, `## [YYYY-MM-DD] <op> | <title>`), `overview.md` (non-technical, for the PO), `architecture/`, `modules/<module>.md`, `apis/`, `events/`, `decisions/`, `runbooks/` | Agent-owned pages with YAML frontmatter (`title`, `audience: dev|po|agent`, `sources`, `last_verified_sha`, `owner`). |
| Raw sources | The code itself, MR descriptions, issues, pipeline logs (read through tools, never copied) | Immutable "source of truth" per the gist. |
| Cross-repo hub | Central `platform-wiki` project: `contracts/`, `events/`, `ownership.md`, `services.md` | Aggregates per-repo wikis (see 3.6). |

GitLab Wiki specifics if the wiki is mirrored there: pages are files in `<project>.wiki.git`, Markdown/AsciiDoc/RDoc/Org supported, `_sidebar` page customises navigation, front-matter titles exist but sit behind flags disabled by default (16.7), `templates/` directory supported, REST API `GET/POST/PUT/DELETE /projects/:id/wikis[/:slug]` plus attachments. [33][35]

**Agent readability of the two stores** (this is the decisive point):

| Consumer | In-repo `wiki/*.md` | GitLab Wiki (`.wiki.git`) |
|----------|---------------------|---------------------------|
| Duo Agentic Chat (UI/IDE) | ✅ "your entire project and all of its files tracked by Git"; wiki not listed as context [14][15][16] | ❌ no wiki context or tool documented [14][15] |
| Duo flows (registry v1 tools) | ✅ `read_file`, `get_repository_file(s)`, `list_repository_tree` (cross-project) [5] | ❌ no wiki tool in the v1 spec; only via `run_command` + git clone or REST API with `GITLAB_TOKEN` ❓ |
| GitLab MCP server (beta) for external clients incl. GitHub Copilot in VS Code | ✅ `get_repository_file`, `semantic_code_search` [22] | 🟡 `list_wiki_pages` added in 19.3 (list only, no page read/write) [22] |
| GitLab Orbit (ex-Knowledge Graph, beta 19.1) | 🟡 indexes code entities in 12 languages; Markdown/wiki indexing not documented [23] | ❌ not documented |
| GitHub Copilot (local checkout, CLI, IDE) | ✅ ordinary files | 🟡 only if the wiki repo is cloned alongside |
| Humans | via Pages/Quartz or repo browser | ✅ native wiki UI, search (advanced search on self-managed; GitLab.com global search excludes wikis [36]) |

Conclusion: **in-repo Markdown is the primary store; GitLab Wiki is at most a human-facing mirror written by the flow through the Wikis API.**

### 3.4 Trigger and automation model

Available trigger event types as of the current docs (versions are GitLab minor releases) [7][41]:

| Event | Since | Notes for the wiki use case |
|-------|-------|-----------------------------|
| Mention of service account in issue/MR comment | 18.3 (GA 18.8) | Manual re-run with free-text instructions (`context:goal` = comment text) |
| Assign / Assign reviewer | 18.5 | Alternative manual trigger; goal = IID |
| Pipeline events (Running/Passed/Failed/Canceled) | 18.9 experiment, GA 19.1 | **Closest substitute for a push hook**: a "Passed" pipeline on the default branch after merge; goal = full pipeline webhook payload |
| Merge request: Approved / Marked ready / Merge conflict | 19.0–19.1 | Pre-merge docs update on approval |
| Merge request: Created | 19.4 (docs) | 19.4 is not released as of 2026-09-02 ❓ (expected mid-September per monthly cadence) |
| Work item: Created / Status changed | 19.1 / 19.2 | Issue-form-driven instructions |
| **Push / commit** | not available | Epic "Create Stage Trigger Expansion" (opened 2026-01-29, still open) lists "Code Pushed" in Phase 1 (Q1–Q2 2026); not shipped [45] |
| **Schedule** | not available | Use a GitLab scheduled pipeline + Pipeline event trigger, or Duo CLI headless in a scheduled job [20] |
| External webhook | not available | — |

Triggers are created in the project UI (**AI > Triggers**), need Maintainer/Owner, one condition at a time, a service account, and either an AI Catalog flow or a configuration path. "A trigger cannot be created for a custom agent or foundational agent" — only flows and external agents. [7]

Loop prevention and concurrency (nothing built in; must be designed):
- The flow's own commit/MR re-fires "Pipeline Passed" / "MR Created". Guard inside the flow: first step inspects the pipeline payload (`user.username` = `ai-wiki-flow-<group>`, or commit title prefix `docs(wiki):`) and ends; alternatively skip the pipeline for wiki-only commits (`rules: changes`) so no event fires.
- Concurrent merges → parallel flow sessions → conflicting wiki edits. Mitigation: always open an MR (never push to default), let the second run rebase; or batch via a scheduled pipeline (hourly) instead of per-merge. `resource_group` cannot be set on GitLab-generated flow jobs ❓.
- Credits: each run bills the pool; set **usage caps** (GA 19.3) and alert on the Credits dashboard. [28][43]

### 3.5 Human retry / instruction channel ("the form")

- **Comment as form**: `@ai-wiki-flow-<group> Re-index the payments module; the retry policy changed in !412` on any issue or MR. The whole comment becomes `context:goal` (`Input: ... Context: {Issue IID: n}`). [4]
- **Issue template as form**: an issue template `wiki-update.md` with fields (scope, pages, instructions) + trigger "Work item created" filtered by the flow prompt on a label/title prefix (filtering by label is not a trigger condition; the flow must check and exit). [7]
- **Manual pipeline as form** (no Duo trigger needed): CI job with `when: manual` and pipeline variables (`WIKI_SCOPE`, `WIKI_INSTRUCTIONS`) running **GitLab Duo CLI in headless mode**; the "Run pipeline" page is the form. Duo CLI GA 19.2, Premium/Ultimate, supports AGENTS.md/skills, headless mode "for runners, scripts, and other automated workflows". Exact headless flags not verified ❓ (docs page `/user/gitlab_duo_cli/use/` not fetched). [20][42]
- **Flow Creator agent** (19.3) lets a non-engineer describe a flow in plain language and get runnable YAML — useful for the PO to adjust the wiki flow without editing prompts by hand. [43]

### 3.6 Multi-repo / microservice fit

- Per-repo `wiki/` maintained by one shared flow: create the flow once in a group-level managing project, visibility **Restricted** (19.3) so it is not world-public, and enable it in up to 100 projects at once (19.2). Each project gets the group's service account added as Developer. [3][10][12]
- Cross-repo reads from a flow are native: `get_repository_file`, `get_repository_files` (glob, capped at 50 results per call), `list_repository_tree` take a project id; "the service account can access all projects that both you have access to and the flow has been added to". [3][5]
- Hub: a central `platform-wiki` project whose flow is triggered by the same events in the service repos ❓ (a trigger belongs to the project where the event happens; cross-project fan-out needs the service repo's flow to also write into the hub via `create_commit` on another project id — supported by the API tools but not demonstrated in docs). Simpler: hub pipeline (scheduled) aggregates `wiki/` from all repos with `git archive`/API and runs a lint flow.
- Contracts/APIs/events: hub pages `contracts/<producer>-<consumer>.md`, `events/<topic>.md`, `ownership.md` with CODEOWNERS-derived data.
- Future autonomous agents: composite identity, tool approvals, network policies (Ultimate, 19.0), usage caps, and Orbit's cross-project graph point in the right direction; custom flows cannot yet call custom agents ("Custom flows create and use their own agents based on their YAML configuration") so prompts are duplicated between chat agents and flows. [3][23][40]

### 3.7 Publishing / UI

- **Quartz on GitLab Pages**: Quartz documents a `.gitlab-ci.yml` (`image: node:24`, `npx quartz build`, `pages` job publishing `public/`). Put Quartz in the `platform-wiki` project; pull each repo's `wiki/` into `content/<repo>/` in a pre-build job. Pages sites default to private (group members only) which suits internal docs. [38][37]
- **GitLab Wiki UI** as a second human surface: mirror `wiki/*.md` into the group wiki via the Wikis API at the end of the flow ❓ (a wiki repo cannot run its own CI pipelines — [memory], verify). Group wikis need Premium/Ultimate. [34][35]
- Non-technical PO pages: `overview.md`/`glossary.md` written with `audience: po`, surfaced as the Quartz landing page.

## 4. Concrete implementation sketch for our environment

Assumes: GitLab Premium or Ultimate (SaaS or self-managed ≥ 19.2), a Monthly Commitment Pool of GitLab Credits, runners with docker executor and outbound access to `cloud.gitlab.com` (or a local AI Gateway), and — crucially — **an amended R6** (see 4.7). Anything below marked ❓ is syntax or behaviour not verified against a fetched source.

### 4.1 Directory layout (per service repository)

```
AGENTS.md                       # schema: how the wiki is structured, when to update, style
.gitlab/duo/chat-rules.md       # short rules for Duo chat/agents/flows (project-level custom rules)
skills/wiki-maintainer/SKILL.md # GitLab Agent Skills location (note: not .claude/skills)
wiki/
  index.md                      # catalog: one line per page + summary
  log.md                        # append-only: ## [2026-09-02] ingest | MR !412 retry policy
  overview.md                   # audience: po
  architecture.md
  modules/<module>.md
  apis/<api>.md
  events/<topic>.md
  decisions/ADR-*.md
```

### 4.2 Custom flow (AI Catalog, flow registry v1)

Verified keys: `version`, `environment: ambient` (only value allowed in custom flows), `components`, `prompts` (inline), `routers`, `flow.entry_point`, `coding_environment` (19.3). `model` in prompts is rejected; the model comes from the group's model selection. [4][5]

```yaml
version: "v1"
environment: ambient
coding_environment: full            # clone repo so read_file/edit_file act on a checkout (19.3)
components:
  - name: "guard"
    type: AgentComponent
    prompt_id: "guard_prompt"
    inputs:
      - "context:goal"                 # pipeline webhook payload | comment text | IID
      - from: "context:project_id"
        as: "project_id"
    toolset: ["get_pipeline"]          # ❓ tool name from tools_registry.py not verified
    max_cycles: 3
  - name: "wiki_maintainer"
    type: AgentComponent
    prompt_id: "wiki_prompt"
    inputs:
      - "context:goal"
      - from: "context:project_id"
        as: "project_id"
      - from: "context:inputs.user_rule"   # AGENTS.md content, per GitLab blog example
        as: "agents_dot_md"
        optional: true
    toolset:
      - "read_file"
      - "list_dir"
      - "find_files"
      - "edit_file"
      - "create_file_with_contents"
      - "get_merge_request"
      - "get_repository_files"          # cross-repo reads for contracts/events
      - "create_commit"                 # names as used in GitLab's published example [46]
      - "create_merge_request"
      - "create_merge_request_note":
          "internal": true
    max_cycles: 40
    ui_log_events: ["on_agent_final_answer", "on_tool_execution_success", "on_tool_execution_failed"]
prompts:
  - prompt_id: "guard_prompt"
    name: "Wiki loop guard"
    prompt_template:                    # ❓ exact prompt-template keys (system/user) not verified
      system: "If the triggering pipeline was started by user ai-wiki-flow-* or the commit title starts with 'docs(wiki):', answer STOP. Otherwise answer CONTINUE with the merged MR IID and changed paths."
      user: "{{goal}}"
  - prompt_id: "wiki_prompt"
    name: "Wiki maintainer"
    prompt_template:
      system: |
        You maintain wiki/ per {{agents_dot_md}}. Read wiki/index.md first. Update only pages affected
        by the change, keep frontmatter, append one line to wiki/log.md, never touch code.
        Commit to branch duo/docs/wiki-<short-sha> with title 'docs(wiki): ...' and open an MR.
      user: "{{goal}}"
routers:
  - from: "guard"
    to: "wiki_maintainer"               # ❓ conditional routing on guard output needs a router condition; syntax not verified
  - from: "wiki_maintainer"
    to: "end"
flow:
  entry_point: "guard"
```

Create it under **AI > Flows > New flow** in the managing project (or with the VS Code flow builder, beta 19.3, or ask the Flow Creator agent), set visibility Restricted, then **Enable** it in each service project and pick trigger events. [3][43]

### 4.3 Triggers (UI, not YAML)

Per project: **AI > Triggers > New flow trigger** → condition "On an event" → `Pipeline events` with action `Passed` (post-merge update) and `Mention` (manual re-run) → service account `ai-wiki-flow-<group>` → Configuration source `AI Catalog` → the flow above. The Merge request `Approved` event is the pre-merge alternative. [7]

CI guard so wiki-only commits do not re-fire the trigger:

```yaml
# .gitlab-ci.yml (service repo)
workflow:
  rules:
    - if: '$CI_COMMIT_TITLE =~ /^docs\(wiki\):/'
      when: never
    - when: always
```

### 4.4 Alternative without flow triggers: Duo CLI headless in CI (also the "form")

```yaml
wiki-update:
  stage: docs
  image: registry.example.com/duo-cli:latest      # image with glab + duo installed ❓
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'          # manual form: Run pipeline with variables
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_TITLE !~ /^docs\(wiki\):/'
  variables:
    WIKI_INSTRUCTIONS: ""                          # free text from the Run-pipeline form
  script:
    - duo ... "Update wiki/ for $CI_COMMIT_SHORT_SHA. $WIKI_INSTRUCTIONS"   # ❓ headless flags not verified
    - git checkout -b "duo/docs/wiki-$CI_COMMIT_SHORT_SHA" && git add wiki && git commit -m "docs(wiki): update for $CI_COMMIT_SHORT_SHA"
    - glab mr create --fill --yes
```

Authentication of the Duo CLI inside CI (token type, credit attribution to a service account) is not verified ❓; the release note only says headless mode exists "for CI/CD". [20][42]

### 4.5 Hub project and Pages

`platform-wiki` project: scheduled pipeline (daily) that (1) fetches `wiki/` from every service repo via `GET /projects/:id/repository/archive?path=wiki`, (2) writes `content/<repo>/`, (3) runs the lint flow (Karpathy's "lint": orphans, contradictions, stale `last_verified_sha`) via Duo CLI headless or a mention on a tracking issue, (4) builds Quartz and publishes Pages. Quartz job per the Quartz docs (node:24, `npx quartz build`, artifact `public`). [38]

### 4.6 Migration from a Copilot-based approach (ADR-01/02/03)

| Artefact in the Copilot design | Carries over? | What changes |
|--------------------------------|---------------|--------------|
| `wiki/*.md`, `index.md`, `log.md`, frontmatter | ✅ 100 % | Nothing; same files are read by Duo tools |
| `AGENTS.md` (root + nested) | ✅ | GitLab honours the AGENTS.md spec in Chat and flows [17] |
| `.github/copilot-instructions.md` | 🟡 | Copy into `.gitlab/duo/chat-rules.md` [18] |
| Copilot custom agents (`.github/agents/*.agent.md`) | 🟡 | Re-create as GitLab custom agents in the AI Catalog (UI: system prompt + tools; no in-repo file format) [9] |
| Prompt files (`.github/prompts/*.prompt.md`) | 🟡 | Inline them into flow `prompts:` |
| Agent Skills (`SKILL.md`) | 🟡 | Same spec; GitLab reads `<root>/skills/<name>/SKILL.md` — move or symlink [19] |
| CI job running `copilot -p ...` headless | 🟡 | Replace with a flow + trigger, or Duo CLI headless in the same job |
| Webhook relay (satomic-style) | ❌ not needed | Flow triggers replace the relay [58] |
| Quartz site / Pages job | ✅ | Unchanged |
| "Form" (issue template / manual pipeline) | ✅ | Unchanged; optionally add Mention trigger |

Reverse direction is equally cheap: because the store is plain Markdown plus `AGENTS.md`, nothing in this ADR locks the wiki to Duo.

### 4.7 The minimal policy change that makes this viable

R6 today: "Developers only have GitHub Copilot ... no third-party LLM SaaS ... self-hosted model is out." Minimal amendment: **"Approved AI providers are GitHub Copilot and GitLab Duo (Agent Platform) under the company's GitLab subscription; developers still hold no personal API keys."** Rationale for the owner: like Copilot, Duo is a platform vendor's managed service (GitLab is the data controller's processor; models are sub-processors; no training on customer data; contractual terms via GitLab's AI Functionality Terms) [31]. If the concern is specifically "code leaves the company", the self-managed + Duo Self-Hosted variant keeps inference in-house (vLLM/Bedrock/Azure), but R6 as written also excludes that, so it needs the same one-line amendment. Commercially: Premium/Ultimate subscription + Monthly Commitment Pool of credits (SaaS/online) or the "GitLab Duo Agent Platform Self-Hosted" seat add-on (offline licence). [28][29]

## 5. Requirements check

Use exactly these IDs and the legend from `../requirements.md`.

| ID | Requirement (short) | Rating | Evidence / notes |
|----|---------------------|--------|------------------|
| R1 | Dual audience (agents + devs + PO) | ✅ | Markdown in-repo is readable by Duo chat/flows (repository files, `read_file`/`get_repository_file`), by Copilot, and by humans via Pages or the GitLab UI; PO pages are a prompt-design matter. Rating assumes in-repo store; a GitLab-Wiki-only store would be 🟡 because no Duo context source or flow tool reads wiki pages [5][14][15][22]. |
| R2 | Context layer for whole AI dev pipeline | ✅ | `AGENTS.md`, `.gitlab/duo/chat-rules.md`, skills, custom agents and flows can all be pointed at `wiki/index.md`; foundational flows (Developer, Code Review, Fix CI/CD, Security Review) read repo files and honour AGENTS.md (except Code Review Flow) [8][17]. |
| R3 | Multi-repo microservices, future autonomous agents | 🟡 | Flows read across projects (`get_repository_files`, service account spans enabled projects), catalog items enable in up to 100 projects, Orbit (beta) is cross-project; but the hub aggregation and cross-project writes are custom, custom flows cannot reuse custom agents, and 19.4 features are unreleased [3][5][23][12]. |
| R4 | Bootstrap once, dev-owned upkeep, hook-triggered auto-update | 🟡 | Bootstrap = one manual flow run per repo. No push/commit trigger exists; workaround = Pipeline "Passed" or MR "Approved" trigger, or Duo CLI headless in CI; loop guard must be built [7][45][20]. |
| R5 | Human retry / instructions via a form | ✅ | Mention/assign the service account with free text (goal = comment), Work-item-created trigger with an issue template, or manual pipeline with variables [4][7]. |
| R6 | Copilot-only (no API keys, no direct model access) | ❌ | Duo is not Copilot; prompts go through GitLab's AI Gateway to Anthropic/Google/OpenAI sub-processors [31]; self-hosted models (also excluded by R6) require self-managed + add-on [24][29]. BYO keys on GitLab.com exist only for external agents Amazon Q/Gemini, and Claude Code/Codex external agents use GitLab-managed credentials [10] — none of which is Copilot. Viable only after the policy change in 4.7. |
| R7 | GitLab, not GitHub | ✅ | Entirely GitLab-native (triggers, service accounts, CI runners, Pages) [1][7][37]. |
| R8 | UI on GitLab Pages (Quartz) | ✅ | Quartz documents a GitLab Pages pipeline; aggregation across repos via the hub project [38]. GitLab-Wiki mirror to Pages would need an extra mirror job ❓. |

## 6. Pros

- Most integrated option: triggers, identity (composite identity, audit trail), runners, credits, network policies and usage caps are all first-party; no webhook relay or bot-token juggling [6][7][11][40][43].
- Flow definitions are versioned, shareable across the group (Restricted visibility), enable-able in 100 projects at once — good fit for many microservice repos [3][12].
- Cross-repo reads are built into the tool set (`get_repository_files`, `list_repository_tree` with project id) [5].
- Same Markdown + `AGENTS.md` + Skills conventions as Copilot/Claude Code, so the wiki is portable in both directions [17][19].
- Works on GitLab.com, Self-Managed and Dedicated; self-hosted models for regulated setups (vLLM, Bedrock, Azure OpenAI; any OpenAI-compatible endpoint as "compatible model") [24][25][26].
- Model choice per top-level group (Claude, Gemini, GPT) without holding keys [13].
- Human "form" comes for free (mention/assign/issue), plus Flow Creator for non-engineers [4][43].

## 7. Cons and risks

- **Violates R6 today**; requires a policy decision and a GitLab subscription tier/credits the owner may not have (tier is unknown) [1][28].
- **No push or schedule trigger**; pipeline/MR events are proxies and need loop guards; epic for "Code Pushed" open since January 2026 with no delivery date [7][45].
- **Cost uncertainty**: usage-billed credits; forum reports of $3.5–5 per Code Review flow run and the $12/user promo gone after two reviews plus ten chats; the service account has no included credits [28][50-f].
- **Immaturity/churn**: 18.8 → 19.3 changed flags, names ("Duo Workflow" → Agent Platform, Knowledge Graph → Orbit), and rules monthly; custom flows only GA since July 2026; 19.4 trigger already documented but unreleased [42][7].
- Flow YAML lives in the AI Catalog UI, not in the repo (in-repo config path is flag-gated and only for external agents) — weaker GitOps story than a `.github/workflows` file [7][10].
- Custom flows cannot call custom agents; prompt duplication between chat agents and flows [3].
- Wiki store mismatch: GitLab Wiki is invisible to Duo agents; only in-repo Markdown works, which some teams find odd for a "wiki" [14][22].
- Self-managed needs docker/kubernetes runners tagged `gitlab--duo` with outbound access; offline licences need the Self-Hosted add-on and GPUs [6][24].
- Vendor lock-in for the orchestration layer (not for the content).
- Composite identity requires the triggering human to have access; automated pipeline-event runs are attributed to whoever pushed ❓ (behaviour for non-interactive triggers not verified).

## 8. Known problems reported by practitioners, and fixes

| Problem (source, date) | Fix / mitigation |
|------------------------|------------------|
| Custom flow fires only on `@mention`, not on assign/assign-reviewer, with a group-level service account (forum, 2025-12-10) [50-a] | Use the service account GitLab creates when enabling the flow (`ai-<flow>-<group>`), not a hand-made one; assign events were added in 18.5 and require that account [3][7]. |
| "External" agent type missing in the UI; YAML in `.gitlab/duo/flows/` not picked up (forum, 2026-02-06) [50-b] | Turn on "experiment and beta features" for the group/instance; files are indexed only from the **default branch**; at that time Duo Enterprise seats were required; today the configuration-path option is flag-gated (`ai_catalog_create_third_party_flows`) [7][32]. |
| Empty AI Catalog on Self-Managed 18.8.2 Premium; unclear how to invoke flows (forum, 2026-01-29) [50-d] | Foundational flows are invoked by assigning the flow's service account as reviewer/assignee; catalog seeding for external agents needs `gitlab-rake gitlab:ai_catalog:seed_external_agents`; check Duo is turned on for the instance [10][12]. |
| Duo job fails pulling Git LFS objects on `gitlab-duo` runner (forum, 2025-12-29) [50-e] | Exclude LFS content from the wiki flow's needs (`coding_environment: none` + API tools) or use a custom image with LFS configured ❓; unresolved on the forum. |
| "Expensive AI": $4–5 per code-review run, promo credits exhausted quickly (forum, 2026-01-27, staff acknowledged) [50-f] | Use cheaper models for the wiki flow (credit table: `claude-4.5-haiku` 6.7 calls/credit vs `gpt-5` 3.3), cap `max_cycles`, batch runs, set usage caps (19.3) [28][43]. |
| "Too confusing": agents vs flows, cannot reuse a custom agent in a flow, sharing required Public (forum, 2026-01-30) [50-c] | Restricted visibility added in 19.3; keep one prompt source in `AGENTS.md`/skills that both agents and flows include; the agent-in-flow limitation remains [3][43]. |
| Credit-only customers refused support ("no subscription") (forum, 2026-07-03) [50-g] | Buy the credits under a Premium/Ultimate subscription, not stand-alone. |
| Self-hosted with Ollama and zero credits? (forum, 2026-03-07, unanswered) [50-h] | Docs: online licences bill self-hosted model calls at 8 calls/credit; only offline licences with the Self-Hosted add-on are seat-priced; Ollama is not a listed platform (vLLM is; any OpenAI-compatible endpoint is "compatible" without guarantees) [28][25][26]. |
| Flow config read only from default branch; predefined CI variables cannot configure `agent-config.yml` (docs) [6] | Develop flows in the AI Catalog with versions; test via **Run > Execute** in the execution console before enabling triggers [3]. |

## 9. Scaling considerations

- **Token/credit budget**: a flow bills every LLM call ("one flow makes one or many calls"); failed GitLab.com runs are free, self-hosted calls are billed as started. Budget per run ≈ `max_cycles × calls-per-credit⁻¹`; with a Haiku-class model 40 cycles ≈ 6 credits ≈ $6 list ❓ (Claude Sonnet/Opus multipliers were not captured from the table). Use incremental scope (only files in the merged MR diff, `get_merge_request` → paths) rather than whole-repo passes; run full "lint" passes weekly, not per merge [28].
- **Repository size**: `get_repository_files` caps results at 50 per call and the flow clone is a full checkout; for large monoliths prefer `coding_environment: none` + targeted API reads, and keep `wiki/index.md` small enough to read first (Karpathy: index-first navigation works to "hundreds of pages") [5][59].
- **Many repos**: one Restricted flow enabled in ≤100 projects per action; per-project triggers still need creation (UI or API ❓ — no trigger API verified). Credits are billed at the top-level namespace, so cost scales with merge volume across all repos [12][28].
- **Drift/staleness**: store `last_verified_sha` in frontmatter; the lint flow flags pages whose sources changed; `log.md` gives the timeline. Orbit could eventually answer "which pages reference symbols that no longer exist" but does not index Markdown today [23].
- **Concurrency**: parallel sessions per merge; MR-based writes plus rebase; or serialize via a scheduled hub pipeline.
- **Cache**: flow execution supports a dependency cache keyed on up to two files; irrelevant for docs-only flows [6].
- **AI Catalog limits**: flow YAML has a maximum configuration size (value not captured ❓) — keep prompts short and move guidance into `AGENTS.md`/skills read at run time [4][12].

## 10. Effort and cost estimate

| Item | Estimate | Notes |
|------|----------|-------|
| Bootstrap (one-off) | 3–5 person-days engineering + ~$5–20 credits per repository ❓ | Write `AGENTS.md`, flow YAML, triggers, hub pipeline, Quartz; one full flow run per repo (forum data: $3.5–5 per Code Review flow run on premium models [50-f]; cheaper model and capped cycles bring it down). |
| Per-commit / per-MR run | $0.5–5 credits per run ❓; 1–3 min runner time | Incremental scope; Pipeline-Passed trigger fires once per merged MR. 100 merges/week ≈ $50–500/week list before commitment discounts. |
| Ongoing maintenance per week | 1–3 h | Reviewing wiki MRs (or auto-merge with approval rules), prompt tuning after GitLab releases, credit monitoring. |
| Infrastructure | GitLab.com: none extra (hosted runners on by default). Self-managed: 1–2 docker-executor runners tagged `gitlab--duo` with outbound access; optional local AI Gateway + GPU (vLLM; e.g. 1× A100 40 GB for a 7B model, far more for the DAP-capable models listed) [6][25][26] | Pages: existing. |
| Licensing / seats | Premium $29/user/month (annual) incl. $12 promo credits/user/month; Ultimate incl. $24 promo credits/user/month (Ultimate list price not captured from the page; historically $99/user/month [memory] ❓); credits $1 list on-demand, Monthly Commitment Pool with tiered discounts; Duo Pro/Enterprise seats ($19/$39 per snippet [61]) are **not** needed for flows; offline self-managed needs the "GitLab Duo Agent Platform Self-Hosted" seat add-on (price ❓). Copilot Business seats ($19/user/month, 1,900 AI credits) stay for developers [30][28][29][55]. |

## 11. Open questions and spike plan

| # | Question | Smallest experiment |
|---|----------|--------------------|
| 1 | Will the owner amend R6 to include GitLab Duo? Which GitLab tier/offering do we actually have? | Ask; read the subscription page (Admin > Subscription or group Billing). Blocks everything else. |
| 2 | Does the "Pipeline events: Passed" trigger fire for post-merge default-branch pipelines and pass enough payload to find the merged MR? | 1-day spike: trial group on GitLab.com (Ultimate trial gives evaluation credits [28]), one repo, the flow from 4.2 with `max_cycles: 5`, merge a trivial MR, inspect `context:goal`. |
| 3 | Real credit cost per wiki run with Haiku- vs Sonnet-class models | Same spike; read the Credits dashboard per session; try 5 runs each. |
| 4 | Loop guard: does a `docs(wiki):` MR from the service account re-trigger the flow, and does the `workflow: rules` skip work? | Same spike; observe AI > Sessions. |
| 5 | Duo CLI headless in CI: auth method, flags, credit attribution (human vs service account) | Fetch `/user/gitlab_duo_cli/use/` and `/set_up/`; run one job with `-p`-style prompt ❓. |
| 6 | Exact prompt-template keys and conditional router syntax in flow registry v1 | Read `docs/flow_registry/index.md` and the `duo_workflow_service/.../flows/configs/` examples in the ai-assist repo [5]; or ask the Flow Creator agent to generate the YAML [43]. |
| 7 | Can a flow in repo A commit to repo B (hub) with the composite identity? | Spike: enable the flow in both projects; use `create_commit` with the hub project id. |
| 8 | GitLab Wiki mirror: can a CI job push to `<project>.wiki.git` with a project access token, and is Pages build from a wiki repo possible? | 2-hour spike with a dummy project. |
| 9 | Trigger creation via API/Terraform for 30+ projects | Look for `ai_flow_triggers` in the REST/GraphQL docs ❓; else script the UI. |
| 10 | Copilot side: does GitHub's Copilot Product Specific Terms allow a Copilot seat on a machine account for the interim Copilot approach? | Fetch the terms page (returned HTTP 500 during this research) and ask the GitHub account manager; GitHub ToS permits machine accounts and paid orgs "may only provide access to as many Personal Accounts as your subscription allows" [56][57]. |

## 12. Verdict

**Fit score 3/10** against `../requirements.md` as written. The approach would score roughly 8/10 on R1–R5, R7, R8 (native triggers, identity, cross-repo tools, form-like channels, Pages), losing points only for the missing push/schedule trigger and the UI-bound flow definitions. But R6 is a hard constraint and is failed outright: GitLab Duo is a third-party managed LLM service (Anthropic/Google/OpenAI behind GitLab's AI Gateway), not GitHub Copilot, and its self-hosted variant is excluded by the same clause. A hard-constraint failure caps the score regardless of technical merit.

Choose this approach when (a) the AI policy is amended to "Copilot and GitLab Duo", (b) the company is or becomes a GitLab Premium/Ultimate customer with a credits commitment, and (c) the team values first-party triggers and audit trail over the ability to keep flow definitions in git. Until then use it as the **benchmark**: any Copilot-based design (ADR-01/02/03) should produce exactly the artefacts listed in 4.6 (`wiki/` Markdown with `index.md`/`log.md`, `AGENTS.md`, skills, Quartz hub) so that switching maintainers later is a one-day change rather than a migration.

Combines well with: ADR-01/02/03 (same content model; Duo becomes an additional or replacement maintainer), any Quartz-on-Pages publishing ADR (identical pipeline), and a future ADR on GitLab Orbit/MCP if cross-repo code intelligence for agents is wanted. GitHub Copilot in VS Code can already consume GitLab repositories and the GitLab MCP server (beta) today, which is the bridge between the two worlds [21][22].

## 13. Sources

1. GitLab Docs — "GitLab Duo Agent Platform" overview (tiers, offerings, GA 18.8, ways to use agents, credits note). https://docs.gitlab.com/user/duo_agent_platform/ — `[fetched]`
2. GitLab Docs — "Flows" (foundational vs custom, run in CI/CD, custom flows GA 19.2). https://docs.gitlab.com/user/duo_agent_platform/flows/ — `[fetched]`
3. GitLab Docs — "Custom flows" (creation in project/AI Catalog/VS Code flow builder, service account naming, cannot call custom agents, Restricted visibility 19.3). https://docs.gitlab.com/user/duo_agent_platform/flows/custom/ — `[fetched]`
4. GitLab Docs — "Custom flow YAML schema" (goal values per trigger, `coding_environment`, restricted fields). https://docs.gitlab.com/user/duo_agent_platform/flows/custom_flows_schema/ — `[fetched]`
5. GitLab, ai-assist repository — "Flow Registry Framework v1 version documentation" (YAML structure, component types, tools such as `read_file`, `get_repository_files`, tool options, inline prompts, examples). https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/blob/main/docs/flow_registry/v1.md — `[fetched]` (raw file)
6. GitLab Docs — "Flow execution" (CI/CD execution, hosted runners, `gitlab--duo` tag, executors, default-branch config, cache, sandbox images). https://docs.gitlab.com/user/duo_agent_platform/flows/execution/ — `[fetched]`
7. GitLab Docs — "Triggers" (event types with versions, UI steps, configuration path flag, not for agents). https://docs.gitlab.com/user/duo_agent_platform/triggers/ — `[fetched]`
8. GitLab Docs — "Foundational flows" (list; no documentation flow). https://docs.gitlab.com/user/duo_agent_platform/flows/foundational_flows/ — `[fetched]`
9. GitLab Docs — "Agents" and "Custom agents" (UI creation, system prompt, tools, enablement; no in-repo file format). https://docs.gitlab.com/user/duo_agent_platform/agents/ and https://docs.gitlab.com/user/duo_agent_platform/agents/custom/ — `[fetched]`
10. GitLab Docs — "External agents" (Claude Code/Codex with GitLab-managed credentials, Amazon Q/Gemini with customer credentials, `injectGatewayToken`, CI/CD variables, `.gitlab/duo/flows/claude.yaml`, agent branch pattern, seed rake task). https://docs.gitlab.com/user/duo_agent_platform/agents/external/ — `[fetched]`
11. GitLab Docs — "Composite identity" (service account + human, where used, Developer role). https://docs.gitlab.com/user/duo_agent_platform/composite_identity/ — `[fetched]`
12. GitLab Docs — "AI Catalog" (versioning, pinning, instance prerequisites). https://docs.gitlab.com/user/duo_agent_platform/ai_catalog/ — `[fetched]`
13. GitLab Docs — "Model selection" (selectable Claude/Gemini/GPT models, defaults, group Owner). https://docs.gitlab.com/user/duo_agent_platform/model_selection/ — `[fetched]`
14. GitLab Docs — "GitLab Duo Agent Platform contextual awareness" (context list; no wiki). https://docs.gitlab.com/user/duo_agent_platform/context/ — `[fetched]`
15. GitLab Docs — "GitLab Duo contextual awareness" (context list; no wiki). https://docs.gitlab.com/user/gitlab_duo/context/ — `[fetched]`
16. GitLab Docs — "GitLab Duo Agentic Chat" (capabilities, tool approvals, Free tier with credits 18.10). https://docs.gitlab.com/user/gitlab_duo_chat/agentic_chat/ — `[fetched]`
17. GitLab Docs — "AGENTS.md customization files" (locations, nesting, Chat 18.7 / flows 18.8). https://docs.gitlab.com/user/duo_agent_platform/customize/agents_md/ — `[fetched]`
18. GitLab Docs — "Custom rules" (`.gitlab/duo/chat-rules.md`). https://docs.gitlab.com/user/duo_agent_platform/customize/custom_rules/ — `[fetched]`
19. GitLab Docs — "Agent Skills" (`<root>/skills/<name>/SKILL.md`, 18.10). https://docs.gitlab.com/user/duo_agent_platform/customize/agent_skills/ — `[fetched]`
20. GitLab Docs — "GitLab Duo CLI" (headless mode, glab/standalone install, customization files). https://docs.gitlab.com/user/gitlab_duo_cli/ — `[fetched]`
21. GitLab Docs — "MCP server" (beta, OAuth DCR, clients incl. GitHub Copilot in VS Code, Claude Code, Cursor). https://docs.gitlab.com/user/model_context_protocol/mcp_server/ — `[fetched]`
22. GitLab Docs — "MCP server tools" (tool list; `list_wiki_pages` introduced 19.3; `get_repository_file`, `semantic_code_search`). https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/ — `[fetched]`
23. GitLab Docs — "GitLab Orbit" (formerly Knowledge Graph; beta 19.1; languages; cross-project). https://docs.gitlab.com/orbit/ — `[fetched]`
24. GitLab Docs — "GitLab Duo Self-Hosted" (offerings, add-ons, feature status). https://docs.gitlab.com/administration/gitlab_duo_self_hosted/ — `[fetched]`
25. GitLab Docs — "Supported models and hardware requirements" (DAP model table, compatible models, hardware). https://docs.gitlab.com/administration/gitlab_duo_self_hosted/supported_models_and_hardware_requirements/ — `[fetched]`
26. GitLab Docs — "Supported LLM serving platforms" (vLLM, Bedrock, Azure OpenAI, LiteLLM-compatible). https://docs.gitlab.com/administration/gitlab_duo_self_hosted/supported_llm_serving_platforms/ — `[fetched]`
27. GitLab Docs — "Configure GitLab Duo features" (self-hosted Agent Platform access, GA 18.8, add-on for offline). https://docs.gitlab.com/administration/gitlab_duo_self_hosted/configure_duo_features/ — `[fetched]`
28. GitLab Docs — "GitLab Credits and usage billing" (credit types, $1 on-demand, non-human subjects, multipliers, failure billing, Free tier). https://docs.gitlab.com/subscriptions/gitlab_credits/ — `[fetched]`
29. GitLab Docs — "Subscription add-ons" (Duo Core/Pro/Enterprise, DAP Self-Hosted add-on, Core chat changes 2026-05-21). https://docs.gitlab.com/subscriptions/subscription-add-ons/ — `[fetched]`
30. GitLab — Pricing page (Premium $29/user/month annual, $12/$24 included promo credits, $1 per credit). https://about.gitlab.com/pricing/ — `[fetched]` (Ultimate list price not captured in extraction)
31. GitLab Docs — "GitLab Duo data usage" (sub-processors Anthropic, Fireworks, Gemini Enterprise Agent Platform, OpenAI; no training; retention). https://docs.gitlab.com/user/gitlab_duo/data_usage/ — `[fetched]`
32. GitLab Docs — "Turn GitLab Duo on or off" (instance/group settings, Duo Core, beta/experiment toggle). https://docs.gitlab.com/user/gitlab_duo/turn_on_off/ — `[fetched]`
33. GitLab Docs — "Wiki" (separate Git repo, formats, sidebar, front matter flags, templates). https://docs.gitlab.com/user/project/wiki/ — `[fetched]`
34. GitLab Docs — "Group wikis" (Premium/Ultimate). https://docs.gitlab.com/user/project/wiki/group/ — `[fetched]`
35. GitLab Docs — "Project wikis API" (endpoints). https://docs.gitlab.com/api/wikis/ — `[fetched]`
36. GitLab Docs — "Advanced search" (wiki scope; GitLab.com global search excludes wikis). https://docs.gitlab.com/user/search/advanced_search/ — `[fetched]`
37. GitLab Docs — "GitLab Pages" (tiers, domains). https://docs.gitlab.com/user/project/pages/ — `[fetched]`
38. Quartz — "Hosting" (GitLab Pages `.gitlab-ci.yml`, node:24, `npx quartz build`). https://quartz.jzhao.xyz/hosting — `[fetched]`
39. GitLab — "GitLab 18.8 release notes" (2026-01-15; Agent Platform GA; DAP for Self-Hosted offline GA, seat-based). https://docs.gitlab.com/releases/18/gitlab-18-8-released/ — `[fetched]`
40. GitLab — "GitLab 19.0 release notes" (2026-05-21; Duo Core usage billing; MR-ready trigger; network policies; open-source models). https://docs.gitlab.com/releases/19/gitlab-19-0-released/ — `[fetched]`
41. GitLab — "GitLab 19.1 release notes" (2026-06-18; new event triggers; custom flow validation). https://docs.gitlab.com/releases/19/gitlab-19-1-released/ — `[fetched]`
42. GitLab — "GitLab 19.2 release notes" (2026-07-16; Duo CLI GA; custom flows GA; ID tokens in flows). https://docs.gitlab.com/releases/19/gitlab-19-2-released/ — `[fetched]`
43. GitLab — "GitLab 19.3 release notes" (2026-08-20; Flow Creator agent; Restricted visibility; credits usage caps GA). https://docs.gitlab.com/releases/19/gitlab-19-3-released/ — `[fetched]`
44. GitLab.org Epic #20463 — "Bring Your Own Model for Duo Agent Platform" (opened 2026-01-13, updated 2026-08-03, open; two SKUs; target GA 18.9). https://gitlab.com/groups/gitlab-org/-/epics/20463 — `[fetched]` (via public REST API)
45. GitLab.org Epic #20654 — "Create Stage Trigger Expansion for GitLab Duo Agent Platform" (opened 2026-01-29, open; "Code Pushed" and other triggers planned). https://gitlab.com/groups/gitlab-org/-/epics/20654 — `[fetched]` (via public REST API)
46. Itzik Gan Baruch, GitLab Blog — "Understanding flows: Multi-agent workflows" (updated 2026-05-27; example custom flow YAML with `create_commit`/`create_merge_request` tools; AGENTS.md input). https://about.gitlab.com/blog/understanding-flows-multi-agent-workflows/ — `[fetched]`
47. GitLab Blog — "AI Catalog: discover and share agents" (visibility, managing project, versions). https://about.gitlab.com/blog/ai-catalog-discover-and-share-agents/ — `[fetched]`
48. GitLab Blog — "Introduction to GitLab Duo Agent Platform" (FAQ: self-hosted models since 18.8). https://about.gitlab.com/blog/introduction-to-gitlab-duo-agent-platform/ — `[fetched]`
49. GitLab Blog — "More AI models for GitLab Duo Agent Platform Self-Hosted" (2026-05-21; 19.0; hybrid self-hosted + managed). https://about.gitlab.com/blog/more-ai-models-for-duo-agent-platform-self-hosted/ — `[fetched]`
50. GitLab Forum threads (all `[fetched]` via Discourse JSON): (a) "Custom Automation Flows On Merge Request", 2025-12-10, https://forum.gitlab.com/t/custom-automation-flows-on-merge-request/131888; (b) "GitLab Duo External Agent - Missing UI Option and Configuration Questions", 2026-02-06, https://forum.gitlab.com/t/gitlab-duo-external-agent-missing-ui-option-and-configuration-questions/132637; (c) "AI duo platform thingy is just too confusing in the current state", 2026-01-30, https://forum.gitlab.com/t/ai-duo-platform-thingy-is-just-too-confusing-in-the-current-state/132547; (d) "Empty AI Catalog in GitLab 18.8.2 (Premium)", 2026-01-29, https://forum.gitlab.com/t/empty-ai-catalog-in-gitlab-18-8-2-premium-missing-foundational-agents/132515; (e) "Git LFS and Duo Jobs", 2025-12-29, https://forum.gitlab.com/t/git-lfs-and-duo-jobs/132111; (f) "Expensive AI", 2026-01-27, https://forum.gitlab.com/t/expensive-ai/132493; (g) "GitLab Duo stop working although buying credits every month", 2026-07-03, https://forum.gitlab.com/t/gitlab-duo-stop-working-although-buying-credits-every-month/134426; (h) "Gitlab Duo Agent Self Hosted and credits consumption", 2026-03-07, https://forum.gitlab.com/t/gitlab-duo-agent-self-hosted-and-credits-consumption/133084.
51. GitHub Docs — "About Copilot cloud agent" (runs in GitHub Actions on GitHub.com; integrations create PRs; no GitLab). https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent — `[fetched]`
52. GitHub Docs — "About GitHub Copilot CLI" (all plans if org policy enabled; programmatic `-p`). https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli — `[fetched]`
53. GitHub Docs — "Running GitHub Copilot CLI programmatically" (CI/CD use, `COPILOT_GITHUB_TOKEN`, `--allow-tool`, `--no-ask-user`). https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically — `[fetched]`
54. GitHub Docs — "Administering Copilot CLI for your enterprise" (policy, model controls, BYOK). https://docs.github.com/en/copilot/how-tos/copilot-cli/administer-copilot-cli-for-your-enterprise — `[fetched]`
55. GitHub Docs — "About billing for GitHub Copilot in organizations and enterprises" (Business $19 / 1,900 AI credits; Enterprise $39 / 3,900; seat = license for a user). https://docs.github.com/en/copilot/concepts/billing/organizations-and-enterprises — `[fetched]`
56. GitHub — "GitHub Terms of Service" (machine accounts permitted; one login per person; Section J AI Features). https://docs.github.com/en/site-policy/github-terms/github-terms-of-service — `[fetched]`
57. GitHub — "GitHub Copilot Product Specific Terms". https://github.com/customer-terms/github-copilot-product-specific-terms — `[snippet]` (page returned HTTP 500 twice during this research; bot-seat clause unverified ❓)
58. satomic — "gitlab-copilot-coding-agent" README (Copilot CLI in GitLab CI via webhook relay; fine-grained PAT with "Copilot Requests"). https://github.com/satomic/gitlab-copilot-coding-agent — `[fetched]` (raw README)
59. Andrej Karpathy — "LLM Wiki" gist (created 2026-04-04; architecture, operations, index/log). https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f — `[fetched]` (raw; gist URL confirmed via GitHub Gists API and [60])
60. Hjarni — "Andrej Karpathy's LLM Wiki gist, hosted" (blog; used only to confirm the gist link). https://hjarni.com/blog/karpathys-llm-wiki-is-right — `[fetched]`
61. Stackpick / eesel AI — GitLab Duo pricing summaries 2026 (Duo Pro ≈ $19, Duo Enterprise $39 per user/month; DAP GA with $1 credits). https://stackpick.net/pricing/gitlab-duo/ and https://www.eesel.ai/blog/gitlab-pricing — `[snippet]`
62. Cloudfresh — "GitLab Duo Agent Platform Is GA: What Changes for AI in the SDLC". https://cloudfresh.com/en/news/gitlab-duo-agent-platform-is-now-generally-available/ — `[snippet]`
63. Statement that GitLab wiki repositories do not run CI/CD pipelines — `[memory]`, unverified ❓ (verify with spike 8).
64. GitLab Ultimate list price ≈ $99/user/month — `[memory]`, unverified ❓ (pricing page fetched but the figure did not survive text extraction).
