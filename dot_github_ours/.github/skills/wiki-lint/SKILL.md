---
name: wiki-lint
description: >-
  Audit the wiki: run the deterministic lint, backlink and staleness scripts, then sample pages for
  contradictions, weak evidence, gaps and blind spots, and report a findings table with proposed
  repairs. Use when asked to check, audit, lint or find problems in the wiki. Repairs narrative pages
  only after approval (headless: report only).
argument-hint: "[--fix] [--sample N]"
allowed-tools: [read, edit, search, execute]
---
# /wiki-lint — audit and repair

Procedure only. Authoring rules: `.github/instructions/wiki.instructions.md`; script flags:
`.github/skills/wiki-maintain/SKILL.md`. `S/<name>.py` = `python3 .github/skills/wiki-maintain/scripts/<name>.py`.
**S1** = STOP for `ask_user`; headless (`--no-ask-user`): report only, no narrative edits.

## 1. Deterministic pass
- `S/run.py begin --mode lint`.
- `S/lint.py --all --json` (L01–L17 minus L11), `S/backlinks.py --all --json` (orphans, `--suggest` for
  `related` candidates), `S/affected.py --check-only --json` (stale pages and why).
- `S/lint.py --fix` applies the mechanical repairs (line endings, trailing whitespace, hidden Unicode,
  missing H1, canonical `id`) on any page; re-run `S/lint.py --all --json` and keep the remaining
  findings as rows for the table. `--fix` given by the user changes nothing here; it only pre-approves
  the repairs of step 4.

## 2. Model pass over a sample
Pick ≤ `lint_sample_pages` pages (`--sample N` overrides), oldest `last_verified_commit` first, narrative
types only (never `generated/**`, `api/<router>.md`, `events/<channel>.md`). Read each page whole, then
its sources through `S/excerpt.py <path> --symbol NAME` / `--lines a-b` for the statements you check.
Check for:
1. **Contradictions** – pages that contradict each other, or a page that contradicts its sources.
2. **Staleness** – statements superseded by newer code the deterministic pass did not catch
   (unranged sources, renamed concepts).
3. **Orphans** and **missing cross-references** – pages that belong together but are not linked.
4. **Gaps** – concepts mentioned across several pages but lacking their own page.
5. **Weak evidence** – statements with no footnote; "spot-check 5 statements against the code".
6. **Blind spots** – areas of the code with no wiki coverage at all (`affected.py` gaps, inventory
   sub-trees no page cites).
7. **Frontmatter** – implausible values the schema check cannot see (a `description` that no longer
   matches the body, a `team` that CODEOWNERS does not know).

## 3. Report
Output a findings table `Category | Page | Finding | Proposal | Severity (high/medium/low)`,
deterministic rows first (rule id in the finding). Add at the end:
- the three repairs with the best effort-to-value ratio,
- three questions about the system the wiki cannot answer today but should.
Headless: write nothing to the wiki; the table goes to `.git/wiki/lint-report.md` through
`S/run.py end` (the run writes your final message there) and the result line lists `proposed`.

## 4. Repair — S1
**S1**: "Select the repairs to apply" (all three, numbered rows, or none). `--fix` pre-selects the
three best-ratio repairs; still show the table first. Apply only the approved repairs, only on narrative
pages you may edit (`owner: agent|both`), section by section, `status` unchanged, contradictions
recorded as in the agent file §7. A repair that needs a new page is a proposal, not an edit.

## 5. Verify and end
`S/index.py --write` → `S/lint.py --changed --json` → `S/backlinks.py --changed --json` → fix, rerun
until clean → `S/log.py add --action Lint --text "<n> findings, <m> repaired"` → `S/run.py end` →
prose summary → the single `WIKI-RUN-RESULT` line (`updated` = repaired pages, `proposed` = the rest).

## Do not
Edit generated pages, `index.md`, `log.md`, `requests.md` or `owner: human|process` pages (report
them); promote `draft` to `stable`; delete pages (propose `status: deprecated` instead); read more than
the sample; rewrite a page whose only finding is style.
