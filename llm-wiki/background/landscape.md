---
title: "Landscape and literature survey: LLM-maintained repository wikis"
date: 2026-09-02
researcher: researcher-landscape
confidence: "High for §1, §5, §6, §8 (primary sources opened). Medium for §2, §4 (GitHub READMEs opened; star counts are a 2026-09-02 snapshot). Medium for §7 (arXiv abstract pages opened; venues taken from the abstract page or arXiv comments field). Low for items marked ❓ or [snippet]/[memory]."
---

# Landscape and literature survey: LLM-maintained repository wikis

Shared factual reference for the approach ADRs in `../approaches/`. Requirement IDs (R1–R8) refer to `../requirements.md`.
Source tags: **[fetched]** = page opened during this survey; **[snippet]** = seen only in a search-result snippet; **[memory]** = not verified online. ❓ marks any claim that could not be verified.

Note on tooling: the search budget for this session was exhausted after the first sweep; the remaining research was done by opening primary pages directly (GitHub, arXiv, arXiv API, HN Algolia API, vendor docs). Medium.com and HackerNoon block automated fetches (HTTP 403), so those posts are [snippet] only.

---

## 1. Karpathy's LLM Wiki idea

| Item | Fact | Source |
|---|---|---|
| Artefact | GitHub gist `llm-wiki.md`, titled on HN as *"LLM Wiki – example of an 'idea file'"* | [S1] [fetched], [S2] [fetched] |
| URL | https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | [S1] |
| Date | Gist created 2026-04-04; HN thread same day (296 points, 95 comments, HN id 47640875) | [S1], [S2] |
| Reach | X post in April 2026 with 16M+ views; gist at 5,000+ stars within days; "dozens" of re-implementations within two weeks | [S3] [fetched], [S4] [snippet] |
| Companion tools named | Obsidian (as "IDE"), Claude Code / OpenAI Codex (as "programmer"), `qmd` (local BM25+vector search), Marp, Dataview, git for storage | [S1] |

**What it is.** A pattern, not a product: instead of retrieving from raw documents at query time (RAG), an LLM agent *"incrementally builds and maintains a persistent wiki"* of Markdown files. The human curates sources and asks questions; the LLM does *"everything else"* — summarising, cross-referencing, keeping the index and log consistent. Karpathy frames it as a buildable Memex (Vannevar Bush, 1945): *"The part he couldn't solve was who does the maintenance. The LLM handles that."* [S1]

**Schema (three layers).** [S1]

```
my-kb/
├── raw/            # Layer 1: immutable sources (LLM reads, never writes)
│   └── assets/
└── wiki/           # Layer 2: LLM-owned pages
    ├── index.md    # content catalogue, one line per page
    ├── log.md      # append-only chronological record of ingests/queries/lint
    ├── overview.md
    ├── sources/    # one summary page per raw source
    ├── entities/   # people, orgs, systems
    ├── concepts/   # theories, methods, patterns
    └── analyses/   # comparisons, syntheses, filed query answers
CLAUDE.md           # Layer 3: the schema file — conventions + workflows the agent must follow
```

**The loop.** [S1]
- *Ingest*: read a new raw source, write its summary page, update/create entity and concept pages, fix cross-references, update `index.md`, append to `log.md`. *"A single source may update 10–15 wiki pages."*
- *Query*: consult `index.md`, read the relevant pages, answer with citations, and *file valuable answers back* as new pages so the wiki compounds.
- *Lint*: periodic health check for contradictions, stale claims, orphan pages, missing cross-references, and gaps worth researching.

**"Wiki instead of RAG" argument.** RAG must *"find and piece together the relevant fragments every time"*; the wiki does the synthesis once at ingest and keeps it current, so the artefact is *"persistent, compounding"*. [S1]

**Stated limitations and caveats.** [S1]
- Scale: the flat `index.md` works *"at moderate scale (~100 sources, ~hundreds of pages)"*; beyond that a search layer (e.g. `qmd`) is needed.
- Deliberately abstract: *"exact directory structure, schema conventions, page formats, tooling ... will depend on your domain, your preferences, and your LLM of choice."*
- Designed for *documents* as sources (articles, papers, data files), not for source code; there is no notion of code-change triggers, citations to lines, or freshness checks — those were added by spin-offs (§2) and by OpenWiki (§5).
- No token-cost analysis; maintenance is assumed cheap.
- Human remains the source curator; the wiki is single-user/single-agent in the original write-up.

---

## 2. Spin-offs and forks applied to code repositories (and the main general-purpose ones)

Snapshot 2026-09-02. Star counts are as shown on GitHub at fetch time. The GitHub topic `karpathy-llm-wiki` listed **42** repositories [S5] [fetched]; topics `llm-wiki` and `karpathy-wiki` also exist [S6] [snippet]. Around 30 distinct projects were examined; the ones below are the relevant subset.

### 2a. Code-repository-focused

| Project | Author | First seen | What it adds over the gist | Agents / providers | Activity, licence | Src |
|---|---|---|---|---|---|---|
| **langchain-ai/openwiki** — see §5 | LangChain | 2026-07-01 (HN) | Repo → `openwiki/` Markdown wiki, OKF v0.2 output, claims/evidence sidecars, `--update`, GitHub Actions / GitLab CI / Bitbucket examples that open PR/MR | 13 providers incl. **GitHub Copilot**, OpenAI, Anthropic, Gemini, Bedrock, OpenRouter, OpenAI-compatible (Ollama) | 16k★, v0.5.0 on 2026-09-01, MIT | [S7]–[S11] |
| **Egonex-AI/Understand-Anything** | Egonex-AI | 2026 | tree-sitter + LLM agents → JSON knowledge graph in `.ua/`, guided tours, semantic search, diff impact; incremental re-analysis; `--auto-update` via post-commit hook. Graph, not a wiki | Native: Claude Code, Cursor, VS Code + Copilot, **Copilot CLI**; 14+ others; Ollama for local | 81.3k★ (Sep 2026), MIT | [S12] [fetched] |
| **FSoft-AI4Code/CodeWiki** — see §4, §7 | FPT Software AI Center | 2025-10 | Research framework (ACL 2026): hierarchical decomposition, recursive agents, diagrams; `--update` incremental, `--compare-to` for CI; GitHub Pages viewer | OpenAI-compatible, Anthropic, Bedrock, Azure OpenAI, Atlas Cloud, **Claude Code CLI / Codex CLI "subscription mode"** | 1.7k★, MIT | [S13] [fetched] |
| **vouchdev/vouch** | vouchdev | 2026 | Git-native, review-gated KB: agents *propose* writes via MCP, humans approve; content-hashed sources, every claim cites evidence, append-only audit log, stored under `.vouch/` | Claude Code primary; adapters for Cursor, Codex, Zed, Windsurf, OpenClaw | 91★, Aug 2026, MIT | [S14] [fetched] |
| **mxmzb/autowiki** | mxmzb | 2026 | CLI to scaffold/maintain a Karpathy wiki *inside a project*; deterministic indexing/linking/lint; `--target claude` (managed CLAUDE.md block) or `--target generic` (AGENTS.md) | Claude Code or any AGENTS.md agent | 5★, Aug 2026, MIT | [S15] [fetched] |
| **christianb93/WikiSpec** | Christian B. | 2026-05 | Spec-driven development where each implemented change is archived and *ingested into the wiki*; later proposals/specs query the wiki | Claude primarily | 4★, MIT | [S16] [fetched] |
| **Pratiyush/llm-wiki** | Pratiyush | 2026 | Builds the wiki from *coding-session transcripts* (`.jsonl`); exports `llms.txt`, JSON-LD graph, static HTML site | Claude Code, Codex CLI (prod); Cursor, Gemini CLI, **Copilot Chat & CLI (beta)** | 383★, MIT | [S17] [fetched] |
| **barvhaim/pi-openwiki** | barvhaim | 2026-07-06 (HN) | OpenWiki re-implemented as a Pi coding-agent extension | Pi ≥ 0.80 | 8★, MIT | [S18] [fetched] |
| Balu Kosuri's "wiki from code" tool ❓ name | Balu Kosuri | 2026 | git commit as trigger; every claim cites `path:line`; git blob SHAs used to detect stale citations | not stated | Medium post only; repo name not verified | [S19] [snippet] |
| **nex-crm/wuphf** ❓ | nex-crm | 2026-04-25 (Show HN, 260 pts, 114 comments) | "A Karpathy-style LLM wiki your agents maintain (Markdown and Git)" | — | The GitHub URL now redirects to a different project (`najmuzzaman-mohammad/gawkbot`, a workflow-agent tool); treat the original as unavailable | [S20] [fetched], [S21] [fetched] |

### 2b. Agent-packaged general-purpose implementations (usable on a repo with a different schema file)

| Project | Author | Adds | Agents | Activity, licence | Src |
|---|---|---|---|---|---|
| **Astro-Han/karpathy-llm-wiki** | Astro-Han | Single installable Agent Skill (`npx add-skill`), ingest/query/lint, citation rules, "design boundary" doc; KB maintained daily since Apr 2026 | Claude Code, Cursor, Codex CLI, OpenCode (any agentskills.io tool) | 2.1k★, MIT | [S22] [fetched] |
| **SamurAIGPT/llm-wiki-agent** | SamurAIGPT | Schema files per agent (CLAUDE.md, AGENTS.md, GEMINI.md), contradiction detection at ingest, graph view, lint reports; "no API key needed" (runs inside the agent's subscription) | Claude Code, Codex/OpenCode, Gemini CLI | 3.5k★, MIT | [S23] [fetched] |
| **yugasun/llm-wiki-skills** | yugasun | Cross-platform `SKILL.md` installable via Claude plugin marketplace or `npx skills install` | Claude Code, **GitHub Copilot**, Codex | 6★, MIT | [S24] [fetched] |
| **SriSatyaLokesh/copilot-llm-wiki** | SriSatyaLokesh | Copilot-native template: schema lives in `.github/copilot-instructions.md`; `/ingest` in chat; "librarian" custom agent for Copilot CLI | **GitHub Copilot (VS Code, CLI)** | 12★, Apr 2026 | [S25] [fetched] |
| **lewislulu/llm-wiki-skill** | lewislulu | Skill for OpenClaw/Codex | Codex, OpenClaw | experimental | [S26] [snippet] |
| Hermes Agent bundled `llm-wiki` skill | Nous Research | Ingest/query/lint skill shipped with Hermes Agent v2.1.0; explicitly *not* for code (separate "codebase-inspection" skill) | Hermes | MIT | [S27] [fetched] |
| **rohitg00 "LLM Wiki v2"** (gist) | Rohit G | Confidence scores, supersession, decay, typed graph, hybrid search, event hooks, multi-agent scoping | any | updated 2026-08-31 | [S28] [fetched] |

### 2c. Obsidian-centred

| Project | Author | Adds | Agents | Activity, licence | Src |
|---|---|---|---|---|---|
| **AgriciDaniel/claude-obsidian** | AgriciDaniel | Self-organising vault; drop any source, Claude files it | Claude Code | 14.6k★, Aug 2026 | [S5] |
| **eugeniughelbur/obsidian-second-brain** | E. Ghelbur | 47 slash commands, write-back ingest, scheduled background maintenance agents, optional semantic search | Claude Code + 6 CLI agents | 4.3k★, v0.14 Jul 2026, MIT | [S29] [fetched] |
| **ekadetov/llm-wiki** | ekadetov | Claude Code plugin for an Obsidian vault | Claude Code | 107★, MIT | [S30] [fetched] |
| **ignromanov/llm-obsidian-wiki** | I. Romanov | 4 agents, 7 skills, 27 scripts, confidence-scored claims with source-drift detection | Claude Code | 20★, v0.4.0, MIT | [S31] [fetched] |
| **pssah4/vault-operator** | pssah4 | Obsidian plugin + MCP server; local vector index; provenance | Claude, ChatGPT, **Copilot**, Bedrock, Ollama, … | 246★, Apache-2.0 | [S32] [fetched] |
| MehmetGoekce/llm-wiki, shannhk/llm-wikid, 2233admin/obsidian-llm-wiki, ussumant/llm-wiki-compiler | various | L1/L2 cache; Logseq; 6-persona MCP team; topic compiler | Claude Code, Codex, OpenCode, Gemini CLI | not opened | [S6] [snippet] |

### 2d. Hosted / other

| Project | Notes | Src |
|---|---|---|
| **lucasastorian/llmwiki** — MCP server + REST API + Next.js UI; Claude via MCP; SQLite or Postgres/S3 | 1.6k★, Apache-2.0; personal docs, not code | [S33] [fetched] |
| **dcouple/openwiki** — Docker image running Claude Code over SSH/tmux to curate a private vault + public Astro site | 0★, licence "TBD"; **name collision with LangChain's OpenWiki** | [S34] [fetched] |
| **sillok-os/sillok** — "productised LLM Wiki" with typed pack registry and proposal-only 4-gate governance; MCP bridge for Claude Code/Cursor/Continue | 5★, alpha 0.3.0a1, Apache-2.0 | [S35] [fetched] |
| **thisismydesign/okf-lint** — linter for Google OKF bundles (v0.1) | 7★, MIT | [S36] [fetched] |
| Hjarni (hosted, MCP), CacheZero (npm), PageFly, mcptube, inkeep/open-knowledge (381-pt Show HN, AI-first Obsidian/Notion alternative) | personal-knowledge products citing the pattern | [S37] [fetched], [S20] |

**Observations for the ADRs.** (1) Only OpenWiki, Understand-Anything, CodeWiki, vouch, autowiki and WikiSpec treat *the repository* as the raw source; everything else treats documents as sources. (2) Copilot appears as a first-class provider or host in OpenWiki, Understand-Anything, Pratiyush/llm-wiki (beta), yugasun/llm-wiki-skills, copilot-llm-wiki and vault-operator. (3) The "no API key, run inside the coding agent's subscription" pattern (SamurAIGPT, CodeWiki "subscription mode", Astro-Han skill) is the closest analogue to the R6 constraint. (4) Review-gated writes (vouch, sillok, rosidotidev's Copilot variant) are the community's answer to trust.

---

## 3. Practitioner posts, talks and threads (2026)

| Date | Author / venue | Takeaway | Tag |
|---|---|---|---|
| 2026-04-04 | HN thread on the gist (296 pts / 95 comments) — https://news.ycombinator.com/item?id=47640875 | Received "less as a note-taking trick and more as an architectural pattern for agent workflows" | [S2] [fetched via Algolia API], [S38] [snippet] |
| 2026-04-08 | Evert Van den Bruel, Hjarni — https://hjarni.com/blog/karpathys-llm-wiki-is-right | "The pattern is right"; the *local* setup (one device, one LLM) is the friction, hence hosted + MCP | [S37] [fetched] |
| 2026-04-09 | Dylan Boudro, Starmorph — https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide | The schema file (CLAUDE.md) is the critical success factor; no vector DB needed at personal/team scale | [S3] [fetched] |
| 2026-04-13 | Jonadas, "Beyond Karpathy's LLM-Wiki: the necessity of cognitive governance" — https://www.jonadas.com/writing/essays/beyond-karpathys-llm-wiki | Argues for governance/review layers over the raw pattern | [S20] [snippet] |
| 2026-04-16 | Mehul Gupta, "Andrej Karpathy's LLM Wiki Is a Bad Idea" (Medium) | Contrarian take: maintenance and hallucination costs | [S20] [snippet] |
| 2026-04-25 | Show HN: nex-crm/wuphf (260 pts / 114 comments) — https://news.ycombinator.com/item?id=47899844 | Largest code-oriented spin-off discussion; repo since redirected (see §2a) ❓ | [S20] [fetched] |
| 2026-04-29 | Eugeniu Ghelbur, The AI Operator — https://theaioperator.io/p/i-rebuilt-karpathys-llm-wiki-heres | Append-only fails at scale; add write-back ingest, automatic reconciliation, scheduled maintenance agents, AI-first note structure | [S39] [fetched] |
| 2026-05 | Viktor Ponamarev, "The Wiki Is the Codebase" (Medium) | Frames the wiki as the primary artefact agents work from | [S40] [snippet] |
| 2026-05-23 | rosidotidev, DEV — https://dev.to/rosidotidev/karpathys-llm-wiki-no-code-with-claude-or-github-copilot-5fb0 | No-code Copilot variant using `.github/prompts/` and `.github/agents/`; **human-gated review queue** before integration | [S41] [fetched] |
| 2026 | Balu Kosuri, "How I turned Karpathy's LLM Wiki into a tool that writes wikis from code" (Medium) | git commit as trigger; `path:line` citations; blob-SHA freshness check | [S19] [snippet] |
| 2026 | HackerNoon, "Self-maintaining knowledge base for 6 projects using Claude Code" | Multi-project setup with Claude Code | [S42] [snippet] |
| 2026 | Leandro Bernardo, Towards AI, "I built Karpathy's LLM Wiki twice — once as code, once as a .md" | Code implementation vs pure-prompt implementation trade-offs | [S43] [snippet] |
| 2026-07 | Mike Written, "I tested 5 LLM Wiki implementations" (Medium) | Comparative review of community implementations | [S44] [snippet] |
| 2026-07-01 | HN: "OpenWiki: CLI that writes and maintains agent documentation for your codebase" (96 pts / 31 comments) — https://news.ycombinator.com/item?id=48752949 | First public appearance of LangChain's OpenWiki found | [S45] [fetched] |
| 2026-07-03 | Prahlad Menon, The Menon Lab — https://themenonlab.blog/blog/openwiki-langchain-agent-documentation | OpenWiki = tooling for the pattern applied to codebases (note: its claim that OpenWiki shipped "two days after" the gist conflicts with the July dates above ❓) | [S46] [fetched] |
| 2026-07 | Mehul Gupta, "LangChain OpenWiki: Karpathy's LLM Wiki in action" (Medium) | Walk-through of OpenWiki | [S47] [snippet] |
| 2026-06/07 | Marc Bara, "Google's new format for agent context: a standard, or just a folder?" (Medium) | Sceptical read of OKF | [S48] [snippet] |
| 2026 | gingonai Substack, "Build Karpathy's LLM KB in Copilot Cowork" | Copilot-hosted variant | [S49] [snippet] |
| 2026 | LangChain YouTube, "Introducing OpenWiki, an open source agent for repo documentation" — https://www.youtube.com/watch?v=nIVu3zfYprI | Official launch video (date not extractable) | [S50] [fetched, title only] |
| 2026-08-31 | Rohit G, "LLM Wiki v2" gist | Confidence, supersession, decay, hooks, multi-agent scoping | [S28] [fetched] |

---

## 4. Commercial and open-source repository-to-wiki generators

**DeepWiki / Devin Wiki (Cognition).** Launched 2025-04-25 [S51] [snippet]; Cognition's blog (2025-05-05) calls DeepWiki *"the free public version of Devin Wiki and Devin Search"*, with 50,000+ public GitHub repos indexed; any public repo via `deepwiki.com/<org>/<repo>` [S52] [fetched]. Private repositories require a Devin account; wiki generation has effort levels Low (free), Medium (~5–10 ACUs), High (~20–40 ACUs) [S53] [fetched]. Plans since 2026-04-14: Free, Pro $20/mo, Max $200/mo, Teams usage-based ($80/mo minimum), Enterprise; "DeepWiki and deepwiki.com will remain free with the existing generation experience" [S54] [fetched]. A public MCP server (`https://mcp.deepwiki.com/mcp`, tools `read_wiki_structure`, `read_wiki_contents`, `ask_question`) covers **public repos only**; private repos need the Devin MCP server with an API key [S55] [fetched]. **GitLab:** Devin integrates with GitLab ≥ 15.0, SaaS and self-managed (self-hosted GitLab requires Enterprise), for MRs and comments; the GitLab page does *not* mention DeepWiki/Devin Wiki, so wiki generation for GitLab-hosted private repos is ❓ [S56] [fetched]. Provider: Cognition's own hosted models; no bring-your-own-key and no Copilot route. Proprietary SaaS; no self-hosting.

**DeepWiki-Open (AsyncFuncAI).** MIT, 17.9k★ [S57] [fetched]. Self-hosted Docker (backend :8001, frontend :3000). Requires at least `GOOGLE_API_KEY` or `OPENAI_API_KEY`; also OpenRouter, Azure OpenAI, Ollama, LiteLLM proxy [S57], [S58] [fetched]. **GitLab:** supported for public repos by URL and for private repos via a personal access token entered in the UI; self-managed GitLab URL configuration not documented ❓ [S58]. Regenerates a wiki per request; incremental update behaviour is not documented ❓. No GitHub Copilot provider. Requires API keys → conflicts with R6 unless a Copilot-backed OpenAI-compatible proxy is used (licence question, see §5 and ADRs).

**CodeWiki (FSoft-AI4Code, ACL 2026).** MIT, 1.7k★ [S13] [fetched]. CLI `codewiki generate`; ten languages (Python, Java, JS, TS, C, C++, C#, Kotlin, PHP, Ruby); Python 3.12+, Node.js, git. Providers: OpenAI-compatible endpoints, Atlas Cloud, Anthropic, AWS Bedrock, Azure OpenAI, plus **"subscription mode" through Claude Code CLI or Codex CLI** (no API key). `--update` regenerates only changed modules; `--compare-to <commit>` for CI; optional GitHub-Pages HTML viewer and git branch creation. GitLab not mentioned (plain git, so a GitLab CI job is plausible ❓); no Copilot mode. Paper: §7 P3.

**OpenWiki (LangChain).** See §5. The only generator found that lists GitHub Copilot as a provider *and* ships a GitLab CI example.

**Understand-Anything (Egonex-AI).** MIT, 81.3k★ [S12] [fetched]. Produces a JSON knowledge graph (`.ua/knowledge-graph.json`) rather than a Markdown wiki; incremental; post-commit auto-update; runs natively inside Claude Code, Cursor, VS Code + Copilot and **Copilot CLI**; Ollama for local. GitLab not mentioned (host-agnostic). Relevant for R1 agent-side navigation, less so for the human-readable wiki in R1/R8.

**Google "Code Wiki".** `https://codewiki.google/` exists but the page returned only a "Code Wiki" shell to the fetcher; guessed announcement URLs on developers.googleblog.com and blog.google returned 404 ❓. From memory: a Google product (announced Nov 2025, public preview) that generates and refreshes wiki-style docs for public GitHub repositories with Gemini; private-repo/enterprise access was waitlisted [memory] ❓. Not verifiable in this session; ADRs should not rely on it.

**Not surveyed** (out of budget): GitLab Duo Agent Platform documentation features, Swimm, Mintlify, Komment ❓.

---

## 5. OpenWiki: verification of the "LangChain" attribution

**Verdict: the attribution is correct.** `langchain-ai/openwiki` is a LangChain project; two unrelated projects share the name (below).

| Item | Verified fact | Source |
|---|---|---|
| Repo | https://github.com/langchain-ai/openwiki — *"OpenWiki is a CLI that writes and maintains agent documentation for your codebase"*; tagline *"The self-maintaining wiki. Built for agents, explored by humans."* | [S7] [fetched] |
| Docs | https://docs.langchain.com/oss/openwiki/overview | [S8] [fetched] |
| Licence | MIT, "Copyright (c) 2026" | [S59] [fetched] |
| Size | 16,000★ / 1,200 forks (2026-09-02) | [S7] |
| First public appearance | HN 2026-07-01 (96 pts / 31 comments); GitHub releases listed from v0.2.5 (2026-07-31) to **v0.5.0 (2026-09-01)**: v0.3.3 custom MCP connector, **v0.4.0 (2026-08-25) adopted OKF v0.2** with code-owned provenance and grounded claims, v0.5.0 durable page-level resumability across local/CI/host runs | [S45], [S9] [fetched] |
| Architecture | Built on LangChain **Deep Agents**; LangSmith tracing; "resumable page-job architecture" with a durable ordered queue: `begin → submit_plan → next_page → submit_page → … → finish`, checkpointed in `openwiki/.run.json` | [S7], [S8] |
| Output | `openwiki/` directory of Markdown pages in **OKF v0.2** (YAML front matter with non-empty `type`; `verified: {by: openwiki/<version>, at: …}` stamped only after a page's claims reconcile); `openwiki/.page-manifest.json`; `openwiki/.claims/` versioned evidence sidecars; `openwiki/INSTRUCTIONS.md` user-authored scope brief (read, never rewritten); links injected into `AGENTS.md` and `CLAUDE.md` | [S7], [S10] [fetched] |
| Modes | *Code mode* (`openwiki --init`, `openwiki --update`) and *Personal mode* (`openwiki personal --init/--update`, KB at `~/.openwiki/wiki`); `openwiki visualize` graph viewer; `openwiki ingest <source>` connectors; `openwiki auth <provider>` | [S7], [S8] |
| `--update` semantics | Evidence-based, not time-based: checks every persisted evidence version before deciding whether the run is a no-op; stale claims force work even if the planner omits a page; a clean update "skips model work and leaves wiki content untouched while refreshing `.last-update.json`" | [S10] |
| Providers (13) | openai (default), openai-chatgpt (ChatGPT OAuth login), **copilot**, anthropic, gemini, gemini-enterprise (Vertex), bedrock, openrouter, nebius, fireworks, baseten, nvidia, openai-compatible (Ollama, LM Studio, …) | [S11] [fetched] |
| **Copilot provider detail** | `OPENWIKI_PROVIDER=copilot`; auth reuses an existing `gh auth login` session, or in CI set `COPILOT_API_KEY` to a GitHub **OAuth token** — *"Personal Access Tokens (classic or fine-grained) are rejected by the Copilot API for third-party integrations"*; optional `COPILOT_BASE_URL`; example model `gpt-5.5`. Which Copilot plans are permitted, and whether GitHub's terms allow this third-party use, is **not stated** in the docs ❓ (ADRs must verify against GitHub Copilot terms) | [S11] |
| CI automation | Example workflows for GitHub Actions (`examples/openwiki-update.yml`, daily cron + manual dispatch, opens PR via `peter-evans/create-pull-request`, keeps partial progress) and **GitLab CI** (`examples/openwiki-update.gitlab-ci.yml`: runs on `schedule` or `web` trigger, `node:22`, `npm i -g openwiki`, `openwiki code --update --print`, commits `openwiki AGENTS.md CLAUDE.md`, pushes branch `openwiki/update-<pipeline id>` with `OPENWIKI_GITLAB_TOKEN`, then creates an MR through the GitLab REST API); Bitbucket Pipelines also mentioned. Example provider in both files is OpenRouter (`z-ai/glm-5.2`), swappable by env vars | [S60] [fetched], [S61] [fetched] |
| Hooks | No git-hook integration shipped; scheduling is via CI cron. `openwiki --update` is a CLI, so a local `post-commit`/`pre-push` hook is straightforward (ADR-level design) | [S7], [S60] |

**Other projects named "OpenWiki" (not LangChain):**
- `dcouple/openwiki` — Dcouple, Inc.; Docker + SSH/tmux + Claude Code curating a private Obsidian vault and a public Astro site; 0★; licence TBD [S34] [fetched].
- `barvhaim/pi-openwiki` — port of LangChain's OpenWiki to the Pi coding-agent harness; MIT [S18] [fetched].
- LangChain's own blog post could not be opened (`langchain.com/blog/openwiki` → 404), so the official announcement date is inferred from HN and third-party posts (2026-07-01 ± 2 days) ❓.

---

## 6. Google Open Knowledge Format (OKF)

OKF is Google Cloud's open specification for the on-disk shape of an LLM-maintained wiki: a directory of Markdown files with YAML front matter. It was published as v0.1 in June 2026 and revised to v0.2 in July 2026; it is licensed Apache-2.0 and lives in `GoogleCloudPlatform/open-knowledge-format`. Google explicitly positions it as a formalisation of Karpathy's LLM-wiki pattern (§1), and LangChain's OpenWiki (§5) already emits it.

| Item | Verified fact | Source |
|---|---|---|
| Announcement | Google Cloud blog, **2026-06-12**, by Sam McVeety (Tech Lead, Data Analytics) and Amir Hormati (Tech Lead, BigQuery): *"an open specification that formalizes the LLM-wiki pattern into a portable, interoperable format"*; quotes Karpathy's gist directly | [S62] [fetched] |
| Repo | Originally `GoogleCloudPlatform/knowledge-catalog/okf`; canonical home now **https://github.com/GoogleCloudPlatform/open-knowledge-format** (spec, reference agent, sample bundles, graph viewer). Apache-2.0. 246★ / 9 forks. No GitHub "releases" objects | [S63] [fetched], [S64] [fetched], [S65] [fetched] |
| What it is | A *format*: a directory ("bundle") of Markdown files with YAML front matter, cross-linked, optionally with `index.md` at any level for progressive disclosure. *"Just markdown … just files … just YAML frontmatter."* Root `index.md` may carry `okf_version` | [S62], [S66] [fetched] |
| v0.1 (2026-06-12) | Exactly one required field, `type`; reserved optional fields `title`, `description`, `resource`, `tags`, `timestamp`; `# Citations` body section | [S62], [S66] |
| v0.2 (2026-07-25 [snippet] ❓ exact date) | Breaking: `timestamp` → `generated: {by, at}`; body `# Citations` → front-matter `sources` (with per-source `author`, `usage_count`, `last_modified`, `usage_window` credibility signals; per-claim footnotes keyed to `sources[].id`). New: `verified: [{by, at}]`, `status: draft|stable|deprecated`, `stale_after` (ISO 8601), actor convention `<producer>/<version>`, `human:<id>`, `process:<id>`; new concept type *Attested Computation* (`runtime`, `parameters`, `computation`, `executor`, `attester`) | [S66], [S67] [snippet] |
| Linking | Absolute links from bundle root recommended; links are untyped; *consumers must tolerate broken links* | [S66] |
| What it is not | *"Format, not platform"*; not a database, not a retrieval system, not an agent-communication protocol, not a RAG replacement; *"will never require a proprietary account or SDK to read, write, or serve"* | [S62], [S68] [fetched] |
| Reference implementation | A proof-of-concept agent producing bundles from BigQuery metadata plus an LLM web-crawl enrichment pass; sample bundles (GA4 e-commerce, Stack Overflow, Bitcoin, "Acme Retail") | [S63] |
| Activity / adoption | Spec repo: 246★, 9 forks, no tagged releases (versions are tracked in `SPEC.md`) [S63], [S65]; **OpenWiki emits OKF v0.2 since v0.4.0 (2026-08-25)** [S9]; `okf-lint` community linter (validates v0.1) [S36]; GitBook positions itself as "OKF-ready" (compatibility, not adoption) [S69] [fetched]; trade coverage MarkTechPost / Search Engine Journal / GitBook 2026-06-16..18 | — |
| Relation to Karpathy's pattern | The announcement quotes the gist directly (*"LLMs don't get bored, don't forget to update a cross-reference, and can touch 15 files in one pass"*) and says OKF *"formalizes the small set of conventions needed to make these patterns interoperable"*. OKF standardises the **wiki layer** (files, front matter, index, links); it says nothing about the raw-source layer, the schema file, or the ingest/query/lint loop, which remain implementation choices | [S62] |

Implication: OKF is a plausible *on-disk contract* for a repo wiki (front matter with `type`, `generated`, `verified`, `stale_after`, `sources`), and adopting it would make the wiki readable by OpenWiki's tooling and by any future OKF consumer. It does not prescribe ingest/lint behaviour, hosting, or code-citation semantics.

---

## 7. Research papers 2024–2026

All arXiv IDs below were opened on arxiv.org (abstract page) or returned by the arXiv API during this survey. Affiliations are given only where the abstract page or the arXiv API listing stated them; otherwise omitted. "Implies" = relevance to this project.

### 7a. Repository-level documentation generation

| # | Paper | Authors / org | Venue / id | Date | Contribution | Implies for us |
|---|---|---|---|---|---|---|
| P1 | RepoAgent: An LLM-Powered Open-Source Framework for Repository-level Code Documentation Generation | Luo, Ye, Liang, … Liu, Sun (Tsinghua / Siemens [snippet]) | arXiv 2402.16667 | 2024-02-26 | First open framework to *generate, maintain and update* repo docs from AST + LLM | Baseline for "bootstrap once" (R4); later benchmarks still rank it top for downstream usefulness (P5) |
| P2 | DocAgent: A Multi-Agent System for Automated Code Documentation Generation | Yang et al. (Meta; code at facebookresearch/DocAgent) | ACL 2025; arXiv 2504.08725 | 2025-04-11 | Reader/Searcher/Writer/Verifier/Orchestrator agents; **topological (dependency-ordered) processing** for incremental context; evaluates Completeness/Helpfulness/Truthfulness | Process modules in dependency order; add a verifier agent to the ingest loop |
| P3 | CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases | Nguyen Hoang, Le-Anh, Le, Bui (FPT Software AI Center, U. Melbourne) | **ACL 2026**; arXiv 2510.24428 (v6 2026-04-04) | 2025-10-28 | Hierarchical decomposition + recursive agent delegation + diagrams; **CodeWikiBench**; 68.79% vs DeepWiki 64.06% | Open, MIT, incremental `--update`, subscription mode; the strongest open baseline for R4 bootstrap |
| P4 | Remember Your Trace: Memory-Guided Long-Horizon Agentic Framework for Consistent and Hierarchical Repository-Level Code Documentation (MemDocAgent) | Bae, Lee, Choi, Choi, Lee | arXiv 2605.14563 (v2 2026-07-10) | 2026-05-14 | Whole-repo single-context processing with dependency-aware traversal and a shared "RepoMemory" (read/write/verify) for cross-page consistency | Consistency across pages is a first-order problem at scale; a shared memory/index during bootstrap helps |
| P5 | CIAO — Code In Architecture Out: Automated Software Architecture Documentation with LLMs | De Luca, Santilli, Amalfitano, Fasolino, Pelliccione | **ICSA 2026**; arXiv 2604.08293 | 2026-04-09 | Generates system-level architecture docs (ISO 42010, Views & Beyond, C4) from repos; 22-developer study; weak on deployment views/diagrams | Human-facing architecture pages (R1) can follow C4/arc42 templates; expect diagram quality issues |
| P6 | The Illusion of Agentic Complexity in README.md Generation | Saleh, Tesfay, Nguyen, Di Rocco, Zeshan, Di Ruscio | **ICSME 2026**; arXiv 2606.30524 | 2026-06-29 | Single-agent RAG matches multi-agent quality with **86% fewer tokens**, 2× faster; developer-guided planning beats fully autonomous | Keep the ingest agent simple; let humans supply the plan/scope (cf. R5 instruction form) |
| P7 | CODENS: Transforming Code Changes into Living, Accessible, and Queryable Documentation | Kelious, Tahri, Bardet | **DocEng 2026**; arXiv 2607.18356 | 2026-07-20 | Builds a typed knowledge graph **from pull requests** and answers repo-level questions by graph traversal | MR-driven incremental ingest is viable; MRs are a natural unit of change for R4 |
| P8 | Documentation-Guided Agentic Codebase Migration from C to Rust (RustPrint) | Le-Anh, Nguyen Hoang, Le, Bui | arXiv 2605.14634 | 2026-05-14 | Architecture-aware docs used as a "migration blueprint"; 93% feature preservation | Evidence that agent-readable architecture docs make downstream agents markedly better (R2) |
| P9 | LLM-Based Code Documentation Generation and Multi-Judge Evaluation | Ghrab et al. | arXiv 2606.09852 | 2026-05-11 | Eight LLM variants, multi-LLM-as-judges on nine criteria | Judge ensembles as a lint/quality gate |

### 7b. Evaluation benchmarks

| # | Paper | Authors / org | Venue / id | Date | Contribution | Implies for us |
|---|---|---|---|---|---|---|
| P10 | Evaluating Repository-level Software Documentation via Question Answering and Feature-Driven Development (**SWD-Bench**) | Wang, Hu, Gao, Gao, Peng | arXiv 2604.06793 | 2026-04-08 | 4,170 PR-derived tasks: functionality detection / localisation / completion; docs judged by whether an agent can *use* them; best docs raise SWE-Agent issue-solving by 20%; RepoAgent 52.6% > DocAgent = AutoDoc 49.1% > DeepWiki 47.4% | Evaluate the wiki by agent task success, not by prose quality; documentation and source are complementary |
| P11 | Code-QA-Bench: Separating Code Reasoning from Documentation Memorization in Repository-Level QA | Zhang, Qu, Du, Sun, Yang, Zhao | arXiv 2605.29277 | 2026-05-28 | 528 code-derivable + 100 documentation-dependent tasks; code access +0.23, docs a further +0.071 on doc-dependent tasks | Docs add most where knowledge is *not* derivable from code (decisions, contracts, ownership — R3) |
| P12 | CodeWikiBench (in P3) | — | ACL 2026 | 2025-10 | Rubric-based, agentic assessment of holistic docs | Reusable rubric for lint |

### 7c. Agent context files (AGENTS.md / CLAUDE.md / rules) — do they help?

| # | Paper | Authors / org | Venue / id | Date | Contribution | Implies for us |
|---|---|---|---|---|---|---|
| P13 | Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents? | Gloaguen, Mündler, Müller, Raychev, Vechev | arXiv 2602.11988 (v2 2026-06-23) | 2026-02-12 | Context files did **not** raise success rates and added >20% inference cost; *instructions* are followed, *repository overviews* are not helpful | A wiki must be **retrieved on demand**, not dumped into context; keep AGENTS.md to pointers + rules |
| P14 | On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents | Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude | arXiv 2601.20404 | 2026-01-28 | 124 PRs, 10 repos: AGENTS.md → −28.6% median runtime, −16.6% output tokens, same completion | Efficiency, not correctness, is the measurable win |
| P15 | Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories | Khatri | arXiv 2607.27250 | 2026-07-28 | 288 runs, Claude Code + Codex: no measurable correctness change; failures are implementation skill, not missing knowledge | Same conclusion as P13; set expectations for R1 "faster and more accurate" |
| P16 | Guardrails Beat Guidance: A Large-Scale Study of Rules, Skills, and Persistent Configuration for Coding Agents | Zhang, Wang, Cui, Qiu, Li, Zhu, He | arXiv 2604.11088 | 2026-04-13 | 679 rule files, 5,000+ runs: negative constraints help, positive style directives hurt; random rules ≈ expert rules (+13.8pp) | Write wiki-usage rules as "do not" constraints |
| P17 | Probe-and-Refine Tuning of Repository Guidance for Coding Agents | Shepard, Albrecht | arXiv 2606.20512 | 2026-06-18 | Iteratively tune the guidance file with synthetic bug-fix probes: 33.0% vs 25.5% unguided on SWE-bench Verified; gains come from *locating files* | Guidance should be tuned/evaluated, not just written; a lint loop can do this |
| P18 | Configuration Smells in AGENTS.md Files | dos Santos, Costa, Montandon, Silva, Valente | **SCAM 2026**; arXiv 2606.15828 | 2026-06-14 | Six smells in 100 projects: Lint Leakage 62%, Context Bloat 42%, Skill Leakage 35%, Conflicting Instructions … | Lint rules for the agent-facing files themselves |
| P19 | Why Does CLAUDE.md Keep Growing? Catastrophic Remembering in Agentic Coding | Chakrabarti | arXiv 2608.11095 | 2026-08-11 | 250k instructions / 1,867 repos: files grow +226% over life, +4.9 instructions per commit; reasoning comments cut excess by 99.3% | Record *why* each rule exists; prune during lint |
| P20 | Agent READMEs: An Empirical Study of Context Files for Agentic Coding | Chatlatanagulchai, Li, Kashiwa, … Hassan, Iida | arXiv 2511.12884 (v2 2026-08-09) | 2025-11-17 | 2,303 files: tests 75.9%, implementation 70.8%, architecture 68.1%; security 14.8%, performance 14.5% | Template gaps to fill for non-functional concerns |
| P21 | On the Use of Agentic Coding Manifests: An Empirical Study of Claude Code | Chatlatanagulchai et al. | PROFES 2025; arXiv 2509.14744 | 2025-09-18 | 253 CLAUDE.md files: shallow hierarchies, operational commands dominate | — |
| P22 | How Do Developers Maintain and Evolve Their Agents' Instructions? | Voria, Cannavale, De Lucia, Kashiwa, Catolino, Palomba | arXiv 2606.25257 | 2026-06-24 | Taxonomy of context-file changes and links to code quality | Governance of who edits the schema file (R4/R5) |
| P23 | When "Do Not" Is Not Deny: Security Rules in CLAUDE.md vs Built-In Controls | Yan | arXiv 2608.23550 | 2026-08-24 | Only ~4–16% of natural-language security rules map to an enforceable control | Enforce hard rules with hooks/permissions, not prose |
| P24 | ContextCov: Deriving and Enforcing Executable Constraints from Agent Instruction Files | Sharma | arXiv 2603.00822 | 2026-02-28 | Converts passive instructions into executable guardrails (88.3% compliance) | Same lesson as P23 |

### 7d. Staleness, incremental updates, trust

| # | Paper | Authors / org | Venue / id | Date | Contribution | Implies for us |
|---|---|---|---|---|---|---|
| P25 | READU: Inconsistency-Driven Just-in-Time Detection and Repair of README Bugs | Baek, Krampf, Pradel | arXiv 2607.15780 | 2026-07-17 | Per-commit checker (filter → parallel consistency checkers → alert judge): 244 TPs at 75% precision, 217 auto-repaired, 44 confirmed upstream; **< $0.01 and < 1 min per commit** | Commit-triggered doc lint is cheap and effective — direct support for R4 hook design |
| P26 | Context Rot in AI-Assisted Software Development: Repurposing Documentation Consistency for AI Configuration Artifacts | Treude, Baltes | arXiv 2606.09090 | 2026-06-08 | Existing README/wiki consistency checker finds stale code references in 23% of repos' AI config files | Agent-facing files rot like any docs; include them in lint |
| P27 | When Retrieval Hurts Code Completion: A Diagnostic Study of Stale Repository Context | Weng, Yang, Fu, Pan, Lv | arXiv 2605.14478 | 2026-05-14 | Stale retrieved snippets induced outdated code in 76–88% of cases; fresh evidence recovers performance | A stale wiki is *worse than none*; freshness metadata (OKF `stale_after`, `verified`) and citation checks matter |
| P28 | Context-as-AI-Service: Surfacing Cross-File Dependency Chains for LLM-Generated Developer Documentation | Gawde, Repantis, Singh, Moys | arXiv 2606.04397 | 2026-06-03 | Keyword+semantic retrieval layer for doc-writing agents; surfaced cross-file factual errors; −22–34% wall-clock | Give the wiki agent a code-search tool, not just file reads |
| P29 | Knowledge-Based Pull Requests: A Trusted Workflow for Agent-Mediated Knowledge Collaboration | Zhang, Sun | arXiv 2606.26721 | 2026-06-25 | Separate human-confirmed *knowledge packages* (design memo, risk checklist, test plan) from regenerated code | A wiki MR reviewed by humans is the trust boundary (R4, R5) |
| P30 | RepoRepair: Leveraging Code Documentation for Repository-Level Automated Program Repair | Pan, Li, Zhong, Feng, Luo, Ng | arXiv 2603.01048 | 2026-03-01 | Cheap-model hierarchical docs, then strong-model repair: 45.7% SWE-bench Lite at $0.44/fix | Two-tier model use (cheap for docs, strong for tasks) — relevant to Copilot premium-request budgeting |
| P31 | STALE: Can LLM Agents Know When Their Memories Are No Longer Valid? | — | arXiv 2605.06527 | 2026-05 | 400 conflict scenarios; agents poor at detecting outdated beliefs | Do not rely on the agent to notice staleness; make lint deterministic | [snippet] |

---

## 8. Agent-context standards and GitHub Copilot support (as of 2026-09-02)

Support columns follow GitHub's *Custom instructions support* reference [S70] [fetched] and *Customization cheat sheet* [S71] [fetched] ("P" = preview in the cheat sheet). Copilot CLI = `@github/copilot`.

| Standard | Spec / owner | Copilot CLI | VS Code (Copilot) | JetBrains (Copilot) | Notes |
|---|---|---|---|---|---|
| **AGENTS.md** | https://agents.md — stewarded by the Agentic AI Foundation (Linux Foundation); 60k+ OSS projects; nearest file in the tree wins; 25+ agents (Codex, Jules, Cursor, Copilot, Junie, Devin, …) [S72] [fetched] | ✅ read from repo root, cwd, intermediate dirs and nested paths [S73] [fetched] | ✅ chat and cloud agent [S70] | 🟡 reference matrix: cloud agent ✅, chat ✗; but the 2026-03-11 changelog added AGENTS.md/CLAUDE.md support (with optional nested files) to the JetBrains plugin [S74] [fetched] — treat as ✅ for agent mode, verify per plugin version | Copilot treats `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` identically as "agent instructions" [S70] |
| **Agent Skills (SKILL.md)** | https://agentskills.io/specification — required `name`, `description`; optional `license`, `compatibility`, `metadata`, `allowed-tools`; `scripts/`, `references/`, `assets/`; progressive disclosure [S75] [fetched]; reference impl. github.com/agentskills/agentskills | ✅ [S76] [fetched] | ✅ agent mode | 🟡 "P" in cheat sheet; agent mode listed as supported in concept page [S76] | Copilot loads from `.github/skills/`, `.claude/skills/`, `.agents/skills/`, `~/.copilot/skills/`, `~/.agents/skills/`; also cloud agent, code review, Copilot app [S76] |
| **llms.txt** | https://llmstxt.org — Jeremy Howard (Answer.AI), proposed Sep 2024; v2 2026-08-10; H1 + blockquote + H2 link lists; adopters incl. OpenAI, Anthropic, Google, Mintlify, GitBook; Lighthouse audits it [S77] [fetched] | ❌ no native support; community request open (discussion #162955) [S78] [snippet] | ❌ | ❌ | Useful as a *published* artefact of the wiki site (R8) for other agents; Pratiyush/llm-wiki emits one |
| **Copilot custom instructions** `.github/copilot-instructions.md` | GitHub docs [S70], [S71] | ✅ (+ `~/.copilot/copilot-instructions.md`, `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`) [S73] | ✅ | ✅ chat, cloud agent, code review | Applies to chat, code review, coding agent — not inline completions |
| **Path-specific** `.github/instructions/*.instructions.md` | GitHub docs [S70] | ✅ (root/cwd only, not intermediate dirs) [S73] | ✅ | ✅ | `applyTo` globs |
| **Prompt files** `.github/prompts/*.prompt.md` | GitHub docs [S71] | ❌ | ✅ | P | Candidate for the R5 "instruction form" only in VS Code/JetBrains |
| **Custom agents** `.github/agents/*.agent.md` (and org-level `/agents/`) | GitHub docs [S71] | ✅ | ✅ | P | Used by copilot-llm-wiki's "librarian" agent [S25] |
| **Hooks** `.github/hooks/*.json` | GitHub docs [S71], [S79] [fetched] | ✅ events `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `errorOccurred` (+ `agentStop`) | P | ❌ (cheat sheet) — but JetBrains changelog 2026-03-11 lists "agent hooks" [S74] ❓ | Agent-session hooks, not git hooks |
| **Copilot CLI programmatic mode** | GitHub docs [S80] [fetched] | ✅ `copilot -p "<prompt>"` runs once and exits; MCP servers configurable; usage billed as AI credits by tokens | — | — | This is the mechanism a git hook or GitLab CI job would call under R6; auth/licensing for a bot user is an ADR question |
| **Cursor rules** `.cursor/rules/*.mdc` | https://cursor.com/docs/context/rules — front matter `description`, `globs`, `alwaysApply`; legacy `.cursorrules`; Cursor also reads nested `AGENTS.md` [S81] [fetched] | ❌ not read by Copilot | ❌ | ❌ | Claude Code `/init` imports Cursor and Copilot rules into CLAUDE.md [S82] |
| **CLAUDE.md** | https://code.claude.com/docs/en/memory — managed/user/project/local scopes; nested files load on demand; `@path` imports (4 hops); `.claude/rules/*.md` with `paths:` globs; Claude Code does **not** read AGENTS.md (import or symlink it) [S82] [fetched] | ✅ read as agent instructions [S73] | ✅ (cloud agent) | 🟡 see AGENTS.md row | Copilot reading CLAUDE.md means one file can serve Claude Code and Copilot |
| **MCP resources** | MCP spec 2025-06-18: `resources/list`, `resources/read`, `resources/templates/list`, `subscribe`, `notifications/resources/list_changed`; annotations `audience`, `priority`, `lastModified`; URI schemes `file://`, `https://`, `git://` [S83] [fetched] | 🟡 MCP servers ✅ (cheat sheet); resource support in CLI not confirmed ❓ | ✅ tools, **resources** ("Add Context › MCP Resources"), prompts, MCP apps; `.vscode/mcp.json` or `~/.copilot/mcp-config.json` [S84] [fetched] | 🟡 MCP ✅ with server/tool auto-approve [S74]; resources ❓ | A wiki exposed as MCP resources works in VS Code today; treat CLI/JetBrains resource support as unverified |

---

## 9. Timeline

| Date | Event | Why it matters |
|---|---|---|
| 2024-02-26 | RepoAgent (arXiv 2402.16667) | First open repo-level doc generator; still a strong baseline in 2026 benchmarks |
| 2024-09 | llms.txt proposed (Answer.AI) | Site-level agent context convention; later adopted by major doc platforms |
| 2025-04-11 | DocAgent (ACL 2025) | Dependency-ordered multi-agent documentation |
| 2025-04-25 / 05-05 | DeepWiki launched by Cognition | Defined the "repo → wiki" product category; free for public GitHub repos |
| 2025-06-18 | MCP spec revision with resources/annotations | Basis for exposing a wiki to agents |
| 2025-09-18 / 11-17 | First empirical studies of CLAUDE.md / agent READMEs | Context files are shallow, functional, security-light |
| 2025-10-28 | CodeWiki + CodeWikiBench (later ACL 2026) | Open, MIT, incremental; beats DeepWiki on its own benchmark |
| 2026-01-28 / 02-12 | AGENTS.md efficiency study; "Evaluating AGENTS.md" | Context files save tokens but do not raise correctness; overviews unhelpful |
| 2026-03-11 | Copilot for JetBrains: AGENTS.md/CLAUDE.md, custom agents, hooks, MCP auto-approve | JetBrains (owner's IDE) catches up on agent-context features |
| 2026-04-04 | Karpathy publishes the LLM Wiki gist; HN 296 pts | The idea this project is named after; 5k★ within days |
| 2026-04-08 | SWD-Bench | Evaluate docs by agent task success |
| 2026-04-13 | "Guardrails Beat Guidance" | Negative constraints work; style directives hurt |
| 2026-04-14 | Cognition new Devin plans; DeepWiki stays free for public repos | Private-repo wiki = paid Devin |
| 2026-04-25 | Show HN wuphf (agents-maintained Markdown+Git wiki) | Peak of community code-wiki interest |
| 2026-06-12 | Google Cloud publishes **OKF v0.1** | Front-matter contract formalising the LLM-wiki pattern |
| 2026-06-14 / 06-08 | AGENTS.md configuration smells; "Context rot" | Lint the agent-facing files too |
| 2026-07-01 | **LangChain OpenWiki** on HN | First mature open tool with Copilot provider + GitLab CI example |
| 2026-07-17 / 07-20 | READU; CODENS | Per-commit doc repair for < $0.01; PR-driven knowledge graph |
| 2026-07-25 ❓ | OKF v0.2 (provenance, verified, status, stale_after) | Freshness/trust metadata for wiki pages |
| 2026-08-10 | llms.txt v2 | — |
| 2026-08-11 | "Why does CLAUDE.md keep growing?" | Unbounded growth of agent instructions; record reasons |
| 2026-08-25 | OpenWiki v0.4.0 adopts OKF v0.2 | Two ecosystems converge on one file format |
| 2026-09-01 | OpenWiki v0.5.0 (durable resumability in CI) | Long bootstraps survive CI job limits |

---

## 10. Sources

| # | Title — author/org — date — URL | Tag |
|---|---|---|
| S1 | llm-wiki.md gist — Andrej Karpathy — 2026-04-04 — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f | [fetched] |
| S2 | HN Algolia API: "LLM Wiki – example of an 'idea file'" (296 pts, 95 comments, id 47640875) — 2026-04-04 — https://hn.algolia.com/api/v1/search?query=gist.github.com%2Fkarpathy%2F442a6bf555914893e9891c11519de94f&tags=story | [fetched] |
| S3 | How to Build Karpathy's LLM Wiki — Dylan Boudro, Starmorph — 2026-04-09 — https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide | [fetched] |
| S4 | LLM Wiki Setup: Karpathy's Knowledge Base [2026 Guide] — Kunal Ganglani — 2026 — https://www.kunalganglani.com/blog/llm-wiki-karpathy-local-knowledge-base | [snippet] (fetch 403) |
| S5 | GitHub topic `karpathy-llm-wiki` (42 repos) — https://github.com/topics/karpathy-llm-wiki | [fetched] |
| S6 | GitHub topics `llm-wiki`, `karpathy-wiki`; search snippets for MehmetGoekce/llm-wiki, shannhk/llm-wikid, 2233admin/obsidian-llm-wiki, ussumant/llm-wiki-compiler — https://github.com/topics/llm-wiki | [snippet] |
| S7 | langchain-ai/openwiki README — LangChain — 2026 — https://github.com/langchain-ai/openwiki | [fetched] |
| S8 | OpenWiki overview — LangChain docs — https://docs.langchain.com/oss/openwiki/overview | [fetched] |
| S9 | OpenWiki releases (v0.2.5 2026-07-31 … v0.5.0 2026-09-01) — https://github.com/langchain-ai/openwiki/releases | [fetched] |
| S10 | OpenWiki README raw (Copilot, GitLab CI, OKF, `--update`, INSTRUCTIONS.md) — https://raw.githubusercontent.com/langchain-ai/openwiki/main/README.md | [fetched] |
| S11 | OpenWiki model providers — LangChain docs — https://docs.langchain.com/oss/openwiki/providers | [fetched] |
| S12 | Egonex-AI/Understand-Anything — https://github.com/Egonex-AI/Understand-Anything | [fetched] |
| S13 | FSoft-AI4Code/CodeWiki — FPT Software AI Center — https://github.com/FSoft-AI4Code/CodeWiki | [fetched] |
| S14 | vouchdev/vouch — https://github.com/vouchdev/vouch | [fetched] |
| S15 | mxmzb/autowiki — https://github.com/mxmzb/autowiki | [fetched] |
| S16 | christianb93/WikiSpec — https://github.com/christianb93/WikiSpec | [fetched] |
| S17 | Pratiyush/llm-wiki — https://github.com/Pratiyush/llm-wiki | [fetched] |
| S18 | barvhaim/pi-openwiki — https://github.com/barvhaim/pi-openwiki | [fetched] |
| S19 | How I turned Andrej Karpathy's LLM Wiki into a tool that writes wikis from code — Balu Kosuri, Medium — 2026 — https://medium.com/@k.balu124/how-i-turned-andrej-karpathys-llm-wiki-into-a-tool-that-writes-wiki-s-from-code-cfb7f73afa52 | [snippet] (fetch 403) |
| S20 | HN Algolia API results for "karpathy llm-wiki" and "LLM Wiki" (wuphf 47899844, open-knowledge 48675435, jonadas, Gupta, okf-lint, …) — https://hn.algolia.com/api/v1/search?query=karpathy%20llm-wiki&tags=story | [fetched] |
| S21 | github.com/nex-crm/wuphf (redirects to najmuzzaman-mohammad/gawkbot at fetch time) — https://github.com/nex-crm/wuphf | [fetched] ❓ |
| S22 | Astro-Han/karpathy-llm-wiki — https://github.com/Astro-Han/karpathy-llm-wiki | [fetched] |
| S23 | SamurAIGPT/llm-wiki-agent — https://github.com/SamurAIGPT/llm-wiki-agent | [fetched] |
| S24 | yugasun/llm-wiki-skills — https://github.com/yugasun/llm-wiki-skills | [fetched] |
| S25 | SriSatyaLokesh/copilot-llm-wiki — https://github.com/SriSatyaLokesh/copilot-llm-wiki | [fetched] |
| S26 | lewislulu/llm-wiki-skill — https://github.com/lewislulu/llm-wiki-skill | [snippet] |
| S27 | Hermes Agent bundled skill "llm-wiki" — Nous Research — https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki | [fetched] |
| S28 | LLM Wiki v2 gist — Rohit G — updated 2026-08-31 — https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2 | [fetched] |
| S29 | eugeniughelbur/obsidian-second-brain — https://github.com/eugeniughelbur/obsidian-second-brain | [fetched] |
| S30 | ekadetov/llm-wiki — https://github.com/ekadetov/llm-wiki | [fetched] |
| S31 | ignromanov/llm-obsidian-wiki — https://github.com/ignromanov/llm-obsidian-wiki | [fetched] |
| S32 | pssah4/vault-operator — https://github.com/pssah4/vault-operator | [fetched] |
| S33 | lucasastorian/llmwiki — https://github.com/lucasastorian/llmwiki | [fetched] |
| S34 | dcouple/openwiki — Dcouple, Inc. — https://github.com/dcouple/openwiki | [fetched] |
| S35 | sillok-os/sillok — https://github.com/sillok-os/sillok | [fetched] |
| S36 | thisismydesign/okf-lint — https://github.com/thisismydesign/okf-lint | [fetched] |
| S37 | Andrej Karpathy's LLM Wiki gist, hosted — Evert Van den Bruel, Hjarni — 2026-04-08 — https://hjarni.com/blog/karpathys-llm-wiki-is-right | [fetched] |
| S38 | Hacker News Picks Up Karpathy's "LLM Wiki" Pattern — marvin-42 insights — 2026 — https://insights.marvin-42.com/articles/hacker-news-picks-up-karpathys-llm-wiki-pattern-for-persistent-knowledge-bases | [snippet] (fetch 404) |
| S39 | Karpathy's LLM Wiki Gist Decoded: What I Added — Eugeniu Ghelbur — 2026-04-29 — https://theaioperator.io/p/i-rebuilt-karpathys-llm-wiki-heres | [fetched] |
| S40 | The Wiki Is the Codebase — Viktor Ponamarev, Medium — 2026-05 — https://medium.com/@vikpoca/the-wiki-is-the-codebase-6467dd51a5d3 | [snippet] (fetch 403) |
| S41 | Karpathy's LLM Wiki? No Code with Claude or GitHub Copilot — rosidotidev, DEV — 2026-05-23 — https://dev.to/rosidotidev/karpathys-llm-wiki-no-code-with-claude-or-github-copilot-5fb0 | [fetched] |
| S42 | How I Built a Self-Maintaining Knowledge Base for 6 Projects Using Claude Code & Karpathy's LLM Wiki — HackerNoon — 2026 — https://hackernoon.com/how-i-built-a-self-maintaining-knowledge-base-for-6-projects-using-claude-code-and-karpathys-llm-wiki | [snippet] (fetch 403) |
| S43 | I built Karpathy's LLM Wiki twice — Leandro Bernardo, Towards AI — 2026 — https://pub.towardsai.net/i-built-karpathys-llm-wiki-twice-once-as-code-once-as-a-md-heres-what-each-one-gives-up-08b31170999a | [snippet] |
| S44 | I Tested 5 'LLM Wiki' Implementations — Mike Written, Medium — 2026-07 — https://medium.com/@aitrends24/i-tested-5-llm-wiki-implementations-so-you-don-t-have-to-d68ba7cc9100 | [snippet] |
| S45 | HN Algolia API: "OpenWiki: CLI that writes and maintains agent documentation for your codebase" (96 pts, 31 comments, id 48752949) — 2026-07-01 — https://hn.algolia.com/api/v1/search?query=openwiki%20langchain&tags=story | [fetched] |
| S46 | OpenWiki: LangChain's Answer to the Karpathy Wiki Problem — Prahlad G. Menon — 2026-07-03 — https://themenonlab.blog/blog/openwiki-langchain-agent-documentation | [fetched] |
| S47 | LangChain OpenWiki: Andrej Karpathy's LLM Wiki in Action — Mehul Gupta, Medium — 2026-07 — https://medium.com/data-science-in-your-pocket/langchain-openwiki-andrej-karpathys-llm-wiki-in-action-8a14996101e8 | [snippet] |
| S48 | Google's New Format for Agent Context: A Standard, or Just a Folder? — Marc Bara, Medium — 2026 — https://medium.com/@marc.bara.iniesta/googles-new-format-for-agent-context-a-standard-or-just-a-folder-82fb21d92041 | [snippet] |
| S49 | Build Karpathy's LLM Knowledge Base in Copilot Cowork — gingonai Substack — 2026 — https://gingonai.substack.com/p/karpathys-llm-knowledge-base-built | [snippet] |
| S50 | Introducing OpenWiki, an open source agent for repo documentation — LangChain, YouTube — https://www.youtube.com/watch?v=nIVu3zfYprI | [fetched] (title only) |
| S51 | DeepWiki — Learn AI wiki (Miraheze) — https://ai.miraheze.org/wiki/DeepWiki | [snippet] (fetch 403) |
| S52 | DeepWiki launch post — Cognition — 2025-05-05 — https://cognition.com/blog/deepwiki | [fetched] |
| S53 | DeepWiki — Devin docs — https://docs.devin.ai/work-with-devin/deepwiki | [fetched] |
| S54 | New self-serve plans for Devin — Cognition — 2026-04-14 — https://cognition.com/blog/new-self-serve-plans-for-devin | [fetched] |
| S55 | DeepWiki MCP — Devin docs — https://docs.devin.ai/work-with-devin/deepwiki-mcp | [fetched] |
| S56 | GitLab integration — Devin docs — https://docs.devin.ai/integrations/gitlab | [fetched] |
| S57 | AsyncFuncAI/deepwiki-open — https://github.com/AsyncFuncAI/deepwiki-open | [fetched] |
| S58 | DeepWiki-Open Quick Start — https://asyncfunc.mintlify.app/getting-started/quick-start | [fetched] |
| S59 | OpenWiki LICENSE (MIT) — https://github.com/langchain-ai/openwiki/blob/main/LICENSE | [fetched] |
| S60 | OpenWiki GitLab CI example — https://raw.githubusercontent.com/langchain-ai/openwiki/main/examples/openwiki-update.gitlab-ci.yml | [fetched] |
| S61 | OpenWiki GitHub Actions example — https://raw.githubusercontent.com/langchain-ai/openwiki/main/examples/openwiki-update.yml | [fetched] |
| S62 | How the Open Knowledge Format can improve data sharing — Sam McVeety, Amir Hormati, Google Cloud Blog — 2026-06-12 — https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing | [fetched] |
| S63 | GoogleCloudPlatform/open-knowledge-format — Google Cloud — https://github.com/GoogleCloudPlatform/open-knowledge-format | [fetched] |
| S64 | knowledge-catalog/okf (original location) — https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf | [snippet] |
| S65 | open-knowledge-format releases page (none) — https://github.com/GoogleCloudPlatform/open-knowledge-format/releases | [fetched] |
| S66 | OKF SPEC.md v0.2 — https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/SPEC.md | [fetched] |
| S67 | OKF v0.2 date (2026-07-25) — search snippets (startuphub.ai, Medium) — https://www.startuphub.ai/ai-news/insights/2026/google-open-knowledge-format-okf-explained-2026 | [snippet] ❓ |
| S68 | Google Cloud Introduces OKF — MarkTechPost — 2026-06-16 — https://www.marktechpost.com/2026/06/16/google-cloud-introduces-open-knowledge-format-okf-a-vendor-neutral-markdown-spec-for-giving-ai-agents-curated-context/ | [fetched] |
| S69 | What is OKF? — Steve Ashby, GitBook Blog — 2026-06-18 (updated 2026-09-02) — https://www.gitbook.com/blog/what-is-okf-open-knowledge-format | [fetched] |
| S70 | Custom instructions support (reference matrix) — GitHub Docs — https://docs.github.com/en/copilot/reference/custom-instructions-support | [fetched] |
| S71 | Copilot customization cheat sheet — GitHub Docs — https://docs.github.com/en/copilot/reference/customization-cheat-sheet | [fetched] |
| S72 | AGENTS.md — Agentic AI Foundation / Linux Foundation — https://agents.md/ | [fetched] |
| S73 | Adding custom instructions for GitHub Copilot CLI — GitHub Docs — https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions | [fetched] |
| S74 | Major agentic capabilities improvements in GitHub Copilot for JetBrains IDEs — GitHub Changelog — 2026-03-11 — https://github.blog/changelog/2026-03-11-major-agentic-capabilities-improvements-in-github-copilot-for-jetbrains-ides/ | [fetched] |
| S75 | Agent Skills specification — https://agentskills.io/specification | [fetched] |
| S76 | About agent skills — GitHub Docs — https://docs.github.com/en/copilot/concepts/agents/about-agent-skills | [fetched] |
| S77 | llms.txt — Jeremy Howard, Answer.AI — 2024-09 / v2 2026-08-10 — https://llmstxt.org/ | [fetched] |
| S78 | Support /llms.txt in Copilot? — GitHub Community discussion #162955 — https://github.com/orgs/community/discussions/162955 | [snippet] |
| S79 | Using hooks with Copilot CLI — GitHub Docs — https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks | [fetched] |
| S80 | About GitHub Copilot CLI — GitHub Docs — https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli | [fetched] |
| S81 | Rules — Cursor docs — https://cursor.com/docs/context/rules | [fetched] |
| S82 | How Claude remembers your project (CLAUDE.md) — Anthropic — https://code.claude.com/docs/en/memory | [fetched] |
| S83 | MCP specification 2025-06-18: Resources — https://modelcontextprotocol.io/specification/2025-06-18/server/resources | [fetched] |
| S84 | MCP servers in VS Code — Microsoft — https://code.visualstudio.com/docs/copilot/customization/mcp-servers | [fetched] |
| S85 | arXiv API queries used for §7 (repository-level ∧ documentation; "code documentation" ∧ LLM ∧ agent; "context files" ∧ "coding agents"; AGENTS.md ∨ CLAUDE.md ∨ llms.txt; documentation generation ∧ repository) — http://export.arxiv.org/api/query | [fetched] |
| S86 | arXiv abstract pages for P1–P30 — https://arxiv.org/abs/{2402.16667, 2504.08725, 2510.24428, 2605.14563, 2604.08293, 2606.30524, 2607.18356, 2605.14634, 2604.06793, 2605.29277, 2602.11988, 2601.20404, 2607.27250, 2604.11088, 2606.20512, 2606.15828, 2608.11095, 2511.12884, 2509.14744, 2606.25257, 2608.23550, 2607.15780, 2606.09090, 2605.14478, 2606.04397, 2606.26721, 2603.01048} | [fetched]; 2606.09852, 2603.00822 via API listing only; 2605.06527 [snippet] |
| S87 | Google Code Wiki — https://codewiki.google/ (page shell only; announcement URLs not found) | [memory] ❓ |
