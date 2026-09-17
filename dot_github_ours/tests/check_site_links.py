#!/usr/bin/env python3
"""check_site_links.py PUBLIC_DIR [--base /prefix] [--no-breadcrumbs] [--verbose]

Post-build checks for the Quartz site (plan §10 d), stdlib only:
  1. every internal href/src in every HTML file resolves to a file: `x`, `x.html` or `x/index.html`
     (fails on the FIRST miss, naming page and link);
  2. with --base, every absolute internal link starts with that prefix (sub-path deployments);
  3. at least two folder pages (`<folder>/index.html`) render DISTINCT titles, and the folder crumb in the
     breadcrumbs of pages inside two different folders differs (Quartz issue #676 regression guard).
Exit 0 when everything passes, 1 on the first failure, 2 on usage errors.
"""
from __future__ import annotations

import argparse
import posixpath
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SKIP_SCHEMES = ("http:", "https:", "mailto:", "tel:", "javascript:", "data:", "//")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []      # (attr, value)
        self.title = ""
        self._in_title = False
        self._title_done = False     # only the <head> title counts (SVG icons carry <title> too)
        self.h1 = ""
        self._in_h1 = False
        self._h1_done = False        # only the first <h1> counts (templates/popovers may repeat it)
        self.crumbs: list[str] = []
        self._crumb_depth = 0
        self._stack: list[bool] = []
        self._in_crumb_text = False
        self._crumb_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and a.get("href") is not None:
            self.links.append(("href", a["href"]))
        elif tag in ("img", "script", "source", "video", "audio") and a.get("src"):
            self.links.append(("src", a["src"]))
        elif tag == "link" and a.get("href") and a.get("rel", "") not in ("canonical", "alternate"):
            self.links.append(("href", a["href"]))
        if tag == "title" and not self._title_done:
            self._in_title = True
        if tag == "h1" and not self._h1_done:
            self._in_h1 = True
        in_container = "breadcrumb-container" in cls or "breadcrumb" in cls and tag == "nav"
        self._stack.append(in_container)
        if in_container:
            self._crumb_depth += 1
        if self._crumb_depth and tag in ("a", "p", "span"):
            self._in_crumb_text = True
            self._crumb_buf = []

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self._h1_done = True
        if self._in_crumb_text and tag in ("a", "p", "span"):
            text = "".join(self._crumb_buf).strip()
            if text and text not in ("❯", ">", "/", "›", "»"):
                self.crumbs.append(text)
            self._in_crumb_text = False
        if self._stack:
            was = self._stack.pop()
            if was:
                self._crumb_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1 += data
        if self._in_crumb_text:
            self._crumb_buf.append(data)


def internal(link: str) -> bool:
    l = link.strip()
    if not l or l.startswith("#"):
        return False
    low = l.lower()
    return not any(low.startswith(s) for s in SKIP_SCHEMES)


def resolve(public: Path, page_rel: str, link: str, base: str) -> tuple[Path | None, list[str], str | None]:
    """(resolved path or None, candidates tried, error) for one internal link."""
    parts = urlsplit(link)
    path = unquote(parts.path)
    if not path:
        return public / page_rel, [], None          # fragment/query only
    if path.startswith("/"):
        if base:
            if not (path == base or path.startswith(base + "/")):
                return None, [], f"absolute link {link!r} does not start with base {base!r}"
            path = path[len(base):] or "/"
        rel = path.lstrip("/")
    else:
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(page_rel), path))
        if rel.startswith(".."):
            return None, [], f"link {link!r} escapes the site root"
    rel = rel.rstrip("/")
    if rel in ("", "."):
        rel = ""
    cands = []
    if rel == "":
        cands = ["index.html"]
    elif path.endswith("/"):
        cands = [f"{rel}/index.html"]
    else:
        cands = [rel, f"{rel}.html", f"{rel}/index.html"]
    for c in cands:
        p = public / c
        if p.is_file():
            return p, cands, None
    return None, cands, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("public", help="site output directory (Quartz `public/`)")
    ap.add_argument("--base", default="", help="deployment sub-path, e.g. /preview")
    ap.add_argument("--no-breadcrumbs", action="store_true", help="skip the folder-title / breadcrumb check")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    public = Path(a.public)
    if not public.is_dir():
        print(f"check_site_links: not a directory: {public}", file=sys.stderr)
        return 2
    base = ("/" + a.base.strip("/")) if a.base.strip("/") else ""
    pages = sorted(p for p in public.rglob("*.html"))
    if not pages:
        print("check_site_links: no HTML files found", file=sys.stderr)
        return 1
    if not (public / "index.html").is_file():
        print("check_site_links: public/index.html missing (GitLab Pages needs it)", file=sys.stderr)
        return 1
    parsed: dict[str, PageParser] = {}
    n_links = 0
    for page in pages:
        rel = page.relative_to(public).as_posix()
        pp = PageParser()
        try:
            pp.feed(page.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # pragma: no cover
            print(f"check_site_links: cannot parse {rel}: {e}", file=sys.stderr)
            return 1
        parsed[rel] = pp
        for attr, link in pp.links:
            if not internal(link):
                continue
            n_links += 1
            target, cands, err = resolve(public, rel, link, base)
            if err:
                print(f"FAIL {rel}: {err}", file=sys.stderr)
                return 1
            if target is None:
                print(f"FAIL {rel}: {attr}={link!r} resolves to none of {cands}", file=sys.stderr)
                return 1
            if a.verbose:
                print(f"ok   {rel}: {link} -> {target.relative_to(public).as_posix()}")
    print(f"check_site_links: {len(pages)} pages, {n_links} internal links resolved" + (f", base {base}" if base else ""))
    if a.no_breadcrumbs:
        return 0
    # folder pages must have distinct titles
    folder_pages = {rel.split("/")[0]: pp for rel, pp in parsed.items() if rel.count("/") == 1 and rel.endswith("/index.html")}
    if len(folder_pages) < 2:
        print(f"FAIL: expected at least two folder pages (<folder>/index.html), found {sorted(folder_pages)}", file=sys.stderr)
        return 1

    def _title(pp: PageParser) -> str:
        t = (pp.h1 or pp.title).strip()
        return t.split(" | ")[0].strip()

    titles = {f: _title(pp) for f, pp in folder_pages.items()}
    dup = {t for t in titles.values() if list(titles.values()).count(t) > 1}
    if dup or "" in titles.values():
        print(f"FAIL: folder pages do not render distinct titles: {titles}", file=sys.stderr)
        return 1
    # breadcrumbs of pages inside two different folders must name their own folder
    crumb_by_folder: dict[str, str] = {}
    any_crumbs = False
    for rel, pp in parsed.items():
        if rel.count("/") != 1 or rel.endswith("/index.html"):
            continue
        folder = rel.split("/")[0]
        if pp.crumbs:
            any_crumbs = True
            if len(pp.crumbs) >= 2 and folder not in crumb_by_folder:
                crumb_by_folder[folder] = pp.crumbs[-2]
    if not any_crumbs:
        print("FAIL: no breadcrumb markup found in any folder page (breadcrumbs plugin missing? use --no-breadcrumbs to skip)",
              file=sys.stderr)
        return 1
    if len(crumb_by_folder) >= 2:
        vals = list(crumb_by_folder.values())
        if len(set(vals)) != len(vals):
            print(f"FAIL: breadcrumbs of pages in different folders show the same folder label: {crumb_by_folder}", file=sys.stderr)
            return 1
        for folder, label in crumb_by_folder.items():
            if label != titles.get(folder) and label.lower() != folder.lower():
                print(f"FAIL: breadcrumb folder label {label!r} for {folder}/ is neither the folder title {titles.get(folder)!r} nor the folder name",
                      file=sys.stderr)
                return 1
        print(f"check_site_links: breadcrumbs distinct across folders: {crumb_by_folder}")
    else:
        print(f"check_site_links: warning: fewer than two folders contain non-index pages with breadcrumbs ({crumb_by_folder}); "
              f"folder titles are distinct: {titles}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
