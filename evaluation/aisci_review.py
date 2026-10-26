"""Review the final modeling papers with the AI Scientist reviewer (perform_review).

The paper text is the same whole-paper text used for the MMBench evaluation
(run metadata stripped, system names masked). The reviewer's prompts, NeurIPS
form, few-shot examples and parsing are used unchanged.

Usage
    . ~/.qdm_api_env
    python -I aisci_review.py --tasks 2022_A --model deepseek-chat
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repository root
# official AI Scientist repository (github.com/SakanaAI/AI-Scientist)
AISCI = Path(os.environ.get("AI_SCIENTIST_DIR", ROOT / "external" / "AI-Scientist"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(AISCI))
sys.path.insert(0, str(ROOT / "controlled"))
# pymupdf4llm is only used to read PDFs; we pass text, so a stub is enough for the import
sys.modules.setdefault("pymupdf4llm", types.ModuleType("pymupdf4llm"))
# llm.py imports google.generativeai at top level but only uses it for Gemini models
_g = types.ModuleType("google")
_ga = types.ModuleType("google.generativeai")
_gt = types.ModuleType("google.generativeai.types")
_gt.GenerationConfig = object
_ga.types = _gt
_g.generativeai = _ga
for _name, _mod in [("google", _g), ("google.generativeai", _ga), ("google.generativeai.types", _gt)]:
    sys.modules.setdefault(_name, _mod)

import openai  # noqa: E402
import ai_scientist.perform_review as pr  # noqa: E402
from ai_scientist.perform_review import perform_review  # noqa: E402

# Venue switched from an ML conference to mathematical modeling; everything else unchanged.
MM_BASE = ("You are an expert reviewing a paper submitted to a prestigious mathematical modeling journal. "
           "The paper is a solution to the mathematical modeling problem given below.")
MM_FORM = (pr.neurips_form
           .replace("the NeurIPS ethics guidelines", "the journal's ethics guidelines")
           .replace("the broader NeurIPS community", "the broader mathematical modeling community")
           .replace("one or more areas of AI", "one or more areas of mathematical modeling")
           .replace("at least one area of AI", "at least one area of mathematical modeling")
           .replace("multiple sub-areas", "multiple sub-areas of mathematical modeling")
           .replace("one sub-area of AI", "one sub-area of mathematical modeling")
           .replace("more than one sub-area", "more than one sub-area of mathematical modeling"))
import mmbench_eval as me  # noqa: E402

CLIENTS = {
    "deepseek-chat": lambda: openai.OpenAI(api_key=os.environ["QDM_DS_KEY"], base_url="https://api.deepseek.com"),
}
OUT = ROOT / "outputs" / "ai_scientist_review"


def review_one(task, method, model, reflections, ensemble):
    out = OUT / model / f"{task}__{method}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    text = me.whole_text(task, method)
    import run_ablation as ra
    paper = "# Problem\n\n" + ra.problem_text(task) + "\n\n# Paper\n\n" + text
    # few-shot examples are ML-conference reviews, so they are not used
    review = perform_review(paper, model, CLIENTS[model](), num_reflections=reflections,
                            num_fs_examples=0, num_reviews_ensemble=ensemble, temperature=0.1,
                            review_instruction_form=MM_FORM, reviewer_system_prompt_base=MM_BASE,
                            reviewer_system_prompt="")  # neutral: no "give bad scores if unsure"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"task": task, "method": method, "chars": len(text), "review": review},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return json.loads(out.read_text(encoding="utf-8"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=me.TASKS)
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--reflections", type=int, default=1)
    ap.add_argument("--ensemble", type=int, default=1)
    a = ap.parse_args()
    jobs = [(t, m) for t in a.tasks for m in ["QDM", "ClaudeCode", "MM"]]
    keys = ["Soundness", "Presentation", "Contribution", "Originality", "Quality", "Clarity",
            "Significance", "Overall", "Decision"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(review_one, t, m, a.model, a.reflections, a.ensemble): (t, m) for t, m in jobs}
        for f in as_completed(futs):
            t, m = futs[f]
            try:
                r = f.result()["review"] or {}
                print(t, m, {k: r.get(k) for k in keys}, flush=True)
            except Exception as e:
                print("FAIL", t, m, type(e).__name__, str(e)[:200], flush=True)


if __name__ == "__main__":
    main()
