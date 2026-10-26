"""Question-selection policy for problem-driven modeling."""

from __future__ import annotations

from typing import Any, Dict, List


QUESTION_STATUS_WEIGHT = {
    "conflict": 1.20,
    "missing": 1.00,
    "partial": 0.70,
    "assumption_based": 0.35,
    "clear": 0.00,
}

QUESTION_FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    "problem_boundary": {
        "priority": 10.0,
        "mode": "mixed",
        "probe": "What is inside the modeled system, what is outside it, and what evidence fixes that split?",
        "dependents": ["variables", "time_structure", "space_structure", "relations", "constraints", "objectives", "algorithm_implications", "validation_requirements"],
    },
    "variables": {
        "priority": 10.0,
        "mode": "ask",
        "probe": "Which symbols are decision variables, state variables, parameters, and outputs, and what are their units?",
        "dependents": ["relations", "constraints", "objectives", "algorithm_implications", "validation_requirements"],
    },
    "time_structure": {
        "priority": 8.5,
        "mode": "ask",
        "probe": "Is the problem continuous, discrete, event-based, delayed, or stage-wise, and which variables evolve in time?",
        "dependents": ["relations", "constraints", "algorithm_implications", "validation_requirements"],
    },
    "space_structure": {
        "priority": 8.0,
        "mode": "ask",
        "probe": "What is the spatial geometry, coordinate system, or routing structure, and which relations depend on it?",
        "dependents": ["relations", "constraints", "algorithm_implications", "validation_requirements"],
    },
    "relations": {
        "priority": 10.0,
        "mode": "ask",
        "probe": "What candidate equations, mappings, or conservation relations connect the variables, and under what conditions do they hold?",
        "dependents": ["constraints", "objectives", "algorithm_implications", "validation_requirements"],
    },
    "constraints": {
        "priority": 9.5,
        "mode": "ask",
        "probe": "Which constraints are hard, which are soft, and what happens if each one is violated?",
        "dependents": ["algorithm_implications", "validation_requirements"],
    },
    "objectives": {
        "priority": 9.0,
        "mode": "ask",
        "probe": "What is the primary objective, what are secondary objectives, and what trade-off is acceptable?",
        "dependents": ["algorithm_implications", "validation_requirements"],
    },
    "data_support": {
        "priority": 6.0,
        "mode": "search",
        "probe": "Which facts, datasets, or parameter values are already supported by the statement or files, and what needs retrieval?",
        "dependents": ["variables", "relations", "constraints", "algorithm_implications", "validation_requirements"],
    },
    "uncertainty": {
        "priority": 4.0,
        "mode": "infer",
        "probe": "Which uncertainties materially change the model, and which are only sensitivity concerns?",
        "dependents": ["validation_requirements", "writing_claims"],
    },
    "algorithm_implications": {
        "priority": 8.5,
        "mode": "infer",
        "probe": "Given the current specification, what problem class and solver family fit best, and what pseudocode skeleton follows?",
        "dependents": ["validation_requirements", "writing_claims"],
    },
    "validation_requirements": {
        "priority": 8.0,
        "mode": "infer",
        "probe": "What unit, feasibility, boundary, and sensitivity checks are required before the model can be trusted?",
        "dependents": ["writing_claims"],
    },
    "writing_claims": {
        "priority": 2.0,
        "mode": "infer",
        "probe": "What is the paper-level claim, and what evidence is still needed to defend it?",
        "dependents": [],
    },
}


def _support_value(status: str) -> float:
    values = {
        "missing": 0.0,
        "partial": 0.45,
        "assumption_based": 0.8,
        "conflict": 0.0,
        "clear": 1.0,
    }
    return values.get(status, 0.0)


def feature_is_structural(field: str) -> bool:
    return field in {
        "problem_boundary",
        "variables",
        "time_structure",
        "space_structure",
        "relations",
        "constraints",
        "objectives",
        "data_support",
        "uncertainty",
        "algorithm_implications",
        "validation_requirements",
    }


def _entry_ready(field: str, entry: Dict[str, Any]) -> bool:
    if entry.get("status", "missing") != "clear":
        return False
    if not str(entry.get("summary", "")).strip() or not entry.get("items"):
        return False
    if not [value for value in entry.get("evidence", []) if str(value).strip()]:
        return False
    if [value for value in entry.get("open_questions", []) if str(value).strip()]:
        return False
    try:
        if float(entry.get("confidence", 0.0) or 0.0) < 0.75:
            return False
    except (TypeError, ValueError):
        return False
    if field == "data_support":
        if not any(
            isinstance(item, dict)
            and any(item.get(key) for key in ("path", "source", "source_path", "file", "dataset", "assumption"))
            for item in entry.get("items", [])
        ):
            return False
    return True


def _rounds_since_asked(state: Dict[str, Any], field: str) -> int:
    history = state.get("interview_history", [])
    for offset, item in enumerate(reversed(history), start=1):
        if item.get("target_field") == field:
            return offset
    return len(history) + 1


def rank_question_fields(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rankings = []
    table = state.get("feature_table", {})
    required = {name for name in QUESTION_FIELD_SPECS if feature_is_structural(name)}
    for field, spec in QUESTION_FIELD_SPECS.items():
        entry = table.get(field, {})
        status = entry.get("status", "missing")
        if _entry_ready(field, entry):
            continue
        effective_status = "partial" if status == "clear" else status
        support = _support_value(effective_status)
        unresolved = 1.0 - support
        if field in required:
            unresolved += 0.25
        downstream = sum(
            1
            for dep in spec.get("dependents", [])
            if table.get(dep, {}).get("status", "missing") != "clear"
        )
        recency = _rounds_since_asked(state, field)
        recency_factor = 1.0 + min(recency, 5) * 0.05
        confidence = entry.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence_factor = 1.0 - min(max(confidence, 0.0), 1.0) * 0.5
        score = (
            float(spec.get("priority", 1.0))
            * max(unresolved, 0.05)
            * (1.0 + downstream / max(len(QUESTION_FIELD_SPECS), 1))
            * recency_factor
            * confidence_factor
            * float(QUESTION_STATUS_WEIGHT.get(effective_status, 0.5))
        )
        rankings.append(
            {
                "field": field,
                "score": round(score, 3),
                "status": effective_status,
                "mode": spec.get("mode", "ask"),
                "probe": spec.get("probe", ""),
                "priority": spec.get("priority", 1.0),
                "downstream_blockers": downstream,
                "rounds_since_asked": recency,
                "confidence": round(confidence, 3),
            }
        )
    rankings.sort(key=lambda item: (-item["score"], item["field"]))
    return rankings


def pick_next_field(state: Dict[str, Any], preferred: str = "") -> str:
    rankings = rank_question_fields(state)
    if preferred:
        if any(item["field"] == preferred for item in rankings):
            return preferred
        if preferred in QUESTION_FIELD_SPECS:
            return preferred
    for item in rankings:
        if item["mode"] != "stop":
            return item["field"]
    return ""


def recompute_question_gate(state: Dict[str, Any]) -> None:
    rankings = rank_question_fields(state)
    required_fields = [name for name, spec in QUESTION_FIELD_SPECS.items() if feature_is_structural(name)]
    weighted_total = 0.0
    weighted_support = 0.0
    blockers = []

    for field in required_fields:
        entry = state.get("feature_table", {}).get(field, {})
        status = entry.get("status", "missing")
        support = _support_value(status)
        weight = float(QUESTION_FIELD_SPECS.get(field, {}).get("priority", 1.0))
        weighted_total += weight
        weighted_support += weight * support
        if status == "conflict":
            blockers.append(f"{field}: conflict")
        elif not _entry_ready(field, entry):
            blockers.append(f"{field}: {status}")

    support_score = round(weighted_support / max(weighted_total, 1e-6), 3)
    top_field = rankings[0]["field"] if rankings else ""
    top_score = rankings[0]["score"] if rankings else 0.0
    ready_for_modeling = (
        support_score >= 0.80
        and not any(item.endswith("conflict") for item in blockers)
        and not any(
            not _entry_ready(field, state.get("feature_table", {}).get(field, {}))
            for field in required_fields
        )
    )
    state["question_gate"] = {
        "support_score": support_score,
        "required_fields": required_fields,
        "ready_for_modeling": ready_for_modeling,
        "top_field": top_field,
        "top_score": round(top_score, 3),
        "blockers": blockers,
        "ranked_fields": rankings,
    }


def build_question_policy(state: Dict[str, Any], preferred: str = "") -> Dict[str, Any]:
    rankings = rank_question_fields(state)
    if preferred:
        top = next((item for item in rankings if item["field"] == preferred), None)
        if top is None:
            top = {
                "field": preferred,
                "score": 0.0,
                "status": state.get("feature_table", {}).get(preferred, {}).get("status", "missing"),
                "mode": QUESTION_FIELD_SPECS.get(preferred, {}).get("mode", "ask"),
                "probe": QUESTION_FIELD_SPECS.get(preferred, {}).get("probe", ""),
                "priority": QUESTION_FIELD_SPECS.get(preferred, {}).get("priority", 1.0),
                "downstream_blockers": 0,
                "rounds_since_asked": _rounds_since_asked(state, preferred),
                "confidence": 0.0,
            }
    else:
        top = rankings[0] if rankings else {
            "field": "",
            "score": 0.0,
            "status": "missing",
            "mode": "stop",
            "probe": "",
            "priority": 0.0,
            "downstream_blockers": 0,
            "rounds_since_asked": 0,
            "confidence": 0.0,
        }

    gate = state.get("question_gate", {})
    action = "stop" if gate.get("ready_for_modeling") else top.get("mode", "ask")
    if action not in {"stop", "ask", "search", "infer", "mixed"}:
        action = "ask"
    return {
        "action": action,
        "ready_for_modeling": bool(gate.get("ready_for_modeling", False)),
        "support_score": gate.get("support_score", 0.0),
        "top_field": top.get("field", ""),
        "top_score": top.get("score", 0.0),
        "recommended_probe": top.get("probe", ""),
        "recommended_mode": top.get("mode", "ask"),
        "ranked_fields": rankings[:5],
        "blockers": gate.get("blockers", []),
        "remaining_required": [
            field
            for field in gate.get("required_fields", [])
            if state.get("feature_table", {}).get(field, {}).get("status", "missing") != "clear"
        ],
    }
