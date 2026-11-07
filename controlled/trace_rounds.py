"""Trace, round by round, which questions were asked and how the draft changed.

For every B/C/D run: draft before round r (initial draft for r=1), the questions of
round r, and the field-level diff between that draft and the draft returned in the
answer to round r. Items are compared as normalized strings, so a reworded item
counts as removed + added.

Writes trace/<task>__<model>__<cond>.md and prints a per-run summary
(items added / removed per round).

Usage:
    python -I trace_rounds.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "data" / "controlled" / "runs"
OUT = HERE.parent / "data" / "controlled" / "trace"

FIELDS = ["objective", "estimands_or_decisions", "key_definitions", "variables", "assumptions",
          "constraints", "conditional_or_unidentifiable", "validation", "subquestion_plan"]


def extract_json(text: str):
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    for cand in reversed(blocks):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def items(d, field) -> list[str]:
    if not isinstance(d, dict):
        return []
    v = d.get(field)
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()]
    out = []
    for x in v:
        if isinstance(x, dict):
            # key on the identifying part so a changed rationale shows as a change
            out.append(json.dumps(x, ensure_ascii=False, sort_keys=True))
        else:
            out.append(str(x).strip())
    return out


def short(s: str, n: int = 260) -> str:
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            s = " | ".join(f"{k}: {v}" for k, v in obj.items() if v)
    except (json.JSONDecodeError, TypeError):
        pass
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def diff(a, b):
    res = {}
    for f in FIELDS:
        ia, ib = items(a, f), items(b, f)
        added = [x for x in ib if x not in ia]
        removed = [x for x in ia if x not in ib]
        if added or removed:
            res[f] = (added, removed)
    return res


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    for f in sorted(RUNS.glob("*/*/[BCD]_rep01.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        calls = {c["role"]: c for c in rec["calls"]}
        drafts = [extract_json(calls["modeler_initial"]["content"])]
        for r in range(1, len(rec["questions"]) + 1):
            drafts.append(extract_json(calls[f"modeler_answer_r{r}"]["content"]) or drafts[-1])
        drafts.append(rec["final_definition"])
        lines = [f"# {rec['task']} — {rec['model']} — {rec['condition']}\n"]
        summ = []
        for r, rnd in enumerate(rec["questions"], 1):
            d = diff(drafts[r - 1], drafts[r])
            na = sum(len(v[0]) for v in d.values())
            nr = sum(len(v[1]) for v in d.values())
            summ.append(f"r{r}:+{na}/-{nr}")
            lines.append(f"\n## Round {r}\n\n### Questions")
            lines += [f"- {q}" for q in rnd["questions"]]
            lines.append("\n### Draft changes after the answer")
            for fld, (added, removed) in d.items():
                lines.append(f"\n**{fld}**")
                lines += [f"- ＋ {short(x)}" for x in added]
                lines += [f"- － {short(x)}" for x in removed]
        dfin = diff(drafts[-2], drafts[-1])
        summ.append(f"final:+{sum(len(v[0]) for v in dfin.values())}/-{sum(len(v[1]) for v in dfin.values())}")
        (OUT / f"{rec['task']}__{rec['model']}__{rec['condition']}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        print(f"{rec['task']} {rec['model']:<20} {rec['condition']}  " + "  ".join(summ))


if __name__ == "__main__":
    main()
