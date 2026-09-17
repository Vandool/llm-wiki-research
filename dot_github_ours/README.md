# Wiki-Kit

A repository-agnostic **GitHub Copilot custom agent** that bootstraps, maintains and publishes a
per-repository LLM wiki. Install it into any repository, steer it through `wiki/instructions.md`,
initialise it once interactively, and let it run automatically from a git hook. The site is built with
**Quartz v5** and published to **GitLab Pages** per branch. No API keys: the model runs only on a
developer machine through the Copilot CLI under that developer's login; GitLab runs deterministic
checks only.

This directory is the kit *and* its own repository: `.github/` is copied verbatim into targets and is
also the Copilot configuration of this repository (dogfood).

## What you get

| Piece | Where (in a target repository) |
|---|---|
| Custom agent `wiki-maintainer` (librarian, not developer) | `.github/agents/wiki-maintainer.agent.md` |
| Skills `/wiki-init`, `/wiki-update`, `/wiki-page`, `/wiki-query`, `/wiki-lint` and the `wiki-maintain` toolbox | `.github/skills/*/SKILL.md` |
| Hooks: session context, write/shell/read guard, lint feedback, stop gate | `.github/hooks/wiki-guard.json` + `scripts/hook_guard.py`, `scripts/stop_gate.py` |
| Deterministic scripts (facts, staleness, lint, backlinks, indexes, manifest, plan, drivers) | `.github/skills/wiki-maintain/scripts/` (Python >= 3.10, stdlib only) |
| Authoring contract and the managed block in `copilot-instructions.md` | `.github/instructions/wiki.instructions.md`, `.github/copilot-instructions.md` |
| Config | `.github/wiki.config.json` |
| Wiki scaffold and the project brief | `wiki/`, `wiki/instructions.md` |
| GitLab CI include (`wiki:verify`, `wiki:pages`, `wiki:pages:staging`, `wiki:pages:preview`) | `.gitlab/ci/wiki.gitlab-ci.yml` + a two-line `include` in `.gitlab-ci.yml` |
| Quartz v5 site definition and build script | `.gitlab/wiki-site/{quartz.config.yaml,quartz.lock.json,build.sh}` |
| Git hooks (post-commit starts the maintainer in the background; pre-push warns about staleness) | `.git/hooks/{post-commit,pre-push}` trampolines |

## Lifecycle

1. **Install** (deterministic, idempotent): `python3 install.py /path/to/repo` — see `docs/INSTALL.md`.
2. **Init** (interactive, once): `cd repo && WIKI_RUN=1 copilot --agent wiki-maintainer --model <models.bootstrap>` then `/wiki-init`.
   Q&A in five screens, writes `wiki/instructions.md` and the config, generates the fact pages, proposes the
   module map (with the negative-space list and the three least-understood places) for approval, compiles
   `wiki/conventions.md`, integrates CI, writes the cluster plan `wiki/.wiki-plan.json`.
3. **Bootstrap** (driver, resumable): `python3 .github/skills/wiki-maintain/scripts/bootstrap.py` runs one
   fresh `copilot -p … /wiki-page <cluster>` session per cluster, leaves before overviews, lint-gated,
   one commit per cluster. Review `overview.md`, `glossary.md`, `product/` afterwards.
4. **Maintenance**: every commit that touches code starts `run.py worker` in the background; `affected.py`
   computes the work list (pages whose declared sources changed, OPEN lines in `wiki/requests.md`, an
   optional instruction). Nothing affected: no model call. Otherwise a headless session edits only the listed
   narrative pages, the stop gate verifies, the worker commits `docs(wiki): update …` with the trailer
   `Wiki-Update: auto`. CI `wiki:verify` re-runs every deterministic check on every MR; `wiki:pages` publishes.

Steering: `wiki/requests.md` (`- [ ] OPEN YYYY-MM-DD @you: …`), `/wiki-update "focus on …"`,
`run.py worker --issue N` (needs `glab`). Details: `docs/OPERATIONS.md`.

## Design in one paragraph

Facts versus narrative: scripts generate every factual page (inventory, symbol index, dependencies,
changelog, ADR index, owners, API and event contracts from OpenAPI/AsyncAPI, every `index.md`, the log);
the model writes only narrative pages, one section at a time, from declared `sources` and diff hunks read
through `excerpt.py` under a byte budget. Every page declares `sources[]` and `last_verified_commit`, so
staleness is a git query (`wiki/.manifest.json`). The guard hook confines writes to the wiki directory,
whitelists shell commands, meters reads and blocks the stop until lint, backlinks and indexes are clean.
The model is denied every git write; the drivers commit after the gate passes. The design rationale lives in
`docs/DESIGN.md`, which is self-contained.

## Repository layout

```
install.py  install.sh  .pre-commit-hooks.yaml  VERSION  CHANGELOG.md  LICENSE
.github/                       the kit (copied verbatim into targets)
  agents/  skills/  hooks/  instructions/  prompts/  wiki.config.json  copilot-instructions.md
  skills/wiki-maintain/{scripts,references,prompts,hooks}/
templates/                     scaffold (wiki/), quartz/, ci/, issue_templates/, gitattributes, gitignore,
                               copilot-instructions.block.md
tests/                         unit + integration tests, fixtures, fake_copilot.py, check_site_links.py
docs/                          INSTALL.md  OPERATIONS.md  DESIGN.md
wiki/                          this repository's own wiki (scaffold until bootstrapped)
```

## Development

```sh
python3 -m unittest discover -s tests -v          # or: python3 -m pytest -q tests
python3 .github/skills/wiki-maintain/scripts/<script>.py --help
```

End-to-end dry run without a model (installs the kit into a copy of the fixture repository, generates
facts, lints, integrates CI):

```sh
KIT=$PWD; T=$(mktemp -d) && git init -q "$T/repo" && cp -R "$KIT/tests/fixtures/sample-repo/." "$T/repo/" \
 && git -C "$T/repo" add -A && git -C "$T/repo" commit -qm fixture \
 && python3 "$KIT/install.py" "$T/repo" --hooks git --yes && cd "$T/repo" \
 && S=.github/skills/wiki-maintain/scripts \
 && python3 $S/facts.py && python3 $S/index.py --write && python3 $S/manifest.py --init \
 && python3 $S/lint.py --all --strict && python3 $S/backlinks.py --check \
 && python3 $S/ci_integrate.py apply --prod-branch main --yes && python3 $S/ci_integrate.py check \
 && python3 $S/affected.py --check-only && git add -A && git commit -qm "wiki: install" \
 && python3 "$KIT/install.py" "$T/repo" --yes | grep -q "up to date" && echo E2E-OK
```

Site build (Node 22, network): `WIKI_BASE_URL=localhost:8080 bash .gitlab/wiki-site/build.sh` in the
target, then `python3 $KIT/tests/check_site_links.py public`.

## Verification status (1.0.0)

Run on 2026-09-07 with Python 3.14, git 2.55, Node 22; `copilot`, `glab`, `pre-commit` and PyYAML absent.

| Check (plan §10) | Result |
|---|---|
| (a) unit and integration tests, `python3 -m unittest discover -s tests` | 188 tests, all pass |
| (b) end-to-end dry run without a model | `E2E-OK`, clean `git status`, exactly one include line |
| (c) hook contract (guard deny/pass in wiki and passive mode, stop gate allow/block/retry, malformed payloads) | as specified |
| (d) Quartz v5.0.0 build at the site root and under `/preview` | built; private files excluded; no external fonts; 424 internal links resolve; breadcrumbs show distinct folder titles |
| (e) CI YAML | structural validator OK (`glab ci lint` needs `glab`); the real gate is the first pipeline on a throwaway GitLab project |
| (f) manual Copilot checks | **not run** (no Copilot CLI on this machine), see below |
| (g) line budgets (copilot block ≤40, `wiki.instructions.md` <150, agent body ≤250, skills ≤120, brief ≤300) | 13 / 95 / 101 / 36–86 / 76 |

Manual checks still to do once the Copilot CLI is installed and logged in (plan §10 f):

1. `copilot -p "say ok" --agent wiki-maintainer -s --no-ask-user` in an installed repository prints ok without an auth error.
2. `WIKI_RUN=1 copilot --agent wiki-maintainer`, ask it to write `README.md`: the deny fires with our reason; read
   `.git/wiki/guard.log` (`keys=` and `args=` fields) for the exact `toolName`/`toolArgs` keys, pin them in
   `hook_guard.py` and add `matcher`s to `.github/hooks/wiki-guard.json`.
3. `/wiki-init` on the fixture repository end to end, then `bootstrap.py --dry-run` and one real cluster run.
4. A one-line code change and commit: a `Wiki-Update: auto` commit touching only `wiki/` appears within minutes.

## Assumptions and open items

Confirm these during the manual Copilot checks (`docs/DESIGN.md` has the full list):

1. Exact `toolName`/`toolArgs` keys of the Copilot CLI hooks are learned from `.git/wiki/guard.log`
   during the first guarded session; until then the guard matches loosely and no `matcher` is set.
2. Whether `/wiki-page <id>` inside `-p` text invokes the skill; the prompts also name the skill in prose.
3. `stop_hook_active` semantics; the retry counter file makes the gate correct either way.
4. `--output-format=json` usage fields are undocumented; token metrics are best-effort (`null` when absent).
5. `npx quartz plugin install` honours the committed `quartz.lock.json`; plugin names/options were verified
   by the build test only.
6. `.post` + `needs: []` starts immediately; worst case is timing.
7. Windows: `nohup … &` detachment from an MSYS hook and the winget install path are unverified.
8. `GIT_DEPTH: 0` costs a full clone on big repositories.
9. The changelog page carries sanitised commit subjects (`audience: [dev]`, never in context packs).
10. In-place runs read the developer's working tree while staleness is computed against HEAD;
    `isolation: worktree` is the fix (default for `commit_policy: branch-and-mr`).
11. `git commit --trailer` needs git >= 2.32; the drivers write trailers into the message instead.
12. `pages.path_prefix` must not equal an existing site folder; `ci_integrate.py detect` warns.

## License

MIT, see `LICENSE`.
