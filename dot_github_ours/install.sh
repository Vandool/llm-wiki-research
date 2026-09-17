#!/usr/bin/env sh
# wiki-kit installer wrapper. Two ways to use it:
#   1) from a checkout:      sh /path/to/kit/install.sh /path/to/repo [install.py flags]
#   2) piped from a URL:     curl -fsSL https://<host>/<group>/wiki-kit/-/raw/main/install.sh | sh -s -- /path/to/repo
#      (set WIKI_KIT_URL to the kit's git URL; WIKI_KIT_REF picks the tag/branch, default main)
# Finds python3 / python / py -3 and hands over to install.py with the kit directory derived from $0.
set -u

find_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$c"; return 0
      fi
    fi
  done
  if command -v py >/dev/null 2>&1; then echo "py -3"; return 0; fi
  return 1
}

PY=$(find_python) || { echo "install.sh: Python >= 3.10 not found (python3 / python / py -3)" >&2; exit 3; }

kit_dir=""
case "$0" in
  sh|-sh|bash|-bash|dash|-dash|"") kit_dir="" ;;                  # piped: $0 is the shell name
  *) d=$(cd "$(dirname "$0")" 2>/dev/null && pwd) && [ -f "$d/install.py" ] && kit_dir="$d" ;;
esac

if [ -z "$kit_dir" ]; then
  url="${WIKI_KIT_URL:-}"
  [ -n "$url" ] || { echo "install.sh: not running from a checkout; set WIKI_KIT_URL=<git url of the kit> (and WIKI_KIT_REF, default main)" >&2; exit 2; }
  command -v git >/dev/null 2>&1 || { echo "install.sh: git is required to fetch the kit" >&2; exit 3; }
  tmp=$(mktemp -d 2>/dev/null || mktemp -d -t wikikit)
  trap 'rm -rf "$tmp"' EXIT INT TERM
  echo "install.sh: cloning $url at ${WIKI_KIT_REF:-main} ..." >&2
  git clone -q --depth 1 --branch "${WIKI_KIT_REF:-main}" "$url" "$tmp/kit" || { echo "install.sh: clone failed" >&2; exit 3; }
  kit_dir="$tmp/kit"
fi

exec $PY "$kit_dir/install.py" "$@"
