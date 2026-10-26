"""QDM question loop helper for benchmark_auto mode.
Bypasses the broken build_question_prompt in mechanism/prompt.py (label KeyError).
"""
import sys, os, json, shutil
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# This file: project_root/qdm/auto/qdm_question.py
# MMA_ROOT = repository root (2 levels up from auto/)
MMA_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if MMA_ROOT not in sys.path:
    sys.path.insert(0, MMA_ROOT)

from qdm.protocol import (
    load_state, save_state, write_text,
    FEATURE_FIELDS, parse_json_object,
    update_feature_entry, append_unique,
    next_round_id, check_cross_field_consistency,
    format_consistency_report, build_answer_review,
    now, STATUS_ORDER
)
from qdm.mechanism.policy import (
    QUESTION_FIELD_SPECS, pick_next_field, build_question_policy,
    rank_question_fields
)

CLAUDE_WORKSPACE = "claude_workspace"

def state_path(workspace):
    return os.path.join(workspace, "state", "modeling_state.json")

def ensure_dirs(base):
    dirs = {
        "to_claude": os.path.join(base, "codex_to_claude"),
        "from_claude": os.path.join(base, "claude_to_codex"),
        "reviews": os.path.join(base, "codex_reviews"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs

def write_question_prompt(workspace, target_field, round_id):
    """Write a question prompt without using the broken build_question_prompt."""
    state = load_state(workspace)
    spec = QUESTION_FIELD_SPECS[target_field]
    policy = build_question_policy(state, target_field)
    problem_text = state["problem"]["text"]
    recent_history = state.get("interview_history", [])[-3:]

    # Get label from FEATURE_FIELDS (protocol.py)
    ff_spec = FEATURE_FIELDS.get(target_field, {})
    label = ff_spec.get("label", target_field)
    expected = ff_spec.get("expected", "table format")

    # compact feature table
    compact = {}
    for field, entry in state.get("feature_table", {}).items():
        compact[field] = {
            "status": entry.get("status", "missing"),
            "summary": entry.get("summary", ""),
            "open_questions": entry.get("open_questions", []),
        }

    prompt = f"""# QDM Interview Round {round_id:03d}

You are Claude Code acting as an independent modeling expert.
Codex only asks a narrow question; do not solve the whole problem.

## Target Field

- target_field: `{target_field}`
- label: {label}
- current_question: {spec["probe"]}

## Response Rules

- Answer only the current field.
- Use `assumption_based` when the claim is plausible but not fixed by the statement.
- Use `conflict` when the statement contains incompatible evidence.
- Keep conclusions traceable to the prompt, formulas, units, or verifiable checks.
- If this field still does not close the specification, list 1-3 follow-up questions in `questions_for_codex`.
- Prefix searchable facts with `[SEARCH]` and inferential gaps with `[INFER]`.

## Question Policy

```json
{json.dumps(policy, ensure_ascii=False, indent=2)}
```

## Current Feature Table

```json
{json.dumps(compact, ensure_ascii=False, indent=2)}
```

## Recent History

```json
{json.dumps(recent_history, ensure_ascii=False, indent=2)}
```

## Problem Text

{problem_text}

## Required JSON

```json
{{
  "round_id": {round_id},
  "target_field": "{target_field}",
  "direct_answer": "",
  "feature_updates": [
    {{
      "field": "{target_field}",
      "status": "missing | partial | assumption_based | conflict | clear",
      "summary": "",
      "items": [],
      "evidence": [],
      "open_questions": [],
      "confidence": 0.0
    }}
  ],
  "algorithm_modules": [],
  "assumptions": [],
  "questions_for_codex": []
}}
```
"""
    dirs = ensure_dirs(workspace)
    path = os.path.join(dirs["to_claude"], f"round_{round_id:03d}_{target_field}.md")
    write_text(path, prompt)

    # Update interview_history in state
    state.setdefault("interview_history", []).append({
        "round_id": round_id,
        "target_field": target_field,
        "prompt_path": os.path.abspath(path),
        "status": "prompt_written",
        "created_at": now(),
    })
    save_state(workspace, state)
    return path

def next_round_id(state):
    history = state.get("interview_history", [])
    return max((item.get("round_id", 0) for item in history), default=0) + 1

def import_answer_safe(workspace, answer_path, round_id=None):
    """Import an answer and update the state."""
    state = load_state(workspace)
    raw_text = open(answer_path, "r", encoding="utf-8").read()
    data = parse_json_object(raw_text)

    actual_round = int(round_id or data.get("round_id") or next_round_id(state))
    changed_fields = []

    for update in data.get("feature_updates", []) or []:
        field = update.get("field")
        if field not in FEATURE_FIELDS:
            continue
        update_feature_entry(state["feature_table"][field], update, actual_round)
        changed_fields.append(field)

    append_unique(state.setdefault("algorithm_modules", []), data.get("algorithm_modules", []) or [])

    # Update interview_history
    for item in state.get("interview_history", []):
        if item.get("round_id") == actual_round:
            item["status"] = "answer_imported"
            item["answer_path"] = os.path.abspath(answer_path)
            item["imported_at"] = now()
            item["changed_fields"] = changed_fields
            break
    else:
        state.setdefault("interview_history", []).append({
            "round_id": actual_round,
            "target_field": data.get("target_field", ""),
            "status": "answer_imported",
            "answer_path": os.path.abspath(answer_path),
            "imported_at": now(),
            "changed_fields": changed_fields,
        })

    save_state(workspace, state)

    # Write review
    dirs = ensure_dirs(workspace)
    review_path = os.path.join(dirs["reviews"], f"round_{actual_round:03d}_review.md")
    review_lines = [build_answer_review(state, data, changed_fields)]
    # Cross-field consistency
    consistency_findings = check_cross_field_consistency(state)
    if consistency_findings:
        review_lines.append(format_consistency_report(consistency_findings))
        state["consistency_report"] = consistency_findings
        save_state(workspace, state)

    write_text(review_path, "\n\n---\n\n".join(review_lines))
    return review_path, changed_fields


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--action", required=True, choices=["write_question", "import_answer"])
    parser.add_argument("--answer", default="")
    args = parser.parse_args()

    if args.action == "write_question":
        state = load_state(args.workspace)
        field = pick_next_field(state)
        if not field:
            print(json.dumps({"error": "no_fields_remaining", "field": ""}))
        else:
            rid = next_round_id(state)
            path = write_question_prompt(args.workspace, field, rid)
            print(json.dumps({"path": path, "field": field, "round_id": rid}))

    elif args.action == "import_answer":
        review_path, changed = import_answer_safe(args.workspace, args.answer)
        state = load_state(args.workspace)
        cg = state.get("clarity_gate", {})
        qg = state.get("question_gate", {})
        print(json.dumps({
            "review_path": review_path,
            "changed_fields": changed,
            "clarity_gate_ready": cg.get("ready_for_modeling", False),
            "clarity_score": cg.get("score", 0.0),
            "question_gate_ready": qg.get("ready_for_modeling", False),
            "support_score": qg.get("support_score", 0.0),
            "clarity_blockers": cg.get("blockers", []),
            "question_gate_top_field": qg.get("top_field", ""),
        }, ensure_ascii=False, indent=2))
