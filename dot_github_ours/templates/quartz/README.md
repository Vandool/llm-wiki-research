# Wiki site (Quartz v5) — `.gitlab/wiki-site/`

Installed by wiki-kit. These four files build the repository wiki (`wiki/` by default) into a static
site with [Quartz v5](https://quartz.jzhao.xyz/) and are used unchanged by the CI jobs in
`.gitlab/ci/wiki.gitlab-ci.yml` and by you locally.

| File | Purpose |
|---|---|
| `build.sh` | The whole build: pinned Quartz fetch, `npm ci`, config placeholders, content copy, `npx quartz plugin install`, `npx quartz build`. Same steps in CI and locally. |
| `quartz.config.yaml` | Quartz v5 YAML config (`configuration:` + `plugins:`). `build.sh` resolves `__WIKI_PAGE_TITLE__`, `__WIKI_REPO_URL__`, `__WIKI_REQUESTS_URL__` and rewrites `baseUrl`; never edit those placeholders by hand. |
| `quartz.lock.json` | Pins the `github:quartz-community/*` plugins (commit per plugin) used by `npx quartz plugin install`. Committed; regenerate deliberately (below). |
| `README.md` | This file. |

## Local preview

Needs Node >= 22, git and network access (the first run fetches Quartz and its dependencies; 2–4 minutes).

```sh
source ~/.nvm/nvm.sh && nvm use 22 && WIKI_SERVE=1 bash .gitlab/wiki-site/build.sh
```

Then open <http://localhost:8080>. Without `WIKI_SERVE=1` the script only writes `public/` and exits.

One-off build with a sub-path (what the preview and staging jobs do):

```sh
WIKI_BASE_URL=localhost:8080/preview WIKI_BASE_DIR=/preview bash .gitlab/wiki-site/build.sh
```

## Environment variables read by `build.sh`

| Variable | Default | Meaning |
|---|---|---|
| `WIKI_DIR` | `wiki` | Wiki source directory (copied into Quartz's `content/`). |
| `WIKI_SITE_DIR` | `.gitlab/wiki-site` | Where these files live. |
| `WIKI_BUILD_DIR` | `.wiki-build` | Scratch checkout of Quartz (git-ignored; cached in CI). |
| `WIKI_OUT` | `<repo>/public` | Output directory (GitLab Pages publishes `public/`). |
| `WIKI_QUARTZ_REPO` | `https://github.com/jackyzha0/quartz.git` | Quartz source. Quartz core is not on npm. |
| `WIKI_QUARTZ_REF` | `v5.0.0` | Tag, branch or SHA to fetch. Keep in sync with `quartz.lock.json` and the CI variable of the same name. |
| `WIKI_BASE_URL` | `localhost:8080` | Deployed host (+ sub-path) without protocol; written into `baseUrl`. |
| `WIKI_BASE_DIR` | `/` | Sub-path passed to `quartz build --baseDir` (e.g. `/staging`, `/<branch-slug>`). |
| `WIKI_PAGE_TITLE` | `pages.site_title` from `.github/wiki.config.json`, else `<project> wiki` | Site title. |
| `WIKI_CONCURRENCY` | (Quartz default) | `quartz build --concurrency N`; lower it on small runners. |
| `WIKI_SERVE` | `0` | `1` adds `--serve` (local preview server). |
| `npm_config_cache` | `<repo>/.npm` | npm cache location (cached in CI). |

`CI_PROJECT_URL`, `CI_DEFAULT_BRANCH` and `CI_PROJECT_TITLE` are picked up automatically in CI to fill
the footer links ("Repository", "Request a wiki change" → `wiki/requests.md` in the GitLab editor).

## What is never published

`build.sh` copies `wiki/` into `content/` and then deletes `instructions.md`, `requests.md`,
`.manifest.json`, `.wiki-plan.json`, `.gitignore`, `log/`, `private/`, `templates/`, `.obsidian/`.
`quartz.config.yaml`'s `ignorePatterns` lists the same names, so both layers agree. Pages with
`draft: true` are removed by the `remove-draft` plugin; the kit never sets `draft` (it uses `status: draft`
instead), so draft wiki pages are published and shown with their status.

## How `quartz.lock.json` is produced and committed

1. Run a build once with the plugin lock absent (or with the versions you want to bump):
   `rm -f .gitlab/wiki-site/quartz.lock.json && bash .gitlab/wiki-site/build.sh`
   `npx quartz plugin install` resolves every `github:quartz-community/*` plugin named in
   `quartz.config.yaml` and writes `.wiki-build/quartz.lock.json`.
2. Check the site (`python3 tests/check_site_links.py public` in the kit repo, or open it locally).
3. Copy the lock next to the config and commit it:
   `cp .wiki-build/quartz.lock.json .gitlab/wiki-site/quartz.lock.json`
4. CI never runs `plugin install --latest`; it installs exactly what the committed lock says and caches
   `.wiki-build/.quartz/plugins/` per `WIKI_QUARTZ_REF`.

Upgrading Quartz itself: bump `WIKI_QUARTZ_REF` in `.gitlab/ci/wiki.gitlab-ci.yml` (and locally via the
env var), rebuild, regenerate the lock as above, review the diff of `public/`, commit both.

## Troubleshooting

- `Quartz v5 needs Node >= 22`: `nvm use 22` (or use the `node:22-bookworm` image in CI).
- `wiki/index.md missing`: run `python3 .github/skills/wiki-maintain/scripts/index.py --write` first.
- Plugin errors ("… is not a function", unknown option): compare `quartz.config.yaml` with
  `.wiki-build/quartz.config.default.yaml` from the fetched Quartz version; plugin names and options
  are only validated by a real build.
- Links broken under a sub-path: check that `WIKI_BASE_URL` includes the sub-path and `WIKI_BASE_DIR`
  starts with `/`; the CI `before_script` derives both from `CI_PAGES_URL`.
- External font requests in the output: `fontOrigin: local` is set; the build prints a warning if any
  `fonts.googleapis.com` reference survives.
