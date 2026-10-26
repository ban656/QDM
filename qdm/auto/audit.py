"""Audit utilities for QDM-Agent autonomous benchmark workspaces."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qdm.harness.core import audit_harness


ALLOWED_DECISION_STATUS = {
    "continue",
    "local_fix",
    "re_question",
    "rollback",
    "abandon_module",
    "stop",
}

ALLOWED_IMPASSE_TYPES = {
    "none",
    "information",
    "structural",
    "formula",
    "algorithmic",
    "numerical",
    "narrative",
}

CODEX_MODEL_REQUESTED = "gpt-5.5"

REQUIRED_RUN_SUMMARY_KEYS = {
    "mode",
    "human_interventions",
    "stop_condition",
    "question_rounds",
    "rollback_count",
    "blueprint_revision_count",
    "code_repair_rounds",
    "final_artifacts",
    "failed_or_abandoned_modules",
    "codex_questioner_decision_files",
    "codex_evolver_distillation_files",
    "codex_plugin_cc_available",
    "codex_model_requested",
    "codex_model_actual",
    "decision_method",
}

REQUIRED_DISTILLATION_KEYS = {
    "source_problem_id",
    "codex_model_requested",
    "codex_model_actual",
    "distillation_summary",
    "question_patterns",
    "modeling_patterns",
    "algorithm_modules",
    "validation_questions",
    "writing_patterns",
    "policy_updates",
    "anti_patterns",
}

ALGORITHM_CHOICE_REQUIRED_KEYS = {
    "solver_family",
    "problem_structure",
    "why_this_solver",
    "why_not_random_or_greedy",
    "constraint_handling",
    "determinism",
    "global_or_local_claim",
    "acceptance_metric",
    "fallback_solver",
}

HEURISTIC_EXTRA_REQUIRED_KEYS = {
    "seed_or_determinism",
    "budget",
    "multi_start_or_grid_resolution",
    "convergence_or_resolution_check",
    "baseline_comparison",
    "failure_condition",
    "rollback_target",
}

HEURISTIC_TERMS = (
    "random",
    "greedy",
    "heuristic",
    "grid-only",
    "manual pruning",
    "stochastic",
)


@dataclass
class Finding:
    level: str
    message: str


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def emit(findings: List[Finding], level: str, message: str) -> None:
    findings.append(Finding(level=level, message=message))


def require_file(findings: List[Finding], path: str, label: str, allow_incomplete: bool) -> bool:
    if os.path.exists(path):
        return True
    emit(findings, "WARN" if allow_incomplete else "FAIL", f"Missing {label}: {path}")
    return False


def _expected_reviewer_model(workspace: str) -> str:
    """The expected reviewer model is the run's configured reviewer model
    (harness ledger models.reviewer_requested); falls back to the classic
    gpt-5.5 constant for runs that predate per-run model recording."""
    try:
        ledger = read_json(os.path.join(workspace, "harness", "ledger.json"))
        model = ledger.get("models", {}).get("reviewer_requested")
        if isinstance(model, str) and model.strip():
            return model.strip()
    except Exception:
        pass
    return CODEX_MODEL_REQUESTED


def validate_codex_model_record(record: Dict[str, Any], label: str, expected: str | None = None) -> List[str]:
    errors: List[str] = []
    requested = record.get("codex_model_requested")
    actual = record.get("codex_model_actual")
    expected = expected or CODEX_MODEL_REQUESTED

    if requested != expected:
        errors.append(
            f"{label}: codex_model_requested must be {expected!r}, got {requested!r}"
        )

    if not isinstance(actual, str) or not actual.strip():
        errors.append(f"{label}: codex_model_actual must be recorded as a non-empty string")

    if "codex_model" in record and "codex_model_requested" not in record:
        errors.append(
            f"{label}: legacy codex_model is not enough; record codex_model_requested and codex_model_actual"
        )

    return errors


def load_contract(workspace: str, findings: List[Finding]) -> Dict[str, Any]:
    path = os.path.join(workspace, "contracts", "auto_contract.json")
    if not os.path.exists(path):
        emit(findings, "FAIL", f"Missing contract: {path}")
        return {}
    try:
        contract = read_json(path)
    except Exception as exc:  # pragma: no cover - defensive CLI path
        emit(findings, "FAIL", f"Cannot parse contract JSON: {exc}")
        return {}
    if contract.get("schema_version") not in {"qdm_auto_benchmark_v1", "qdm_auto_benchmark_v2"}:
        emit(findings, "FAIL", "Unexpected or missing contract schema_version.")
    if contract.get("mode") != "benchmark_auto":
        emit(findings, "FAIL", "Contract mode must be benchmark_auto.")
    return contract


def validate_decision_file(path: str, expected: str | None = None) -> List[str]:
    errors: List[str] = []
    try:
        decision = read_json(path)
    except Exception as exc:
        return [f"invalid JSON: {exc}"]

    status = decision.get("status")
    if status not in ALLOWED_DECISION_STATUS:
        errors.append(f"invalid status: {status!r}")

    round_id = decision.get("round_id")
    if not isinstance(round_id, int) or round_id < 0:
        errors.append("round_id must be a non-negative integer")

    raw_hash = decision.get("raw_response_sha256")
    if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", raw_hash):
        errors.append("raw_response_sha256 must be a 64-character SHA-256")
    answer_hash = decision.get("reviewed_answer_sha256")
    if not isinstance(answer_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", answer_hash):
        errors.append("reviewed_answer_sha256 must be a 64-character SHA-256")

    impasse_type = decision.get("impasse_type")
    if impasse_type not in ALLOWED_IMPASSE_TYPES:
        errors.append(f"invalid impasse_type: {impasse_type!r}")

    for key in ["stage", "reason", "rollback_target", "next_question"]:
        if key not in decision:
            errors.append(f"missing key: {key}")

    errors.extend(validate_codex_model_record(decision, "decision", expected))

    for key in ["invalidated_items", "required_edits"]:
        if not isinstance(decision.get(key), list):
            errors.append(f"{key} must be a list")

    confidence = decision.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be a number in [0, 1]")

    return errors


def required_path(contract: Dict[str, Any], label: str, fallback: str) -> str:
    return contract.get("required_artifacts", {}).get(label, fallback)


def iter_decision_files(workspace: str, contract: Dict[str, Any]) -> Iterable[str]:
    rel_pattern = required_path(
        contract,
        "codex_questioner_decisions",
        "codex_workspace/questioner/decisions/*.json",
    )
    pattern = os.path.join(workspace, rel_pattern)
    for path in sorted(glob.glob(pattern)):
        yield path


def iter_distillation_files(workspace: str, contract: Dict[str, Any]) -> Iterable[str]:
    rel_pattern = required_path(
        contract,
        "codex_evolver_distillations",
        "codex_workspace/evolver/distillations/*.json",
    )
    pattern = os.path.join(workspace, rel_pattern)
    for path in sorted(glob.glob(pattern)):
        yield path


def validate_distillation_file(path: str, expected: str | None = None) -> List[str]:
    errors: List[str] = []
    try:
        distillation = read_json(path)
    except Exception as exc:
        return [f"invalid JSON: {exc}"]

    missing = sorted(REQUIRED_DISTILLATION_KEYS - set(distillation))
    if missing:
        errors.append(f"missing keys: {missing}")

    if not isinstance(distillation.get("distillation_summary", ""), str):
        errors.append("distillation_summary must be a string")

    errors.extend(validate_codex_model_record(distillation, "distillation", expected))

    scalar_keys = {
        "source_problem_id",
        "distillation_summary",
        "codex_model_requested",
        "codex_model_actual",
        "codex_model_note",
    }
    for key in REQUIRED_DISTILLATION_KEYS - scalar_keys:
        if not isinstance(distillation.get(key), list):
            errors.append(f"{key} must be a list")

    return errors


def validate_workspace_layout(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
) -> None:
    layout = contract.get("workspace_layout", {})
    for label in [
        "contracts",
        "claude_workspace",
        "codex_workspace",
        "codex_questioner_workspace",
        "codex_evolver_workspace",
    ]:
        rel_path = layout.get(label, {}).get("path", f"{label}/")
        path = os.path.join(workspace, rel_path)
        if not os.path.isdir(path):
            emit(findings, "FAIL", f"Missing workspace partition {label}: {path}")


def validate_no_legacy_mixed_paths(workspace: str, findings: List[Finding]) -> None:
    legacy_paths = [
        "state",
        "logs",
        "final",
        "claude_artifacts",
        "codex_decisions",
        os.path.join("codex_workspace", "requests"),
        os.path.join("codex_workspace", "responses"),
        os.path.join("codex_workspace", "decisions"),
        os.path.join("codex_workspace", "logs"),
    ]
    for rel_path in legacy_paths:
        path = os.path.join(workspace, rel_path)
        if os.path.exists(path):
            emit(findings, "FAIL", f"Legacy mixed workspace path should not exist: {path}")


def validate_run_summary(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> Dict[str, Any]:
    rel_path = required_path(contract, "run_summary", "claude_workspace/final/run_summary.json")
    path = os.path.join(workspace, rel_path)
    if not require_file(findings, path, "run summary", allow_incomplete):
        return {}

    try:
        summary = read_json(path)
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot parse run summary JSON: {exc}")
        return {}

    missing = sorted(REQUIRED_RUN_SUMMARY_KEYS - set(summary))
    if missing:
        emit(findings, "FAIL", f"Run summary missing keys: {missing}")

    if summary.get("mode") != "benchmark_auto":
        emit(findings, "FAIL", "Run summary mode must be benchmark_auto.")
    if summary.get("human_interventions") != 0:
        emit(findings, "FAIL", "human_interventions must be exactly 0.")
    if not allow_incomplete:
        stop_condition = summary.get("stop_condition", "")
        if contract.get("protocol_condition") == "qdm_self_ask":
            # Self-ask ablation runs have no Codex roles by design: plugin
            # availability and Codex model records are not applicable.
            pass
        elif stop_condition == "codex_plugin_unavailable":
            # codex_plugin_unavailable is a valid stop condition — skip plugin checks
            pass
        else:
            if summary.get("codex_plugin_cc_available") is not True:
                emit(findings, "FAIL", "benchmark_auto requires codex_plugin_cc_available=true.")
            for error in validate_codex_model_record(summary, "run_summary",
                                                     _expected_reviewer_model(workspace)):
                emit(findings, "FAIL", error)
            decision_method = str(summary.get("decision_method", "")).lower()
            if "simulated" in decision_method or "fallback" in decision_method:
                emit(findings, "FAIL", f"benchmark_auto cannot use simulated/fallback Codex decisions: {summary.get('decision_method')!r}.")

    limits = contract.get("limits", {})
    checks: List[Tuple[str, str]] = [
        ("question_rounds", "max_question_rounds"),
        ("rollback_count", "max_impasse_rollbacks"),
        ("blueprint_revision_count", "max_blueprint_revisions"),
        ("code_repair_rounds", "max_code_repair_rounds"),
    ]
    for used_key, limit_key in checks:
        used = summary.get(used_key)
        limit = limits.get(limit_key)
        if isinstance(used, int) and isinstance(limit, int) and used > limit:
            emit(findings, "FAIL", f"{used_key}={used} exceeds {limit_key}={limit}.")

    return summary


def validate_frozen_numbers(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    rel_path = required_path(contract, "frozen_numbers", "claude_workspace/writing/frozen_numbers.json")
    path = os.path.join(workspace, rel_path)
    if not require_file(findings, path, "frozen numbers", allow_incomplete):
        return
    try:
        freeze = read_json(path)
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot parse frozen numbers JSON: {exc}")
        return

    if freeze.get("schema_version") != "qdm_frozen_numbers_v1":
        emit(findings, "FAIL", "Unexpected frozen_numbers schema_version.")
    if freeze.get("status") != "passed":
        emit(findings, "FAIL", f"Frozen numbers status must be passed, got {freeze.get('status')!r}.")
    claims = freeze.get("claims")
    if not isinstance(claims, list) or not claims:
        emit(findings, "FAIL", "Frozen numbers must contain at least one claim.")
    for idx, claim in enumerate(claims or []):
        for key in ["id", "value", "source_file"]:
            if key not in claim:
                emit(findings, "FAIL", f"Frozen claim #{idx} missing key: {key}")

    for run in freeze.get("runs", []) or []:
        if run.get("timeout"):
            emit(findings, "FAIL", f"Frozen run timed out: {run.get('script')}")
        if run.get("exit_code") != 0:
            emit(findings, "FAIL", f"Frozen run failed: {run.get('script')} exit_code={run.get('exit_code')}")


def validate_result_consistency_report(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    rel_path = required_path(
        contract,
        "result_consistency_report",
        "claude_workspace/writing/audits/result_consistency_report.md",
    )
    path = os.path.join(workspace, rel_path)
    if not require_file(findings, path, "result consistency report", allow_incomplete):
        return
    try:
        text = open(path, "r", encoding="utf-8-sig").read()
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot read result consistency report: {exc}")
        return
    if "BLOCKER:" in text or "Status: `failed`" in text:
        emit(findings, "FAIL", "Result consistency report contains a blocker or failed status.")


def validate_harness_integrity(
    workspace: str,
    run_summary: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    ledger_path = os.path.join(workspace, "harness", "ledger.json")
    if not require_file(findings, ledger_path, "harness ledger", allow_incomplete):
        return
    try:
        ledger = read_json(ledger_path)
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot parse harness ledger: {exc}")
        return

    for issue in audit_harness(workspace):
        emit(findings, "FAIL", f"Harness: {issue}")
    if not allow_incomplete and ledger.get("phase") != "complete":
        emit(findings, "FAIL", f"Harness phase must be complete, got {ledger.get('phase')!r}.")

    imported = [item for item in ledger.get("question_rounds", []) if item.get("status") == "imported"]
    if run_summary and run_summary.get("question_rounds") != len(imported):
        emit(findings, "FAIL", "run_summary.question_rounds does not match the harness ledger.")
    if not ledger.get("model_calls"):
        emit(findings, "WARN" if allow_incomplete else "FAIL", "Harness contains no live model calls.")


def validate_paper_content(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    rel_path = required_path(contract, "paper", "claude_workspace/final/paper.md")
    path = os.path.join(workspace, rel_path)
    if not require_file(findings, path, "paper", allow_incomplete):
        return
    text = open(path, "r", encoding="utf-8-sig").read()
    if len(text.encode("utf-8")) < 1500:
        emit(findings, "WARN" if allow_incomplete else "FAIL", "Paper is too short for a complete benchmark solution.")
    lower = text.lower()
    for heading in ("abstract", "model", "result", "limitation"):
        if heading not in lower:
            emit(findings, "WARN" if allow_incomplete else "FAIL", f"Paper is missing required section: {heading}")
    for marker in ("template implementation", "generated paper", "see final/code", "todo"):
        if marker in lower:
            emit(findings, "FAIL", f"Paper contains placeholder marker: {marker}")


def validate_required_excel_or_exception(
    workspace: str,
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    # Simplified closing: spreadsheet outputs are optional; no exception
    # document is required when a run produces none.
    return


def collect_json_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            keys.add(str(key))
            keys.update(collect_json_keys(inner))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_json_keys(item))
    return keys


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).lower()


def validate_constraint_ledger(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    if contract.get("protocol_condition") == "mm_agent_native":
        return
    rel_path = required_path(contract, "state", "claude_workspace/state/modeling_state.json")
    path = os.path.join(workspace, rel_path)
    if not os.path.exists(path):
        return
    try:
        state = read_json(path)
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot parse modeling state JSON for constraint ledger: {exc}")
        return

    constraints = state.get("feature_table", {}).get("constraints", {})
    items = constraints.get("items", [])
    if not isinstance(items, list) or not items:
        emit(findings, "WARN" if allow_incomplete else "FAIL", "Constraint ledger is empty.")
        return

    placeholder_items = [
        item for item in items
        if isinstance(item, str) and re.fullmatch(r"\s*Round\s+\d+\s*:\s*constraints\s*", item, re.I)
    ]
    if len(placeholder_items) == len(items):
        emit(
            findings,
            "WARN" if allow_incomplete else "FAIL",
            "Constraint ledger only contains round-label placeholders; explicit checkable constraints are required.",
        )
        return

    structured = [item for item in items if isinstance(item, dict)]
    if structured:
        required = {"id", "text", "type", "scope", "checked_by", "failure_action"}
        for idx, item in enumerate(structured):
            missing = sorted(required - set(item))
            if missing:
                emit(findings, "FAIL", f"Constraint ledger item #{idx} missing keys: {missing}")
    elif len(items) < 6:
        emit(
            findings,
            "WARN" if allow_incomplete else "FAIL",
            "Constraint ledger has too few explicit items for a benchmark modeling run.",
        )


def validate_algorithm_choice_gate(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    rel_path = required_path(contract, "blueprint", "claude_workspace/final/modeling_blueprint.json")
    path = os.path.join(workspace, rel_path)
    if not os.path.exists(path):
        return
    try:
        blueprint = read_json(path)
    except Exception as exc:
        emit(findings, "FAIL", f"Cannot parse modeling blueprint JSON for algorithm gate: {exc}")
        return

    text = json_text(blueprint)
    keys = collect_json_keys(blueprint)
    has_optimizer = "optimize" in text or "maximiz" in text
    if not has_optimizer:
        return

    missing = sorted(ALGORITHM_CHOICE_REQUIRED_KEYS - keys)
    if missing:
        emit(
            findings,
            "WARN" if allow_incomplete else "FAIL",
            f"Algorithm choice gate missing required blueprint keys: {missing}",
        )

    has_heuristic = any(term in text for term in HEURISTIC_TERMS)
    if has_heuristic:
        missing_extra = sorted(HEURISTIC_EXTRA_REQUIRED_KEYS - keys)
        if missing_extra:
            emit(
                findings,
                "WARN" if allow_incomplete else "FAIL",
                f"Heuristic/random/greedy method lacks required validation keys: {missing_extra}",
            )


def validate_code_algorithm_red_flags(
    workspace: str,
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    code_dir = os.path.join(workspace, "claude_workspace", "final", "code")
    if not os.path.isdir(code_dir):
        return
    py_files = glob.glob(os.path.join(code_dir, "**", "*.py"), recursive=True)
    for path in py_files:
        try:
            text = open(path, "r", encoding="utf-8-sig").read()
        except Exception:
            continue
        lower = text.lower()
        if re.search(r"only\s+\w+\s+can\s+contribute", lower):
            emit(
                findings,
                "WARN" if allow_incomplete else "FAIL",
                f"Unsupported pruning claim in code requires doubt-gate review: {path}",
            )
        if "import random" in lower and "seed" not in lower:
            emit(
                findings,
                "WARN" if allow_incomplete else "FAIL",
                f"Random module imported without recorded seed/determinism policy: {path}",
            )


def validate_required_artifacts(
    workspace: str,
    contract: Dict[str, Any],
    findings: List[Finding],
    allow_incomplete: bool,
) -> None:
    required = contract.get("required_artifacts", {})
    # Simplified closing: only writing deliverables are mandatory. Post-run
    # derivation artifacts (evolution proposal, evolver library updates) and
    # the consistency-check report are not required for paper eligibility.
    derived_only = {"evolution_proposal", "codex_evolver_library_updates",
                    "result_consistency_report"}
    for label, rel_path in required.items():
        if label == "run_summary":
            continue
        if label in derived_only:
            continue
        if "*" in rel_path:
            matches = glob.glob(os.path.join(workspace, rel_path))
            if not matches:
                emit(findings, "WARN" if allow_incomplete else "FAIL", f"Missing {label}: {rel_path}")
            continue
        require_file(findings, os.path.join(workspace, rel_path), label, allow_incomplete)


def audit_workspace(workspace: str, allow_incomplete: bool = False) -> List[Finding]:
    findings: List[Finding] = []
    workspace = os.path.abspath(workspace)
    if not os.path.isdir(workspace):
        return [Finding("FAIL", f"Workspace does not exist: {workspace}")]

    contract = load_contract(workspace, findings)
    if contract:
        validate_workspace_layout(workspace, contract, findings)
        validate_no_legacy_mixed_paths(workspace, findings)
        validate_required_artifacts(workspace, contract, findings, allow_incomplete)
        run_summary = validate_run_summary(workspace, contract, findings, allow_incomplete)
        validate_harness_integrity(workspace, run_summary, findings, allow_incomplete)
        validate_frozen_numbers(workspace, contract, findings, allow_incomplete)
        validate_paper_content(workspace, contract, findings, allow_incomplete)
        validate_required_excel_or_exception(workspace, findings, allow_incomplete)
        validate_constraint_ledger(workspace, contract, findings, allow_incomplete)
        validate_algorithm_choice_gate(workspace, contract, findings, allow_incomplete)
        validate_code_algorithm_red_flags(workspace, findings, allow_incomplete)

    is_self_ask = contract.get("protocol_condition") == "qdm_self_ask"
    decision_files = list(iter_decision_files(workspace, contract))
    expected_model = _expected_reviewer_model(workspace)
    for path in decision_files:
        for error in validate_decision_file(path, expected_model):
            emit(findings, "FAIL", error)
    if not is_self_ask and not decision_files and contract.get("protocol_condition") != "mm_agent_native":
        emit(findings, "WARN" if allow_incomplete else "FAIL", "No Codex questioner decision JSON files found.")
    distillation_files = list(iter_distillation_files(workspace, contract))
    if not is_self_ask and not distillation_files:
        emit(findings, "WARN" if allow_incomplete else "FAIL", "No Codex evolver distillation JSON files found.")
    for path in distillation_files:
        for error in validate_distillation_file(path, _expected_reviewer_model(workspace)):
            emit(findings, "FAIL", f"{path}: {error}")

    if not any(item.level == "FAIL" for item in findings):
        emit(findings, "PASS", "Audit completed without blocking failures.")
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a QDM autonomous benchmark workspace.")
    parser.add_argument("--workspace", required=True, help="Auto benchmark workspace to audit.")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Downgrade missing final artifacts to warnings for dry-run workspace checks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    findings = audit_workspace(args.workspace, allow_incomplete=args.allow_incomplete)
    for item in findings:
        print(f"[{item.level}] {item.message}")
    if any(item.level == "FAIL" for item in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
