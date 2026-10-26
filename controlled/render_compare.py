"""Render a side-by-side reading sheet per task and model, for manual analysis.

No scoring and no LLM: it lays out, for each condition, the questions that were
asked and the final problem definition, next to the task's audit items, so the
differences can be read and discussed case by case.

Usage:
    python -I render_compare.py --tasks 2023_A
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "data" / "controlled" / "runs"
OUT = HERE.parent / "data" / "controlled" / "compare"
AUDIT_DIR = HERE.parent / "data" / "audit"

COND_NAMES = {
    "A": "A direct (no questions)",
    "B": "B self-ask (same context)",
    "C": "C separate questioner, sees full transcript",
    "D": "D isolated questioner (QDM)",
}


def audit_items(task: str) -> list[list[str]]:
    rows = []
    for f in AUDIT_DIR.glob("MMBench_item_annotations_*_v2.md"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.match(rf"^\| {task}_\d+ \|", line):
                rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def fmt_def(d) -> str:
    if d is None:
        return "_final definition could not be parsed_"
    lines = []
    for key in ["objective", "estimands_or_decisions", "key_definitions", "assumptions",
                "constraints", "conditional_or_unidentifiable", "validation"]:
        val = d.get(key) if isinstance(d, dict) else None
        if not val:
            lines.append(f"- **{key}**: _(empty)_")
            continue
        if isinstance(val, str):
            lines.append(f"- **{key}**: {val}")
            continue
        lines.append(f"- **{key}**:")
        for item in val:
            if isinstance(item, dict):
                item = "; ".join(f"{k}: {v}" for k, v in item.items() if v)
            lines.append(f"  - {item}")
    return "\n".join(lines)


def render(task: str) -> list[Path]:
    written = []
    items = audit_items(task)
    for model_dir in sorted((RUNS / task).glob("*")):
        parts = [f"# {task} — {model_dir.name}\n"]
        parts.append("## Audit items (U/M = ambiguous or missing in the problem)\n")
        for r in items:
            if len(r) > 3 and r[3] in ("U", "M"):
                parts.append(f"- `{r[0]}` [{r[3]}] {r[1]}: {r[-1]}")
        for f in sorted(model_dir.glob("*_rep*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            cond = rec["condition"]
            parts.append(f"\n---\n\n## {COND_NAMES.get(cond, cond)} — rep {rec['rep']}\n")
            parts.append(f"calls={rec['n_calls']}, tokens in/out="
                         f"{rec['usage']['prompt_tokens']}/{rec['usage']['completion_tokens']}\n")
            if rec["questions"]:
                parts.append("### Questions asked\n")
                for rnd in rec["questions"]:
                    for q in rnd["questions"]:
                        parts.append(f"- R{rnd['round']}: {q}")
            parts.append("\n### Final definition\n")
            parts.append(fmt_def(rec["final_definition"]))
        out = OUT / f"{task}__{model_dir.name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
        written.append(out)
    return written


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    args = ap.parse_args()
    for t in args.tasks:
        for p in render(t):
            print(p)


if __name__ == "__main__":
    main()
