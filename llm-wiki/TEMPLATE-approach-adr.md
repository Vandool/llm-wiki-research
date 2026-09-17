---
id: ADR-NN
title: <Approach name>
status: candidate        # candidate | recommended | rejected | superseded (changed by decision, not by researcher)
date: 2026-09-02
researcher: <agent label>
fit_score: <0-10>        # overall fit against ../requirements.md, justified in section 12
confidence: <low|medium|high>   # how well the key claims are verified against fetched sources
requirement_ratings: {R1: "", R2: "", R3: "", R4: "", R5: "", R6: "", R7: "", R8: ""}   # same symbols as section 5
tags: []
---

# ADR-NN: <Approach name>

<!--
Uniform template for all approach ADRs in llm-wiki/approaches/.
Keep ALL headings, in this order, with these numbers. Add sub-sections freely.
Target length: 250-600 lines. Prefer tables and short paragraphs.
Mark unverified claims with ❓ and say what would verify them.
Never invent product features, URLs, or paper titles; if a search finds nothing, say so.
-->

## 1. Summary
One paragraph: what the approach is, who originated it (project / paper / company), maturity as of 2026-09, and a one-sentence verdict for our situation.

## 2. Context
Why this approach is on the table for us. Link back to requirement IDs (R1..R8) and to the background docs in `../background/` where relevant.

## 3. The approach
### 3.1 Origin and provenance
Who made it, when, licence, activity level, notable forks/spin-offs.
### 3.2 How it works (architecture)
Components, data flow, where the LLM runs, who authenticates, what triggers a run, what is written and committed. Include a mermaid or ASCII diagram.
### 3.3 Wiki content model it implies
Page types, index/log conventions, frontmatter, linking, where agent-facing vs human-facing content lives.
### 3.4 Trigger and automation model
Local hook, CI job, webhook service, manual, scheduled. Loop-prevention, concurrency, and merge-conflict handling.
### 3.5 Human retry / instruction channel ("the form")
How a human re-triggers a run or hands over instructions without editing prompt code.
### 3.6 Multi-repo / microservice fit
Per-repo vs central wiki, cross-repo links, contracts/APIs/events, ownership.
### 3.7 Publishing / UI
How it would be served (Quartz on GitLab Pages or alternatives).

## 4. Concrete implementation sketch for our environment
Step-by-step for GitLab + Copilot-only + multi-repo. Directory layout, config snippets, CI YAML or hook skeletons where useful. Mark anything unverified with ❓.

## 5. Requirements check
Use exactly these IDs and the legend from `../requirements.md`.

| ID | Requirement (short) | Rating | Evidence / notes |
|----|---------------------|--------|------------------|
| R1 | Dual audience (agents + devs + PO) | | |
| R2 | Context layer for whole AI dev pipeline | | |
| R3 | Multi-repo microservices, future autonomous agents | | |
| R4 | Bootstrap once, dev-owned upkeep, hook-triggered auto-update | | |
| R5 | Human retry / instructions via a form | | |
| R6 | Copilot-only (no API keys, no direct model access) | | |
| R7 | GitLab, not GitHub | | |
| R8 | UI on GitLab Pages (Quartz) | | |

## 6. Pros

## 7. Cons and risks

## 8. Known problems reported by practitioners, and fixes
Concrete issues people hit with this approach (blogs, issues, forum posts) and the fixes or mitigations they found. Cite each.

## 9. Scaling considerations
Large codebases, many repos, token budget, drift/staleness, incremental vs full regeneration. Cite papers and posts where they apply.

## 10. Effort and cost estimate
| Item | Estimate | Notes |
|------|----------|-------|
| Bootstrap (one-off) | | |
| Per-commit / per-MR run | | |
| Ongoing maintenance per week | | |
| Infrastructure | | |
| Licensing / seats | | |

## 11. Open questions and spike plan
What must be verified before adoption, and the smallest experiment that verifies it.

## 12. Verdict
Fit score N/10 with justification. When to choose this. Which other approaches it combines well with (reference their ADR ids).

## 13. Sources
Numbered list. For each: title, author/org, date, URL, what was taken from it, and a tag: `[fetched]` (you opened it) or `[snippet]` (search result only) or `[memory]` (not verified online).
