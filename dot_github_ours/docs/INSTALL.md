# Installing the wiki kit

The kit turns a repository into one that maintains and publishes its own wiki: a GitHub Copilot custom
agent (`wiki-maintainer`) with skills, hooks and deterministic scripts, plus Quartz v5 publishing to
GitLab Pages per branch. Installation is deterministic and idempotent; nothing calls a model.

## Prerequisites

| Need | Why | Check |
|---|---|---|
| Python >= 3.10 (stdlib only) | installer, scripts, git hooks, CI `wiki:verify` | `python3 --version` |
| git >= 2.20 | hooks, trailers, worktrees | `git --version` |
| GitHub Copilot CLI with a seat that allows the CLI | the only place a model runs (on your machine, under your login) | `copilot --version`, then `copilot login` once |
| Node >= 22 | only for building the site locally (CI uses `node:22-bookworm`) | `source ~/.nvm/nvm.sh && nvm use 22` |
| `glab` (optional) | `ci_integrate.py check` server-side lint; `--issue N` steering; `branch-and-mr` commit policy | `glab auth status` |
| PyYAML (optional) | second-best CI validator when `glab` is absent; the structural validator always works | `python3 -c "import yaml"` |
| GitLab >= 17.9 | the CI include as shipped (`pages:` keyword with `publish`, user-named Pages jobs, `path_prefix`) | older: `docs/OPERATIONS.md`, "GitLab 17.4–17.8" |

Install the Copilot CLI with `npm i -g @github/copilot` (Node 22) or `curl -fsSL https://gh.io/copilot-install | bash`.

## Install

From a checkout of the kit:

```sh
python3 /path/to/wiki-kit/install.py /path/to/your/repo
# or
sh /path/to/wiki-kit/install.sh /path/to/your/repo
```

Piped from a URL (clones the kit at `WIKI_KIT_REF`, default `main`, into a temp dir first):

```sh
WIKI_KIT_URL=https://gitlab.example.com/platform/wiki-kit.git \
  curl -fsSL https://gitlab.example.com/platform/wiki-kit/-/raw/main/install.sh | sh -s -- /path/to/your/repo
```

Flags:

| Flag | Effect |
|---|---|
| `--wiki-dir DIR` | wiki directory other than `wiki` (recorded in the config, `git config wiki.dir`, CI variable and `.gitattributes` lines follow) |
| `--hooks auto\|git\|pre-commit\|none` | `auto` (default): pre-commit when `.pre-commit-config.yaml` and the binary exist, else `.git/hooks` trampolines; `none` also allows a non-git target |
| `--no-ci` / `--no-site` | skip `.gitlab/ci/wiki.gitlab-ci.yml` / `.gitlab/wiki-site/` |
| `--issue-template` | also install `.gitlab/issue_templates/Wiki request.md` (the GitLab "form") |
| `--dry-run` | print every action and diff, write nothing |
| `--check` | report the state (missing, modified, hooks); exit 1 when anything needs attention |
| `--upgrade` | overwrite kit files with this kit version unless you modified them (see below) |
| `--force` | overwrite (or, with `--uninstall`, remove) locally modified kit files too |
| `--uninstall` | remove everything the kit added; keep `wiki/` and the config answers |
| `--yes` | no confirmation prompt (needed in scripts) |
| `--json` | one JSON object on stdout |

What lands in the repository (plan §7):

```
.github/copilot-instructions.md       managed block between <!-- WIKI-AGENT:START --> and <!-- WIKI-AGENT:END -->
.github/wiki.config.json              defaults + detected values; /wiki-init fills in the rest
.github/agents/wiki-maintainer.agent.md
.github/instructions/wiki.instructions.md
.github/hooks/wiki-guard.json         Copilot hooks: write guard, lint feedback, stop gate
.github/prompts/wiki-*.prompt.md      optional VS Code wrappers
.github/skills/{wiki-init,wiki-update,wiki-page,wiki-query,wiki-lint,wiki-maintain}/
.github/skills/wiki-maintain/{scripts,references,prompts,hooks}/
.gitlab/ci/wiki.gitlab-ci.yml         CI jobs; the include line is added by /wiki-init (ci_integrate.py apply)
.gitlab/wiki-site/{quartz.config.yaml,quartz.lock.json,build.sh,README.md}
.gitattributes / .gitignore           lines under `# wiki-kit`
.git/hooks/{post-commit,pre-push}     trampolines (per clone, not committed)
wiki/                                 scaffold: index, instructions, requests, overview, glossary, catalog, folder indexes
```

Every kit file is recorded with its sha256 under `kit.files` in `.github/wiki.config.json`; that record is
what makes upgrades and uninstalls safe. Commit everything except `.git/hooks`.

## First run

```sh
copilot login                                                   # once per machine
cd /path/to/your/repo
WIKI_RUN=1 copilot --agent wiki-maintainer --model claude-sonnet-4.6   # the model pinned in models.bootstrap
/wiki-init
```

`/wiki-init` is interactive: five screens of questions prefilled from detection, writes
`wiki/instructions.md` and the config, generates the fact pages, proposes the module map for approval,
integrates the CI include (shows the diff, asks, validates) and hands over to the bootstrap driver, which
writes the wiki one cluster per fresh Copilot session and commits per cluster. Review `overview.md`,
`glossary.md` (and `product/` if enabled); from then on the `post-commit` hook keeps the wiki current.

Two fifteen-minute checks before relying on it (research README §7): `copilot -p "say ok" --agent
wiki-maintainer -s --no-ask-user` under the company login must print ok; and in `WIKI_RUN=1 copilot --agent
wiki-maintainer`, asking it to write `README.md` must be denied by the guard hook.

## Every teammate, every clone

Git hooks are not committed. After cloning (or pulling the kit commit):

```sh
python3 .github/skills/wiki-maintain/scripts/hooks.py install      # trampolines into .git/hooks
python3 .github/skills/wiki-maintain/scripts/hooks.py status
copilot login
```

With a hook manager: `hooks.py install` prints the lines for husky/lefthook when `core.hooksPath` is set,
and the `.pre-commit-config.yaml` snippet with `--hooks pre-commit` (then
`pre-commit install --hook-type pre-commit --hook-type post-commit --hook-type pre-push`).
Pre-existing `.git/hooks/post-commit` or `pre-push` scripts are kept as `<name>.local` and still run.

A clone without hooks is harmless: the CI job `wiki:verify` reports a stale wiki on every merge request.

## Upgrade

```sh
python3 /path/to/newer-kit/install.py /path/to/your/repo --upgrade
```

- Kit files whose sha256 still matches the record are replaced; files you modified are skipped with a
  warning (`--force` overwrites them).
- The PROJECT SETTINGS block of `.gitlab/ci/wiki.gitlab-ci.yml` (branches, publish flags) is carried over.
- New config keys are merged; your values and `/wiki-init` answers stay.
- The managed block in `.github/copilot-instructions.md` is replaced; text outside it is untouched.
- Scaffold files (`wiki/**`) are never overwritten.
- `--check` beforehand shows what would happen; `--dry-run --upgrade` shows the diffs.

A second identical run prints `up to date`.

## Uninstall

```sh
python3 /path/to/wiki-kit/install.py /path/to/your/repo --uninstall
```

Removes the include line from `.gitlab-ci.yml`, the trampolines (restoring `<name>.local`), kit files
whose sha256 still matches, the managed block, the `# wiki-kit` lines, and empty directories. Leaves
`wiki/` and `.github/wiki.config.json` (answers; the `kit` record is cleared) in place. Locally modified
kit files are kept unless `--force`.

## Windows notes

- Hooks are POSIX `sh`; Git for Windows runs them under its bundled bash. `hooks.py` writes the same
  trampolines. The background start (`nohup … &` from a hook) is unverified on MSYS (plan §11.7); if a
  commit appears to hang or the worker never starts, use `--hooks pre-commit` (pre-commit runs hooks
  through Python) or start runs by hand: `python3 .github/skills/wiki-maintain/scripts/run.py worker --foreground`.
- `install.sh`/the hooks look for `python3`, then `python`, then `py -3`.
- Set `git config core.autocrlf false` for the repository or keep `* text=auto eol=lf`; the scripts write
  LF and lint rejects CRLF.
- Paths in the config are POSIX (`docs/wiki`, not `docs\wiki`).
- `copilot` on Windows is `copilot.cmd`; `run.py` finds it, or set `WIKI_COPILOT_BIN`.
