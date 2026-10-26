"""Build a blinded question set for open coding.

For every question asked in conditions B/C/D, write:
  blind/questions_<task>.md   questions in shuffled order, with a context id
  blind/ctx/<ctx_id>.md       what existed when the question was asked:
                              initial free-text analysis, the current draft
                              definition, and earlier questions of the same run
  blind/KEY.json              qid -> model / condition / round  (do not open while coding)

Neither the questions file nor the context files mention condition or model.

Usage:
    python -I blind_extract.py --tasks 2023_A 2022_C 2024_B 2025_A --seed 20261022
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "data" / "controlled" / "runs"
OUT = HERE.parent / "data" / "controlled" / "blind"


def extract_json(text: str):
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    for cand in reversed(blocks):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def free_text(text: str) -> str:
    return text.split("```json")[0].strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--seed", type=int, required=True)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    (OUT / "ctx").mkdir(parents=True, exist_ok=True)
    key = {}
    ctx_counter = 0
    for task in args.tasks:
        items = []
        for f in sorted((RUNS / task).glob("*/[BCD]_rep*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            calls = {c["role"]: c for c in rec["calls"]}
            initial = calls["modeler_initial"]["content"]
            earlier: list[str] = []
            for rnd in rec["questions"]:
                r = rnd["round"]
                src = initial if r == 1 else calls[f"modeler_answer_r{r - 1}"]["content"]
                draft = extract_json(src)
                ctx_counter += 1
                ctx_id = f"X{ctx_counter:04d}"
                body = [
                    f"# Context {ctx_id} (task {task})\n",
                    "## Modeler's initial free-text analysis\n",
                    free_text(initial),
                    "\n## Draft definition at the time the questions were asked\n",
                    "```json\n" + (json.dumps(draft, ensure_ascii=False, indent=1)
                                   if draft is not None else "(could not be parsed)") + "\n```",
                    "\n## Questions asked earlier in the same session\n",
                    "\n".join(f"- {q}" for q in earlier) or "(none)",
                ]
                (OUT / "ctx" / f"{ctx_id}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
                for q in rnd["questions"]:
                    items.append({"q": q, "ctx": ctx_id,
                                  "meta": {"model": rec["model"], "condition": rec["condition"],
                                           "round": r, "rep": rec["rep"], "task": task}})
                earlier.extend(rnd["questions"])
        rng.shuffle(items)
        lines = [f"# Blinded questions — task {task}\n",
                 "Each question lists the context file that shows what existed when it was asked.\n"]
        for i, it in enumerate(items, 1):
            qid = f"{task}-Q{i:03d}"
            key[qid] = {**it["meta"], "ctx": it["ctx"]}
            lines.append(f"## {qid}  (context: ctx/{it['ctx']}.md)\n\n{it['q']}\n")
        (OUT / f"questions_{task}.md").write_text("\n".join(lines), encoding="utf-8")
        print(task, len(items), "questions")
    (OUT / "KEY.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print("contexts", ctx_counter, "| key ->", OUT / "KEY.json")


if __name__ == "__main__":
    main()
