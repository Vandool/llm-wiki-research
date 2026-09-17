#!/usr/bin/env bash
# .gitlab/wiki-site/build.sh — build the wiki with Quartz v5 (Wiki-Kit 1.0.0). Same steps in CI and locally.
# Env (optional): WIKI_DIR=wiki WIKI_SITE_DIR=.gitlab/wiki-site WIKI_BUILD_DIR=.wiki-build WIKI_OUT=<root>/public
#   WIKI_QUARTZ_REPO=https://github.com/jackyzha0/quartz.git WIKI_QUARTZ_REF=v5.0.0
#   WIKI_BASE_URL=localhost:8080 WIKI_BASE_DIR=/ WIKI_PAGE_TITLE= WIKI_CONCURRENCY= WIKI_SERVE=0
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; cd "$ROOT"
WIKI_DIR="${WIKI_DIR:-wiki}"; SITE_DIR="${WIKI_SITE_DIR:-.gitlab/wiki-site}"; BUILD="${WIKI_BUILD_DIR:-.wiki-build}"
OUT="${WIKI_OUT:-$ROOT/public}"; REPO="${WIKI_QUARTZ_REPO:-https://github.com/jackyzha0/quartz.git}"
REF="${WIKI_QUARTZ_REF:-v5.0.0}"; BASE_URL="${WIKI_BASE_URL:-localhost:8080}"; BASE_DIR="${WIKI_BASE_DIR:-/}"
node -e 'const m=+process.versions.node.split(".")[0]; if(m<22){console.error("Quartz v5 needs Node >= 22, found "+process.version);process.exit(1)}'
test -f "$WIKI_DIR/index.md" || { echo "build.sh: $WIKI_DIR/index.md missing — GitLab Pages needs an index page" >&2; exit 1; }
# 1. Quartz core at a pinned ref; refreshed only when the ref changes (keeps the .quartz/ plugin cache)
mkdir -p "$BUILD"
if [ "$(cat "$BUILD/.quartz-ref" 2>/dev/null || true)" != "$REF" ]; then
  find "$BUILD" -mindepth 1 -maxdepth 1 ! -name .quartz -exec rm -rf {} +
  git -C "$BUILD" init -q
  git -C "$BUILD" fetch -q --depth 1 "$REPO" "$REF"
  git -C "$BUILD" checkout -q --force FETCH_HEAD
  echo "$REF" > "$BUILD/.quartz-ref"
fi
# 2. dependencies from the upstream package-lock.json (reproducible)
( cd "$BUILD" && hash -r && npm ci --cache "${npm_config_cache:-$ROOT/.npm}" --prefer-offline --no-audit --no-fund )
# 3. our config and plugin lock, placeholders resolved
TITLE="${WIKI_PAGE_TITLE:-}"
if [ -z "$TITLE" ] && [ -f ".github/wiki.config.json" ]; then
  TITLE="$(node -p 'try{((JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"))).pages||{}).site_title||""}catch(e){""}' ".github/wiki.config.json")"
fi
[ -n "$TITLE" ] || TITLE="${CI_PROJECT_TITLE:-$(basename "$ROOT")} wiki"
REPO_URL="${CI_PROJECT_URL:-}"; REQ_URL="${REPO_URL:+$REPO_URL/-/edit/${CI_DEFAULT_BRANCH:-main}/$WIKI_DIR/requests.md}"
sed -e "s|__WIKI_PAGE_TITLE__|${TITLE//|/\\|}|g" -e "s|__WIKI_REPO_URL__|$REPO_URL|g" -e "s|__WIKI_REQUESTS_URL__|$REQ_URL|g" \
    -e "s|^\([[:space:]]*baseUrl:\).*|\1 \"$BASE_URL\"|" "$SITE_DIR/quartz.config.yaml" > "$BUILD/quartz.config.yaml"
[ -f "$SITE_DIR/quartz.lock.json" ] && cp "$SITE_DIR/quartz.lock.json" "$BUILD/quartz.lock.json"
# 4. content: copy, then prune what must never be published (belt and braces with ignorePatterns)
rm -rf "$BUILD/content"; mkdir -p "$BUILD/content"; cp -R "$WIKI_DIR/." "$BUILD/content/"
( cd "$BUILD/content" && rm -rf .manifest.json .wiki-plan.json .gitignore instructions.md requests.md private templates .obsidian log )
# 5. plugins per quartz.lock.json / config (never --latest in CI), then build
( cd "$BUILD" && npx quartz plugin install )
ARGS=(build -o "$OUT" --baseDir "$BASE_DIR")
[ -n "${WIKI_CONCURRENCY:-}" ] && ARGS+=(--concurrency "$WIKI_CONCURRENCY")
[ "${WIKI_SERVE:-0}" = "1" ] && ARGS+=(--serve)
( cd "$BUILD" && npx quartz "${ARGS[@]}" )
test -f "$OUT/index.html" || { echo "build.sh: no index.html produced" >&2; exit 1; }
if grep -rqs "fonts.googleapis.com" "$OUT"; then echo "build.sh: WARNING external font references despite fontOrigin: local" >&2; fi
echo "build.sh: built $OUT for https://$BASE_URL (baseDir $BASE_DIR, quartz $REF)"
