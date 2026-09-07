#!/usr/bin/env python3
"""prior_art.py: has this already been measured, decided, or built?

WHY THIS EXISTS.

`superseded.py` catches "this SCRIPT was replaced". It does not catch "this MEASUREMENT was
already taken", and that is the more common and more expensive failure. On 2026-09-06 the
same day produced three of them:

  1. Wrote `player_merge.py`, a worse copy of `spine_merge.py`, which had solved the same
     problem generically on 2026-08-24.
  2. Measured that `players.id` drifts between dev and prod and presented `id=29174` as a
     finding. `promote_player_positions.py`'s DOCSTRING had recorded the same drift, the same
     id, and the same two players (Paul George on dev, Max Kepler on prod) on 2026-08-17.
  3. Nearly filed a dry-run artefact as an identity defect, which a comment in the same file
     already explained.

The knowledge existed in all three cases. It was unfindable in the ninety seconds anybody
was willing to spend looking.

WHERE THIS REPO ACTUALLY KEEPS ITS KNOWLEDGE, in descending order of signal:

  * MODULE DOCSTRINGS. This is the surprising one and the reason a plain `grep docs/` fails.
    The drift measurement lived in a docstring, not a document. So did the ESPN request
    budget, the pick'em constant, and the reason MLS rosters are keyed on espn_id.
  * `docs/CONTEXT-*.md`, 87 files and 16,313 lines of day summaries. Nobody reads the right
    one of 87 before touching the right one of 12 scripts.
  * `.claude/skills/*/SKILL.md`, the doctrine.
  * `AGENTS.md`, which is read but is also where a stale pointer did the most damage.

So this searches all four, ranks docstrings first, and prints enough context to decide
whether to keep reading. It is deliberately dumb: no index to go stale, no database, nothing
to schedule. It reads the tree every time, which takes under a second.

USE IT BEFORE WRITING A NEW SCRIPT OR REPORTING A NEW FINDING:

    scripts/prior_art.py "id drift"
    scripts/prior_art.py dedupe orphan
    scripts/prior_art.py "request budget"
"""
import argparse
import os
import re
import sys
from typing import Dict, Iterable, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (label, weight, roots, extensions). Weight orders the report: a measurement recorded in a
# docstring is the thing most likely to be re-derived, so it leads.
_SOURCES: Tuple[Tuple[str, int, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("docstring", 4, ("backend", "scripts"), (".py",)),
    ("skill", 3, (".claude/skills",), (".md",)),
    ("agents", 3, ("",), ("AGENTS.md",)),
    ("context summary", 2, ("docs",), (".md",)),
    ("code comment", 1, ("backend", "scripts"), (".py",)),
)

_SKIP = ("/venv/", "/node_modules/", "/.git/", "/__pycache__/", "/.next/")


def _files(roots: Iterable[str], extensions: Tuple[str, ...]) -> Iterable[str]:
    for root in roots:
        base = os.path.join(ROOT, root) if root else ROOT
        if os.path.isfile(base):
            yield base
            continue
        for dirpath, _, filenames in os.walk(base):
            if any(skip in dirpath + "/" for skip in _SKIP):
                continue
            for filename in filenames:
                if filename.endswith(extensions) or filename in extensions:
                    yield os.path.join(dirpath, filename)
            if root == "":
                break  # AGENTS.md lives at the top level; do not walk the whole tree


def _docstring_spans(text: str) -> List[Tuple[int, int]]:
    """Line ranges covered by triple-quoted strings. Cheap and good enough.

    A real parse would be exact, but a file that fails to parse is exactly the file someone
    is mid-edit on, and refusing to search it would be the wrong trade.
    """
    spans, start = [], None
    for index, line in enumerate(text.splitlines(), start=1):
        for _ in range(line.count('"""') + line.count("'''")):
            if start is None:
                start = index
            else:
                spans.append((start, index))
                start = None
    if start is not None:
        spans.append((start, index))
    return spans


def search(terms: List[str], limit: int = 40) -> List[Tuple[int, str, str, int, str]]:
    patterns = [re.compile(re.escape(term), re.IGNORECASE) for term in terms]
    seen: Dict[Tuple[str, int], int] = {}
    hits: List[Tuple[int, str, str, int, str]] = []
    for label, weight, roots, extensions in _SOURCES:
        for path in _files(roots, extensions):
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            spans = _docstring_spans(text) if label in ("docstring", "code comment") else []
            for number, line in enumerate(text.splitlines(), start=1):
                if not all(pattern.search(line) for pattern in patterns):
                    continue
                if label == "docstring" and not any(a <= number <= b for a, b in spans):
                    continue
                if label == "code comment":
                    if any(a <= number <= b for a, b in spans):
                        continue
                    if not line.lstrip().startswith("#"):
                        continue
                key = (path, number)
                if seen.get(key, 0) >= weight:
                    continue
                seen[key] = weight
                hits.append((weight, label, os.path.relpath(path, ROOT), number,
                             line.strip()[:150]))
    hits.sort(key=lambda hit: (-hit[0], hit[2], hit[3]))
    return hits[:limit]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("terms", nargs="+", help="all terms must appear on the same line")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)

    hits = search(args.terms, args.limit)
    query = " ".join(args.terms)
    if not hits:
        # Say the zero clearly. "No prior art" is a finding worth trusting, and a silent
        # empty result reads the same as a search that never ran.
        print('no prior art found for "{}". Searched module docstrings, skills, AGENTS.md, '
              "docs/ and code comments.".format(query))
        return 1
    print('prior art for "{}" ({} hit(s), docstrings first):\n'.format(query, len(hits)))
    current = None
    for _, label, path, number, line in hits:
        if label != current:
            print("--- {} ---".format(label))
            current = label
        print("  {}:{}: {}".format(path, number, line))
    print("\nRead these before writing anything new. The measurement you are about to take "
          "may already be in one of them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
