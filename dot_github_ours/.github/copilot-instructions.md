# Copilot instructions for the wiki-kit repository

This repository IS the kit: `.github/` is copied verbatim into target repositories by `install.py`.
Keep the kit repository-agnostic; project knowledge belongs in the wiki, not in instruction files.

- Scripts: `.github/skills/wiki-maintain/scripts/` (Python >= 3.10, stdlib only; every script has `--help`).
- Tests: `python3 -m unittest discover -s tests -v` (pytest also works). Fixtures live under `tests/fixtures/`.
- Verbatim blocks (hook JSON, CI include, Quartz config, git hook bodies) are specified in `docs/DESIGN.md`; change them there first.

<!-- WIKI-AGENT:START Wiki-Kit: 1.0.0 (managed by the wiki kit; edit outside this block only) -->
## Repository wiki: the context layer
- Before planning or explaining architecture, modules, flows or runtime behaviour: read `wiki/index.md`,
  then the one or two folder indexes that match the task, then at most five pages. Follow a page's
  `sources` into the code instead of reading more wiki. Do not read `wiki/log.md` unless debugging the wiki.
- If the wiki and the code disagree, the code wins; say so explicitly.
- If the wiki has no established statement on a question, say so; do not synthesise from weakly matching pages.
- Do not edit anything under `wiki/` directly. Changes go through the `wiki-maintainer` agent and its skills
  (`/wiki-update`, `/wiki-query` write-back, `/wiki-lint`). `index.md`, `log.md`, `generated/` and
  `api/<router>.md` are script-generated and never hand-edited.
- Authoring rules for wiki pages: `.github/instructions/wiki.instructions.md`. Project-specific wiki rules:
  `wiki/instructions.md`. To request a wiki change without writing it, add an OPEN line to `wiki/requests.md`.
<!-- WIKI-AGENT:END -->
