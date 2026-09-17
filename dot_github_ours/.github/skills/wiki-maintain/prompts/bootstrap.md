<!-- wiki-kit prompt bootstrap/1.0.0 -->
/wiki-page {{cluster_id}}
Run the wiki-page skill for cluster `{{cluster_id}}` (/wiki-page {{cluster_id}}). Mode: page. The cluster's page specs, source packs and budget were injected at session start; if missing, run `python3 .github/skills/wiki-maintain/scripts/plan.py show {{cluster_id}} --json` and `python3 .github/skills/wiki-maintain/scripts/run.py status --json`.
This is a headless session (`--no-ask-user`): read `wiki/instructions.md` and `wiki/conventions.md` first, write only the pages the cluster lists, mark the cluster done or deferred, and end with a prose summary followed by exactly one final line `WIKI-RUN-RESULT: {…}`.
