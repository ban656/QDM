"""Blind paper-level review of the final modeling papers (QDM / Claude Code / MM-Agent).

prep : collect one final paper per method per task, mask method names, assign
       random labels; writes papers/<task>__<label>.md and KEY.json
run  : each paper is reviewed on its own by each judge model (no side-by-side),
       using the paper text only; writes reviews/<judge>/<task>__<label>.json
summ : unblind and tabulate

Usage
    . ~/.qdm_api_env
    python -I judge.py prep --seed 20261023
    python -I judge.py run --tasks 2022_C
    python -I judge.py summ
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repository root
sys.path.insert(0, str(ROOT / "controlled"))
import run_ablation as ra  # noqa: E402

ra.TEMPERATURE = 0.0
QDM = ROOT / "data" / "qdm_runs"
BASE = ROOT / "data" / "baselines"
MMX = ROOT / "outputs" / "mm_export"
PAPERS, REVIEWS = ROOT / "outputs" / "judge_papers", ROOT / "outputs" / "judge_reviews"
TASKS = ["2021_C", "2022_C", "2023_A", "2023_C", "2024_B", "2024_D", "2025_A"]
JUDGES = ["glm-5.3", "kimi-k3"]
MASK = [(r"\bQDM\b", "the system"), (r"MM-Agent|MMAgent", "the system"),
        (r"\bClaude( Code)?\b", "the system"), (r"\bCodex\b", "the system"),
        (r"\bDeepSeek\b", "the model")]

RUBRIC = """You are reviewing a solution paper for a mathematical modeling contest problem (MCM/ICM).
Judge the paper only from its text. A mathematical modeling paper must (1) state and justify the
assumptions it relies on, (2) build a model that suits the problem and is mathematically sound,
(3) obtain its conclusions from the model by actual computation, (4) be consistent: the same
quantity, assumption or setting must not change between sections without explanation, and
(5) answer every sub-question of the problem. Extra mechanisms or length earn credit only if they
are used in the computation that answers a sub-question.

Score each dimension from 1 (very poor) to 10 (excellent):
- assumptions: assumptions stated and justified; simplifications appropriate
- model: model choice suits the problem; formulation and derivations are correct
- computation: conclusions come from concrete computed results (numbers, tables, figures) that follow from the stated model
- consistency: settings, symbols and numbers agree across sections
- completeness: every sub-question gets a clear answer
- clarity: the paper can be followed as one coherent argument
- overall: your overall judgment as a reviewer

For every dimension give a short justification that cites the paper (verbatim quotes of at most 25 words).
Then list concrete issues found, each with a type (unjustified_assumption, unsound_model, uncomputed_result,
inconsistency, unanswered_subquestion, other) and verbatim quotes.
Then, for each sub-question of the problem, say whether the paper answers it (yes / partly / no).

Return only a ```json block:
{"scores": {"assumptions": n, "model": n, "computation": n, "consistency": n, "completeness": n, "clarity": n, "overall": n},
 "justifications": {"assumptions": "...", "model": "...", "computation": "...", "consistency": "...", "completeness": "...", "clarity": "...", "overall": "..."},
 "issues": [{"type": "...", "quote": "...", "explanation": "..."}],
 "subquestions": [{"subquestion": "...", "answered": "yes|partly|no", "evidence": "..."}]}"""


def sources(task: str) -> dict[str, Path]:
    final = QDM / task / "claude_workspace/final"
    q = final / ("paper_full.md" if (final / "paper_full.md").exists() else "paper.md")
    return {"QDM": q, "ClaudeCode": BASE / "claude_code" / f"{task}.md", "MM": MMX / f"{task}.md"}


PROCESS_HEAD = re.compile(r"^(#+)\s*(\d+\.\s*)?(Reproducibility|Traceability|Provenance|Run metadata)\b.*$", re.I)
PROCESS_LINE = re.compile(r"claude_workspace|codex_workspace|harness/|\bsha256\b|^\*\*(Run|Source of all numbers|Protocol)\b",
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


def cmd_prep(seed: int, tasks: list[str]) -> None:
    rng = random.Random(seed)
    PAPERS.mkdir(exist_ok=True)
    keyf = ROOT / "outputs" / "judge_KEY.json"
    key = json.loads(keyf.read_text(encoding="utf-8")) if keyf.exists() else {}
    for t in tasks:
        src = sources(t)
        labels = ["X", "Y", "Z"]
        rng.shuffle(labels)
        for (meth, p), lab in zip(src.items(), labels):
            (PAPERS / f"{t}__{lab}.md").write_text(mask(p.read_text(encoding="utf-8", errors="replace")),
                                                    encoding="utf-8")
            key[f"{t}__{lab}"] = {"method": meth, "source": str(p)}
        print(t, {k.split("__")[1]: v["method"] for k, v in key.items() if k.startswith(t)})
    keyf.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")


def review(paper: Path, judge: str) -> None:
    out = REVIEWS / judge / f"{paper.stem}.json"
    if out.exists():
        return
    task = paper.stem.split("__")[0]
    prompt = (f"# Problem\n\n{ra.problem_text(task)}\n\n# Paper under review\n\n"
              f"{paper.read_text(encoding='utf-8')}\n\n# Instructions\n\n{RUBRIC}")
    calls: list[dict] = []
    text = ra.chat(judge, [{"role": "user", "content": prompt}], calls, "review")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"paper": paper.stem, "judge": judge, "parsed": ra.extract_json(text),
                               "raw": text, "usage": calls[-1]["usage"],
                               "finish_reason": calls[-1]["finish_reason"]}, ensure_ascii=False, indent=1),
                   encoding="utf-8")


def cmd_run(tasks: list[str], workers: int) -> None:
    jobs = [(p, j) for t in tasks for p in sorted(PAPERS.glob(f"{t}__*.md")) for j in JUDGES]
    print(len(jobs), "reviews", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(review, p, j): (p.stem, j) for p, j in jobs}
        for f in as_completed(futs):
            try:
                f.result()
                print("done", *futs[f], flush=True)
            except Exception as e:  # rerun resumes
                print("FAIL", *futs[f], type(e).__name__, str(e)[:200], flush=True)


def cmd_summ() -> None:
    key = json.loads((ROOT / "outputs" / "judge_KEY.json").read_text(encoding="utf-8"))
    dims = ["assumptions", "model", "computation", "consistency", "completeness", "clarity", "overall"]
    for judge in JUDGES:
        agg = defaultdict(lambda: defaultdict(list))
        rows = []
        for f in sorted((REVIEWS / judge).glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            p = r["parsed"] or {}
            meth = key[r["paper"]]["method"]
            sc = p.get("scores", {})
            for d in dims:
                if isinstance(sc.get(d), (int, float)):
                    agg[meth][d].append(sc[d])
            sq = [s.get("answered") for s in p.get("subquestions", [])]
            rows.append((r["paper"].split("__")[0], meth, sc.get("overall"), len(p.get("issues", [])),
                         f"{sq.count('yes')}/{len(sq)}", r["finish_reason"]))
        print(f"== {judge}")
        for meth in ["QDM", "ClaudeCode", "MM"]:
            print(f"  {meth:10s} " + " ".join(f"{d[:5]}={sum(v)/len(v):.1f}" for d, v in agg[meth].items()))
        for row in sorted(rows):
            print("   ", *row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "run", "summ"])
    ap.add_argument("--tasks", nargs="+", default=TASKS)
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    {"prep": lambda: cmd_prep(a.seed, a.tasks), "run": lambda: cmd_run(a.tasks, a.workers),
     "summ": cmd_summ}[a.cmd]()


if __name__ == "__main__":
    main()
