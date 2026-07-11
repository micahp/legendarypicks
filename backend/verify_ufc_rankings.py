#!/usr/bin/env python3
"""Release gate for the deployed UFC rankings API."""
import argparse
import json
import sys
import urllib.request


def validate_payload(payload):
    try:
        men = payload["pound_for_pound"]["men"]
        women = payload["pound_for_pound"]["women"]
        divisions = payload["divisions"]
    except (KeyError, TypeError) as exc:
        raise ValueError("UFC rankings response has the wrong schema") from exc
    if not men:
        raise ValueError("men's P4P rankings are empty")
    if not women:
        raise ValueError("women's P4P rankings are empty")
    if not isinstance(divisions, list) or len(divisions) != 11:
        count = len(divisions) if isinstance(divisions, list) else "not a list"
        raise ValueError(f"expected 11 UFC weight divisions, got {count}")
    if any(not division.get("ranked") for division in divisions):
        raise ValueError("one or more UFC weight divisions have no ranked fighters")
    return len(men), len(women), len(divisions)


def verify(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"UFC rankings endpoint returned HTTP {response.status}")
        payload = json.load(response)
    return validate_payload(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="https://legendarypicks.xyz/api/ufc/rankings",
        help="deployed rankings endpoint",
    )
    args = parser.parse_args()
    try:
        men, women, divisions = verify(args.url)
    except Exception as exc:
        sys.exit(f"UFC rankings release gate FAILED: {exc}")
    print(
        "UFC rankings release gate PASSED: "
        f"men's P4P={men}, women's P4P={women}, divisions={divisions}"
    )


if __name__ == "__main__":
    main()
