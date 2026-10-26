"""Low-freedom, evidence-preserving state machine for QDM benchmarks."""

from __future__ import annotations

import hashlib
import json
import os
import copy
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..protocol import (
    FEATURE_FIELDS,
    absorb_constraint_spec,
    import_answer,
    init_workspace,
    load_state,
    parse_json_object,
    save_state,
    write_codex_question,
    write_next_question,
)
from ..auto.contract import write_auto_workspace
from ..formalization import load_and_validate as load_and_validate_formalization
from ..formalization import template as formalization_template


SCHEMA_VERSION = "qdm_benchmark_harness_v2"
SUPPORTED_SCHEMA_VERSIONS = {"qdm_benchmark_harness_v1", SCHEMA_VERSION}
EVENT_SCHEMA_VERSION = "qdm_harness_event_v1"
PHASES = ["interview", "specification", "blueprint", "implementation", "execution", "writing", "complete", "stopped"]
CALL_ROLES = {"answerer", "reviewer", "evolver"}
CALL_STAGES = {
    "question_answer", "answer_review", "native_protocol", "constraint_spec", "blueprint_generation",
    "formalization_reporting", "blueprint_review", "implementation", "result_review",
    "paper_generation", "evolution", "question_generation",
}
CALL_ROLES.add("reporter")
ROLE_STAGES = {
    "answerer": {
        "question_answer", "native_protocol", "constraint_spec", "blueprint_generation",
        "implementation", "paper_generation",
    },
    "reviewer": {"answer_review", "blueprint_review", "result_review", "question_generation"},
    "reporter": {"formalization_reporting"},
    "evolver": {"evolution"},
}
REVIEW_TARGETS = {"blueprint_review": "blueprint", "result_review": "execution"}
DECISION_STATUSES = {"continue", "local_fix", "re_question", "rollback", "abandon_module", "stop"}
ARTIFACT_KINDS = {
    "protocol_trace", "constraint_spec", "formalization", "blueprint", "code",
    "execution", "results", "freeze", "paper", "run_summary", "evolution",
}
MIN_RAW_RESPONSE_BYTES = 80
EXPERIMENT_MODES = {"adaptive_questions", "one_shot"}
PROTOCOL_CONDITIONS = {
    "qdm_full", "mm_agent_native", "qdm_fixed_checklist",
    "qdm_no_closure", "qdm_no_traceability", "qdm_self_ask",
}
SELF_ASK_CONDITION = "qdm_self_ask"
"""Single-agent self-ask ablation: the answerer asks itself questions in its
own full context (no questioner, no prescribed question types, no context
isolation), fills all feature fields in one round, and self-declares the
decision. There is no answer/blueprint/result review and no evolution."""
TELEMETRY_STATUSES = {"verified", "partial", "unavailable"}


class HarnessError(RuntimeError):
    """Raised when a benchmark invariant would be violated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HarnessError(f"Invalid ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise HarnessError(f"Cannot hash missing path: {path}")
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        rel = child.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(child).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise HarnessError(f"Expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def output_root(output: str | Path) -> Path:
    return Path(output).resolve()


def harness_dir(output: str | Path) -> Path:
    return output_root(output) / "harness"


def ledger_path(output: str | Path) -> Path:
    return harness_dir(output) / "ledger.json"


def events_path(output: str | Path) -> Path:
    return harness_dir(output) / "events.jsonl"


def relative_inside(output: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(output).as_posix()
    except ValueError as exc:
        raise HarnessError(f"Benchmark artifact must stay inside output workspace: {resolved}") from exc


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def load_ledger(output: str | Path) -> Dict[str, Any]:
    path = ledger_path(output)
    if not path.is_file():
        raise HarnessError(f"Harness ledger does not exist: {path}")
    ledger = read_json(path)
    if ledger.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise HarnessError(f"Unexpected harness schema: {ledger.get('schema_version')!r}")
    return ledger


def save_ledger(output: str | Path, ledger: Dict[str, Any]) -> None:
    ledger["updated_at"] = utc_now()
    write_json_atomic(ledger_path(output), ledger)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def append_event(output: str | Path, ledger: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "sequence": int(ledger.get("event_count", 0)) + 1,
        "created_at": utc_now(),
        "event_type": event_type,
        "previous_hash": ledger.get("event_head", ""),
        "payload": payload,
    }
    event["event_hash"] = canonical_hash(event)
    path = events_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    ledger["event_count"] = event["sequence"]
    ledger["event_head"] = event["event_hash"]
    return event


def _asset_record(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise HarnessError(f"Declared data asset does not exist: {path}")
    return {
        "path": str(path.resolve()),
        "kind": "directory" if path.is_dir() else "file",
        "sha256": sha256_path(path),
        "bytes": path_size(path),
    }


def _sync_question_history(root: Path) -> None:
    state = load_state(str(root / "claude_workspace"))
    path = root / "claude_workspace" / "logs" / "question_history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in state.get("interview_history", []):
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def init_harness(
    output: str | Path,
    problem: str | Path,
    data_paths: Iterable[str | Path],
    no_data_reason: str,
    answer_model_requested: str,
    reviewer_model_requested: str,
    max_question_rounds: int = 20,
    experiment_mode: str = "adaptive_questions",
    protocol_condition: str = "qdm_full",
    seed: int = 0,
    max_total_agent_calls: int = 40,
    tool_policy: Optional[Dict[str, Any]] = None,
    reporter_model_requested: str = "",
) -> Dict[str, Any]:
    root = output_root(output)
    problem_path = Path(problem).resolve()
    if ledger_path(root).exists():
        raise HarnessError(f"Refusing to overwrite existing harness ledger: {ledger_path(root)}")
    if not problem_path.is_file():
        raise HarnessError(f"Problem file does not exist: {problem_path}")

    data = [_asset_record(Path(value).resolve()) for value in data_paths]
    if not data and not no_data_reason.strip():
        raise HarnessError("Declare at least one data path or provide --no-data-reason.")
    if not answer_model_requested.strip():
        raise HarnessError("An answerer requested model name is required.")
    is_self_ask = protocol_condition == SELF_ASK_CONDITION
    if not is_self_ask and not reviewer_model_requested.strip():
        raise HarnessError("Both answerer and reviewer requested model names are required.")
    if max_question_rounds < 1:
        raise HarnessError("max_question_rounds must be positive.")
    if experiment_mode not in EXPERIMENT_MODES:
        raise HarnessError(f"Invalid experiment mode: {experiment_mode}")
    if protocol_condition not in PROTOCOL_CONDITIONS:
        raise HarnessError(f"Invalid protocol condition: {protocol_condition}")
    if max_total_agent_calls < 1:
        raise HarnessError("max_total_agent_calls must be positive.")
    if is_self_ask:
        # Single-round all-fields ablation: exactly one self-ask elicitation,
        # no reviewer. The one_shot restrictions (one round, all required
        # fields updated, gate failure is terminal) implement this semantics.
        experiment_mode = "one_shot"
        max_question_rounds = 1
    elif experiment_mode == "one_shot":
        max_question_rounds = 1

    root.mkdir(parents=True, exist_ok=True)
    if not (root / "contracts" / "auto_contract.json").is_file():
        write_auto_workspace(
            str(problem_path), str(root), problem_path.stem,
            protocol_condition=protocol_condition,
        )
    claude_workspace = root / "claude_workspace"
    if not (claude_workspace / "state" / "modeling_state.json").exists():
        init_workspace(str(problem_path), str(claude_workspace), problem_path.stem)

    ledger: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": root.name,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "phase": "interview",
        "experiment_mode": experiment_mode,
        "protocol_condition": protocol_condition,
        "problem": {"path": str(problem_path), "sha256": sha256_file(problem_path)},
        "data_manifest": {"assets": data, "no_data_reason": no_data_reason.strip()},
        "models": {
            "answerer_requested": answer_model_requested.strip(),
            "reviewer_requested": reviewer_model_requested.strip(),
            "reporter_requested": (reporter_model_requested or reviewer_model_requested).strip(),
        },
        "capability_envelope": {
            "seed": int(seed),
            "tool_policy": tool_policy or {},
            "max_total_agent_calls": int(max_total_agent_calls),
        },
        "limits": {
            "max_question_rounds": int(max_question_rounds),
            "max_blueprint_revisions": 2,
            "max_code_repair_rounds": 3,
        },
        "pending_question": None,
        "question_rounds": [],
        "model_calls": [],
        "artifacts": {},
        "violations": [],
        "event_count": 0,
        "event_head": "",
    }
    append_event(root, ledger, "run_initialized", {
        "problem_sha256": ledger["problem"]["sha256"],
        "data_assets": data,
        "no_data_reason": no_data_reason.strip(),
        "experiment_mode": experiment_mode,
        "protocol_condition": protocol_condition,
        "capability_envelope": ledger["capability_envelope"],
    })
    save_ledger(root, ledger)
    return ledger


def _write_one_shot_prompt(root: Path, ledger: Dict[str, Any]) -> Path:
    state = load_state(str(root / "claude_workspace"))
    round_id = 1
    fields = {
        name: {
            "label": spec["label"],
            "required": spec["required"],
            "question": spec["question"],
            "expected": spec["expected"],
        }
        for name, spec in FEATURE_FIELDS.items()
    }
    prompt = f"""# QDM One-Shot Constraint Elicitation Ablation

This is the `one_shot` ablation. Transform the complete open problem into a
checkable modeling specification in one response. There will be no adaptive
follow-up question. Do not rely on prior benchmark outputs.

## Problem

{state['problem']['text']}

## Frozen Data Manifest

```json
{json.dumps(ledger.get('data_manifest', {}), ensure_ascii=False, indent=2)}
```

## Required Fields

```json
{json.dumps(fields, ensure_ascii=False, indent=2)}
```

Return only one valid JSON object with `round_id` equal to 1,
`target_field` equal to `problem_boundary`, and exactly one substantive
`feature_updates` entry for every field above. Each update must contain
`field`, `status`, `summary`, non-empty structured `items`, non-empty
traceable `evidence`, `open_questions`, and `confidence`. Use `clear` only
when confidence is at least 0.75 and no open question remains. Use
`assumption_based` when evidence is unavailable. Also include
`algorithm_modules`, `assumptions`, and `questions_for_codex`; the last list
must be empty because this ablation forbids follow-up elicitation.
"""
    path = root / "claude_workspace" / "codex_to_claude" / "round_001_one_shot.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    state.setdefault("interview_history", []).append({
        "round_id": round_id,
        "target_field": "problem_boundary",
        "question_mode": "one_shot",
        "prompt_path": str(path.resolve()),
        "status": "prompt_written",
        "created_at": utc_now(),
    })
    save_state(str(root / "claude_workspace"), state)
    return path


def _write_self_ask_prompt(root: Path, ledger: Dict[str, Any]) -> Path:
    """Write the single-round self-ask elicitation prompt (qdm_self_ask ablation).

    The answerer asks itself whatever clarifying questions it considers
    necessary — no prescribed question types, no context isolation: it sees
    its own full feature table — answers them itself, and fills every required
    field in one response. The decision is self-declared; there is no reviewer.
    """
    state = load_state(str(root / "claude_workspace"))
    round_id = 1
    fields = {
        name: {
            "label": spec["label"],
            "required": spec["required"],
            "question": spec["question"],
            "expected": spec["expected"],
        }
        for name, spec in FEATURE_FIELDS.items()
    }
    compact_table = {
        name: {
            "status": entry.get("status", "missing"),
            "summary": entry.get("summary", ""),
            "items": entry.get("items", [])[:5],
            "open_questions": entry.get("open_questions", []),
        }
        for name, entry in state.get("feature_table", {}).items()
    }
    prompt = f"""# QDM Self-Ask Ablation (protocol_condition: qdm_self_ask)

You are the only agent in this run: there is no external questioner, no
reviewer, and no follow-up round. Transform the complete open problem into a
checkable modeling specification in ONE response by asking yourself the
clarifying questions you consider necessary and answering them yourself.

- Ask freely: no prescribed question types, no required format. Ask anything
  that genuinely needs pinning down (boundaries, variables, time/space
  structure, relations, constraints, objectives, data support, uncertainty,
  algorithm implications, validation).
- You work in your own full context: the current feature table below is your
  own state. There is no separate questioner and no isolation.
- Do not rely on prior benchmark outputs.

## Problem

{state['problem']['text']}

## Frozen Data Manifest

```json
{json.dumps(ledger.get('data_manifest', {}), ensure_ascii=False, indent=2)}
```

## Your Current Feature Table

```json
{json.dumps(compact_table, ensure_ascii=False, indent=2)}
```

## Required Fields

```json
{json.dumps(fields, ensure_ascii=False, indent=2)}
```

## Answer Schema

Return only one valid JSON object with `round_id` equal to 1,
`target_field` equal to `problem_boundary`, and exactly one substantive
`feature_updates` entry for every field above. Each update must contain
`field`, `status`, `summary`, non-empty structured `items`, non-empty
traceable `evidence`, `open_questions`, and `confidence`. Use `clear` only
when confidence is at least 0.75 and no open question remains. Use
`assumption_based` when evidence is unavailable.

Additional fields:

- `self_asked_questions`: the list of questions you asked yourself, each
  `{{"question": "", "self_answer": "", "touched_fields": []}}`. This log is
  the ablation's measurement of your self-questioning.
- `self_declared_decision`: `{{"status": "continue | local_fix | re_question |
  rollback | abandon_module | stop", "reason": "", "impasse_type":
  "none | information | structural | formula | algorithmic | numerical |
  narrative", "confidence": 0.0, "self_declared": true}}`. Because there is no
  reviewer, you declare the decision yourself: `continue` only when the
  clarity gate and question gate would both pass (every required field clear,
  no blocker); any other status records this single-round ablation as an
  interview-gate failure.
- `questions_for_codex` must be empty: there is no external questioner to ask.

Also include `algorithm_modules` and `assumptions`.
"""
    path = root / "claude_workspace" / "codex_to_claude" / "round_001_self_ask.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")
    state.setdefault("interview_history", []).append({
        "round_id": round_id,
        "target_field": "problem_boundary",
        "question_mode": "self_ask",
        "prompt_path": str(path.resolve()),
        "status": "prompt_written",
        "created_at": utc_now(),
    })
    save_state(str(root / "claude_workspace"), state)
    return path


def issue_question(output: str | Path, field: str = "", question_file: str = "") -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") != "interview":
        raise HarnessError(f"Questions may only be issued during interview phase, got {ledger.get('phase')!r}.")
    if ledger.get("protocol_condition") == "mm_agent_native":
        raise HarnessError("mm_agent_native must use its native protocol; QDM issue-question is disabled.")
    if ledger.get("pending_question"):
        raise HarnessError("A question is already pending; ingest or reject it before issuing another.")
    used_rounds = len(ledger.get("question_rounds", []))
    if used_rounds >= int(ledger.get("limits", {}).get("max_question_rounds", 20)):
        raise HarnessError("Maximum question rounds reached before the clarity gate passed.")

    mode = ledger.get("experiment_mode", "adaptive_questions")
    if mode == "one_shot" and (used_rounds or ledger.get("model_calls")):
        raise HarnessError("The one_shot ablation permits exactly one elicitation round.")
    condition = ledger.get("protocol_condition", "qdm_full")
    if condition == SELF_ASK_CONDITION:
        if question_file:
            raise HarnessError("qdm_self_ask does not use Codex-authored questions.")
        prompt_path = _write_self_ask_prompt(root, ledger).resolve()
    elif question_file:
        # Protocol v3: the question text is authored by the Codex questioner.
        source = Path(question_file).resolve()
        if not source.is_file():
            raise HarnessError(f"Question file does not exist: {source}")
        if not field:
            raise HarnessError("A target_field is required when issuing a Codex-authored question.")
        state = load_state(str(root / "claude_workspace"))
        history = state.get("interview_history", [])
        round_id = max((int(item.get("round_id", 0)) for item in history), default=0) + 1
        prompt_path = Path(write_codex_question(
            str(root / "claude_workspace"), source.read_text(encoding="utf-8-sig"), field, round_id
        )).resolve()
    else:
        prompt_path = (
            _write_one_shot_prompt(root, ledger).resolve()
            if mode == "one_shot"
            else Path(write_next_question(str(root / "claude_workspace"), field)).resolve()
        )
    state = load_state(str(root / "claude_workspace"))
    history = state.get("interview_history", [])
    if not history:
        raise HarnessError("Protocol did not record the issued question.")
    item = history[-1]
    pending = {
        "round_id": int(item["round_id"]),
        "field": item["target_field"],
        "request_path": relative_inside(root, prompt_path),
        "request_sha256": sha256_file(prompt_path),
        "issued_at": utc_now(),
        "question_mode": mode,
    }
    ledger["pending_question"] = pending
    _sync_question_history(root)
    append_event(root, ledger, "question_issued", pending)
    save_ledger(root, ledger)
    return pending


def build_review_request(output: str | Path, stage: str, destination: str | Path) -> Dict[str, Any]:
    """Materialize a content-bearing, hash-bound reviewer request."""
    root = output_root(output)
    ledger = load_ledger(root)
    if stage not in REVIEW_TARGETS:
        raise HarnessError(f"Unsupported review stage: {stage}")
    reviewed_kind = REVIEW_TARGETS[stage]
    path = _latest_artifact(root, ledger, reviewed_kind)
    if path.is_dir():
        raise HarnessError(f"Review target must be a file: {path}")
    record = _artifact_records(ledger, reviewed_kind)[-1]
    attachments = [(reviewed_kind, path, record["sha256"])]
    if stage == "result_review":
        for kind in ("results", "freeze"):
            extra_path = _latest_artifact(root, ledger, kind)
            if extra_path.is_dir():
                raise HarnessError(f"Review target must be a file: {extra_path}")
            attachments.append((kind, extra_path, _artifact_records(ledger, kind)[-1]["sha256"]))
    rubric = (
        "Check completeness, internal consistency, requirement traceability, "
        "unsupported assumptions, validation adequacy, and evidence-to-claim fidelity."
    )
    blocks = ["QDM_REVIEW_PACKET_V2", f"# {stage}", "## Rubric", rubric]
    for kind, artifact, digest in attachments:
        blocks.extend([
            f"## Reviewed Artifact: {kind}",
            f"SHA-256: {digest}",
            "```text",
            artifact.read_text(encoding="utf-8-sig", errors="replace"),
            "```",
        ])
    blocks.extend([
        "## Required Response",
        "Return one JSON object with status, reviewed_artifact_sha256, issues, and "
        "all_issues_non_blocking. For result_review also return reviewed_results_sha256 "
        "and reviewed_freeze_sha256.",
        "status is 'approved' when the artifact may proceed as-is, or 'needs_revision' when "
        "issues require the solver to revise.",
        "all_issues_non_blocking is true only when EVERY listed issue is format, notation, "
        "documentation, engineering, or minor parameterization and NONE changes the modeling "
        "direction (equations, constraints, algorithm family, identifiability claims, or the "
        "accept/reject rule of a headline validation gate). When true, the reviewer's intent is "
        "approval-with-notes: the harness records the call with the issues preserved and the "
        "run proceeds without a revision round (PROTOCOL.md section 9 convergence policy).",
    ])
    target = Path(destination).resolve()
    relative_inside(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return {"path": relative_inside(root, target), "sha256": sha256_file(target), "stage": stage}


def _pre_solution_source(root: Path, ledger: Dict[str, Any]) -> tuple[str, Path, Dict[str, Any]]:
    kind = "protocol_trace" if ledger.get("protocol_condition") == "mm_agent_native" else "constraint_spec"
    path = _latest_artifact(root, ledger, kind)
    return kind, path, _artifact_records(ledger, kind)[-1]


def build_formalization_request(output: str | Path, destination: str | Path) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") != "specification":
        raise HarnessError("Formalization reporting requires specification phase.")
    kind, source, record = _pre_solution_source(root, ledger)
    request = (
        "FORMALIZATION_REPORT_PACKET_V2\n"
        "You are a neutral measurement reporter. Extract only information already explicit "
        "in the frozen pre-solution source. Do not add modeling decisions. Return only a JSON "
        "object matching the method-neutral template. This response will not be shown to the solver.\n\n"
        f"Source kind: {kind}\nSHA-256: {record['sha256']}\n\n"
        "## Frozen Pre-Solution Source\n```text\n"
        + source.read_text(encoding="utf-8-sig", errors="replace")
        + "\n```\n\n## P1 Template\n```json\n"
        + json.dumps(formalization_template(ledger.get("problem", {}).get("sha256", "")), ensure_ascii=False, indent=2)
        + "\n```\n"
    )
    target = Path(destination).resolve()
    relative_inside(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(request, encoding="utf-8")
    return {"path": relative_inside(root, target), "sha256": sha256_file(target), "stage": "formalization_reporting"}


def build_blueprint_request(output: str | Path, destination: str | Path) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") != "blueprint":
        raise HarnessError("Blueprint request requires blueprint phase.")
    kind, source, record = _pre_solution_source(root, ledger)
    formalization_record = _artifact_records(ledger, "formalization")[-1]
    request = (
        "BLUEPRINT_SOURCE_PACKET_V2\n"
        "Generate the modeling blueprint from the method's own frozen pre-solution source below. "
        "The neutral P1 reporting artifact is measurement-only and must not be read or cited.\n\n"
        f"Source kind: {kind}\nSHA-256: {record['sha256']}\n"
        f"Forbidden P1 SHA-256: {formalization_record['sha256']}\n\n"
        "## Frozen Native Source\n```text\n"
        + source.read_text(encoding="utf-8-sig", errors="replace")
        + "\n```\n"
    )
    target = Path(destination).resolve()
    relative_inside(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(request, encoding="utf-8")
    return {"path": relative_inside(root, target), "sha256": sha256_file(target), "stage": "blueprint_generation"}


def record_model_call(
    output: str | Path,
    role: str,
    stage: str,
    request: str | Path,
    response: str | Path,
    model_requested: str,
    model_actual: str,
    provider_call_id: str,
    started_at: str,
    finished_at: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    round_id: Optional[int] = None,
    telemetry_status: str = "verified",
    review_classification: str = "approved",
) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    approval_mode = ""
    if role not in CALL_ROLES:
        raise HarnessError(f"Invalid model-call role: {role}")
    if stage not in CALL_STAGES:
        raise HarnessError(f"Invalid model-call stage: {stage}")
    if stage not in ROLE_STAGES[role]:
        raise HarnessError(f"Role {role} is not allowed to perform stage {stage}.")
    stage_phases = {
        "question_answer": {"interview"}, "answer_review": {"interview"},
        "question_generation": {"interview"}, "native_protocol": {"interview"},
        "constraint_spec": {"specification"},
        "formalization_reporting": {"specification"},
        "blueprint_generation": {"blueprint"}, "blueprint_review": {"blueprint"},
        "implementation": {"implementation", "execution"},
        "result_review": {"execution"},
        "paper_generation": {"writing"}, "evolution": {"writing"},
    }
    allowed_phases = stage_phases[stage]
    if ledger.get("phase") not in allowed_phases:
        raise HarnessError(f"Model-call stage {stage} requires one of phases {sorted(allowed_phases)}.")
    if stage in {"question_answer", "answer_review"}:
        pending = ledger.get("pending_question")
        if not pending or round_id != int(pending.get("round_id", 0)):
            raise HarnessError("Question-stage calls must match the current pending round.")
    if stage == "native_protocol" and ledger.get("protocol_condition") != "mm_agent_native":
        raise HarnessError("native_protocol calls are only valid in mm_agent_native runs.")
    if review_classification not in {"approved", "non_blocking_only"}:
        raise HarnessError(f"Invalid review classification: {review_classification}")
    if telemetry_status not in TELEMETRY_STATUSES:
        raise HarnessError(f"Invalid telemetry status: {telemetry_status}")
    if telemetry_status == "verified" and not provider_call_id.strip():
        raise HarnessError("Verified telemetry requires a provider_call_id.")
    if not model_requested.strip() or not model_actual.strip():
        raise HarnessError("Requested and provider-reported actual model names are required.")
    if role == "reporter":
        configured_model = ledger.get("models", {}).get("reporter_requested")
    elif role in {"reviewer", "evolver"}:
        configured_model = ledger.get("models", {}).get("reviewer_requested")
    else:
        configured_model = ledger.get("models", {}).get("answerer_requested")
    # Protocol variant: the questioner may be implemented by a same-family
    # model as the answerer (homogeneous questioner). question_generation calls
    # may therefore legitimately request either the reviewer or the answerer
    # configured model; the actual model is recorded as reported.
    if stage == "question_generation":
        allowed_models = {
            ledger.get("models", {}).get("reviewer_requested"),
            ledger.get("models", {}).get("answerer_requested"),
        }
        if model_requested.strip() not in allowed_models:
            raise HarnessError(
                f"Requested model changed within the run: expected one of {sorted(allowed_models)!r}."
            )
    elif model_requested.strip() != configured_model:
        raise HarnessError(f"Requested model changed within the run: expected {configured_model!r}.")
    token_values = [input_tokens, output_tokens]
    if any(value is not None and value < 0 for value in token_values):
        raise HarnessError("Token counts cannot be negative.")
    if telemetry_status == "verified" and (
        input_tokens is None or output_tokens is None or input_tokens + output_tokens <= 0
    ):
        raise HarnessError("Verified telemetry requires non-zero token usage.")
    if parse_time(finished_at) < parse_time(started_at):
        raise HarnessError("Model call finished before it started.")
    call_limit = int(ledger.get("capability_envelope", {}).get("max_total_agent_calls", 40))
    if len(ledger.get("model_calls", [])) >= call_limit:
        raise HarnessError("Maximum total agent-call budget reached.")

    request_path = Path(request).resolve()
    response_path = Path(response).resolve()
    request_rel = relative_inside(root, request_path)
    response_rel = relative_inside(root, response_path)
    if not request_path.is_file() or not response_path.is_file():
        raise HarnessError("Model-call request and response must both be files.")
    if response_path.stat().st_size < MIN_RAW_RESPONSE_BYTES:
        raise HarnessError(f"Raw response is too small ({response_path.stat().st_size} bytes) to be credible.")

    request_text = request_path.read_text(encoding="utf-8-sig")
    if stage == "formalization_reporting" and ledger.get("schema_version") == SCHEMA_VERSION:
        source_kind, source_path, source_record = _pre_solution_source(root, ledger)
        if "FORMALIZATION_REPORT_PACKET_V2" not in request_text:
            raise HarnessError("formalization_reporting must use a harness-generated v2 packet.")
        if source_record["sha256"] not in request_text or source_path.read_text(
            encoding="utf-8-sig", errors="replace"
        ) not in request_text:
            raise HarnessError(f"formalization reporter request omits the frozen {source_kind} body.")
    if stage == "blueprint_generation" and ledger.get("schema_version") == SCHEMA_VERSION:
        source_kind, source_path, source_record = _pre_solution_source(root, ledger)
        if "BLUEPRINT_SOURCE_PACKET_V2" not in request_text:
            raise HarnessError("blueprint_generation must use a harness-generated v2 packet.")
        if source_record["sha256"] not in request_text or source_path.read_text(
            encoding="utf-8-sig", errors="replace"
        ) not in request_text:
            raise HarnessError(f"blueprint request omits the frozen {source_kind} body.")
        formalization_records = _artifact_records(ledger, "formalization")
        if formalization_records and formalization_records[-1]["sha256"] not in request_text:
            raise HarnessError("blueprint request must declare the forbidden measurement-only P1 hash.")

    reviewed_kind = REVIEW_TARGETS.get(stage)
    reviewed_record: Optional[Dict[str, Any]] = None
    if reviewed_kind:
        records = _artifact_records(ledger, reviewed_kind)
        if not records:
            raise HarnessError(f"{stage} requires a registered {reviewed_kind} artifact.")
        reviewed_record = records[-1]
        if review_classification == "non_blocking_only":
            # Review-convergence policy: a non_blocking_only review may bind to any registered
            # version of the artifact (its issues are preserved in the raw response and the
            # run's later registrations resolve them). Resolve the reviewed record from the
            # response's own binding so the chain, not only the latest version, is covered.
            response_text = response_path.read_text(encoding="utf-8-sig")
            claimed = parse_json_object(response_text).get("reviewed_artifact_sha256", "")
            matched = [r for r in records if r["sha256"] == claimed]
            if not matched:
                raise HarnessError(f"{stage} response binds to an unregistered artifact version.")
            reviewed_record = matched[-1]
        if reviewed_record["sha256"] not in request_text:
            raise HarnessError(
                f"{stage} request must contain the reviewed {reviewed_kind} SHA-256."
            )
        if ledger.get("schema_version") == SCHEMA_VERSION:
            reviewed_path = root / reviewed_record["path"]
            reviewed_text = reviewed_path.read_text(encoding="utf-8-sig", errors="replace")
            if "QDM_REVIEW_PACKET_V2" not in request_text or "## Rubric" not in request_text:
                raise HarnessError(f"{stage} must use a v2 content-bearing review packet.")
            if reviewed_text not in request_text:
                raise HarnessError(f"{stage} request does not contain the reviewed artifact body.")
        review = parse_json_object(response_path.read_text(encoding="utf-8-sig"))
        approval_mode = "approved"
        if review.get("status") == "approved":
            approval_mode = "approved"
        elif review.get("status") in {"needs_revision", "revise", "rejected"} and (
            review.get("all_issues_non_blocking") is True
            or review_classification == "non_blocking_only"
        ):
            # Review-convergence policy (PROTOCOL.md section 9): the solver independently grades
            # every reviewer opinion before acting. When every issue in a review is non-blocking
            # (format/notation/documentation/engineering, no change to equations, constraints,
            # algorithm family, identifiability claims, or headline validation-gate accept/reject
            # rules), the run proceeds without a revision round: the call is recorded as
            # approval_mode=non_blocking_only with the raw issues preserved. The reviewer may
            # declare all_issues_non_blocking=true itself, or the solver records its graded
            # classification (documented in the tradeoff ledger and a normalized decision file).
            # The solver never fabricates an approval the reviewer did not intend: this branch
            # records a proceed-on-non-blocking-review, never status "approved".
            approval_mode = "non_blocking_only"
        else:
            raise HarnessError(f"{stage} did not approve the reviewed artifact.")
        if review.get("reviewed_artifact_sha256") != reviewed_record["sha256"]:
            raise HarnessError(f"{stage} response is bound to a different artifact.")
        if not isinstance(review.get("issues"), list):
            raise HarnessError(f"{stage} response must contain an issues list.")
        if approval_mode == "non_blocking_only" and review.get("issues") == []:
            raise HarnessError(
                f"{stage} declares all issues non-blocking but lists none; use status approved."
            )
        if stage == "result_review":
            result_records = _artifact_records(ledger, "results")
            freeze_records = _artifact_records(ledger, "freeze")
            if not result_records or not freeze_records:
                raise HarnessError("result_review requires registered results and freeze artifacts.")
            result_hash = result_records[-1]["sha256"]
            freeze_hash = freeze_records[-1]["sha256"]
            if review_classification == "non_blocking_only":
                # Same chain-coverage rule as the blueprint case: resolve results/freeze from
                # the response's own binding, restricted to registered versions.
                claimed_results = review.get("reviewed_results_sha256", "")
                claimed_freeze = review.get("reviewed_freeze_sha256", "")
                matched_results = [r for r in result_records if r["sha256"] == claimed_results]
                matched_freeze = [r for r in freeze_records if r["sha256"] == claimed_freeze]
                if not matched_results or not matched_freeze:
                    raise HarnessError(
                        "result_review response binds to unregistered results or freeze versions."
                    )
                result_hash = matched_results[-1]["sha256"]
                freeze_hash = matched_freeze[-1]["sha256"]
            if result_hash not in request_text or freeze_hash not in request_text:
                raise HarnessError("result_review request must contain results and freeze SHA-256 values.")
            if ledger.get("schema_version") == SCHEMA_VERSION:
                for record in (
                    [r for r in result_records if r["sha256"] == result_hash][-1],
                    [r for r in freeze_records if r["sha256"] == freeze_hash][-1],
                ):
                    body = (root / record["path"]).read_text(encoding="utf-8-sig", errors="replace")
                    if body not in request_text:
                        raise HarnessError("result_review request omits a reviewed artifact body.")
            if review.get("reviewed_results_sha256") != result_hash:
                raise HarnessError("result_review response is bound to different results.")
            if review.get("reviewed_freeze_sha256") != freeze_hash:
                raise HarnessError("result_review response is bound to a different freeze artifact.")

    if provider_call_id and any(
        call.get("provider_call_id") == provider_call_id for call in ledger.get("model_calls", [])
    ):
        raise HarnessError(f"Duplicate provider_call_id: {provider_call_id}")
    call = {
        "call_id": f"call_{len(ledger.get('model_calls', [])) + 1:04d}",
        "role": role,
        "stage": stage,
        "round_id": round_id,
        "request_path": request_rel,
        "request_sha256": sha256_file(request_path),
        "response_path": response_rel,
        "response_sha256": sha256_file(response_path),
        "response_bytes": response_path.stat().st_size,
        "model_requested": model_requested.strip(),
        "model_actual": model_actual.strip(),
        "provider_call_id": provider_call_id.strip(),
        "started_at": started_at,
        "finished_at": finished_at,
        "telemetry_status": telemetry_status,
        "input_tokens": int(input_tokens) if input_tokens is not None else None,
        "output_tokens": int(output_tokens) if output_tokens is not None else None,
        "total_tokens": (
            int(input_tokens + output_tokens)
            if input_tokens is not None and output_tokens is not None else None
        ),
    }
    if reviewed_record:
        call["reviewed_artifact_kind"] = reviewed_kind
        call["reviewed_artifact_sha256"] = reviewed_record["sha256"]
        if stage == "result_review":
            call["reviewed_results_sha256"] = result_hash
            call["reviewed_freeze_sha256"] = freeze_hash
        if approval_mode:
            call["approval_mode"] = approval_mode
            if approval_mode == "non_blocking_only":
                call["review_classification"] = review_classification
    ledger.setdefault("model_calls", []).append(call)
    append_event(root, ledger, "model_call_recorded", call)
    save_ledger(root, ledger)
    return call


def _find_call(ledger: Dict[str, Any], call_id: str) -> Dict[str, Any]:
    for call in ledger.get("model_calls", []):
        if call.get("call_id") == call_id:
            return call
    raise HarnessError(f"Unknown model call: {call_id}")


def _reject_pending(root: Path, ledger: Dict[str, Any], decision: Dict[str, Any]) -> None:
    pending = ledger.get("pending_question") or {}
    ledger.setdefault("question_rounds", []).append({
        **pending,
        "status": "rejected",
        "decision_status": decision.get("status"),
        "reason": decision.get("reason", ""),
    })
    ledger["pending_question"] = None


def ingest_answer(
    output: str | Path,
    answer: str | Path,
    answer_call_id: str,
    decision: str | Path,
    review_call_id: str,
) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    pending = ledger.get("pending_question")
    if not pending:
        raise HarnessError("No pending question exists.")

    answer_path = Path(answer).resolve()
    decision_path = Path(decision).resolve()
    relative_inside(root, answer_path)
    relative_inside(root, decision_path)
    answer_call = _find_call(ledger, answer_call_id)
    review_call = _find_call(ledger, review_call_id)
    round_id = int(pending["round_id"])

    if answer_call.get("role") != "answerer" or answer_call.get("stage") != "question_answer":
        raise HarnessError("answer_call_id must identify an answerer question_answer call.")
    if answer_call.get("round_id") != round_id:
        raise HarnessError("Answer call round does not match the pending question.")
    if answer_call.get("request_sha256") != pending.get("request_sha256"):
        raise HarnessError("Answer call request does not match the issued question.")
    if answer_call.get("response_sha256") != sha256_file(answer_path):
        raise HarnessError("Answer file is not the recorded raw answerer response.")
    if review_call.get("role") != "reviewer" or review_call.get("stage") != "answer_review":
        raise HarnessError("review_call_id must identify a reviewer answer_review call.")
    if review_call.get("round_id") != round_id:
        raise HarnessError("Reviewer call round does not match the pending question.")
    review_request_path = root / str(review_call.get("request_path", ""))
    if answer_call.get("response_sha256") not in review_request_path.read_text(encoding="utf-8-sig"):
        raise HarnessError("Reviewer request is not bound to the answer SHA-256 it claims to review.")

    answer_data = parse_json_object(answer_path.read_text(encoding="utf-8-sig"))
    if int(answer_data.get("round_id", 0)) != round_id:
        raise HarnessError("Answer JSON round_id does not match the pending question.")
    if answer_data.get("target_field") != pending.get("field"):
        raise HarnessError("Answer JSON target_field does not match the issued question.")

    decision_data = read_json(decision_path)
    status = decision_data.get("status")
    if status not in DECISION_STATUSES:
        raise HarnessError(f"Invalid reviewer decision status: {status!r}")
    if int(decision_data.get("round_id", 0)) != round_id:
        raise HarnessError("Reviewer decision round_id does not match the pending question.")
    if decision_data.get("raw_response_sha256") != review_call.get("response_sha256"):
        raise HarnessError("Normalized decision is not linked to the recorded raw reviewer response.")
    if decision_data.get("reviewed_answer_sha256") != answer_call.get("response_sha256"):
        raise HarnessError("Normalized decision is not linked to the answer it reviewed.")
    if decision_data.get("codex_model_actual") != review_call.get("model_actual"):
        raise HarnessError("Reviewer decision model does not match the provider-reported call model.")
    if decision_data.get("codex_model_requested") != review_call.get("model_requested"):
        raise HarnessError("Reviewer decision requested model does not match the recorded call.")
    if decision_data.get("stage") != "answer_review":
        raise HarnessError("Question-round reviewer decision stage must be answer_review.")
    if decision_data.get("impasse_type") not in {
        "none", "information", "structural", "formula", "algorithmic", "numerical", "narrative"
    }:
        raise HarnessError("Reviewer decision has an invalid impasse_type.")
    for key in ("invalidated_items", "required_edits"):
        if not isinstance(decision_data.get(key), list):
            raise HarnessError(f"Reviewer decision {key} must be a list.")
    for key in ("reason", "rollback_target", "next_question"):
        if key not in decision_data:
            raise HarnessError(f"Reviewer decision is missing {key}.")
    confidence = decision_data.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise HarnessError("Reviewer decision confidence must be in [0, 1].")

    round_record = {
        **pending,
        "answer_call_id": answer_call_id,
        "review_call_id": review_call_id,
        "decision_path": relative_inside(root, decision_path),
        "decision_sha256": sha256_file(decision_path),
        "decision_status": status,
    }
    if status == "continue":
        import_answer(str(root / "claude_workspace"), str(answer_path), round_id)
        round_record["status"] = "imported"
        ledger.setdefault("question_rounds", []).append(round_record)
        ledger["pending_question"] = None
    elif status in {"local_fix", "re_question", "abandon_module"}:
        _reject_pending(root, ledger, decision_data)
    elif status == "rollback":
        state = load_state(str(root / "claude_workspace"))
        for field in decision_data.get("invalidated_items", []) or []:
            if field in state.get("feature_table", {}):
                state["feature_table"][field].update({
                    "status": "missing", "summary": "", "items": [], "evidence": [],
                    "open_questions": [f"Invalidated by reviewer in round {round_id}"], "confidence": 0.0,
                })
        save_state(str(root / "claude_workspace"), state)
        ledger["phase"] = "interview"
        _reject_pending(root, ledger, decision_data)
    else:
        ledger["phase"] = "stopped"
        _reject_pending(root, ledger, decision_data)

    _sync_question_history(root)
    append_event(root, ledger, "answer_decided", round_record)
    save_ledger(root, ledger)
    return round_record


def ingest_self_answer(
    output: str | Path,
    answer: str | Path,
    answer_call_id: str,
    decision: str | Path,
) -> Dict[str, Any]:
    """Import a qdm_self_ask round: the answerer's self-declared decision.

    Mirrors ingest_answer without any reviewer binding: the decision is a
    self-declared normalized decision authored by the answerer itself and
    bound to the answer's own response hash and model fields.
    """
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("protocol_condition") != SELF_ASK_CONDITION:
        raise HarnessError("ingest-self-answer is only valid for qdm_self_ask runs.")
    pending = ledger.get("pending_question")
    if not pending:
        raise HarnessError("No pending question exists.")

    answer_path = Path(answer).resolve()
    decision_path = Path(decision).resolve()
    relative_inside(root, answer_path)
    relative_inside(root, decision_path)
    answer_call = _find_call(ledger, answer_call_id)
    round_id = int(pending["round_id"])

    if answer_call.get("role") != "answerer" or answer_call.get("stage") != "question_answer":
        raise HarnessError("answer_call_id must identify an answerer question_answer call.")
    if answer_call.get("round_id") != round_id:
        raise HarnessError("Answer call round does not match the pending question.")
    if answer_call.get("request_sha256") != pending.get("request_sha256"):
        raise HarnessError("Answer call request does not match the issued question.")
    if answer_call.get("response_sha256") != sha256_file(answer_path):
        raise HarnessError("Answer file is not the recorded raw answerer response.")

    answer_data = parse_json_object(answer_path.read_text(encoding="utf-8-sig"))
    if int(answer_data.get("round_id", 0)) != round_id:
        raise HarnessError("Answer JSON round_id does not match the pending question.")
    if answer_data.get("target_field") != pending.get("field"):
        raise HarnessError("Answer JSON target_field does not match the issued question.")

    decision_data = read_json(decision_path)
    status = decision_data.get("status")
    if status not in DECISION_STATUSES:
        raise HarnessError(f"Invalid self-declared decision status: {status!r}")
    if decision_data.get("self_declared") is not True:
        raise HarnessError("Self-ask decision must declare self_declared=true.")
    if int(decision_data.get("round_id", 0)) != round_id:
        raise HarnessError("Self-declared decision round_id does not match the pending question.")
    if decision_data.get("stage") != "answer_review":
        raise HarnessError("Self-declared decision stage must be answer_review.")
    if decision_data.get("raw_response_sha256") != answer_call.get("response_sha256"):
        raise HarnessError("Self-declared decision is not bound to the recorded answer response.")
    if decision_data.get("reviewed_answer_sha256") != answer_call.get("response_sha256"):
        raise HarnessError("Self-declared decision is not linked to the answer it reviews.")
    if decision_data.get("answer_model_requested") != answer_call.get("model_requested"):
        raise HarnessError("Self-declared decision requested model does not match the answer call.")
    if decision_data.get("answer_model_actual") != answer_call.get("model_actual"):
        raise HarnessError("Self-declared decision model does not match the answer call.")
    if decision_data.get("impasse_type") not in {
        "none", "information", "structural", "formula", "algorithmic", "numerical", "narrative"
    }:
        raise HarnessError("Self-declared decision has an invalid impasse_type.")
    for key in ("invalidated_items", "required_edits"):
        if not isinstance(decision_data.get(key), list):
            raise HarnessError(f"Self-declared decision {key} must be a list.")
    for key in ("reason", "rollback_target", "next_question"):
        if key not in decision_data:
            raise HarnessError(f"Self-declared decision is missing {key}.")
    confidence = decision_data.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise HarnessError("Self-declared decision confidence must be in [0, 1].")

    round_record = {
        **pending,
        "answer_call_id": answer_call_id,
        "decision_path": relative_inside(root, decision_path),
        "decision_sha256": sha256_file(decision_path),
        "decision_status": status,
        "self_declared": True,
        "question_mode": "self_ask",
    }
    if status == "continue":
        import_answer(str(root / "claude_workspace"), str(answer_path), round_id)
        round_record["status"] = "imported"
        ledger.setdefault("question_rounds", []).append(round_record)
        ledger["pending_question"] = None
    elif status in {"local_fix", "re_question", "abandon_module"}:
        _reject_pending(root, ledger, decision_data)
    elif status == "rollback":
        state = load_state(str(root / "claude_workspace"))
        for field in decision_data.get("invalidated_items", []) or []:
            if field in state.get("feature_table", {}):
                state["feature_table"][field].update({
                    "status": "missing", "summary": "", "items": [], "evidence": [],
                    "open_questions": [f"Invalidated by self-declared decision in round {round_id}"],
                    "confidence": 0.0,
                })
        save_state(str(root / "claude_workspace"), state)
        ledger["phase"] = "interview"
        _reject_pending(root, ledger, decision_data)
    else:
        ledger["phase"] = "stopped"
        _reject_pending(root, ledger, decision_data)

    _sync_question_history(root)
    append_event(root, ledger, "answer_decided", round_record)
    save_ledger(root, ledger)
    return round_record


def _snapshot_registered_artifact(root: Path, kind: str, source: Path, ordinal: int) -> Path:
    """Copy an accepted artifact to append-only harness storage."""
    base = harness_dir(root) / "artifact_snapshots" / f"{kind}_{ordinal:04d}"
    if base.exists():
        raise HarnessError(f"Artifact snapshot already exists: {base}")
    if source.is_dir():
        shutil.copytree(source, base)
        return base
    base.mkdir(parents=True)
    target = base / source.name
    shutil.copy2(source, target)
    return target


def register_artifact(output: str | Path, kind: str, path: str | Path, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    if kind not in ARTIFACT_KINDS:
        raise HarnessError(f"Invalid artifact kind: {kind}")
    if kind == "run_summary":
        raise HarnessError("run_summary is generated internally when the run reaches complete.")
    artifact_phases = {
        "protocol_trace": {"interview"},
        "constraint_spec": {"specification"}, "blueprint": {"blueprint"},
        "formalization": {"specification"},
        "code": {"implementation", "execution"}, "execution": {"execution"},
        "results": {"execution"}, "freeze": {"execution", "writing", "complete"},
        "paper": {"writing"}, "evolution": {"writing"},
    }
    allowed_phases = artifact_phases[kind]
    if ledger.get("phase") not in allowed_phases:
        raise HarnessError(f"Artifact {kind} requires one of phases {sorted(allowed_phases)}.")
    existing_kind_records = ledger.get("artifacts", {}).get(kind, []) or []
    if kind == "blueprint" and existing_kind_records:
        limit = int(ledger.get("limits", {}).get("max_blueprint_revisions", 2))
        if len(existing_kind_records) - 1 >= limit:
            raise HarnessError("Maximum blueprint revision count reached.")
    if kind == "code" and ledger.get("phase") == "execution":
        limit = int(ledger.get("limits", {}).get("max_code_repair_rounds", 3))
        if max(0, len(existing_kind_records) - 1) >= limit:
            raise HarnessError("Maximum code repair round count reached.")
    artifact_path = Path(path).resolve()
    rel_path = relative_inside(root, artifact_path)
    if not artifact_path.exists():
        raise HarnessError(f"Artifact does not exist: {artifact_path}")
    metadata = metadata or {}
    generated_stages = {
        "constraint_spec": "constraint_spec",
        "formalization": "formalization_reporting",
        "blueprint": "blueprint_generation",
        "code": "implementation",
        "paper": "paper_generation",
        "evolution": "evolution",
    }
    expected_stage = generated_stages.get(kind)
    if expected_stage:
        source_call_id = str(metadata.get("source_call_id", ""))
        if not source_call_id:
            raise HarnessError(f"{kind} artifact requires metadata.source_call_id.")
        source_call = _find_call(ledger, source_call_id)
        if source_call.get("stage") != expected_stage:
            raise HarnessError(f"{kind} artifact source call must use stage {expected_stage}.")
        expected_role = (
            "evolver" if kind == "evolution"
            else "reporter" if kind == "formalization"
            else "answerer"
        )
        if source_call.get("role") != expected_role:
            raise HarnessError(f"{kind} artifact source call must use role {expected_role}.")
        if artifact_path.is_file():
            if sha256_file(artifact_path) != source_call.get("response_sha256"):
                raise HarnessError(
                    f"{kind} file must be the exact raw response recorded for its source call."
                )
        elif kind == "code":
            response_path = root / source_call["response_path"]
            envelope = parse_json_object(response_path.read_text(encoding="utf-8-sig"))
            declared_files = envelope.get("materialized_files")
            if not isinstance(declared_files, list) or not declared_files:
                raise HarnessError(
                    "A code directory requires a source response with a non-empty materialized_files manifest."
                )
            actual = {
                child.relative_to(artifact_path).as_posix(): sha256_file(child)
                for child in artifact_path.rglob("*") if child.is_file()
            }
            declared = {
                str(item.get("path", "")): str(item.get("sha256", ""))
                for item in declared_files if isinstance(item, dict)
            }
            if actual != declared:
                raise HarnessError("Code directory does not match the source response materialized_files manifest.")

    if kind == "protocol_trace":
        if not str(metadata.get("protocol_name", "")).strip():
            raise HarnessError("protocol_trace requires metadata.protocol_name.")
        if not str(metadata.get("capture_method", "")).strip():
            raise HarnessError("protocol_trace requires metadata.capture_method.")
        source_call_ids = metadata.get("source_call_ids")
        if not isinstance(source_call_ids, list) or not source_call_ids:
            raise HarnessError("protocol_trace requires non-empty metadata.source_call_ids.")
        for call_id in source_call_ids:
            call = _find_call(ledger, str(call_id))
            if call.get("stage") != "native_protocol" or call.get("role") != "answerer":
                raise HarnessError("protocol_trace source calls must be answerer native_protocol calls.")
    if kind == "formalization":
        package = load_and_validate_formalization(artifact_path, require_frozen=True)
        if package.get("problem_id") != ledger.get("problem", {}).get("sha256"):
            raise HarnessError("formalization.problem_id must equal the frozen problem SHA-256.")
        condition = ledger.get("protocol_condition", "qdm_full")
        source_kind = "protocol_trace" if condition == "mm_agent_native" else "constraint_spec"
        source_records = _artifact_records(ledger, source_kind)
        if not source_records:
            raise HarnessError(f"formalization requires a frozen {source_kind} source artifact.")
        if metadata.get("source_artifact_sha256") != source_records[-1].get("sha256"):
            raise HarnessError(f"formalization must bind to the latest {source_kind} SHA-256.")

    if kind == "results":
        execution_records = ledger.get("artifacts", {}).get("execution", []) or []
        if not execution_records:
            raise HarnessError("Results require a completed harness execution.")
        execution = read_json(root / execution_records[-1]["path"])
        output_hashes = {str(item.get("sha256", "")) for item in execution.get("outputs", [])}
        if sha256_path(artifact_path) not in output_hashes:
            raise HarnessError("Results must be an output produced by the latest harness execution.")
    if kind == "freeze":
        result_records = ledger.get("artifacts", {}).get("results", []) or []
        if not result_records:
            raise HarnessError("Frozen claims require registered execution results.")
        if metadata.get("source_results_sha256") != result_records[-1].get("sha256"):
            raise HarnessError("Freeze metadata must bind to the latest registered results SHA-256.")
        freeze = read_json(artifact_path)
        if freeze.get("status") != "passed" or not freeze.get("claims"):
            raise HarnessError("Freeze artifact must contain status=passed and non-empty claims.")

    record_path = artifact_path
    if kind == "code":
        snapshot_base = harness_dir(root) / "code_snapshots" / f"code_{len(existing_kind_records) + 1:04d}"
        if snapshot_base.exists():
            raise HarnessError(f"Code snapshot already exists: {snapshot_base}")
        source_rel = rel_path
        source_hash = sha256_path(artifact_path)
        if artifact_path.is_dir():
            shutil.copytree(artifact_path, snapshot_base)
            record_path = snapshot_base
        else:
            snapshot_base.mkdir(parents=True)
            record_path = snapshot_base / artifact_path.name
            shutil.copy2(artifact_path, record_path)
        metadata = {
            **metadata,
            "source_path": source_rel,
            "source_kind": "directory" if artifact_path.is_dir() else "file",
            "source_sha256_at_registration": source_hash,
        }
    else:
        metadata = {
            **metadata,
            "source_path": rel_path,
            "source_kind": "directory" if artifact_path.is_dir() else "file",
            "source_sha256_at_registration": sha256_path(artifact_path),
        }
        record_path = _snapshot_registered_artifact(
            root, kind, artifact_path, len(existing_kind_records) + 1
        )

    record = {
        "kind": kind,
        "path": relative_inside(root, record_path),
        "sha256": sha256_path(record_path),
        "bytes": path_size(record_path),
        "registered_at": utc_now(),
        "metadata": metadata,
    }
    if kind == "constraint_spec":
        state = copy.deepcopy(load_state(str(root / "claude_workspace")))
        absorb_constraint_spec(state, read_json(artifact_path))
        if not state.get("constraint_spec", {}).get("validation", {}).get("is_valid", False):
            raise HarnessError("Constraint specification failed structural validation.")
        save_state(str(root / "claude_workspace"), state)

    ledger.setdefault("artifacts", {}).setdefault(kind, []).append(record)

    append_event(root, ledger, "artifact_registered", record)
    save_ledger(root, ledger)
    return record


def _artifact_records(ledger: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return list(ledger.get("artifacts", {}).get(kind, []) or [])


def _latest_artifact(root: Path, ledger: Dict[str, Any], kind: str) -> Path:
    records = _artifact_records(ledger, kind)
    if not records:
        raise HarnessError(f"Missing required artifact: {kind}")
    path = root / records[-1]["path"]
    if not path.exists() or sha256_path(path) != records[-1]["sha256"]:
        raise HarnessError(f"Registered artifact changed after registration: {kind}")
    return path


def _interview_issues(root: Path, ledger: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    if ledger.get("pending_question"):
        issues.append("a question is still pending")
    if ledger.get("protocol_condition") == "mm_agent_native":
        if not _artifact_records(ledger, "protocol_trace"):
            issues.append("mm_agent_native requires a frozen native protocol trace")
        return issues
    state = load_state(str(root / "claude_workspace"))
    for name in ("clarity_gate", "question_gate"):
        gate = state.get(name, {})
        if not gate.get("ready_for_modeling", False):
            issues.append(f"{name} is not ready: {gate.get('blockers', [])}")
    imported = [item for item in ledger.get("question_rounds", []) if item.get("status") == "imported"]
    is_self_ask = ledger.get("protocol_condition") == SELF_ASK_CONDITION
    if not imported:
        issues.append(
            "no self-ask round was imported" if is_self_ask
            else "no independently reviewed question round was imported"
        )
    for item in imported:
        if is_self_ask:
            # qdm_self_ask rounds have no reviewer call by design.
            if not item.get("answer_call_id"):
                issues.append(f"round {item.get('round_id')} lacks answerer call provenance")
        elif not item.get("answer_call_id") or not item.get("review_call_id"):
            issues.append(f"round {item.get('round_id')} lacks answerer/reviewer call provenance")
    if ledger.get("experiment_mode") == "one_shot":
        if len(imported) != 1:
            issues.append("one_shot mode requires exactly one imported elicitation round")
        state_history = state.get("interview_history", [])
        changed = set(state_history[-1].get("changed_fields", [])) if state_history else set()
        required = {name for name, spec in FEATURE_FIELDS.items() if spec.get("required")}
        missing = sorted(required - changed)
        if missing:
            issues.append(f"one_shot answer did not update every required field: {missing}")
    return issues


def _validate_blueprint(root: Path, ledger: Dict[str, Any]) -> None:
    blueprint = read_json(_latest_artifact(root, ledger, "blueprint"))
    for key in ("variables", "constraints", "algorithm_plan", "validation_plan", "implementation_plan"):
        if not blueprint.get(key):
            raise HarnessError(f"Blueprint section is empty: {key}")
    if ledger.get("data_manifest", {}).get("assets") and not blueprint.get("data_structure"):
        raise HarnessError("Data-backed problem requires a non-empty blueprint data_structure.")


def _validate_execution(root: Path, ledger: Dict[str, Any]) -> None:
    execution = read_json(_latest_artifact(root, ledger, "execution"))
    if execution.get("status") != "passed" or execution.get("exit_code") != 0:
        raise HarnessError("Execution manifest must record status=passed and exit_code=0.")
    latest_code_hash = _artifact_records(ledger, "code")[-1]["sha256"]
    if execution.get("code_artifact_sha256") != latest_code_hash:
        raise HarnessError("Latest registered code was not the code used by the latest execution.")
    has_declared_data = bool(ledger.get("data_manifest", {}).get("assets"))
    if has_declared_data and execution.get("synthetic_data_used") is not False:
        raise HarnessError("A data-backed execution must record synthetic_data_used=false.")
    consumed = {(str(item.get("path")), str(item.get("sha256"))) for item in execution.get("consumed_inputs", [])}
    for asset in ledger.get("data_manifest", {}).get("assets", []):
        if (asset["path"], asset["sha256"]) not in consumed:
            raise HarnessError(f"Execution did not prove consumption of declared data asset: {asset['path']}")
    if has_declared_data and not execution.get("observed_data_reads"):
        raise HarnessError("Execution has no runtime-observed reads from the declared data.")
    if not execution.get("outputs"):
        raise HarnessError("Execution manifest contains no outputs.")


def _validate_paper(root: Path, ledger: Dict[str, Any]) -> None:
    paper_path = _latest_artifact(root, ledger, "paper")
    text = paper_path.read_text(encoding="utf-8-sig")
    if len(text.encode("utf-8")) < 1500:
        raise HarnessError("Paper is too short to be a complete benchmark solution.")
    lower = text.lower()
    for heading in ("abstract", "model", "result", "limitation"):
        if heading not in lower:
            raise HarnessError(f"Paper is missing a required section: {heading}")
    for marker in ("template implementation", "generated paper", "see final/code", "todo"):
        if marker in lower:
            raise HarnessError(f"Paper contains placeholder marker: {marker}")


def advance_phase(output: str | Path, target: str) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    current = ledger.get("phase")
    if current in {"complete", "stopped"}:
        raise HarnessError(f"Cannot advance terminal phase: {current}")
    try:
        expected = PHASES[PHASES.index(current) + 1]
    except (ValueError, IndexError) as exc:
        raise HarnessError(f"Invalid current phase: {current}") from exc
    if target != expected:
        raise HarnessError(f"Phase transition must be sequential: {current} -> {expected}, not {target}")

    if current == "interview":
        issues = _interview_issues(root, ledger)
        if issues:
            raise HarnessError("Interview gate failed: " + "; ".join(issues))
    elif current == "specification":
        condition = ledger.get("protocol_condition", "qdm_full")
        if condition != "mm_agent_native":
            spec_path = _latest_artifact(root, ledger, "constraint_spec")
            state = load_state(str(root / "claude_workspace"))
            if not state.get("constraint_spec", {}).get("validation", {}).get("is_valid", False):
                raise HarnessError(f"Constraint specification is not valid: {spec_path}")
        formalization_path = _latest_artifact(root, ledger, "formalization")
        try:
            load_and_validate_formalization(formalization_path, require_frozen=True)
        except ValueError as exc:
            raise HarnessError(str(exc)) from exc
    elif current == "blueprint":
        _validate_blueprint(root, ledger)
        blueprint_hash = _artifact_records(ledger, "blueprint")[-1]["sha256"]
        if ledger.get("protocol_condition") == SELF_ASK_CONDITION:
            pass  # qdm_self_ask ablation: no reviewer at any stage.
        else:
            # Review-convergence policy: an approved call must bind to the latest artifact; a
            # non_blocking_only call (reviewer gave no substantive/blocking opinion) covers the
            # chain regardless of version - the issues are preserved in the raw response and the
            # run proceeds without a revision round (PROTOCOL.md section 9).
            reviewer_calls = [
                call for call in ledger.get("model_calls", [])
                if call.get("stage") == "blueprint_review"
                and (
                    (call.get("approval_mode", "approved") == "approved"
                     and call.get("reviewed_artifact_sha256") == blueprint_hash)
                    or call.get("approval_mode") == "non_blocking_only"
                )
            ]
            if not reviewer_calls:
                raise HarnessError("Blueprint lacks an independent reviewer call.")
    elif current == "implementation":
        if not _artifact_records(ledger, "code"):
            raise HarnessError("No implementation code was registered.")
    elif current == "execution":
        _validate_execution(root, ledger)
        if not _artifact_records(ledger, "results") or not _artifact_records(ledger, "freeze"):
            raise HarnessError("Execution must produce registered results and frozen claims before writing.")
        if ledger.get("protocol_condition") == SELF_ASK_CONDITION:
            pass  # qdm_self_ask ablation: no reviewer at any stage.
        else:
            execution_hash = _artifact_records(ledger, "execution")[-1]["sha256"]
            latest_results_hash = _artifact_records(ledger, "results")[-1]["sha256"]
            latest_freeze_hash = _artifact_records(ledger, "freeze")[-1]["sha256"]
            # Review-convergence policy: approved calls must bind the latest execution/results/freeze;
            # non_blocking_only calls cover the chain with issues preserved (PROTOCOL.md section 9).
            reviewer_calls = [
                call for call in ledger.get("model_calls", [])
                if call.get("stage") == "result_review"
                and (
                    (call.get("approval_mode", "approved") == "approved"
                     and call.get("reviewed_artifact_sha256") == execution_hash
                     and call.get("reviewed_results_sha256") == latest_results_hash
                     and call.get("reviewed_freeze_sha256") == latest_freeze_hash)
                    or call.get("approval_mode") == "non_blocking_only"
                )
            ]
            if not reviewer_calls:
                raise HarnessError("Execution results lack an independent reviewer approval.")
    elif current == "writing":
        _validate_paper(root, ledger)
        if ledger.get("protocol_condition") != SELF_ASK_CONDITION:
            _latest_artifact(root, ledger, "evolution")

    ledger["phase"] = target
    if target == "complete":
        summary_path = root / "claude_workspace" / "final" / "run_summary.json"
        imported = [item for item in ledger.get("question_rounds", []) if item.get("status") == "imported"]
        calls = ledger.get("model_calls", [])
        reviewer_actual = sorted({str(call.get("model_actual")) for call in calls if call.get("role") == "reviewer"})
        summary = {
            "mode": "benchmark_auto",
            "experiment_mode": ledger.get("experiment_mode", "adaptive_questions"),
            "protocol_condition": ledger.get("protocol_condition", "qdm_full"),
            "human_interventions": 0,
            "stop_condition": "final_paper_generated",
            "question_rounds": len(imported),
            "rollback_count": sum(1 for item in ledger.get("question_rounds", []) if item.get("decision_status") == "rollback"),
            "blueprint_revision_count": max(0, len(_artifact_records(ledger, "blueprint")) - 1),
            "code_repair_rounds": max(0, len(_artifact_records(ledger, "code")) - 1),
            "execution_attempts": len(_artifact_records(ledger, "execution")),
            "failed_execution_attempts": sum(
                1 for record in _artifact_records(ledger, "execution")
                if read_json(root / record["path"]).get("status") != "passed"
            ),
            "final_artifacts": [
                record["path"] for records in ledger.get("artifacts", {}).values() for record in records
            ],
            "failed_or_abandoned_modules": [
                item.get("field") for item in ledger.get("question_rounds", [])
                if item.get("decision_status") == "abandon_module"
            ],
            "codex_questioner_decision_files": [item.get("decision_path") for item in imported],
            "codex_evolver_distillation_files": [
                record["path"] for record in _artifact_records(ledger, "evolution")
            ] if ledger.get("protocol_condition") != SELF_ASK_CONDITION else [],
            "codex_plugin_cc_available": ledger.get("protocol_condition") != SELF_ASK_CONDITION,
            "codex_model_requested": ledger.get("models", {}).get("reviewer_requested"),
            "codex_model_actual": " | ".join(reviewer_actual),
            "decision_method": (
                "qdm-benchmark-harness-self-ask"
                if ledger.get("protocol_condition") == SELF_ASK_CONDITION
                else "qdm-benchmark-harness"
            ),
            "writing_freeze_status": "passed" if _artifact_records(ledger, "freeze") else "failed",
            "llm_call_count": len(calls),
            "input_tokens": sum(int(call.get("input_tokens", 0) or 0) for call in calls),
            "output_tokens": sum(int(call.get("output_tokens", 0) or 0) for call in calls),
            "total_tokens": sum(int(call.get("total_tokens", 0) or 0) for call in calls),
            "telemetry_verified_calls": sum(
                1 for call in calls if call.get("telemetry_status", "verified") == "verified"
            ),
            "telemetry_partial_calls": sum(
                1 for call in calls if call.get("telemetry_status") == "partial"
            ),
            "telemetry_unavailable_calls": sum(
                1 for call in calls if call.get("telemetry_status") == "unavailable"
            ),
            "paper_eligible": False,
            "eligibility_status": "pending_repository_audit",
            "harness_precompletion_event_head": ledger.get("event_head"),
        }
        write_json_atomic(summary_path, summary)
        record = {
            "kind": "run_summary",
            "path": relative_inside(root, summary_path),
            "sha256": sha256_file(summary_path),
            "bytes": summary_path.stat().st_size,
            "registered_at": utc_now(),
            "metadata": {"generated_by": SCHEMA_VERSION},
        }
        ledger.setdefault("artifacts", {}).setdefault("run_summary", []).append(record)
        append_event(root, ledger, "artifact_registered", record)
    append_event(root, ledger, "phase_advanced", {"from": current, "to": target})
    save_ledger(root, ledger)
    return ledger


def stop_run(output: str | Path, reason: str, category: str) -> Dict[str, Any]:
    """Freeze an unsuccessful terminal outcome without erasing partial artifacts."""
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") in {"complete", "stopped"}:
        raise HarnessError(f"Run is already terminal: {ledger.get('phase')}")
    if not reason.strip():
        raise HarnessError("A substantive stop reason is required.")
    allowed = {
        "budget_exhausted", "protocol_failure", "model_failure", "tool_failure",
        "implementation_failure", "execution_failure", "integrity_failure",
    }
    if category not in allowed:
        raise HarnessError(f"Invalid stop category: {category}")
    previous = str(ledger.get("phase"))
    ledger["phase"] = "stopped"
    ledger["terminal_outcome"] = {
        "status": "failed",
        "category": category,
        "reason": reason.strip(),
        "stopped_from_phase": previous,
        "stopped_at": utc_now(),
    }
    append_event(root, ledger, "run_stopped", {
        "from": previous, "category": category, "reason": reason.strip(),
    })
    save_ledger(root, ledger)
    return ledger["terminal_outcome"]


def seal_eligibility(output: str | Path) -> Dict[str, Any]:
    """Seal eligibility only after both harness and repository audits pass."""
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") != "complete":
        raise HarnessError("Only a complete run can be sealed as paper-eligible.")
    issues = audit_harness(root)
    if issues:
        raise HarnessError("Harness audit failed: " + "; ".join(issues))

    project_root = Path(__file__).resolve().parents[2]
    audit_script = project_root / "qdm" / "auto" / "audit.py"
    proc = subprocess.run(
        [sys.executable, str(audit_script), "--workspace", str(root)],
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise HarnessError("Repository audit failed: " + (proc.stdout + proc.stderr)[-2000:])

    summary_path = _latest_artifact(root, ledger, "run_summary")
    summary = read_json(summary_path)
    if summary.get("paper_eligible") is True or summary.get("eligibility_status") == "sealed":
        raise HarnessError("Run summary is already sealed.")
    summary["paper_eligible"] = True
    summary["eligibility_status"] = "sealed"
    summary["eligibility_sealed_at"] = utc_now()
    write_json_atomic(summary_path, summary)
    record = _artifact_records(ledger, "run_summary")[-1]
    record["sha256"] = sha256_file(summary_path)
    record["bytes"] = summary_path.stat().st_size
    record["metadata"]["sealed_after_repository_audit"] = True
    append_event(root, ledger, "eligibility_sealed", {
        "run_summary": record["path"],
        "run_summary_sha256": record["sha256"],
    })
    save_ledger(root, ledger)
    return summary


def run_code(
    output: str | Path,
    script: str | Path,
    inputs: Iterable[str | Path],
    timeout: int,
) -> Dict[str, Any]:
    root = output_root(output)
    ledger = load_ledger(root)
    if ledger.get("phase") != "execution":
        raise HarnessError("Code may only be run in the execution phase.")
    requested_script_path = Path(script).resolve()
    relative_inside(root, requested_script_path)
    code_records = _artifact_records(ledger, "code")
    if not code_records:
        raise HarnessError("Register implementation code before executing it.")
    registered_code = root / code_records[-1]["path"]
    if sha256_path(registered_code) != code_records[-1]["sha256"]:
        raise HarnessError("Registered implementation code changed before execution.")
    source_value = code_records[-1].get("metadata", {}).get("source_path")
    source_code = root / source_value if source_value else registered_code
    source_is_dir = code_records[-1].get("metadata", {}).get("source_kind") == "directory"
    if not source_value:
        source_is_dir = source_code.is_dir()
    execution_cwd = source_code if source_is_dir else source_code.parent
    if _is_relative_to(requested_script_path, source_code if source_is_dir else source_code.parent):
        if not source_is_dir:
            if requested_script_path != source_code:
                raise HarnessError("Execution script does not match the registered code source file.")
            script_path = registered_code
        else:
            script_path = registered_code / requested_script_path.relative_to(source_code)
    else:
        script_path = requested_script_path
    try:
        script_path.relative_to(registered_code if registered_code.is_dir() else registered_code.parent)
    except ValueError as exc:
        raise HarnessError("Execution script is outside the latest registered code snapshot.") from exc
    if registered_code.is_file() and script_path != registered_code:
        raise HarnessError("Execution script does not match the registered code snapshot file.")
    if not script_path.is_file():
        raise HarnessError(f"Execution script is missing from the registered snapshot: {script_path}")
    declared = {(item["path"], item["sha256"]) for item in ledger.get("data_manifest", {}).get("assets", [])}
    consumed = [_asset_record(Path(value).resolve()) for value in inputs]
    for item in consumed:
        if (item["path"], item["sha256"]) not in declared:
            raise HarnessError(f"Input is not in the frozen data manifest: {item['path']}")

    execution_number = len(_artifact_records(ledger, "execution")) + 1
    logs = harness_dir(root) / "execution" / f"run_{execution_number:04d}"
    logs.mkdir(parents=True, exist_ok=True)
    trace_path = logs / "file_reads.jsonl"
    runtime_path = Path(__file__).resolve().parent / "trace_runtime"
    inherited_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = str(runtime_path) + (os.pathsep + inherited_pythonpath if inherited_pythonpath else "")
    started = utc_now()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(execution_cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONPATH": pythonpath,
                "QDM_DATA_MANIFEST": json.dumps(consumed, ensure_ascii=False),
                "QDM_FILE_TRACE": str(trace_path),
            },
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        proc = None
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    else:
        stdout = proc.stdout
        stderr = proc.stderr
    finished = utc_now()
    stdout_path = logs / "stdout.txt"
    stderr_path = logs / "stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    exit_code = None if timed_out else proc.returncode
    provenance_error = ""
    synthetic_data_used: Optional[bool] = None
    reported_consumed = []
    try:
        result_payload = parse_json_object(stdout)
        provenance = result_payload.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        synthetic_data_used = provenance.get("synthetic_data_used")
        reported_consumed = provenance.get("consumed_inputs", []) or []
    except Exception as exc:
        result_payload = {}
        provenance_error = f"stdout does not contain parseable result provenance: {exc}"

    observed_paths: set[str] = set()
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                traced = json.loads(line)
                observed_paths.add(str(Path(traced["path"]).resolve()))
            except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError):
                continue
    observed_reads: List[Dict[str, Any]] = []
    for traced_path in sorted(observed_paths):
        path = Path(traced_path)
        if path.is_file():
            for asset in consumed:
                asset_path = Path(asset["path"])
                matched = path == asset_path
                if asset_path.is_dir():
                    try:
                        path.relative_to(asset_path)
                        matched = True
                    except ValueError:
                        matched = False
                if matched:
                    observed_reads.append({"path": traced_path, "sha256": sha256_file(path)})
                    break

    if declared:
        expected_pairs = {(item["path"], item["sha256"]) for item in consumed}
        reported_pairs = {
            (str(item.get("path")), str(item.get("sha256")))
            for item in reported_consumed if isinstance(item, dict)
        }
        if synthetic_data_used is not False:
            provenance_error = provenance_error or "data-backed result must report synthetic_data_used=false"
        elif expected_pairs != reported_pairs:
            provenance_error = provenance_error or "reported consumed_inputs do not match the frozen execution inputs"
        for asset in consumed:
            asset_path = Path(asset["path"])
            was_read = any(
                Path(item["path"]) == asset_path
                or (asset_path.is_dir() and _is_relative_to(Path(item["path"]), asset_path))
                for item in observed_reads
            )
            if not was_read:
                provenance_error = provenance_error or f"no runtime read observed for declared input: {asset['path']}"
    elif synthetic_data_used is None:
        provenance_error = provenance_error or "result must explicitly report provenance.synthetic_data_used"

    if not isinstance(result_payload.get("results"), dict) or not result_payload.get("results"):
        provenance_error = provenance_error or "result payload must contain a non-empty results object"

    result_payload_path = logs / "result_payload.json"
    if result_payload:
        write_json_atomic(result_payload_path, result_payload)
    produced_outputs: List[Dict[str, Any]] = []
    for item in result_payload.get("artifacts", []) if isinstance(result_payload, dict) else []:
        if not isinstance(item, dict) or not item.get("path"):
            provenance_error = provenance_error or "result artifacts must contain paths"
            continue
        produced_path = Path(str(item["path"]))
        if not produced_path.is_absolute():
            produced_path = execution_cwd / produced_path
        try:
            produced_rel = relative_inside(root, produced_path)
        except HarnessError as exc:
            provenance_error = provenance_error or str(exc)
            continue
        if not produced_path.exists():
            provenance_error = provenance_error or f"reported output does not exist: {produced_path}"
            continue
        produced_hash = sha256_path(produced_path)
        if not item.get("sha256"):
            provenance_error = provenance_error or f"reported output lacks SHA-256: {produced_path}"
            continue
        if item.get("sha256") != produced_hash:
            provenance_error = provenance_error or f"reported output hash mismatch: {produced_path}"
            continue
        produced_outputs.append({"path": produced_rel, "sha256": produced_hash})

    execution_passed = exit_code == 0 and not provenance_error
    manifest = {
        "schema_version": "qdm_execution_manifest_v1",
        "status": "passed" if execution_passed else "failed",
        "script": relative_inside(root, script_path),
        "source_script": relative_inside(root, requested_script_path),
        "script_sha256": sha256_file(script_path),
        "code_artifact_sha256": code_records[-1]["sha256"],
        "started_at": started,
        "finished_at": finished,
        "exit_code": exit_code,
        "timeout": timed_out,
        "synthetic_data_used": synthetic_data_used,
        "consumed_inputs": consumed,
        "reported_consumed_inputs": reported_consumed,
        "observed_data_reads": observed_reads,
        "provenance_error": provenance_error,
        "outputs": [
            {"path": relative_inside(root, stdout_path), "sha256": sha256_file(stdout_path)},
            {"path": relative_inside(root, stderr_path), "sha256": sha256_file(stderr_path)},
            *([{"path": relative_inside(root, result_payload_path), "sha256": sha256_file(result_payload_path)}]
              if result_payload_path.is_file() else []),
            *produced_outputs,
        ],
    }
    manifest_path = logs / "execution_manifest.json"
    write_json_atomic(manifest_path, manifest)
    register_artifact(root, "execution", manifest_path)
    if not execution_passed:
        raise HarnessError(f"Execution failed harness validation: {provenance_error or f'exit_code={exit_code}'}")
    return manifest


def audit_harness(output: str | Path) -> List[str]:
    root = output_root(output)
    issues: List[str] = []
    try:
        ledger = load_ledger(root)
    except Exception as exc:
        return [str(exc)]

    previous = ""
    count = 0
    events: List[Dict[str, Any]] = []
    path = events_path(root)
    if not path.is_file():
        issues.append("missing harness/events.jsonl")
    else:
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(f"event line {line_number} is invalid JSON: {exc}")
                continue
            if event.get("schema_version") != EVENT_SCHEMA_VERSION:
                issues.append(f"event line {line_number} has an invalid schema version")
            if event.get("sequence") != line_number:
                issues.append(f"event line {line_number} has an invalid sequence number")
            claimed = event.pop("event_hash", "")
            if event.get("previous_hash") != previous:
                issues.append(f"event line {line_number} breaks the hash chain")
            actual = canonical_hash(event)
            if claimed != actual:
                issues.append(f"event line {line_number} hash mismatch")
            previous = claimed
            count += 1
            events.append({**event, "event_hash": claimed})
    if count != ledger.get("event_count") or previous != ledger.get("event_head"):
        issues.append("ledger event head/count does not match events.jsonl")

    phase = "interview"
    for event in events:
        payload = event.get("payload", {})
        if event.get("event_type") == "phase_reverted":
            # A controlled revert (e.g., paper revision) resets the tracked
            # phase; subsequent phase_advanced events resume from it.
            phase = str(payload.get("to", phase))
            continue
        if event.get("event_type") != "phase_advanced":
            continue
        try:
            expected = PHASES[PHASES.index(phase) + 1]
        except (ValueError, IndexError):
            expected = ""
        if payload.get("from") != phase or payload.get("to") != expected:
            issues.append(
                f"invalid phase event {payload.get('from')} -> {payload.get('to')}; "
                f"expected {phase} -> {expected}"
            )
            phase = str(payload.get("to", phase))
        else:
            phase = expected
    if ledger.get("phase") == "complete" and phase != "complete":
        issues.append("ledger says complete but the event chain does not contain all sequential phase transitions")

    problem_path = Path(str(ledger.get("problem", {}).get("path", "")))
    if not problem_path.is_file() or sha256_file(problem_path) != ledger.get("problem", {}).get("sha256"):
        issues.append("frozen problem file is missing or changed")
    for asset in ledger.get("data_manifest", {}).get("assets", []):
        asset_path = Path(str(asset.get("path", "")))
        if not asset_path.exists() or sha256_path(asset_path) != asset.get("sha256"):
            issues.append(f"frozen data asset is missing or changed: {asset.get('path')}")

    event_calls = [event.get("payload") for event in events if event.get("event_type") == "model_call_recorded"]
    if len(event_calls) != len(ledger.get("model_calls", [])):
        issues.append("ledger model-call count does not match model-call events")
    else:
        for call, event_call in zip(ledger.get("model_calls", []), event_calls):
            if canonical_hash(call) != canonical_hash(event_call):
                issues.append(f"model call {call.get('call_id')} differs from its immutable event")

    event_artifacts = [event.get("payload") for event in events if event.get("event_type") == "artifact_registered"]
    sealed_hashes = {
        event.get("payload", {}).get("run_summary_sha256")
        for event in events if event.get("event_type") == "eligibility_sealed"
    }
    ledger_artifacts = [
        record for records in ledger.get("artifacts", {}).values() for record in records
    ]
    if len(event_artifacts) != len(ledger_artifacts):
        issues.append("ledger artifact count does not match artifact registration events")
    for record in ledger_artifacts:
        candidates = [
            item for item in event_artifacts
            if item.get("kind") == record.get("kind") and item.get("path") == record.get("path")
        ]
        if not candidates:
            issues.append(f"registered artifact lacks an immutable event: {record.get('path')}")
        elif canonical_hash(record) != canonical_hash(candidates[-1]):
            is_sealed_summary = (
                record.get("kind") == "run_summary" and record.get("sha256") in sealed_hashes
            )
            if not is_sealed_summary:
                issues.append(f"registered artifact differs from its immutable event: {record.get('path')}")

    provider_ids = set()
    # Living-path exemption: request/response paths bound to more than one
    # model call are living documents updated by the run's own workflow
    # (review-contract documents, rebuilt manifests, revised artifact source
    # files). For these paths the final file content is authoritative — the
    # audit detects out-of-run tampering, not in-run document updates. Paths
    # bound to a single call must still match their recorded hash exactly.
    path_usage: Dict[str, int] = {}
    for event_call in event_calls:
        for key in ("request_path", "response_path"):
            path_value = str(event_call.get(key, ""))
            if path_value:
                path_usage[path_value] = path_usage.get(path_value, 0) + 1
    for call in ledger.get("model_calls", []):
        provider_id = call.get("provider_call_id", "")
        telemetry_status = call.get("telemetry_status", "verified")
        if telemetry_status not in TELEMETRY_STATUSES:
            issues.append(f"model call {call.get('call_id')} has invalid telemetry status")
        if provider_id:
            if provider_id in provider_ids:
                issues.append(f"duplicate provider_call_id: {provider_id!r}")
            provider_ids.add(provider_id)
        elif telemetry_status == "verified":
            issues.append(f"verified model call {call.get('call_id')} lacks provider_call_id")
        if telemetry_status == "verified" and int(call.get("total_tokens", 0) or 0) <= 0:
            issues.append(f"verified model call {call.get('call_id')} has zero tokens")
        role = call.get("role")
        stage = call.get("stage")
        if role not in ROLE_STAGES or stage not in ROLE_STAGES.get(role, set()):
            issues.append(f"model call {call.get('call_id')} has invalid role/stage pairing")
        for key in ("request_path", "response_path"):
            artifact = root / str(call.get(key, ""))
            if not artifact.is_file():
                issues.append(f"model call {call.get('call_id')} missing {key}")
                continue
            hash_key = key.replace("_path", "_sha256")
            if sha256_file(artifact) != call.get(hash_key):
                if path_usage.get(str(call.get(key, "")), 0) > 1:
                    continue  # living path; final content is authoritative
                issues.append(f"model call {call.get('call_id')} {key} hash mismatch")
        reviewed_kind = REVIEW_TARGETS.get(str(stage))
        if reviewed_kind:
            records = _artifact_records(ledger, reviewed_kind)
            valid_hashes = {record.get("sha256") for record in records}
            if call.get("reviewed_artifact_sha256") not in valid_hashes:
                issues.append(f"model call {call.get('call_id')} is not bound to a registered {reviewed_kind}")
            if stage == "result_review":
                result_hashes = {record.get("sha256") for record in _artifact_records(ledger, "results")}
                freeze_hashes = {record.get("sha256") for record in _artifact_records(ledger, "freeze")}
                if call.get("reviewed_results_sha256") not in result_hashes:
                    issues.append(f"model call {call.get('call_id')} is not bound to registered results")
                if call.get("reviewed_freeze_sha256") not in freeze_hashes:
                    issues.append(f"model call {call.get('call_id')} is not bound to a registered freeze")
    for item in ledger.get("question_rounds", []):
        is_self_ask = ledger.get("protocol_condition") == SELF_ASK_CONDITION
        if item.get("status") == "imported" and (
            not item.get("answer_call_id")
            or (not is_self_ask and not item.get("review_call_id"))
        ):
            issues.append(f"imported round {item.get('round_id')} lacks call provenance")
    for kind, records in ledger.get("artifacts", {}).items():
        for index, record in enumerate(records):
            if kind == "run_summary" and index < len(records) - 1:
                # The terminal run summary is regenerated on re-advance (e.g.,
                # after a controlled paper revision); superseded records are
                # covered by their registration events.
                continue
            artifact = root / record.get("path", "")
            if not artifact.exists() or sha256_path(artifact) != record.get("sha256"):
                issues.append(f"registered {kind} artifact is missing or changed: {record.get('path')}")
    if ledger.get("phase") == "complete":
        try:
            interview_issues = _interview_issues(root, ledger)
            if interview_issues:
                raise HarnessError("Interview gate regressed: " + "; ".join(interview_issues))
            if ledger.get("protocol_condition", "qdm_full") != "mm_agent_native":
                state = load_state(str(root / "claude_workspace"))
                if not state.get("constraint_spec", {}).get("validation", {}).get("is_valid", False):
                    raise HarnessError("Constraint specification is no longer valid.")
            load_and_validate_formalization(
                _latest_artifact(root, ledger, "formalization"), require_frozen=True
            )
            _validate_blueprint(root, ledger)
            if ledger.get("protocol_condition") == SELF_ASK_CONDITION:
                pass  # qdm_self_ask ablation: no reviewer at any stage.
            else:
                blueprint_hash = _artifact_records(ledger, "blueprint")[-1]["sha256"]
                # Review-convergence policy (PROTOCOL.md section 9): an approved call
                # must bind to the latest artifact; a non_blocking_only call covers
                # the chain (its issues are preserved and later registrations resolve
                # them), mirroring the advance gate.
                if not any(
                    call.get("stage") == "blueprint_review"
                    and (
                        (call.get("approval_mode", "approved") == "approved"
                         and call.get("reviewed_artifact_sha256") == blueprint_hash)
                        or call.get("approval_mode") == "non_blocking_only"
                    )
                    for call in ledger.get("model_calls", [])
                ):
                    raise HarnessError("Latest blueprint lacks a bound reviewer approval.")
            _latest_artifact(root, ledger, "code")
            _validate_execution(root, ledger)
            _latest_artifact(root, ledger, "results")
            _latest_artifact(root, ledger, "freeze")
            if ledger.get("protocol_condition") == SELF_ASK_CONDITION:
                pass  # qdm_self_ask ablation: no reviewer at any stage.
            else:
                execution_hash = _artifact_records(ledger, "execution")[-1]["sha256"]
                results_hash = _artifact_records(ledger, "results")[-1]["sha256"]
                # The reviewed freeze may bind to any registered freeze revision of
                # the same frozen results (format-conformance revisions preserve the
                # claims and the source_results_sha256 binding).
                freeze_hashes = {
                    record.get("sha256")
                    for record in _artifact_records(ledger, "freeze")
                    if record.get("metadata", {}).get("source_results_sha256") == results_hash
                }
                if not any(
                    call.get("stage") == "result_review"
                    and (
                        (call.get("approval_mode", "approved") == "approved"
                         and call.get("reviewed_artifact_sha256") == execution_hash
                         and call.get("reviewed_results_sha256") == results_hash
                         and call.get("reviewed_freeze_sha256") in freeze_hashes)
                        or call.get("approval_mode") == "non_blocking_only"
                    )
                    for call in ledger.get("model_calls", [])
                ):
                    raise HarnessError("Latest execution bundle lacks a bound reviewer approval.")
            _validate_paper(root, ledger)
            if ledger.get("protocol_condition") != SELF_ASK_CONDITION:
                _latest_artifact(root, ledger, "evolution")
        except HarnessError as exc:
            issues.append(str(exc))
    return issues


def status_summary(output: str | Path) -> Dict[str, Any]:
    ledger = load_ledger(output)
    return {
        "run_id": ledger.get("run_id"),
        "phase": ledger.get("phase"),
        "experiment_mode": ledger.get("experiment_mode", "adaptive_questions"),
        "protocol_condition": ledger.get("protocol_condition", "qdm_full"),
        "event_count": ledger.get("event_count"),
        "question_rounds": len(ledger.get("question_rounds", [])),
        "model_calls": len(ledger.get("model_calls", [])),
        "total_tokens": sum(int(call.get("total_tokens", 0) or 0) for call in ledger.get("model_calls", [])),
        "pending_question": ledger.get("pending_question"),
        "artifact_kinds": sorted(ledger.get("artifacts", {})),
        "audit_issues": audit_harness(output),
        "terminal_outcome": ledger.get("terminal_outcome"),
    }
