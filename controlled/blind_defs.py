"""Lay out the four final definitions of each task x model under shuffled labels.

Writes blind/defs/<task>__<model>.md with the problem text, the task's audit items,
and the four final definitions labelled P/Q/R/S in random order, plus
blind/defs/KEY_defs.json mapping labels back to conditions.

Usage:
    python -I blind_defs.py --tasks 2023_A 2022_C 2024_B 2025_A --seed 20261023
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # -I drops the script dir from sys.path
import run_ablation as ra  # noqa: E402
RUNS = HERE.parent / "data" / "controlled" / "runs"
OUT = HERE.parent / "data" / "controlled" / "blind" / "defs"
AUDIT_DIR = HERE.parent / "data" / "audit"
LABELS = ["P", "Q", "R", "S"]


def audit_rows(task: str) -> list[str]:
    rows = []
    for f in AUDIT_DIR.glob("MMBench_item_annotations_*_v2.md"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.match(rf"^\| {task}_\d+ \|", line):
                rows.append(line)
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--seed", type=int, required=True)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    key = {}
    for task in args.tasks:
        header = ["| Item | Layer / role | Field | State | Closure | Risk / fork / identifiability | Evidence | Downstream consequence |",
                  "|---|---|---|---|---|---|---|---|"] + audit_rows(task)
        for model_dir in sorted((RUNS / task).glob("*")):
            conds = ["A", "B", "C", "D"]
            rng.shuffle(conds)
            mapping = dict(zip(LABELS, conds))
            key[f"{task}__{model_dir.name}"] = mapping
            parts = [f"# {task} — four final problem definitions (labels are arbitrary)\n",
                     "## Problem\n", ra.problem_text(task),
                     "\n## Audit items for this task\n",
                     "State: E = stated explicitly in the problem; U = several reasonable readings that change the model; "
                     "M = information needed is missing.\n", "\n".join(header)]
            for lab in LABELS:
                rec = json.loads((model_dir / f"{mapping[lab]}_rep01.json").read_text(encoding="utf-8"))
                parts.append(f"\n---\n\n## Definition {lab}\n")
                parts.append("```json\n" + json.dumps(rec["final_definition"], ensure_ascii=False, indent=1) + "\n```")
            # model name is kept out of the file name shown to coders
            (OUT / f"{task}__m{sorted(p.name for p in (RUNS / task).glob('*')).index(model_dir.name) + 1}.md").write_text(
                "\n".join(parts) + "\n", encoding="utf-8")
            key[f"{task}__m{sorted(p.name for p in (RUNS / task).glob('*')).index(model_dir.name) + 1}"] = {
                "model": model_dir.name, "labels": mapping}
            del key[f"{task}__{model_dir.name}"]
    (OUT / "KEY_defs.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(sorted(p.name for p in OUT.glob("*.md"))))


if __name__ == "__main__":
    main()
