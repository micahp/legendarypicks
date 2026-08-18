#!/usr/bin/env python3
"""Print the GitHub release notes for a version, read from CHANGELOG.md.

The span is the whole point. Only MAJOR and MINOR tags get a GitHub release
(feature releases only; fixes ride into the next release's changelog), so a
patch version's work has no release of its own. Notes therefore run from the
version's own heading down to the PREVIOUS MINOR, not down to the previous tag.

Measured 2026-08-18, when the releases were first created by hand: taking only
the version's own section left v0.7.1 through v0.7.10 published nowhere at all,
ten releases' worth of feature work, and v0.6.1 through v0.6.14 the same.

    scripts/release_notes.py 0.8.0            # notes to stdout
    scripts/release_notes.py 0.8.0 --title    # the release title line
    scripts/release_notes.py 0.8.0 --covers   # which sections it spans

Exits non-zero if the version has no CHANGELOG section, so a caller can treat a
missing entry as a failure rather than publishing an empty release.
"""
import argparse
import os
import re
import sys

HEADING = re.compile(r"^## (v[0-9][0-9.]*)\b(.*)$")
MINOR = re.compile(r"^v\d+\.\d+\.0$")


def sections(changelog):
    """[(line_index, version, rest_of_heading)] in file order, newest first."""
    found = []
    for index, line in enumerate(changelog):
        match = HEADING.match(line)
        if match:
            found.append((index, match.group(1), match.group(2).strip()))
    return found


def notes_for(changelog, version):
    tag = version if version.startswith("v") else "v" + version
    found = sections(changelog)
    start = next((i for i, (_, v, _) in enumerate(found) if v == tag), None)
    if start is None:
        raise SystemExit(f"release_notes: CHANGELOG.md has no '## {tag}' section")

    # Stop at the previous MINOR. Everything between is patch work that will
    # never get a release of its own.
    end_line = None
    for line_index, v, _ in found[start + 1:]:
        if MINOR.match(v):
            end_line = line_index
            break

    body = "\n".join(changelog[found[start][0]:end_line]).strip()
    heading, _, rest = body.partition("\n")
    covered = [v for _, v, _ in sections(rest.split("\n"))]
    return heading, rest.strip(), covered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--title", action="store_true", help="print the heading only")
    parser.add_argument("--covers", action="store_true", help="list the versions spanned")
    parser.add_argument("--changelog", default=None)
    args = parser.parse_args()

    path = args.changelog or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md")
    with open(path) as handle:
        changelog = handle.read().split("\n")

    heading, body, covered = notes_for(changelog, args.version)
    if args.title:
        print(heading.replace("## ", "").strip())
    elif args.covers:
        print(" ".join(covered))
    else:
        sys.stdout.write(body + "\n")


if __name__ == "__main__":
    main()
