"""Question-driven modeling protocol — v2 with integrated DeepModeler tree schema.

This module prepares the experiment scaffold for a human-mediated dual-agent
workflow.  The blueprint output schema (v2) absorbs the DeepModeler 8-node
tree structure: physical_background, variable_structure, formula_relations,
data_structure, constraint_structure, algorithm_structure, validation_structure,
paper_narrative, plus experiment_and_rollback_plan and algorithm_module_fusion.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MMA_ROOT = os.path.dirname(CURRENT_DIR)
if MMA_ROOT not in sys.path:
    sys.path.insert(0, MMA_ROOT)

from qdm.mechanism.policy import (
    QUESTION_FIELD_SPECS,
    QUESTION_STATUS_WEIGHT,
    build_question_policy,
    pick_next_field,
    rank_question_fields,
    recompute_question_gate,
)
from qdm.mechanism.prompt import build_question_prompt, build_stop_signal, compact_feature_table


STATUS_ORDER = ["missing", "partial", "assumption_based", "conflict", "clear"]
VALID_STATUS = set(STATUS_ORDER)

FEATURE_FIELDS: Dict[str, Dict[str, Any]] = {
    "problem_boundary": {
        "label": "Problem boundary",
        "required": True,
        "question": "Please define the system boundary, real background, modeled objects, external conditions, and what cannot be crossed by assumption.",
        "expected": "table: entity / role / inside_or_outside / evidence / uncertainty",
    },
    "variables": {
        "label": "Variable structure",
        "required": True,
        "question": "Please classify variables into decision variables, state variables, parameters, and outputs, and annotate units, ranges, and static/dynamic status.",
        "expected": "table: symbol / meaning / type / unit / static_or_dynamic / source",
    },
    "time_structure": {
        "label": "Time structure",
        "required": True,
        "question": "Please determine whether the problem has time evolution, event order, delay, discrete stages, or continuous dynamics, and explain the associated variables.",
        "expected": "table: time_object / continuous_or_discrete / event / equations_needed / evidence",
    },
    "space_structure": {
        "label": "Space structure",
        "required": True,
        "question": "Please determine whether the problem has geometry, route structure, spatial barriers, distance, region, or coordinate structure, and indicate the core spatial relations.",
        "expected": "table: spatial_object / coordinate_or_geometry / relation / computable_formula / evidence",
    },
    "relations": {
        "label": "Relations and formulas",
        "required": True,
        "question": "Please list candidate formulas, mapping relations, and governing equations, and explain applicable conditions, unit checks, and evidence sources.",
        "expected": "table: id / formula_or_relation / meaning / applies_when / unit_check / evidence",
    },
    "constraints": {
        "label": "Constraints",
        "required": True,
        "question": "Please separate hard constraints, soft constraints, boundary conditions, and reasonable assumptions, and state the consequence of each violation.",
        "expected": "table: id / constraint / hard_or_soft / source / violation_effect",
    },
    "objectives": {
        "label": "Objectives",
        "required": True,
        "question": "Please clarify the objective, evaluation metric, primary target, whether it is multi-objective, and how trade-offs should be handled.",
        "expected": "table: objective / maximize_or_minimize / metric / scope / tradeoff",
    },
    "data_support": {
        "label": "Data support",
        "required": True,
        "question": "Please explain which parameters, calibrations, and checks are supported by the given data, and which values require estimation or assumption.",
        "expected": "table: data_item / supports / limitation / needed_assumption",
    },
    "uncertainty": {
        "label": "Uncertainty",
        "required": True,
        "question": "Please identify uncertainty sources, sensitive parameters, noise terms, and how they change the model or solution.",
        "expected": "table: uncertainty / affected_component / sensitivity_test / mitigation",
    },
    "algorithm_implications": {
        "label": "Algorithm implications",
        "required": True,
        "question": "Based on the clarified variables, relations, constraints, and objectives, judge the problem class and the executable algorithm modules, without writing the full final paper plan yet.",
        "expected": "table: module / problem_class / inputs / outputs / pseudocode / rollback_test",
    },
    "validation_requirements": {
        "label": "Validation requirements",
        "required": True,
        "question": "Please design unit checks, feasibility checks, boundary checks, rollback checks, sensitivity analysis, and result interpretation requirements.",
        "expected": "table: check / target / pass_condition / failure_action",
    },
    "writing_claims": {
        "label": "Paper claims",
        "required": False,
        "question": "Please distill the final paper-level insight, innovation points, limitations, and the interpretive path that should appear in the paper.",
        "expected": "table: claim / evidence_needed / risk / paper_section",
    },
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def ensure_workspace(workspace: str) -> Dict[str, str]:
    dirs = {
        "root": workspace,
        "state": os.path.join(workspace, "state"),
        "to_claude": os.path.join(workspace, "codex_to_claude"),
        "from_claude": os.path.join(workspace, "claude_to_codex"),
        "reviews": os.path.join(workspace, "codex_reviews"),
        "artifacts": os.path.join(workspace, "final_artifacts"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def state_path(workspace: str) -> str:
    return os.path.join(workspace, "state", "modeling_state.json")


def load_state(workspace: str) -> Dict[str, Any]:
    path = state_path(workspace)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"QDM state does not exist: {path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_state(workspace: str, state: Dict[str, Any]) -> None:
    state["updated_at"] = now()
    recompute_clarity_gate(state)
    recompute_question_gate(state)
    if not state["clarity_gate"].get("ready_for_modeling", False):
        state["question_gate"]["ready_for_modeling"] = False
        state["question_gate"]["blockers"] = list(dict.fromkeys(
            state["question_gate"].get("blockers", [])
            + state["clarity_gate"].get("blockers", [])
        ))
    write_json(state_path(workspace), state)


def new_feature_entry() -> Dict[str, Any]:
    return {
        "status": "missing",
        "summary": "",
        "items": [],
        "evidence": [],
        "open_questions": [],
        "confidence": 0.0,
        "updated_by_round": [],
    }


MIN_CLEAR_CONFIDENCE = 0.75
GENERIC_EVIDENCE = {
    "",
    "problem",
    "problem statement",
    "problem requirement",
    "standard method",
    "standard practice",
}


def feature_entry_issues(field: str, entry: Dict[str, Any]) -> List[str]:
    """Return machine-checkable reasons a self-declared clear field is not clear."""
    if entry.get("status", "missing") != "clear":
        return []

    issues: List[str] = []
    if not str(entry.get("summary", "")).strip():
        issues.append("empty summary")
    if not entry.get("items"):
        issues.append("no structured items")

    evidence = [str(value).strip() for value in entry.get("evidence", []) if str(value).strip()]
    if not evidence:
        issues.append("no evidence")
    elif all(value.lower() in GENERIC_EVIDENCE for value in evidence):
        issues.append("evidence is only a generic label")

    open_questions = [str(value).strip() for value in entry.get("open_questions", []) if str(value).strip()]
    if open_questions:
        issues.append(f"{len(open_questions)} unresolved open question(s)")

    try:
        confidence = float(entry.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < MIN_CLEAR_CONFIDENCE:
        issues.append(f"confidence {confidence:.3f} < {MIN_CLEAR_CONFIDENCE:.2f}")

    if field == "data_support":
        traceable = any(
            isinstance(item, dict)
            and any(item.get(key) for key in ("path", "source", "source_path", "file", "dataset", "assumption"))
            for item in entry.get("items", [])
        )
        if not traceable:
            issues.append("data support has no traceable source or explicit assumption")
    return issues


def make_initial_state(problem_text: str, problem_path: str, title: str) -> Dict[str, Any]:
    return {
        "schema_version": "qdm_state_v1",
        "created_at": now(),
        "updated_at": now(),
        "problem": {
            "title": title,
            "source_path": os.path.abspath(problem_path),
            "text": problem_text,
        },
        "roles": {
            "codex": "questioner, reviewer, state maintainer, implementation controller",
            "claude_code": "independent answer agent and modeling expert",
            "human": "transition controller and final accept/reject authority",
        },
        "interview_history": [],
        "feature_table": {field: new_feature_entry() for field in FEATURE_FIELDS},
        "clarity_gate": {},
        "question_gate": {},
        "question_policy": {},
        "algorithm_modules": [],
        "modeling_blueprint": {"schema_version": BP_SCHEMA_VERSION},
        "implementation_artifacts": {},
        "paper_artifacts": {},
        "benchmark_feedback": [],
    }


def recompute_clarity_gate(state: Dict[str, Any]) -> None:
    """Recompute the clarity gate with QDM 2.0 constraint completeness checks.

    In addition to counting which ``FEATURE_FIELDS`` are ``clear``, this now
    also checks:

    - **Variable completeness**: every variable entry should mention range/type.
    - **Constraint spec validity**: if ``state["constraint_spec"]`` exists,
      its ``validation.is_valid`` must be ``true``.
    - **Consistency**: any ``consistency_report`` entry with severity ``error``
      blocks the gate.
    """
    feature_table = state.get("feature_table", {})
    required_fields = [name for name, spec in FEATURE_FIELDS.items() if spec["required"]]
    clear_count = 0
    blockers = []
    warnings = []
    detail = {}

    for field in required_fields:
        entry = feature_table.get(field, {})
        status = entry.get("status", "missing")
        if status == "clear":
            issues = feature_entry_issues(field, entry)
            if issues:
                blockers.extend(f"{field}: {issue}" for issue in issues)
            else:
                clear_count += 1
        elif status == "conflict":
            blockers.append(f"{field}: conflict")
        elif status in {"missing", "partial", "assumption_based"}:
            blockers.append(f"{field}: {status}")

    for field, entry in feature_table.items():
        if entry.get("status") == "assumption_based":
            warnings.append(f"{field}: relies on assumptions")

    # ── QDM 2.0: variable completeness check ──
    var_entry = feature_table.get("variables", {})
    if var_entry.get("status") == "clear":
        items = var_entry.get("items", [])
        missing_range = 0
        missing_type = 0
        for item in items:
            if isinstance(item, dict):
                if not item.get("range") and not item.get("unit"):
                    missing_range += 1
                if not item.get("type"):
                    missing_type += 1
        if items:
            detail["variable_range_coverage"] = f"{len(items) - missing_range}/{len(items)}"
            detail["variable_type_coverage"] = f"{len(items) - missing_type}/{len(items)}"
            if missing_range > len(items) * 0.5:
                blockers.append("variables: more than 50 % of variables lack range/unit")
            if missing_type > len(items) * 0.5:
                blockers.append("variables: more than 50 % of variables lack a type tag")

    # ── QDM 2.0: constraint-specification validity check ──
    spec = state.get("constraint_spec", {})
    spec_validation = spec.get("validation", {})
    if spec_validation:
        if not spec_validation.get("is_valid", False):
            issues = spec_validation.get("issues", [])
            for iss in issues[:5]:
                blockers.append(f"constraint_spec: {iss}")
            if len(issues) > 5:
                blockers.append(f"constraint_spec: +{len(issues) - 5} more issues")
        else:
            detail["constraint_spec"] = "valid"

    # ── QDM 2.0: consistency report check ──
    consistency = state.get("consistency_report", [])
    for c in consistency:
        if c["severity"] == "error":
            blockers.append(f"consistency:{c['rule_id']} {c['rule_name']}")

    score = clear_count / max(len(required_fields), 1)
    ready = score >= 0.85 and not blockers

    state["clarity_gate"] = {
        "score": round(score, 3),
        "required_fields": required_fields,
        "ready_for_modeling": ready,
        "blockers": blockers,
        "warnings": warnings,
        "detail": detail,  # QDM 2.0: richer diagnostic information
    }


def sanitize_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value.strip())
    return value.strip("_") or "qdm_problem"


def init_workspace(problem_path: str, workspace: str, title: str) -> None:
    dirs = ensure_workspace(workspace)
    problem_text = read_text(problem_path)
    state = make_initial_state(problem_text, problem_path, title or sanitize_name(os.path.basename(problem_path)))
    save_state(workspace, state)
    write_text(os.path.join(dirs["root"], "00_README.md"), build_workspace_readme(state))
    write_text(os.path.join(dirs["state"], "problem.md"), f"# {state['problem']['title']}\n\n{problem_text}")


def build_workspace_readme(state: Dict[str, Any]) -> str:
    return f"""# QDM Workspace

Problem: {state["problem"]["title"]}

This directory is a shared-file protocol for question-driven mathematical
modeling.  It is designed for manual coordination between Codex, Claude Code,
and the human controller.

## Directories

- `state/modeling_state.json`: single source of truth.
- `codex_to_claude/`: prompts generated by Codex for Claude Code.
- `claude_to_codex/`: Claude answers imported into the state.
- `codex_reviews/`: parse reports, gate reports, and follow-up notes.
- `final_artifacts/`: later modeling blueprints, code plans, paper plans.

## Minimal Loop

1. Codex runs `next-question` and writes a prompt.
2. Human copies the prompt into Claude Code.
3. Human saves Claude's JSON answer as a file.
4. Codex runs `import-answer`.
5. Codex checks `clarity_gate`; repeat until ready.
"""


def write_next_question(workspace: str, target_field: str = "") -> str:
    dirs = ensure_workspace(workspace)
    state = load_state(workspace)
    field = pick_next_field(state, target_field)
    round_id = next_round_id(state)
    prompt = build_question_prompt(state, field, round_id)
    path = os.path.join(dirs["to_claude"], f"round_{round_id:03d}_{field}.md")
    write_text(path, prompt)
    state.setdefault("interview_history", []).append(
        {
            "round_id": round_id,
            "target_field": field,
            "prompt_path": os.path.abspath(path),
            "status": "prompt_written",
            "created_at": now(),
        }
    )
    save_state(workspace, state)
    return path


def write_codex_question(workspace: str, question_text: str, target_field: str, round_id: int) -> str:
    """Write a Codex-generated question as the round prompt.

    Question-driven protocol v3: the questioner (Codex) authors the actual
    question text based on the problem, the solver's planning drafts, and the
    current feature table. The harness binds round_id, target_field, and the
    question file hash exactly as for policy-generated questions.
    """
    dirs = ensure_workspace(workspace)
    path = os.path.join(dirs["to_claude"], f"round_{round_id:03d}_{target_field}.md")
    write_text(path, question_text)
    state = load_state(workspace)
    state.setdefault("interview_history", []).append(
        {
            "round_id": int(round_id),
            "target_field": target_field,
            "prompt_path": os.path.abspath(path),
            "status": "prompt_written",
            "question_source": "codex_questioner",
            "created_at": now(),
        }
    )
    save_state(workspace, state)
    return path


def normalize_status(status: str) -> str:
    normalized = str(status).strip()
    if normalized not in VALID_STATUS:
        raise ValueError(f"Invalid feature status: {status}")
    return normalized


def append_unique(target: List[Any], values: List[Any]) -> None:
    existing = {json.dumps(v, ensure_ascii=False, sort_keys=True) for v in target}
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in existing:
            target.append(value)
            existing.add(key)


def status_rank(status: str) -> int:
    return STATUS_ORDER.index(status) if status in STATUS_ORDER else 0


def update_feature_entry(entry: Dict[str, Any], update: Dict[str, Any], round_id: int) -> None:
    new_status = normalize_status(update.get("status", entry.get("status", "missing")))
    # New evidence may invalidate an earlier conclusion, so status must be able
    # to move both up and down. The benchmark harness records who authorized it.
    entry["status"] = new_status
    if update.get("summary"):
        entry["summary"] = update["summary"]
    append_unique(entry.setdefault("items", []), update.get("items", []) or [])
    append_unique(entry.setdefault("evidence", []), update.get("evidence", []) or [])
    if "open_questions" in update:
        entry["open_questions"] = update.get("open_questions", []) or []
    try:
        entry["confidence"] = float(update.get("confidence", entry.get("confidence", 0.0)) or 0.0)
    except (TypeError, ValueError):
        entry["confidence"] = entry.get("confidence", 0.0)
    append_unique(entry.setdefault("updated_by_round", []), [round_id])


def import_answer(workspace: str, answer_path: str, round_id: Optional[int] = None) -> Tuple[str, str]:
    dirs = ensure_workspace(workspace)
    state = load_state(workspace)
    raw = read_text(answer_path)
    copied_name = os.path.basename(answer_path)
    copied_path = os.path.join(dirs["from_claude"], copied_name)
    if os.path.abspath(answer_path) != os.path.abspath(copied_path):
        shutil.copyfile(answer_path, copied_path)

    try:
        data = parse_json_object(raw)
    except Exception as exc:
        review_path = os.path.join(dirs["reviews"], f"parse_error_{sanitize_name(copied_name)}.md")
        write_text(review_path, f"# Parse Error\n\nAnswer file: `{answer_path}`\n\nError: `{exc}`\n")
        raise

    actual_round = int(round_id or data.get("round_id") or next_round_id(state))
    changed_fields = []
    for update in data.get("feature_updates", []) or []:
        field = update.get("field")
        if field not in FEATURE_FIELDS:
            continue
        update_feature_entry(state["feature_table"][field], update, actual_round)
        changed_fields.append(field)

    followups = [
        str(value).strip()
        for value in data.get("questions_for_codex", []) or []
        if str(value).strip()
    ]
    target_field = data.get("target_field", "")
    if followups and target_field in state.get("feature_table", {}):
        append_unique(state["feature_table"][target_field].setdefault("open_questions", []), followups)
        append_unique(
            state.setdefault("pending_followups", []),
            [{"field": target_field, "question": question, "source_round": actual_round} for question in followups],
        )

    append_unique(state.setdefault("algorithm_modules", []), data.get("algorithm_modules", []) or [])

    # ── Absorb DeepModeler tree blueprint (v2) if present ──
    if data.get("schema_version") == BP_SCHEMA_VERSION:
        state["modeling_blueprint"] = data
    elif data.get("model_specification") or data.get("physical_background") is not None:
        # Accept either explicit v2 or legacy flat blueprint payload
        bp = {
            "schema_version": BP_SCHEMA_VERSION,
            "main_insight": data.get("main_insight", ""),
            "physical_background": data.get("physical_background", []),
            "variables": data.get("variables", [])
            or data.get("model_specification", {}).get("variables", []),
            "equations": data.get("equations", [])
            or data.get("model_specification", {}).get("formulas", []),
            "constraints": data.get("constraints", [])
            or data.get("model_specification", {}).get("constraints", []),
            "objectives": data.get("objectives", [])
            or data.get("model_specification", {}).get("objectives", []),
            "time_structure": data.get("time_structure", []),
            "space_structure": data.get("space_structure", []),
            "data_structure": data.get("data_structure", []),
            "algorithm_plan": data.get("algorithm_plan", []),
            "algorithm_module_fusion": data.get("algorithm_module_fusion", [])
            or data.get("algorithm_fusion", []),
            "experiment_and_rollback_plan": data.get("experiment_and_rollback_plan", []),
            "validation_plan": data.get("validation_plan", []),
            "implementation_plan": data.get("implementation_plan", []),
            "paper_plan": data.get("paper_plan", {}),
            "remaining_human_checks": data.get("remaining_human_checks", []),
        }
        state["modeling_blueprint"] = bp

    for item in state.get("interview_history", []):
        if item.get("round_id") == actual_round:
            item["status"] = "answer_imported"
            item["answer_path"] = os.path.abspath(copied_path)
            item["imported_at"] = now()
            item["changed_fields"] = changed_fields
            break
    else:
        state.setdefault("interview_history", []).append(
            {
                "round_id": actual_round,
                "target_field": data.get("target_field", ""),
                "status": "answer_imported",
                "answer_path": os.path.abspath(copied_path),
                "imported_at": now(),
                "changed_fields": changed_fields,
            }
        )

    save_state(workspace, state)
    review_path = os.path.join(dirs["reviews"], f"round_{actual_round:03d}_review.md")
    review_lines = [build_answer_review(state, data, changed_fields)]

    # ── Run cross-field consistency check and append to review ──
    consistency_findings = check_cross_field_consistency(state)
    if consistency_findings:
        review_lines.append(format_consistency_report(consistency_findings))
        # Update state with consistency findings
        state["consistency_report"] = consistency_findings
        save_state(workspace, state)

    write_text(review_path, "\n\n---\n\n".join(review_lines))
    return copied_path, review_path


def build_answer_review(state: Dict[str, Any], data: Dict[str, Any], changed_fields: List[str]) -> str:
    gate = state.get("clarity_gate", {})
    field_lines = []
    for field in changed_fields:
        entry = state["feature_table"][field]
        field_lines.append(f"- `{field}`: {entry.get('status')} - {entry.get('summary')}")
    if not field_lines:
        field_lines.append("- No recognized feature field was updated.")
    blockers = "\n".join(f"- {item}" for item in gate.get("blockers", [])) or "- None"

    # Check if a DeepModeler tree blueprint was absorbed
    bp = state.get("modeling_blueprint", {})
    blueprint_note = ""
    if bp.get("schema_version") == BP_SCHEMA_VERSION:
        sections = [k for k in (
            "physical_background", "variables", "equations", "constraints",
            "objectives", "time_structure", "space_structure", "data_structure",
            "algorithm_plan", "algorithm_module_fusion",
            "experiment_and_rollback_plan", "validation_plan",
            "implementation_plan", "paper_plan",
        ) if bp.get(k)]
        blueprint_note = f"\n## DeepModeler Blueprint Absorbed\n\n- schema_version: {BP_SCHEMA_VERSION}\n- sections populated: {', '.join(sections) if sections else 'none'}\n"

    return f"""# Codex Review

Round: {data.get("round_id")}
Target field: `{data.get("target_field", "")}`

## Updated Fields

{os.linesep.join(field_lines)}

## Clarity Gate

- score: {gate.get("score")}
- ready_for_modeling: {gate.get("ready_for_modeling")}

## Blockers

{blockers}
{blueprint_note}
## Human Checks

- Did Claude answer only the target field?
- Are formulas, constraints, variables, and modules traceable to evidence?
- Are uncertain claims marked as `assumption_based` instead of `clear`?
- Are algorithm modules specific enough to implement and roll back?
"""


def write_gate_report(workspace: str) -> str:
    dirs = ensure_workspace(workspace)
    state = load_state(workspace)
    gate = state.get("clarity_gate", {})
    table = state.get("feature_table", {})
    lines = ["# QDM Clarity Gate", ""]
    lines.append(f"- score: {gate.get('score')}")
    lines.append(f"- ready_for_modeling: {gate.get('ready_for_modeling')}")
    lines.append("")
    lines.append("## Feature Status")
    lines.append("")
    for field, spec in FEATURE_FIELDS.items():
        entry = table.get(field, {})
        required = "required" if spec["required"] else "optional"
        lines.append(f"- `{field}` ({required}): {entry.get('status')} - {entry.get('summary', '')}")
    lines.append("")
    lines.append("## Blockers")
    lines.append("")
    blockers = gate.get("blockers", [])
    lines.extend([f"- {item}" for item in blockers] or ["- None"])
    path = os.path.join(dirs["reviews"], "clarity_gate.md")
    write_text(path, "\n".join(lines) + "\n")
    return path


BP_SCHEMA_VERSION = "qdm_blueprint_v2"
"""Schema version constant — marks blueprints produced by the merged QDM+DeepModeler format."""


# ---------------------------------------------------------------------------
# QDM 2.0: cross-field consistency rules
# ---------------------------------------------------------------------------
# Each rule names the two fields involved, describes the check, and states how
# the information is read from the feature table.

CONSISTENCY_RULES: List[Dict[str, Any]] = [
    {
        "id": "CS1",
        "name": "variables_in_relations",
        "description": "Relations and formulas must reference variables defined in the variable table.",
        "check_fields": ("variables", "relations"),
        "severity": "error",
        "extract_from_variables": "Extract all defined variable symbols from the variable structure items.",
        "extract_from_relations": "Extract all referenced variable symbols from relation formulas.",
    },
    {
        "id": "CS2",
        "name": "constraints_use_defined_variables",
        "description": "Constraints must reference variables or parameters that exist in the variable table.",
        "check_fields": ("variables", "constraints"),
        "severity": "error",
        "extract_from_variables": "Extract all defined variable symbols.",
        "extract_from_constraints": "Extract variable symbols mentioned in constraint expressions.",
    },
    {
        "id": "CS3",
        "name": "objectives_aligned_with_variables",
        "description": "Objectives must reference variables defined in the variable table.",
        "check_fields": ("variables", "objectives"),
        "severity": "error",
        "extract_from_variables": "Extract all defined variable symbols.",
        "extract_from_objectives": "Extract variable symbols mentioned in objective metrics.",
    },
    {
        "id": "CS4",
        "name": "boundary_scope_matches_variables",
        "description": "Variables should lie inside the system boundary; variables outside the boundary should be flagged.",
        "check_fields": ("problem_boundary", "variables"),
        "severity": "warning",
        "extract_from_boundary": "List entities/objects inside the system boundary.",
        "extract_from_variables": "Check whether each variable's meaning aligns with the bounded entities.",
    },
    {
        "id": "CS5",
        "name": "time_space_consistent_with_algorithm",
        "description": "If time/space structure is continuous, algorithm implications should not rely solely on discrete methods.",
        "check_fields": ("time_structure", "space_structure", "algorithm_implications"),
        "severity": "warning",
        "extract_from_time": "Determine continuous or discrete classification.",
        "extract_from_space": "Determine continuous or discrete geometry.",
        "extract_from_algorithm": "Check solver family for continuous/discrete mismatch.",
    },
    {
        "id": "CS6",
        "name": "algorithm_uses_declared_data",
        "description": "Algorithm modules should reference data fields that exist in the data support description.",
        "check_fields": ("data_support", "algorithm_implications"),
        "severity": "warning",
        "extract_from_data": "List available data items and fields.",
        "extract_from_algorithm": "List required inputs for each algorithm module.",
    },
    {
        "id": "CS7",
        "name": "validation_covers_constraints",
        "description": "Validation requirements should include checks for the declared constraints.",
        "check_fields": ("constraints", "validation_requirements"),
        "severity": "warning",
        "extract_from_constraints": "List all constraint IDs.",
        "extract_from_validation": "List all check targets.",
    },
]


def check_cross_field_consistency(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scan the feature table for cross-field inconsistencies.

    Checks each ``CONSISTENCY_RULES`` entry against the current feature table.
    Results are appended to ``state["consistency_report"]`` and returned.

    Returns
    -------
    list[dict]
        Each entry: ``{"rule_id": str, "rule_name": str, "severity": str,
        "fields": [str], "detail": str}``.
    """
    report_key = "consistency_report"
    table = state.get("feature_table", {})
    all_findings = []

    for rule in CONSISTENCY_RULES:
        # Only check fields that are already clear (otherwise not enough info)
        all_fields_clear = all(
            table.get(f, {}).get("status") == "clear"
            for f in rule.get("check_fields", ())
        )
        if not all_fields_clear:
            continue

        # Build a human-readable summary for the LLM or reviewer
        field_details = {}
        for f in rule.get("check_fields", ()):
            entry = table.get(f, {})
            field_details[f] = {
                "status": entry.get("status"),
                "summary": entry.get("summary", "")[:300],
                "items_count": len(entry.get("items", [])),
            }

        finding = {
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "severity": rule["severity"],
            "fields": list(rule.get("check_fields", ())),
            "detail": rule["description"],
            "field_snapshots": field_details,
        }

        # Downgrade error to warning if all check fields have items (content exists).
        # This prevents structural blocking of the clarity gate when the modeler has
        # provided substantive content in both fields, even if explicit cross-references
        # are missing. Keep error only when a "clear" field is empty (broken state).
        if finding["severity"] == "error":
            all_have_items = all(
                field_details.get(f, {}).get("items_count", 0) > 0
                for f in rule.get("check_fields", ())
            )
            if all_have_items:
                finding["severity"] = "warning"
                finding["detail"] = finding["detail"] + " (downgraded from error: both fields have content)"
        all_findings.append(finding)

    state[report_key] = all_findings
    return all_findings


def format_consistency_report(findings: List[Dict[str, Any]]) -> str:
    """Format cross-field consistency findings as markdown."""
    if not findings:
        return "# Cross-Field Consistency Check\n\nNo inconsistencies detected.\n"
    lines = ["# Cross-Field Consistency Report\n"]
    for f in findings:
        tag = "🔴" if f["severity"] == "error" else "🟡"
        lines.append(f"### {tag} {f['rule_id']}: {f['rule_name']} ({f['severity']})")
        lines.append(f"- **Fields**: {', '.join(f['fields'])}")
        lines.append(f"- **Detail**: {f['detail']}")
        for field_name, snap in f.get("field_snapshots", {}).items():
            lines.append(f"  - `{field_name}`: {snap['status']} — {snap['summary'][:120]}")
        lines.append("")
    return "\n".join(lines)


def build_blueprint_prompt(state: Dict[str, Any]) -> str:
    return f"""# QDM Modeling Blueprint Prompt — v2 (DeepModeler Tree Schema)

You may now start building the integrated modeling blueprint, but do not write
the final paper yet.

The output schema absorbs the DeepModeler 8-node tree structure:
physical_background, variables (variable_structure), equations (formula_relations),
constraints (constraint_structure), algorithm_plan (algorithm_structure),
validation_plan (validation_structure), paper_narrative,
plus experiment_and_rollback_plan, algorithm_module_fusion,
time_structure, space_structure, and data_structure.

## Problem

{state["problem"]["text"]}

## Feature Table

```json
{json.dumps(state.get("feature_table", {}), ensure_ascii=False, indent=2)}
```

## Algorithm Modules

```json
{json.dumps(state.get("algorithm_modules", []), ensure_ascii=False, indent=2)}
```

## Strict JSON Output

```json
{{
  "schema_version": "{BP_SCHEMA_VERSION}",

  "main_insight": "",

  "physical_background": [],
  "variables": [],
  "equations": [],
  "constraints": [],
  "objectives": [],
  "time_structure": [],
  "space_structure": [],
  "data_structure": [],

  "algorithm_plan": [],
  "algorithm_module_fusion": [
    {{
      "module_id": "",
      "decision": "core | optional | merge | reject",
      "absorbed_parts": [],
      "reason": "",
      "rollback_test": "",
      "solver_family": "",
      "constraint_handling": "",
      "determinism": "",
      "global_or_local_claim": ""
    }}
  ],

  "experiment_and_rollback_plan": [],
  "validation_plan": [],

  "implementation_plan": [
    {{
      "file": "",
      "function": "",
      "uses_formula_ids": [],
      "inputs": [],
      "outputs": [],
      "validation": []
    }}
  ],

  "paper_plan": {{
    "sections": [],
    "result_interpretation_requirements": [],
    "figures_and_tables": []
  }},

  "remaining_human_checks": []
}}
```
"""


def write_blueprint_prompt(workspace: str) -> str:
    dirs = ensure_workspace(workspace)
    state = load_state(workspace)
    if not state.get("clarity_gate", {}).get("ready_for_modeling", False):
        raise RuntimeError("Cannot create a blueprint before the clarity gate passes.")
    spec_validation = state.get("constraint_spec", {}).get("validation", {})
    if not spec_validation.get("is_valid", False):
        raise RuntimeError("Cannot create a blueprint before a valid constraint specification is absorbed.")
    path = os.path.join(dirs["artifacts"], "blueprint_prompt.md")
    write_text(path, build_blueprint_prompt(state))
    return path


# ---------------------------------------------------------------------------
# QDM 2.0: formal constraint specification, called after the clarity gate passes and before the blueprint
# ---------------------------------------------------------------------------
# This function builds a prompt asking the LLM for a machine-parsable constraint specification:
#   - Variables: symbol, meaning, type, range, unit
#   - Constraints: expression, hard/soft, referenced variables
#   - Objectives: expression, direction (max/min), metric
#   - Algorithm sketch: problem class, solver family
#
# Downstream code parses this JSON directly, without a further LLM reading of natural language.

CONSTRAINT_SPEC_VERSION = "qdm_constraint_spec_v1"

CONSTRAINT_SPEC_SCHEMA_HINT = """```json
{
  "schema_version": "qdm_constraint_spec_v1",
  "variables": [
    {
      "symbol": "x_i",
      "meaning": "decision variable for ...",
      "type": "decision | state | parameter | output",
      "range": "[0, 100]",
      "unit": "m",
      "static_or_dynamic": "static | dynamic"
    }
  ],
  "constraints": [
    {
      "id": "C1",
      "expression": "sum_i x_i <= TotalBudget",
      "hard_or_soft": "hard | soft",
      "referenced_variables": ["x_i", "TotalBudget"],
      "violation_penalty": "infeasible | penalty=10",
      "source": "problem statement section 2"
    }
  ],
  "objectives": [
    {
      "id": "O1",
      "expression": "sum_i value_i * x_i",
      "direction": "maximize | minimize",
      "metric": "total profit (USD)",
      "referenced_variables": ["x_i", "value_i"],
      "tradeoff_notes": ""
    }
  ],
  "time_horizon": {
    "type": "continuous | discrete | event_based | none",
    "description": ""
  },
  "space_description": {
    "type": "euclidean | graph | grid | none",
    "description": ""
  },
  "algorithm_sketch": {
    "problem_class": "LP | MILP | NLP | simulation | statistical | ...",
    "solver_family": "ortools | cvxpy | scipy | custom | ...",
    "key_inputs": ["data_field_1", "data_field_2"],
    "expected_outputs": ["decision_variable_values", "objective_value"]
  }
}
```
"""


def build_constraint_spec_prompt(state: Dict[str, Any]) -> str:
    """Build a prompt that asks the LLM to output a formal constraint specification.

    This is called **after** the Clarity gate passes (``ready_for_modeling=True``)
    and **before** ``build_blueprint_prompt``.  It extracts all feature-table
    information into a mechanically parseable constraint network.

    Returns
    -------
    str
        Prompt for the LLM.
    """
    table = state.get("feature_table", {})
    compact = {}
    for field, spec in FEATURE_FIELDS.items():
        entry = table.get(field, {})
        compact[field] = {
            "status": entry.get("status", "missing"),
            "summary": entry.get("summary", ""),
            "items": entry.get("items", [])[:5],
        }

    consistency = state.get("consistency_report", [])
    consistency_note = ""
    if consistency:
        errors = [c for c in consistency if c["severity"] == "error"]
        warnings = [c for c in consistency if c["severity"] == "warning"]
        if errors:
            consistency_note = (
                "\n**Unresolved consistency errors** (resolve before declaring "
                "the constraint specification):\n" + "\n".join(
                    f"- {e['rule_id']}: {e['detail']}" for e in errors
                )
            )
        elif warnings:
            consistency_note = (
                "\n**Open warnings** (informational, not blocking):\n" + "\n".join(
                    f"- {w['rule_id']}: {w['detail']}" for w in warnings
                )
            )

    return f"""# QDM Constraint Specification Prompt

The Clarity Gate has been passed.  Now produce a **formal, mechanically
parseable** constraint specification that downstream modelling code can
consume without additional LLM inference.

## Constraint Specification Rules

1. **Every variable must have a range and unit.**  If a variable's range
   cannot be determined with certainty, state the plausible range and mark
   it ``assumed``.
2. **Every constraint must reference only variables that exist in the
   variable list.**  If a constraint mentions a symbol that is not in the
   variable list, add the missing variable first.
3. **Every objective must have a clear direction** (maximize or minimize)
   and a measurable metric.
4. **Cross-field consistency** has been checked.  Any unresolved errors
   are listed below — resolve them in your output before the JSON.
{consistency_note}

## Feature Table Summary

```json
{json.dumps(compact, ensure_ascii=False, indent=2)}
```

## Output Format

Return ONLY a valid JSON object matching this schema.
Do not wrap it in markdown fences — this JSON will be parsed automatically.

{CONSTRAINT_SPEC_SCHEMA_HINT}
"""


def write_constraint_spec_prompt(workspace: str) -> str:
    """Write the constraint specification prompt to the workspace."""
    dirs = ensure_workspace(workspace)
    state = load_state(workspace)
    if not state.get("clarity_gate", {}).get("ready_for_modeling", False):
        raise RuntimeError("Cannot create a constraint specification before the clarity gate passes.")
    path = os.path.join(dirs["artifacts"], "constraint_spec_prompt.md")
    write_text(path, build_constraint_spec_prompt(state))
    return path


def absorb_constraint_spec(state: Dict[str, Any], spec: Dict[str, Any]) -> None:
    """Parse and store a submitted constraint spec into the state.

    Performs basic structural validation:
    - Checks that all referenced variables exist
    - Checks that every constraint has an expression
    - Checks that every objective has a direction

    Stores the result in ``state["constraint_spec"]``.
    """
    spec_version = spec.get("schema_version", "")
    if spec_version != CONSTRAINT_SPEC_VERSION:
        spec["schema_version"] = CONSTRAINT_SPEC_VERSION

    variables = spec.get("variables", []) or []
    constraints = spec.get("constraints", []) or []
    objectives = spec.get("objectives", []) or []

    defined_symbols = {v.get("symbol", "") for v in variables}

    validation_issues = []

    # Check constraint references
    for c in constraints:
        refs = c.get("referenced_variables", []) or []
        for ref in refs:
            if ref not in defined_symbols:
                validation_issues.append(
                    f"Constraint {c.get('id', '?')} references "
                    f"undefined variable '{ref}'"
                )

    # Check objective references
    for o in objectives:
        refs = o.get("referenced_variables", []) or []
        for ref in refs:
            if ref not in defined_symbols:
                validation_issues.append(
                    f"Objective {o.get('id', '?')} references "
                    f"undefined variable '{ref}'"
                )

    # Check for missing expressions
    for c in constraints:
        if not c.get("expression", "").strip():
            validation_issues.append(
                f"Constraint {c.get('id', '?')} has an empty expression"
            )
    for o in objectives:
        if not o.get("direction", "").strip():
            validation_issues.append(
                f"Objective {o.get('id', '?')} has no direction (maximize/minimize)"
            )
        if not o.get("expression", "").strip():
            validation_issues.append(
                f"Objective {o.get('id', '?')} has an empty expression"
            )

    spec["validation"] = {
        "defined_symbols": sorted(defined_symbols),
        "issue_count": len(validation_issues),
        "issues": validation_issues,
        "is_valid": len(validation_issues) == 0,
    }

    state["constraint_spec"] = spec


def next_round_id(state: Dict[str, Any]) -> int:
    history = state.get("interview_history", [])
    if not history:
        return 1
    return max(int(item.get("round_id", 0)) for item in history) + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Question-driven modeling shared-file protocol.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a QDM workspace.")
    p_init.add_argument("--problem", required=True, help="UTF-8 problem text file.")
    p_init.add_argument("--workspace", required=True, help="Workspace directory.")
    p_init.add_argument("--title", default="", help="Problem title.")

    p_next = sub.add_parser("next-question", help="Write the next Codex-to-Claude question prompt.")
    p_next.add_argument("--workspace", required=True)
    p_next.add_argument("--field", default="", help="Optional target field override.")

    p_import = sub.add_parser("import-answer", help="Import Claude's JSON answer and update state.")
    p_import.add_argument("--workspace", required=True)
    p_import.add_argument("--answer", required=True)
    p_import.add_argument("--round-id", type=int, default=0)

    p_gate = sub.add_parser("gate", help="Write a clarity gate report.")
    p_gate.add_argument("--workspace", required=True)

    p_blueprint = sub.add_parser("blueprint-prompt", help="Write the modeling blueprint prompt.")
    p_blueprint.add_argument("--workspace", required=True)

    # QDM 2.0: constraint specification
    p_cspec = sub.add_parser("constraint-spec", help="Write the formal constraint specification prompt.")
    p_cspec.add_argument("--workspace", required=True)

    p_cspec_import = sub.add_parser("absorb-constraint-spec", help="Import a constraint spec JSON answer.")
    p_cspec_import.add_argument("--workspace", required=True)
    p_cspec_import.add_argument("--answer", required=True)

    p_consistency = sub.add_parser("check-consistency", help="Run cross-field consistency check and write report.")
    p_consistency.add_argument("--workspace", required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "init":
        init_workspace(args.problem, args.workspace, args.title)
        print(f"QDM workspace initialized: {args.workspace}")
    elif args.command == "next-question":
        path = write_next_question(args.workspace, args.field)
        print(f"Question prompt written: {path}")
    elif args.command == "import-answer":
        copied, review = import_answer(args.workspace, args.answer, args.round_id or None)
        print(f"Answer imported: {copied}")
        print(f"Review written: {review}")
    elif args.command == "gate":
        path = write_gate_report(args.workspace)
        print(f"Gate report written: {path}")
    elif args.command == "blueprint-prompt":
        path = write_blueprint_prompt(args.workspace)
        print(f"Blueprint prompt written: {path}")
    elif args.command == "constraint-spec":
        path = write_constraint_spec_prompt(args.workspace)
        print(f"Constraint spec prompt written: {path}")
    elif args.command == "absorb-constraint-spec":
        state = load_state(args.workspace)
        raw = read_text(args.answer)
        spec = parse_json_object(raw)
        absorb_constraint_spec(state, spec)
        save_state(args.workspace, state)
        issues = spec.get("validation", {}).get("issues", [])
        if issues:
            for iss in issues:
                print(f"  WARNING: {iss}")
        print(f"Constraint spec absorbed — {len(issues)} issues")
    elif args.command == "check-consistency":
        state = load_state(args.workspace)
        findings = check_cross_field_consistency(state)
        save_state(args.workspace, state)
        report = format_consistency_report(findings)
        dirs = ensure_workspace(args.workspace)
        path = os.path.join(dirs["reviews"], "consistency_check.md")
        write_text(path, report)
        print(f"Consistency report written: {path}")


if __name__ == "__main__":
    main()
