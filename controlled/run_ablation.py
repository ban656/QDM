"""Controlled QDM ablation on the problem-definition stage only.

No planning, modeling or coding is run. The four conditions differ only in
who asks the questions and what the asker can see:

  A direct   - no questions; the modeler writes the definition directly
  B selfask  - the modeler asks and answers its own questions in one context
  C shared   - a separate questioner call that sees the modeler's full transcript
  D isolated - a separate questioner call that sees only the problem, the current
               draft definition and the prior Q&A (the QDM setting)

The question instruction, answer instruction, number of rounds and number of
questions per round are identical in B, C and D.

Usage (key and base URL come from the environment, never from this file):
    . ~/.qdm_api_env
    python -I run_ablation.py --tasks 2023_A --reps 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
# MMBench problem files from the official MM-Agent repository
PROB_DIR = Path(os.environ.get("MMBENCH_DIR", DATA.parent / "external" / "LLM-MM-Agent" / "MMBench")) / "problem"
OUT_DIR = DATA / "controlled" / "runs"

API_BASE = os.environ.get("QDM_API_BASE", "").rstrip("/")
API_KEY = os.environ.get("QDM_API_KEY", "")
# gpt-* models sit behind a separate key on the same gateway
API_KEY_GPT = os.environ.get("QDM_API_KEY_GPT", "")


def key_for(model: str) -> str:
    return API_KEY_GPT if model.startswith("gpt-") else API_KEY

TEMPERATURE = 0.7
MAX_TOKENS = 32768

DEF_SCHEMA = """{
  "objective": "what the model must deliver, stated operationally",
  "estimands_or_decisions": ["each quantity to estimate or decision to make"],
  "key_definitions": [{"term": "...", "definition": "...", "alternatives_rejected": "..."}],
  "variables": [{"name": "...", "meaning": "...", "unit": "...", "role": "state|parameter|decision|output"}],
  "assumptions": [{"statement": "...", "rationale": "...", "consequence_if_wrong": "..."}],
  "constraints": ["..."],
  "conditional_or_unidentifiable": ["conclusions that only hold under an assumption, or quantities the available information cannot determine"],
  "validation": ["how results will be checked"],
  "subquestion_plan": [{"subquestion": "...", "how_the_definition_answers_it": "..."}]
}"""

MODELER_SYSTEM = (
    "You are a mathematical modeler working on an open-ended modeling contest "
    "problem (MCM/ICM). Your current job is only to define the problem precisely "
    "before any planning, modeling or coding. Do not solve the problem."
)

QUESTIONER_SYSTEM = (
    "You review a mathematical modeler's understanding of an open-ended modeling "
    "contest problem (MCM/ICM) before any modeling begins. You do not solve the "
    "problem and you do not answer your own questions."
)

INITIAL_INSTR = (
    "First analyze the problem in free text: what is being asked, what is "
    "ambiguous, and which choices you lean toward. Then give a DRAFT problem "
    "definition as a JSON object in a ```json block, using this schema:\n" + DEF_SCHEMA
)

QUESTION_INSTR = (
    "Ask up to {k} questions that must be settled before modeling this problem. "
    "Choose the questions whose answers would most change the model that gets "
    "built or the conclusions it can support. Return only a JSON list of "
    "question strings in a ```json block."
)

ANSWER_INSTR = (
    "Answer each of the following questions about the problem.\n\n{questions}\n\n"
    "For each question, state the decision you take, the reason, and what would "
    "change if a different choice were made. If a question cannot be settled from "
    "the problem statement, say so and state the assumption you adopt. Then give "
    "the updated DRAFT definition as a JSON object in a ```json block, using the "
    "same schema."
)

FINAL_INSTR = (
    "Write the FINAL problem definition as a JSON object in a ```json block, "
    "using the same schema."
)

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def problem_text(task: str) -> str:
    p = json.loads((PROB_DIR / f"{task}.json").read_text(encoding="utf-8"))
    parts = []
    for key, title in [
        ("background", "Background"),
        ("problem_requirement", "Problem requirement"),
        ("addendum", "Addendum"),
        ("dataset_description", "Dataset description"),
        ("variable_description", "Variable description"),
    ]:
        val = p.get(key)
        if not val:
            continue
        if not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False, indent=1)
        parts.append(f"## {title}\n{val.strip()}")
    files = p.get("dataset_path") or []
    if files:
        parts.append("## Data files provided\n" + "\n".join(f"- {f}" for f in files))
    return "\n\n".join(parts)


def chat(model: str, messages: list[dict], calls: list[dict], role: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")
    delay = 5.0
    for attempt in range(1, 7):
        req = urllib.request.Request(
            f"{API_BASE}/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key_for(model)}", "Content-Type": "application/json"},
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or e.code >= 500
            detail = e.read().decode("utf-8", "replace")[:300]
            if not retryable or attempt == 6:
                raise RuntimeError(f"HTTP {e.code}: {detail}") from e
            log(f"    retry {attempt} after HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == 6:
                raise
            log(f"    retry {attempt} after {type(e).__name__}")
        else:
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            calls.append({
                "role": role,
                "request_messages": messages,
                "content": content,
                "reasoning_content": msg.get("reasoning_content"),
                "finish_reason": data["choices"][0].get("finish_reason"),
                "usage": data.get("usage", {}),
                "latency_s": round(time.time() - t0, 2),
                "attempt": attempt,
            })
            return content
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


def extract_json(text: str):
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    for cand in reversed(blocks):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                pass
    return None


def parse_questions(text: str, k: int) -> list[str]:
    obj = extract_json(text)
    if isinstance(obj, list):
        qs = [q if isinstance(q, str) else json.dumps(q, ensure_ascii=False) for q in obj]
    else:
        qs = [ln.strip(" -*0123456789.)\t") for ln in text.splitlines() if ln.strip().endswith("?")]
    return [q for q in qs if q.strip()][:k]


def run_one(task: str, model: str, cond: str, rep: int, rounds: int, k: int) -> dict:
    out = OUT_DIR / task / model / f"{cond}_rep{rep:02d}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    problem = problem_text(task)
    calls: list[dict] = []
    t0 = time.time()

    modeler = [
        {"role": "system", "content": MODELER_SYSTEM},
        {"role": "user", "content": f"# Problem\n\n{problem}\n\n# Instruction\n\n{INITIAL_INSTR}"},
    ]
    reply = chat(model, modeler, calls, "modeler_initial")
    modeler.append({"role": "assistant", "content": reply})
    draft = extract_json(reply)
    qa_rounds: list[dict] = []

    if cond != "A":
        for r in range(1, rounds + 1):
            instr = QUESTION_INSTR.format(k=k)
            if cond == "B":
                modeler.append({"role": "user", "content": instr})
                qtext = chat(model, modeler, calls, f"self_question_r{r}")
                modeler.append({"role": "assistant", "content": qtext})
            elif cond == "C":
                transcript = "\n\n".join(
                    f"[{m['role'].upper()}]\n{m['content']}" for m in modeler[1:]
                )
                qmsgs = [
                    {"role": "system", "content": QUESTIONER_SYSTEM},
                    {"role": "user", "content": (
                        f"# Problem\n\n{problem}\n\n"
                        f"# Modeler's full working transcript so far\n\n{transcript}\n\n"
                        f"# Instruction\n\n{instr}"
                    )},
                ]
                qtext = chat(model, qmsgs, calls, f"questioner_r{r}")
            else:  # D
                qa_hist = "\n\n".join(
                    f"Round {x['round']}\n" + "\n".join(f"Q: {q}" for q in x["questions"])
                    + f"\nModeler's answers:\n{x['answer_text']}"
                    for x in qa_rounds
                ) or "(none yet)"
                qmsgs = [
                    {"role": "system", "content": QUESTIONER_SYSTEM},
                    {"role": "user", "content": (
                        f"# Problem\n\n{problem}\n\n"
                        f"# Modeler's current draft definition\n\n"
                        f"{json.dumps(draft, ensure_ascii=False, indent=1) if draft is not None else '(draft could not be parsed)'}\n\n"
                        f"# Questions asked and answered so far\n\n{qa_hist}\n\n"
                        f"# Instruction\n\n{instr}"
                    )},
                ]
                qtext = chat(model, qmsgs, calls, f"questioner_r{r}")

            questions = parse_questions(qtext, k)
            qlist = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)) or "(no questions)"
            modeler.append({"role": "user", "content": ANSWER_INSTR.format(questions=qlist)})
            ans = chat(model, modeler, calls, f"modeler_answer_r{r}")
            modeler.append({"role": "assistant", "content": ans})
            new_draft = extract_json(ans)
            if new_draft is not None:
                draft = new_draft
            qa_rounds.append({"round": r, "questions": questions, "answer_text": ans})

    modeler.append({"role": "user", "content": FINAL_INSTR})
    final_text = chat(model, modeler, calls, "modeler_final")
    final_def = extract_json(final_text)

    usage = {
        "prompt_tokens": sum(c["usage"].get("prompt_tokens", 0) for c in calls),
        "completion_tokens": sum(c["usage"].get("completion_tokens", 0) for c in calls),
    }
    record = {
        "task": task, "model": model, "condition": cond, "rep": rep,
        "config": {"rounds": rounds, "questions_per_round": k,
                   "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
        "questions": [{"round": x["round"], "questions": x["questions"]} for x in qa_rounds],
        "final_definition": final_def,
        "final_parse_ok": final_def is not None,
        "usage": usage,
        "n_calls": len(calls),
        "wall_s": round(time.time() - t0, 1),
        "calls": calls,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out)
    return record


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--models", nargs="+",
                    default=["deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6.1-sol"])
    ap.add_argument("--conds", nargs="+", default=["A", "B", "C", "D"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not API_BASE or not API_KEY:
        sys.exit("QDM_API_BASE / QDM_API_KEY not set; run `. ~/.qdm_api_env` first")
    if any(m.startswith("gpt-") for m in args.models) and not API_KEY_GPT:
        sys.exit("QDM_API_KEY_GPT not set but a gpt-* model was requested")

    jobs = [(t, m, c, r) for t in args.tasks for m in args.models
            for c in args.conds for r in range(1, args.reps + 1)]
    log(f"{len(jobs)} runs -> {OUT_DIR}")
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, *j, args.rounds, args.k): j for j in jobs}
        for f in as_completed(futs):
            t, m, c, r = futs[f]
            try:
                rec = f.result()
                log(f"done {t} {m} {c} rep{r}: calls={rec['n_calls']} "
                    f"in={rec['usage']['prompt_tokens']} out={rec['usage']['completion_tokens']} "
                    f"wall={rec['wall_s']}s parse_ok={rec['final_parse_ok']}")
            except Exception as e:  # keep the batch going; the run can be resumed
                failures += 1
                log(f"FAIL {t} {m} {c} rep{r}: {type(e).__name__}: {e}")
    log(f"finished, {failures} failed")


if __name__ == "__main__":
    main()
