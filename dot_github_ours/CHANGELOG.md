# Changelog

All notable changes to the wiki kit. The format follows Keep a Changelog; the kit version is in `VERSION`
and is stamped into every managed file header (`Wiki-Kit: 1.0.0`).

## [1.0.0] - 2026-09-07

### Added
- Custom agent `wiki-maintainer` with skills `wiki-init`, `wiki-update`, `wiki-page`, `wiki-query`,
  `wiki-lint` and the `wiki-maintain` toolbox (page templates, budgets, frontmatter schema, prompt skeletons).
- Hooks: `sessionStart` context injection, `preToolUse` guard (wiki mode / passive mode), `postToolUse`
  lint feedback, `agentStop` gate with three retries and a `verified` marker.
- Deterministic scripts (Python >= 3.10, stdlib only): `facts`, `affected`, `lint` (L01–L17 minus L11),
  `backlinks`, `index`, `manifest` (+ staleness), `requests`, `log`, `excerpt`, `plan`, `detect`,
  `template`, `config`, `ci_integrate`, `hooks`, `run` (worker + interactive run state), `bootstrap`.
- Installer (`install.py`, `install.sh`, pre-commit hook definitions) with kit/scaffold/block/lines/hook/record
  policies, `--upgrade`, `--uninstall`, `--dry-run`, `--check`.
- GitLab CI include with `wiki:verify`, `wiki:pages`, `wiki:pages:staging`, `wiki:pages:preview`
  (parallel deployments) in stage `.post`; Quartz v5 site template with pinned upstream fetch and plugin lock.
- Wiki scaffold, project brief template (`wiki/instructions.md`), requests channel, issue template.
- Test-suite with a sample repository, a fixture wiki (one violation per lint rule), CI include fixtures,
  hook payload samples and a fake Copilot binary.

### Decisions recorded during the first build
- `lint.py` reports coverage gaps (L12) as `info`: a freshly installed, not yet bootstrapped wiki must pass
  `lint --all --strict` in CI; gaps are work for `/wiki-init` and `affected.py`, not an invalid wiki.
- L13 inline citation checks skip human-owned pages and the pages that describe the citation microformat
  (Instructions, Conventions, Requests, Glossary).
- The scaffold actor is `human:<login>` (never the git display name, which may contain spaces).
- `backlinks.py --check` without `--changed`/`--all` means `--all` (the CI include calls it bare).
- `facts.py` reads the working tree and bumps `last_verified_commit`/`generated.at` only when a page's
  content changes, so unchanged fact pages stay byte-identical across commits.
- Links from generated Contract pages to a not-yet-written `<name>-guide.md` are `info`, never errors.
- Coverage gaps become work only when files under them changed since the checkpoint (all gaps in full mode).
### Quartz v5.0.0 build test (fixes against the fetched `quartz.config.default.yaml`)
- Plugin sources use the upstream form `github:quartz-community/<name>` (unquoted). With the npm form
  `"@quartz-community/<name>"` the v5.0.0 CLI resolves the packages but leaves layout components undefined
  (`ComponentResources: Cannot destructure property 'css'`).
- Dropped `unlisted-pages` and `quartz-fonts`: the installer resolves plugins through GitHub and neither has a
  repository in the `quartz-community` organisation (HTTP 404). Fonts are handled by the core theme
  (`fontOrigin: local`; the built site references no `fonts.googleapis.com` URL).
- `defaultDateType: modified` moved from the `created-modified-date` plugin options to the top-level
  `configuration:` block, where the `content-meta` plugin reads it.
- Added the top-level `layout:` block (`groups.toolbar`, `byPageType`) that the `group: toolbar` entries need.
- `quartz.lock.json` committed to `templates/quartz/` from the first successful build (upstream lock, 42 plugins,
  each pinned to a commit).
- Generated Contract pages link to `<name>-guide.md` only when the guide exists (a not-yet-written guide is an L12
  gap), so the published site never carries a broken link.

### Runner and hook decisions
- The checkpoint advances inside the update/bootstrap commit (only on a fully `ok` judge) so the tree ends clean.
- Loop guards (trailer, wiki-only HEAD) apply to `--trigger post-commit` only; manual runs always proceed.
- The judge requires the `verified` marker to equal the wiki tree hash at CLI exit; failing narrative pages are
  reverted and the rest committed as `… (partial)`; timeouts, a missing sentinel or a failed stop gate revert every
  narrative change, commit the facts and log `Deferred` (exit 4); a write outside the wiki resets the wiki dir and
  commits nothing.
- `run.py begin` takes a pid-less interactive lock that a later `begin` reclaims.
- `bootstrap.py` refreshes facts/index/manifest before every cluster, splits a cluster at most once, commits a dirty
  wiki at start (`docs(wiki): bootstrap start`) and the final checkpoint (`docs(wiki): bootstrap checkpoint`);
  `--wait-lock SECONDS` waits for an interactive session to end (used by `run.py bootstrap --detach`).
- `commit_policy: branch-and-mr` is commit-level isolation: the model runs in place, the commit lands on
  `wiki/update-<id>` through a temporary worktree and `glab mr create` (skipped without `glab`). Not exercised
  against a remote.
- The changelog page's `changelog://` range ends at the newest included commit, never HEAD, so `facts.py --check`
  stays clean across wiki-only commits.
- Cluster budgets count only the cited `#La-Lb` range or `::Symbol` span, so `plan.py split` converges.
