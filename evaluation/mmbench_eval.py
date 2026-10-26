"""MMBench official evaluation of QDM / Claude Code / MM-Agent papers.

convert : QDM and Claude Code papers are markdown. Lines are numbered and the model
          returns, per task the paper addresses, the line ranges that serve as the four
          fields the official evaluator reads (task_description, task_analysis,
          mathematical_modeling_process, subtask_outcome_analysis). The script cuts the
          original lines, so every field is verbatim paper text.
          MM-Agent solutions are used as produced (their json already has these fields).
          -> mmbench/solutions/<task>__<method>.json
eval    : the official MMBench evaluator (MMBench/evaluation/run_evaluation.py,
          evaluate_math_modeling) with its own prompts, temperature 0.7, max_tokens 4000,
          one sample per dimension; only the model and endpoint are changed.
summ    : scores per method.

Usage
    . ~/.qdm_api_env
    python -I mmbench_eval.py convert --tasks 2022_C
    python -I mmbench_eval.py eval --tasks 2022_C
    python -I mmbench_eval.py summ
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repository root
sys.path.insert(0, str(HERE))  # -I drops the script dir; judge.py / export_mm.py live here
sys.path.insert(0, str(ROOT / "controlled"))
import run_ablation as ra  # noqa: E402

# MMBench folder of the official MM-Agent repository (github.com/usail-hkust/LLM-MM-Agent)
OFFICIAL = Path(os.environ.get("MMBENCH_DIR", ROOT / "external" / "LLM-MM-Agent" / "MMBench"))
sys.path.insert(0, str(OFFICIAL))
from evaluation.model import gpt  # noqa: E402
import evaluation.run_evaluation as _rev  # noqa: E402
from evaluation.run_evaluation import evaluate_math_modeling  # noqa: E402

_orig_load = _rev.load_solution_json


class _SolutionData(dict):
    """Behaves like the official task dict when iterated (tasks only), but
    .get('background') / .get('problem_requirement') return the problem text."""

    def __init__(self, tasks, extra):
        super().__init__(tasks)
        self._extra = extra

    def get(self, key, default=None):
        if key in self._extra:
            return self._extra[key]
        return super().get(key, default)


def _load_with_problem(file_path):
    """Official loader keeps only the tasks, so the prompts' `background` and
    `problem_requirement` come out empty. Supply them from the MMBench problem file
    (same for every method); everything else is the official code path."""
    data = _orig_load(file_path)
    task = Path(file_path).stem.split("__")[0]
    prob = json.loads((OFFICIAL / "problem" / f"{task}.json").read_text(encoding="utf-8"))
    return _SolutionData(data, {"background": prob.get("background", ""),
                                "problem_requirement": prob.get("problem_requirement", "")})


_rev.load_solution_json = _load_with_problem

QDM = ROOT / "data" / "qdm_runs"
BASE = ROOT / "data" / "baselines"
OUT = ROOT / "outputs" / "mmbench"
SOL = OUT / "solutions"
JUDGE = "gpt-6.1-sol"               # MMBench evaluator model
CONVERT_MODEL = "gpt-6.1-sol"      # only cuts paper lines into fields; never scores
FIELDS = ["task_description", "task_analysis", "mathematical_modeling_process", "subtask_outcome_analysis"]
TASKS = ["2021_C", "2021_F", "2022_A", "2022_C", "2023_A", "2023_C", "2023_D", "2024_B", "2024_D", "2025_A"]

CONVERT_PROMPT = """The numbered lines below are a solution paper for the modeling problem above.
Identify the tasks (sub-problems) the paper addresses, in the paper's own order. For each task give
the line ranges of the paper that serve as:
  task_description: what this task is (the paper's statement of the task or sub-question)
  task_analysis: the paper's analysis of this task, including its assumptions
  mathematical_modeling_process: the model, variables, formulas and solution method used for this task
  subtask_outcome_analysis: the results, answer and conclusions for this task
Rules: use only line numbers; do not rewrite anything. Every line belongs to at most one task and
one field: never list the same line twice. Content shared by several tasks (for example one model
used for all tasks) goes only under the first task that uses it. Leave a field empty if the paper has
nothing for it. Cover the paper's substantive content; skip only title, references and appendix
listings.
Return only a ```json block:
{"tasks": [{"name": "...", "task_description": [[start, end], ...], "task_analysis": [[...]],
            "mathematical_modeling_process": [[...]], "subtask_outcome_analysis": [[...]]}]}"""


def qdm_paper(task: str) -> Path:
    final = QDM / task / "claude_workspace/final"
    return final / ("paper_full.md" if (final / "paper_full.md").exists() else "paper.md")


def cc_paper(task: str) -> Path:
    return BASE / "claude_code" / f"{task}.md"


RERUN_DIRS = {"2021_F": "2021_F_20261023-171010", "2022_A": "2022_A_20261023-191214",
              "2023_D": "2023_D_20261023-213338"}


def mm_json(task: str) -> Path:
    return BASE / "mm_agent" / f"{task}.json"


def convert_one(task: str, method: str, path: Path) -> None:
    out = SOL / f"{task}__{method}.json"
    if out.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    numbered = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines))
    calls: list[dict] = []
    text = ra.chat(CONVERT_MODEL, [{"role": "user", "content":
                            f"# Problem\n\n{ra.problem_text(task)}\n\n# Paper\n\n{numbered}\n\n# Task\n\n{CONVERT_PROMPT}"}],
                   calls, "convert")
    obj = ra.extract_json(text) or {}
    tasks, used = [], set()
    for t in obj.get("tasks", []):
        rec = {}
        for f in FIELDS:
            seg = []
            for r in t.get(f, []) or []:
                if isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r):
                    a, b = max(1, r[0]), min(len(lines), r[1])
                    keep = [i for i in range(a, b + 1) if i not in used]  # each line used once
                    if keep:
                        seg.append("\n".join(lines[i - 1] for i in keep))
                        used.update(keep)
            rec[f] = "\n\n".join(seg)
        if any(rec.values()):
            tasks.append(rec)
    nonblank = {i + 1 for i, l in enumerate(lines) if l.strip()}
    SOL.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tasks": tasks, "_source": str(path), "_ranges": obj.get("tasks", []),
                               "_coverage": round(len(used & nonblank) / max(len(nonblank), 1), 3),
                               "_usage": calls[-1]["usage"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"converted {task} {method}: {len(tasks)} tasks, coverage {len(used & nonblank) / max(len(nonblank), 1):.0%}",
          flush=True)


def cmd_convert(tasks):
    jobs = []
    for t in tasks:
        jobs += [(t, "QDM", qdm_paper(t)), (t, "ClaudeCode", cc_paper(t))]
        SOL.mkdir(parents=True, exist_ok=True)
        dst = SOL / f"{t}__MM.json"
        if not dst.exists():
            shutil.copy(mm_json(t), dst)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(convert_one, *j): j[:2] for j in jobs}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:
                print("FAIL convert", *futs[f], type(e).__name__, str(e)[:200], flush=True)



JUDGES_CFG = {  # name -> (model, base_url, env var holding the key)
    "gpt": ("gpt-6.1-sol", None, "QDM_API_KEY_GPT"),
    "ds": ("deepseek-flash", "https://api.deepseek.com", "QDM_DS_KEY"),
}


def judge_partial():
    name = os.environ.get("MMB_JUDGE", "gpt")
    model, base, keyenv = JUDGES_CFG[name]
    base = base or os.environ["QDM_API_BASE"] + "/v1"
    return partial(gpt, base_url=base, key=os.environ[keyenv], model=model, temperature=0.7, max_tokens=4000)

DIM_PROMPTS = None


def _dim_prompts():
    from evaluation.prompts import (generate_problem_analysis_prompt, generate_modeling_rigorousness_prompt,
                                    generate_practicality_and_scientificity_prompt,
                                    generate_result_and_bias_analysis_prompt)
    return {"analysis_evaluation": generate_problem_analysis_prompt,
            "modeling_rigorousness_evaluation": generate_modeling_rigorousness_prompt,
            "practicality_and_scientificity_evaluation": generate_practicality_and_scientificity_prompt,
            "result_and_bias_analysis_evaluation": generate_result_and_bias_analysis_prompt}


def _judge():
    return judge_partial()


def _n_scores(text: str) -> int:
    return len(re.findall(r"<score>\s*\d+\s*</score>", text or ""))


def fill_one(sol: Path) -> list[str]:
    """For a finished evaluation, redo only the dimensions that did not yield both sub-scores.
    Same official prompt and parser; up to 3 attempts per dimension; same rule for every method."""
    d = sol.parent / "evaluation_result" / sol.stem
    jf = d / "evaluation_results.json"
    res = json.loads(jf.read_text(encoding="utf-8"))
    data = _rev.load_solution_json(str(sol))
    llm, prompts, fixed = _judge(), _dim_prompts(), []
    for dim, gen in prompts.items():
        if len(res.get(dim) or {}) >= 2:
            continue
        prompt = gen(data)
        for _ in range(3):
            out = llm(prompt)
            if out and _n_scores(out[0]) >= 2:
                parsed = _rev.parse_and_save_evaluation_data(out[0])
                if len(parsed) >= 2:
                    res[dim] = parsed
                    fixed.append(dim)
                    break
    jf.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixed


def eval_one(sol: Path) -> None:
    done = sol.parent / "evaluation_result" / sol.stem / "evaluation_results.json"
    if done.exists():
        return
    base = judge_partial()

    def llm(prompt):
        # same rule for every method: if the reply has no parsable <score> tag, ask again (at most 2 more times)
        out = base(prompt)
        for _ in range(2):
            if out and re.search(r"<score>\s*\d+\s*</score>", out[0]):
                break
            out = base(prompt)
        return out

    evaluate_math_modeling(llm, str(sol))


def cmd_eval(tasks):
    sols = [p for t in tasks for p in sorted(SOL.glob(f"{t}__*.json"))]
    print(len(sols), "solutions", flush=True)
    (SOL / "evaluation_result").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(eval_one, s): s.stem for s in sols}
        for f in as_completed(futs):
            try:
                f.result()
                print("evaluated", futs[f], flush=True)
            except Exception as e:
                print("FAIL eval", futs[f], type(e).__name__, str(e)[:200], flush=True)


def cmd_fill(names):
    for name in names:
        sol = SOL / f"{name}.json"
        jf = SOL / "evaluation_result" / name / "evaluation_results.json"
        if not jf.exists():
            shutil.rmtree(jf.parent, ignore_errors=True)
            eval_one(sol)
        print(name, "filled:", fill_one(sol), flush=True)


def cmd_summ(root="solutions"):
    base = OUT / root
    dims = {"analysis_evaluation": "AE", "modeling_rigorousness_evaluation": "MR",
            "practicality_and_scientificity_evaluation": "PS", "result_and_bias_analysis_evaluation": "RBA"}
    rows = {}
    for f in sorted((base / "evaluation_result").glob("*/evaluation_results.json")):
        task, method = f.parent.name.split("__")
        r = json.loads(f.read_text(encoding="utf-8"))
        sc = {}
        for k, short in dims.items():
            # first two sub-scores per dimension (official format); mean of those available
            vals = [v["score"] for v in (r.get(k) or {}).values() if isinstance(v, dict)][:1 if short == "AE" else 2]
            sc[short] = sum(vals) / len(vals) if vals else None
        rows[(task, method)] = sc
    print(f"{'task':8s} {'method':10s} " + " ".join(f"{d:>5s}" for d in dims.values()) + "  total")
    agg = {}
    for (t, m), sc in sorted(rows.items()):
        vals = [v for v in sc.values() if v is not None]
        tot = sum(vals) / len(vals) if vals else None
        agg.setdefault(m, []).append(sc | {"total": tot})
        print(f"{t:8s} {m:10s} " + " ".join(f"{(sc[d] if sc[d] is not None else float('nan')):5.2f}"
                                            for d in dims.values()) + f"  {tot if tot is not None else float('nan'):.2f}")
    print("mean")
    for m, lst in agg.items():
        print(f"  {m:10s} " + " ".join(
            f"{d}={sum(x[d] for x in lst if x[d] is not None) / max(1, sum(1 for x in lst if x[d] is not None)):.2f}"
            for d in list(dims.values()) + ["total"]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["convert", "eval", "fill", "whole", "summ"])
    ap.add_argument("--tasks", nargs="+", default=TASKS)
    ap.add_argument("--names", nargs="+", default=[])
    ap.add_argument("--root", default="solutions", help="solutions | whole")
    a = ap.parse_args()
    if a.cmd != "summ":
        ra.API_KEY = os.environ.get("QDM_API_KEY_GPT", "")
        ra.API_KEY_GPT = os.environ.get("QDM_API_KEY_GPT", "")
        ra.TEMPERATURE = 0.0
        ra.MAX_TOKENS = 16000
    {"convert": lambda: cmd_convert(a.tasks), "eval": lambda: cmd_eval(a.tasks),
     "fill": lambda: cmd_fill(a.names), "whole": lambda: cmd_whole(a.tasks, a.root if a.root != "solutions" else "whole"),
     "summ": lambda: cmd_summ(a.root)}[a.cmd]()




# --------------------------------------------------------------------------- whole-paper mode
WHOLE = OUT / "whole"


def whole_text(task: str, method: str) -> str:
    """Full final paper text, run metadata stripped and system names masked (same rule for all)."""
    import judge
    import export_mm
    if method == "QDM":
        raw = qdm_paper(task).read_text(encoding="utf-8", errors="replace")
    elif method == "ClaudeCode":
        raw = cc_paper(task).read_text(encoding="utf-8", errors="replace")
    else:
        raw = export_mm.md(json.loads(mm_json(task).read_text(encoding="utf-8")))
    return judge.mask(raw)


def cmd_whole(tasks, root="whole"):
    WHOLE = OUT / root
    """Each paper is one task whose four fields all hold the whole paper, so every official
    dimension prompt sees the complete paper. Prompts, criteria and parser are unchanged."""
    WHOLE.mkdir(parents=True, exist_ok=True)
    (WHOLE / "evaluation_result").mkdir(exist_ok=True)  # official code races on this dir in parallel
    sols = []
    for t in tasks:
        for m in ["QDM", "ClaudeCode", "MM"]:
            p = WHOLE / f"{t}__{m}.json"
            if not p.exists():
                text = whole_text(t, m)
                p.write_text(json.dumps({"tasks": [{f: text for f in FIELDS}], "_chars": len(text)},
                                        ensure_ascii=False), encoding="utf-8")
            sols.append(p)
    print(len(sols), "papers", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(lambda s: (eval_one(s), fill_one(s)), s): s.stem for s in sols}
        for f in as_completed(futs):
            try:
                f.result()
                print("evaluated", futs[f], flush=True)
            except Exception as e:
                print("FAIL", futs[f], type(e).__name__, str(e)[:200], flush=True)


if __name__ == "__main__":
    main()
