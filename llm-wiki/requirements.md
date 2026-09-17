# Requirements: LLM-maintained repository wiki

Date: 2026-09-02
Owner: Arvand Kaveh
Status: baseline for evaluating all approaches in `approaches/`

Every approach ADR must rate itself against the IDs below, using exactly these IDs
in its "Requirements check" table.

## Requirement table

| ID | Requirement | Type | Detail |
|----|-------------|------|--------|
| R1 | **Dual audience** | Must | The wiki is consumed by coding agents (to make them faster and more accurate) **and** by humans: technical documentation for developers, non-technical documentation for the product owner. |
| R2 | **Context layer for the whole AI dev pipeline** | Must | The wiki is the knowledge/context layer for feature definition, planning, implementation, testing, bug fixing, review, and operations. Agents at each stage must be able to find what they need without reading the whole codebase. |
| R3 | **Multi-repo, microservice, front + back end; future fully-autonomous agents** | Must | Same setup rolled out across many repositories (frontend and backend services). Cross-repo knowledge (contracts, APIs, events, ownership) must be discoverable. Design must survive the transition to fully automatic agentic coding systems later. |
| R4 | **Bootstrap once, then continuous developer-owned upkeep, ideally hook-triggered** | Must | One-time bootstrap of the wiki from the existing code. Afterwards each developer is responsible for the content; ideally a commit/push hook triggers an agent that updates the wiki and commits the result automatically. |
| R5 | **Human retry / instruction via a form** | Must | A human must be able to re-trigger the update and/or hand the agent explicit instructions through a form-like channel (not by editing prompts in code). |
| R6 | **Copilot-only constraint** | Hard constraint | Developers only have GitHub Copilot (company-provided). No API keys, no direct access to foundation models, no third-party LLM SaaS. Anything that needs an OpenAI/Anthropic/Google/etc. key or a self-hosted model is out unless it can run *through* Copilot in a licence-compliant way. |
| R7 | **GitLab, not GitHub** | Hard constraint | Source is hosted on GitLab (CI/CD, MRs, issues, Pages, webhooks are GitLab's). GitHub-only features (Copilot coding agent on GitHub issues, GitHub Actions, DeepWiki hosted on github repos) do not apply directly. |
| R8 | **UI on GitLab Pages (Quartz or similar)** | Nice to have | Browsable wiki site (Quartz preferred) built and served from GitLab Pages, ideally aggregating all repositories. |

## Environment facts and assumptions

Confirmed by the owner:
- Code hosting: GitLab (edition/tier and self-managed vs SaaS: **unknown, assume both must work**).
- LLM access: GitHub Copilot only (Business or Enterprise plan: **unknown**; assume Business, note where Enterprise differs).
- Architecture: microservices, multiple repositories, separate frontend and backend repositories.
- Owner's IDE: JetBrains (PyCharm). Assume a mix of JetBrains IDEs and VS Code in the team.

Assumptions (state explicitly in the ADR if you rely on them):
- Developers can install CLI tooling on their machines (Node.js, Python, git hooks).
- GitLab CI runners exist and can run containers with outbound internet access.
- A GitLab bot/service account and project access tokens can be created.
- A GitHub account with a Copilot seat can be assigned to a bot user **only if licence terms allow it** (must be verified, not assumed).

## Rating legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Meets the requirement as-is |
| 🟡 | Partial, or meets it with a documented workaround |
| ❌ | Does not meet it |
| ❓ | Could not be verified with available sources |

## Clarifications from the owner (2026-09-02, after the first research pass)

These override anything an ADR assumed to the contrary.

| Topic | Clarification |
|-------|---------------|
| R6 test | "No API key" is the test. Developers have GitHub Copilot CLI and the Copilot IDE plugins (PyCharm, VS Code), nothing else. A tool that uses the developer's Copilot login (OAuth session, no key) passes; a tool that needs a provider key fails. |
| Where the LLM runs | Only on a developer's machine, through Copilot CLI or IDE Copilot logged in as that developer. There is no bot, machine account, or GitHub App identity. Shared GitLab runners never call Copilot; they run deterministic jobs only. Any local pipeline the CLI can use is fine. |
| Trigger (R4) | Generic: automation runs when code is committed or pushed. Server-side execution is fine for anything that does not need the LLM. |
| Manual upkeep | Not an option. Automation maintains the wiki; humans steer it (retry, instructions, focus). Approaches whose maintenance step is a human are rejected. |
| Hard constraints | R6 and R7 are disqualifying. An approach that fails either is discarded, not researched further. |
