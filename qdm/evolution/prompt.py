"""Prompt builders for questioner-guided structural distillation."""

from __future__ import annotations

import json
from typing import Any, Dict


def build_distillation_prompt(state: Dict[str, Any], solution_text: str, feedback_text: str = "") -> str:
    """Build a prompt for the questioner to distill reusable structures.

    This inherits Voyager's idea of turning completed experience into reusable
    skills, but the skill here is not executable Minecraft code.  It is a
    question/modeling pattern that helps future modeling tasks converge faster.
    """
    compact_state = {
        "problem": state.get("problem", {}),
        "feature_table": state.get("feature_table", {}),
        "algorithm_modules": state.get("algorithm_modules", []),
        "clarity_gate": state.get("clarity_gate", {}),
        "question_gate": state.get("question_gate", {}),
    }
    return f"""# Questioner-Guided Structural Distillation

You are Codex acting as the questioner, not the solver.
Your task is to watch a completed modeling solution and extract reusable
structures that would help future question-driven modeling runs.

Do not judge the solution only by correctness.  Ask:

- Which structure, if asked earlier, would have made the modeling path clearer?
- Which variable/formula/constraint pattern can be reused on similar problems?
- Which algorithm module is worth storing as a partial module, not a whole route?
- Which validation question should become a standard check?
- Which paper-writing claim pattern is reusable without copying text?

## Modeling State

```json
{json.dumps(compact_state, ensure_ascii=False, indent=2)}
```

## Completed Solution Or Blueprint

{solution_text}

## Optional Feedback / Blind Review / Human Notes

{feedback_text or "None"}

## Strict JSON Output

```json
{{
  "source_problem_id": "{state.get('problem', {}).get('title', '')}",
  "distillation_summary": "",
  "question_patterns": [
    {{
      "pattern_id": "QP1",
      "trigger": "When should this question pattern be used?",
      "question": "Reusable question wording",
      "target_field": "problem_boundary | variables | time_structure | space_structure | relations | constraints | objectives | data_support | uncertainty | algorithm_implications | validation_requirements | writing_claims",
      "expected_answer_shape": "table/json/list/equations",
      "why_it_matters": "",
      "failure_if_not_asked": ""
    }}
  ],
  "modeling_patterns": [
    {{
      "pattern_id": "MP1",
      "name": "",
      "applies_to": "",
      "structure": "",
      "variables": [],
      "relations": [],
      "constraints": [],
      "transfer_conditions": [],
      "do_not_use_when": []
    }}
  ],
  "algorithm_modules": [
    {{
      "module_id": "EM1",
      "name": "",
      "purpose": "",
      "inputs": [],
      "outputs": [],
      "pseudocode": [],
      "borrowable_parts": [],
      "trial_metric": "",
      "rollback_condition": "",
      "do_not_use_when": []
    }}
  ],
  "validation_questions": [
    {{
      "check_id": "VQ1",
      "question": "",
      "target": "",
      "pass_condition": "",
      "failure_action": ""
    }}
  ],
  "writing_patterns": [
    {{
      "pattern_id": "WP1",
      "claim_type": "",
      "useful_sentence_plan": "",
      "required_evidence": [],
      "risk": ""
    }}
  ],
  "policy_updates": [
    {{
      "target": "question_policy | modeling_tree_schema | validation_checklist | writing_rubric",
      "suggested_change": "",
      "reason": "",
      "requires_human_approval": true
    }}
  ],
  "anti_patterns": [
    {{
      "name": "",
      "symptom": "",
      "why_bad": "",
      "avoidance_question": ""
    }}
  ]
}}
```
"""


def build_retrieval_context(patterns: Dict[str, Any], query: str = "") -> str:
    """Format retrieved evolution patterns for injection into future prompts."""
    return f"""# Retrieved Questioner-Guided Patterns

These patterns were distilled by the questioner from previous completed
modeling solutions.  Use them as structural hints, not as answers.

Query: {query or "None"}

```json
{json.dumps(patterns, ensure_ascii=False, indent=2)}
```
"""

