<!-- wiki-kit prompt update/1.0.0 -->
/wiki-update
Run the wiki-update skill. Mode: update. The work list and untrusted request blocks were injected at session start; if missing, run `python3 .github/skills/wiki-maintain/scripts/run.py status --json`.
This is a headless session (`--no-ask-user`): apply the headless fallback at every STOP point of the skill, read `wiki/instructions.md` and `wiki/conventions.md` first, edit only the pages on the work list, and end with a prose summary followed by exactly one final line `WIKI-RUN-RESULT: {…}`.
