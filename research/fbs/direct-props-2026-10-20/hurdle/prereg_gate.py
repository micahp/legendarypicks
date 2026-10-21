"""The preregistration gate: no fitting until Micah signs.

prereg rev4 §10 leaves `APPROVED BY MICAH:` blank on purpose, and the DECISION
doc says the same. This module turns that sentence into a runtime check so the
experiment cannot be started by accident, by a wrapper script, or by a later
session that has forgotten why the line is blank.

The gate deliberately requires an **explicit signature value** after the marker.
It does not accept "revision 4", a date, an agent's name, or an underscore bar of
any length: blank means blank.
"""
from __future__ import annotations

import os
import re

MARKER = "APPROVED BY MICAH:"
_SUFFIX = re.compile(r"\(date\s*/\s*initials\)", re.I)

DEFAULT_PREREG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "PREREG-FBS-HURDLE-PASSING.md",
)


class PreregNotSigned(RuntimeError):
    """Fitting requested while the owner signature is still blank."""


def signature_value(text):
    """The signature as written, or '' when blank.

    Strips the trailing '(date / initials)' prompt and any underscore filler, so
    an all-underscore line reads as blank rather than as a value.
    """
    if MARKER not in text:
        return ""
    tail = text.split(MARKER, 1)[1].splitlines()[0]
    tail = _SUFFIX.sub("", tail)
    return tail.strip().strip("_").strip()


def gate_status(prereg_path=None):
    path = prereg_path or DEFAULT_PREREG
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    value = signature_value(text)
    return {
        "path": path,
        "marker_present": MARKER in text,
        "signed": bool(value),
        "signature": value,
        "state": "SIGNED" if value else "UNSIGNED — fitting blocked",
    }


def assert_prereg_signed(prereg_path=None):
    """Raise `PreregNotSigned` unless §10 carries an owner signature."""
    st = gate_status(prereg_path)
    if not st["marker_present"]:
        raise PreregNotSigned("no '%s' line found in %s" % (MARKER, st["path"]))
    if not st["signed"]:
        raise PreregNotSigned(
            "preregistration at %s is UNSIGNED; implementation and tests may run, "
            "fitting and tuning may not" % st["path"])
    return st
