"""Strip run metadata and mask system names in a paper before it is scored.

The same rule is applied to every system's paper.
"""

import re

MASK = [(r"\bQDM\b", "the system"), (r"MM-Agent|MMAgent", "the system"),
        (r"\bClaude( Code)?\b", "the system"),
        (r"\bDeepSeek\b", "the model")]

PROCESS_HEAD = re.compile(r"^(#+)\s*(\d+\.\s*)?(Reproducibility|Traceability|Provenance|Run metadata)\b.*$", re.I)
PROCESS_LINE = re.compile(r"\w+_workspace|harness/|\bsha256\b|^\*\*(Run|Source of all numbers|Protocol)\b",
                          re.I)


def strip_process(s: str) -> str:
    """Drop run-metadata sections and lines (file paths, hashes, harness notes). Same rule for every method."""
    out, skip_level = [], None
    for line in s.split("\n"):
        h = re.match(r"^(#+)\s", line)
        if skip_level is not None:
            if h and len(h.group(1)) <= skip_level:
                skip_level = None
            else:
                continue
        m = PROCESS_HEAD.match(line)
        if m:
            skip_level = len(m.group(1))
            continue
        if PROCESS_LINE.search(line):
            continue
        out.append(line)
    return "\n".join(out)


def mask(s: str) -> str:
    s = strip_process(s)
    for p, r in MASK:
        s = re.sub(p, r, s)
    return s

