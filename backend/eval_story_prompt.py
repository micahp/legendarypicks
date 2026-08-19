#!/usr/bin/env python3
"""Replay a saved story prompt against one or more models, and keep the output.

Why this exists: on 2026-08-19 the game-story grounding was changed three times
in an afternoon, each change tested by eyeballing three generations and then
throwing them away. That is not a comparison, it is a memory. The next person
to touch the prompt had no way to see what the old one produced, or to tell an
improvement from a lucky sample.

So: prompts are FILES in docs/evals/story-prompt/prompts/, outputs are dated
files beside them, and a prompt change is a diff.

    # replay every saved prompt version against the default model
    python eval_story_prompt.py

    # one version, three models, five runs each
    python eval_story_prompt.py --prompt v3-winning-percentage \\
        --model deepseek/deepseek-v4-flash-0731 \\
        --model nvidia/nemotron-3-ultra-550b-a55b --runs 5

    # capture a FRESH prompt for a real game, so a saved version can be refreshed
    python eval_story_prompt.py --capture mlb:401816594 --as v4-my-change

Output goes to docs/evals/story-prompt/runs/YYYY-MM-DD-<prompt>-<model>.md and
is appended to, never overwritten: the point is the history.

**This calls a real model and costs real money.** It is a developer tool, not a
timer, and nothing schedules it. At flash-0731 prices a full replay is a
fraction of a cent.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "docs", "evals", "story-prompt")
PROMPTS = os.path.join(ROOT, "prompts")
RUNS = os.path.join(ROOT, "runs")


def _load(name):
    path = os.path.join(PROMPTS, name if name.endswith(".txt") else name + ".txt")
    text = open(path).read()
    system, _, grounding = text.partition("=== GROUNDING ===")
    return system.replace("=== SYSTEM ===", "").strip(), grounding.strip()


def _numbers(s):
    return set(re.findall(r"\d+\.?\d*", s))


def _unsupported(answer, grounding):
    """Numbers in the answer that are nowhere in the facts it was given.

    A weak detector on purpose: it catches invented scores and averages, and it
    does NOT catch a misread ordering or a wrong weekday. It is a tripwire, not
    a grade. Read the text.
    """
    g = _numbers(grounding)
    return [n for n in _numbers(answer)
            if n not in g and n.rstrip("0").rstrip(".") not in
            {x.rstrip("0").rstrip(".") for x in g}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", action="append", help="prompt version(s); default all")
    ap.add_argument("--model", action="append", help="model id(s); default LP_LLM_MODEL")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--capture", help="LEAGUE:GAME_ID, capture a live prompt instead")
    ap.add_argument("--as", dest="save_as", help="name to save a captured prompt under")
    args = ap.parse_args()

    os.makedirs(RUNS, exist_ok=True)

    if args.capture:
        lg, _, gid = args.capture.partition(":")
        import core_stories
        cap = {}
        core_stories._deepseek_chat = (
            lambda s, u, max_tokens=8000, **k: (cap.update({"s": s, "u": u}), None)[1])
        core_stories.generate_game_story(lg, gid, refresh=True)
        if not cap:
            print("no prompt captured (the story may have been served from cache)")
            return 1
        name = args.save_as or f"capture-{lg}-{gid}"
        with open(os.path.join(PROMPTS, name + ".txt"), "w") as f:
            f.write("=== SYSTEM ===\n" + cap["s"] + "\n\n=== GROUNDING ===\n" + cap["u"] + "\n")
        print(f"saved {name}.txt  ({len(cap['u'])} grounding chars)")
        return 0

    import _core
    names = args.prompt or sorted(
        f[:-4] for f in os.listdir(PROMPTS) if f.endswith(".txt"))
    models = args.model or [_core._LLM_MODEL]
    day = datetime.date.today().isoformat()

    for name in names:
        system, grounding = _load(name)
        for model in models:
            before = _core._LLM_MODEL
            _core._LLM_MODEL = model
            out_path = os.path.join(
                RUNS, f"{day}-{name}-{model.replace('/', '_')}.md")
            lines = [f"\n## {datetime.datetime.now().isoformat(timespec='seconds')}",
                     f"prompt `{name}` model `{model}` runs {args.runs}\n"]
            print(f"\n{'=' * 70}\n{name}  x  {model}\n{'=' * 70}")
            for i in range(args.runs):
                t0 = time.time()
                answer = _core._llm_chat(system, grounding) or "(no answer)"
                dt = time.time() - t0
                bad = _unsupported(answer, grounding)
                lines.append(f"**run {i + 1}** ({dt:.1f}s)"
                             + (f" unsupported numbers: `{bad}`" if bad else "")
                             + f"\n\n> {answer}\n")
                print(f"\n[run {i + 1}, {dt:.1f}s]"
                      + (f"  unsupported numbers: {bad}" if bad else ""))
                print(answer)
            with open(out_path, "a") as f:
                f.write("\n".join(lines))
            print(f"\n-> appended to {os.path.relpath(out_path)}")
            _core._LLM_MODEL = before
    return 0


if __name__ == "__main__":
    sys.exit(main())
