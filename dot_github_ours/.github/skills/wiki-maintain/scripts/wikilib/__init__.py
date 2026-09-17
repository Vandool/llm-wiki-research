"""wikilib: shared stdlib-only helpers for the wiki-kit scripts (Python >= 3.10).

Modules: cli (argparse base, emitter, exit codes, logging), config (load/validate/defaults/
scaffold placeholders), gitio (git plumbing), frontmatter, yamlmini, textnorm, pages, symbols,
specs, manifest, budget.
"""
KIT_VERSION = "1.0.0"
SCHEMA_VERSION = 1
__all__ = ["KIT_VERSION", "SCHEMA_VERSION"]
