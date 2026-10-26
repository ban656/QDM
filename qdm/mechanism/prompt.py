"""Prompt builders for the problem-driven modeling mechanism."""

from __future__ import annotations

import json
from typing import Any, Dict

from .policy import build_question_policy


def compact_feature_table(state: Dict[str, Any]) -> Dict[str, Any]:
    compact = {}
    for field, entry in state.get("feature_table", {}).items():
        compact[field] = {
            "status": entry.get("status", "missing"),
            "summary": entry.get("summary", ""),
            "open_questions": entry.get("open_questions", []),
        }
    return compact


def build_question_prompt(state: Dict[str, Any], target_field: str, round_id: int) -> str:
    from .policy import QUESTION_FIELD_SPECS
    from ..protocol import FEATURE_FIELDS

    spec = QUESTION_FIELD_SPECS[target_field]
    ff_spec = FEATURE_FIELDS.get(target_field, {})
    label = ff_spec.get("label", target_field)
    expected = ff_spec.get("expected", "table format")
    open_questions = state.get("feature_table", {}).get(target_field, {}).get("open_questions", [])
    current_probe = next((str(value).strip() for value in open_questions if str(value).strip()), spec["probe"])
    recent_history = state.get("interview_history", [])[-3:]
    policy = build_question_policy(state, target_field)
    problem_text = state["problem"]["text"]
    return f"""# QDM Interview Round {round_id:03d}

You are Claude Code acting as an independent modeling expert.
Codex only asks a narrow question; do not solve the whole problem.

## Target Field

- target_field: `{target_field}`
- label: {label}
- current_question: {current_probe}
- expected: {expected}

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
{json.dumps(compact_feature_table(state), ensure_ascii=False, indent=2)}
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


def build_stop_signal(state: Dict[str, Any]) -> str:
    policy = build_question_policy(state)
    return (
        "# QDM Stop Signal\n\n"
        "The question gate considers the specification sufficiently clear for modeling.\n\n"
        f"```json\n{json.dumps(policy, ensure_ascii=False, indent=2)}\n```\n"
    )
