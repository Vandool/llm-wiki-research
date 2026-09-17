# llm-wiki-research

Research into approaches for building an **LLM-maintained wiki for code repositories** — a
knowledge/context layer consumed by both coding agents and humans (developers and product owners).

This repository holds the research (decision records, background studies, requirements) and a first
working toolkit. The **initial version is decided to be based on LangChain's OpenWiki** (see
`llm-wiki/approaches/ADR-06-openwiki-langchain.md`), an MIT-licensed generator that reads a repo and
maintains an Open Knowledge Format (OKF) wiki, with a Copilot provider and a GitLab CI example.

## Constraints driving the design

- **Copilot-only** — no API keys or third-party LLM SaaS; the model runs through GitHub Copilot.
- **GitLab-hosted** — CI/CD, MRs, issues, Pages are GitLab's (not GitHub).
- **Multi-repo / microservices** — frontend and backend repos; cross-repo knowledge must be discoverable.
- **Bootstrap once, then hook-triggered developer-owned upkeep**, with a form-based human retry channel.
- **Optional** browsable site on GitLab Pages (Quartz preferred).

Full requirements: [`llm-wiki/requirements.md`](llm-wiki/requirements.md).

## Repository map

```
llm-wiki-research/
├── .gitignore                     # repo-wide ignore rules
├── README.md                      # this file
│
├── llm-wiki/                      # Research vault (Obsidian) — the decision material
│   ├── README.md                  #   consolidated decision document (what to act on)
│   ├── requirements.md            #   R1–R8 requirements every ADR is rated against
│   ├── RUN-LOG.md                 #   research run log
│   ├── TEMPLATE-approach-adr.md   #   ADR template for approaches
│   ├── approaches/                #   Architecture Decision Records (one per approach)
│   │   ├── ADR-01-local-git-hook-copilot-cli.md
│   │   ├── ADR-02-gitlab-ci-copilot-cli-headless.md
│   │   ├── ADR-03-copilot-sdk-wiki-bot-service.md
│   │   ├── ADR-06-openwiki-langchain.md        # ← chosen basis for the initial version
│   │   ├── ADR-07-google-okf-and-agent-context-standards.md
│   │   ├── ADR-08-hybrid-deterministic-backbone-plus-llm-narrative.md
│   │   ├── ADR-09-multi-repo-hub-quartz-gitlab-pages.md
│   │   └── rejected/              #   ADR-04, ADR-05, ADR-10 (rejected approaches)
│   └── background/                #   supporting studies
│       ├── landscape.md           #     existing tools / prior art
│       ├── content-model.md       #     page types, frontmatter, links
│       └── problems-and-fixes.md  #     known failure modes and mitigations
│
└── dot_github_ours/               # "Wiki-Kit" — first working toolkit (Copilot custom agent)
    ├── README.md                  #   kit overview and lifecycle
    ├── install.py / install.sh    #   deterministic installer into a target repo
    ├── .github/                   #   Copilot config copied into targets (agents, skills, hooks)
    │   ├── copilot-instructions.md
    │   ├── agents/                #     wiki-maintainer agent profile
    │   ├── skills/               #     wiki-init / update / page / query / lint + toolbox scripts
    │   ├── hooks/                #     write/shell/read guard, lint feedback, stop gate
    │   ├── instructions/         #     authoring contract
    │   ├── prompts/
    │   └── wiki.config.json
    ├── wiki/                       #   wiki scaffold (OKF pages: api, events, modules, concepts, …)
    ├── templates/                 #   gitignore, gitattributes, CI, Quartz site, issue templates
    ├── docs/                      #   DESIGN.md, INSTALL.md, OPERATIONS.md
    ├── tests/                     #   pytest suite for the deterministic scripts
    ├── CHANGELOG.md · VERSION · LICENSE
    └── .gitlab-ci.yml · .pre-commit-hooks.yaml
```

## Where to start

| I want to… | Read |
|---|---|
| Understand the decision and what to build | [`llm-wiki/README.md`](llm-wiki/README.md) |
| See the chosen OpenWiki/LangChain approach | [`llm-wiki/approaches/ADR-06-openwiki-langchain.md`](llm-wiki/approaches/ADR-06-openwiki-langchain.md) |
| Check the requirements | [`llm-wiki/requirements.md`](llm-wiki/requirements.md) |
| Install / run the current toolkit | [`dot_github_ours/README.md`](dot_github_ours/README.md), [`dot_github_ours/docs/INSTALL.md`](dot_github_ours/docs/INSTALL.md) |
| Understand the toolkit design | [`dot_github_ours/docs/DESIGN.md`](dot_github_ours/docs/DESIGN.md) |

## Status

Research complete; initial implementation based on OpenWiki (LangChain) in progress. The `dot_github_ours`
kit is an earlier deterministic-backbone-plus-Copilot prototype kept as reference and dogfood.
