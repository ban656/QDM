"""Frozen, blinded evaluation protocol for protocol-level modeling studies."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import re
import shutil
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..formalization import SCHEMA_VERSION as FORMALIZATION_SCHEMA_VERSION
from ..formalization import load_and_validate as load_formalization
from ..harness.core import SCHEMA_VERSION as HARNESS_SCHEMA_VERSION
from ..harness.core import load_ledger, sha256_path


PROTOCOL_SCHEMA = "qdm_protocol_evaluation_v2"
PACKET_SCHEMA = "anonymous_modeling_packet_v2"
SCORE_SCHEMA = "blind_modeling_score_v2"
ENDPOINTS = ("formulation", "outcome")
FORMULATION_DIMENSIONS = (
    "requirement_completeness",
    "boundary_precision",
    "operationalization",
    "variable_relation_coherence",
    "constraint_quality",
    "assumption_uncertainty_quality",
    "identifiability_analysis",
    "validation_traceability_closure",
)
OUTCOME_DIMENSIONS = (
    "problem_model_fit",
    "model_correctness",
    "constraint_fidelity",
    "implementation_fidelity",
    "execution_validity",
    "validation_robustness",
    "result_support",
    "reporting_and_limitations",
)
LEAKAGE_TERMS = (
    "qdm_full", "mm_agent_native", "mm-agent", "mm_agent", "mmagent",
    "qdm-agent", "qdm", "question-driven modeling", "question driven modeling",
    "提问驱动", "问题驱动",  # Chinese for "question-driven" / "problem-driven", for papers written in Chinese
)


class EvaluationError(RuntimeError):
    pass


def canonical_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise EvaluationError(f"Expected JSON object: {path}")
    return value


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _protocol_payload(expected_judges: int) -> Dict[str, Any]:
    if expected_judges < 2:
        raise EvaluationError("At least two independent judges are required by default.")
    return {
        "schema_version": PROTOCOL_SCHEMA,
        "status": "frozen",
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "harness_schema_version": HARNESS_SCHEMA_VERSION,
        "formalization_schema_version": FORMALIZATION_SCHEMA_VERSION,
        "research_unit": "problem",
        "replicate_structure": "seeds_nested_within_problem",
        "primary_endpoint": "formulation",
        "secondary_endpoints": ["propagation", "outcome", "cost"],
        "expected_independent_judges_per_endpoint": expected_judges,
        "score_scale": {
            "minimum": 0,
            "maximum": 4,
            "anchors": {
                "0": "absent or contradicted",
                "1": "major defects prevent reliable use",
                "2": "partially adequate with material defects",
                "3": "adequate and mostly well supported",
                "4": "complete, precise, and strongly supported",
            },
        },
        "dimensions": {
            "formulation": list(FORMULATION_DIMENSIONS),
            "outcome": list(OUTCOME_DIMENSIONS),
        },
        "evidence_rule": "Every dimension score requires at least one valid JSON pointer and quote from that anonymous packet.",
        "overall_rule": "Overall score is the unweighted arithmetic mean of the frozen dimension scores.",
        "reveal_rule": "Method labels remain private until all required judge score files for both endpoints are frozen.",
        "implemented_met_rule": [
            "relevant code parses",
            "the feature is invoked by the executed path",
            "the frozen execution succeeds",
            "the result artifact contains corresponding evidence",
        ],
        "attribution_precedence": [
            "integrity_issue",
            "elicitation_failure",
            "specification_retention_failure",
            "implementation_failure",
            "result_validation_failure",
            "writing_overclaim",
            "none",
        ],
        "analysis_rule": "Aggregate within problem first; bootstrap and paired inference resample problems only.",
        "inclusion_rule": "Include every terminal run (complete or explicitly stopped); exclude only non-comparable P0, contamination, or non-terminal runs.",
        "token_telemetry": "optional_cost_metric",
    }


def freeze_protocol(output: str | Path, expected_judges: int = 2) -> Dict[str, Any]:
    target = Path(output).resolve()
    if target.exists():
        raise EvaluationError(f"Refusing to overwrite frozen evaluation protocol: {target}")
    protocol = _protocol_payload(expected_judges)
    protocol["protocol_hash"] = canonical_hash(protocol)
    write_json(target, protocol)
    return protocol


def load_protocol(path: str | Path) -> Dict[str, Any]:
    protocol = read_json(path)
    claimed = protocol.pop("protocol_hash", "")
    actual = canonical_hash(protocol)
    protocol["protocol_hash"] = claimed
    if protocol.get("schema_version") != PROTOCOL_SCHEMA or protocol.get("status") != "frozen":
        raise EvaluationError("Evaluation protocol is not a frozen v2 protocol.")
    if claimed != actual:
        raise EvaluationError("Frozen evaluation protocol hash mismatch.")
    current_implementation = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if protocol.get("implementation_sha256") != current_implementation:
        raise EvaluationError("Evaluator implementation changed after protocol freeze; create a new protocol and replicates.")
    return protocol


def _latest_record(ledger: Dict[str, Any], kind: str) -> Dict[str, Any]:
    records = ledger.get("artifacts", {}).get(kind, [])
    if not records:
        raise EvaluationError(f"Run lacks required artifact: {kind}")
    return records[-1]


def _load_artifact(run: Path, ledger: Dict[str, Any], kind: str) -> Tuple[Path, Dict[str, Any]]:
    record = _latest_record(ledger, kind)
    path = run / record["path"]
    if not path.exists() or sha256_path(path) != record.get("sha256"):
        raise EvaluationError(f"Run artifact is missing or changed: {kind}")
    return path, record


def _fairness_signature(ledger: Dict[str, Any]) -> Dict[str, Any]:
    assets = ledger.get("data_manifest", {}).get("assets", [])
    envelope = ledger.get("capability_envelope", {})
    return {
        "problem_sha256": ledger.get("problem", {}).get("sha256"),
        "data_sha256": sorted(str(item.get("sha256")) for item in assets),
        "no_data_reason": ledger.get("data_manifest", {}).get("no_data_reason", ""),
        "models": ledger.get("models", {}),
        "seed": envelope.get("seed"),
        "tool_policy": envelope.get("tool_policy", {}),
        "max_total_agent_calls": envelope.get("max_total_agent_calls"),
        "max_blueprint_revisions": ledger.get("limits", {}).get("max_blueprint_revisions"),
        "max_code_repair_rounds": ledger.get("limits", {}).get("max_code_repair_rounds"),
    }


def verify_pair(run_a: str | Path, run_b: str | Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ledgers = (load_ledger(run_a), load_ledger(run_b))
    if _fairness_signature(ledgers[0]) != _fairness_signature(ledgers[1]):
        raise EvaluationError("Paired runs do not share the same frozen capability envelope.")
    conditions = {ledger.get("protocol_condition") for ledger in ledgers}
    if conditions != {"qdm_full", "mm_agent_native"}:
        raise EvaluationError("Primary pair must contain qdm_full and mm_agent_native exactly once.")
    for run, ledger in zip((Path(run_a), Path(run_b)), ledgers):
        if ledger.get("phase") not in {"complete", "stopped"}:
            raise EvaluationError(f"Run is not terminal: {run}")
    return ledgers


def _try_artifact(run: Path, ledger: Dict[str, Any], kind: str) -> Tuple[Path | None, Dict[str, Any] | None, str]:
    records = ledger.get("artifacts", {}).get(kind, [])
    if not records:
        return None, None, "missing"
    record = records[-1]
    path = run / str(record.get("path", ""))
    if not path.exists():
        return None, record, "registered artifact is missing"
    if sha256_path(path) != record.get("sha256"):
        return path, record, "registered artifact hash mismatch"
    return path, record, ""


def _redact(value: Any, secrets: Sequence[str], log: List[str], pointer: str = "") -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, inner in value.items():
            safe_key = _redact(str(key), secrets, log, f"{pointer}/<key>")
            redacted[safe_key] = _redact(inner, secrets, log, f"{pointer}/{safe_key}")
        return redacted
    if isinstance(value, list):
        return [_redact(inner, secrets, log, f"{pointer}/{index}") for index, inner in enumerate(value)]
    if not isinstance(value, str):
        return value
    result = value
    for secret in secrets:
        if secret and re.search(re.escape(secret), result, flags=re.I):
            result = re.sub(re.escape(secret), "[BLINDED]", result, flags=re.I)
            log.append(pointer or "/")
    for term in LEAKAGE_TERMS:
        if re.search(re.escape(term), result, flags=re.I):
            result = re.sub(re.escape(term), "[METHOD_LABEL_REDACTED]", result, flags=re.I)
            log.append(pointer or "/")
    return result


def _assert_blinded(packet: Dict[str, Any], secrets: Sequence[str]) -> None:
    text = json.dumps(packet, ensure_ascii=False).lower()
    residual = [term for term in LEAKAGE_TERMS if term in text]
    residual.extend(secret for secret in secrets if secret and secret.lower() in text)
    if residual:
        raise EvaluationError(f"Anonymous packet still contains method/run leakage: {residual}")


def _read_content(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return read_json(path)
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _code_bundle(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    bundle: List[Dict[str, Any]] = []
    parse_report = {"python_files": 0, "parse_failures": []}
    for index, child in enumerate(files, start=1):
        if child.stat().st_size > 1_000_000:
            continue
        try:
            content = child.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        generic_name = f"source_{index:03d}{child.suffix.lower()}"
        bundle.append({"file": generic_name, "content": content})
        if child.suffix.lower() == ".py":
            parse_report["python_files"] += 1
            try:
                ast.parse(content, filename=generic_name)
            except SyntaxError as exc:
                parse_report["parse_failures"].append({"file": generic_name, "line": exc.lineno, "message": exc.msg})
    parse_report["all_python_parses"] = not parse_report["parse_failures"]
    return bundle, parse_report


def _build_packets(run: Path, ledger: Dict[str, Any], submission: str) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    paths: Dict[str, Path | None] = {}
    integrity: Dict[str, str] = {}
    for kind in ("formalization", "blueprint", "code", "execution", "results", "freeze", "paper"):
        path, _record, issue = _try_artifact(run, ledger, kind)
        paths[kind] = path
        integrity[kind] = issue or "verified"
    formalization: Dict[str, Any] = {}
    formalization_valid = False
    if paths["formalization"] is not None and integrity["formalization"] == "verified":
        try:
            formalization = load_formalization(paths["formalization"])
            formalization_valid = True
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            integrity["formalization"] = f"invalid: {exc}"
            try:
                formalization = read_json(paths["formalization"])
            except Exception:
                formalization = {}
    code, parse_report = _code_bundle(paths["code"]) if paths["code"] is not None else (
        [], {"python_files": 0, "parse_failures": [], "all_python_parses": False}
    )
    p1 = {
        "schema_version": PACKET_SCHEMA,
        "endpoint": "formulation",
        "submission": submission,
        "formalization": formalization,
        "run_outcome": ledger.get("terminal_outcome", {"status": "complete"}),
        "deterministic_checks": {
            "formalization_schema_valid": formalization_valid,
            "integrity": {"formalization": integrity["formalization"]},
            "requirement_count": len(formalization.get("requirements", [])),
            "traced_requirement_count": len({
                item.get("requirement_id") for item in formalization.get("traceability", [])
                if isinstance(item, dict) and item.get("requirement_id")
            }),
            "unresolved_blocker_count": sum(
                1 for item in formalization.get("unresolved_items", [])
                if isinstance(item, dict) and item.get("classification") == "blocker"
            ),
            "closure_status": formalization.get("closure", {}).get("status"),
        },
    }
    def content(kind: str) -> Any:
        path = paths[kind]
        if path is None or path.is_dir():
            return None
        try:
            return _read_content(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            integrity[kind] = f"unreadable: {exc}"
            return None

    execution = content("execution")
    p2 = {
        "schema_version": PACKET_SCHEMA,
        "endpoint": "outcome",
        "submission": submission,
        "requirement_index": formalization.get("requirements", []),
        "run_outcome": ledger.get("terminal_outcome", {"status": "complete"}),
        "blueprint": content("blueprint"),
        "code": code,
        "execution": execution,
        "results": content("results"),
        "frozen_claims": content("freeze"),
        "paper": content("paper"),
        "deterministic_checks": {
            **parse_report,
            "execution_passed": isinstance(execution, dict) and execution.get("status") == "passed" and execution.get("exit_code") == 0,
            "artifact_integrity": integrity,
            "all_required_artifact_hashes_verified": all(value == "verified" for value in integrity.values()),
        },
    }
    log: List[str] = []
    secrets = [str(run), str(run.resolve()), str(ledger.get("protocol_condition", ""))]
    blind_p1 = _redact(p1, secrets, log)
    blind_p2 = _redact(p2, secrets, log)
    _assert_blinded(blind_p1, secrets)
    _assert_blinded(blind_p2, secrets)
    return blind_p1, blind_p2, sorted(set(log))


def prepare_pair(
    protocol_path: str | Path,
    run_a: str | Path,
    run_b: str | Path,
    output: str | Path,
    pair_id: str,
    seed: int,
    problem_id: str = "",
    replicate_id: str = "",
) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    output_root = Path(output).resolve()
    if output_root.exists():
        raise EvaluationError(f"Refusing to overwrite evaluation pair: {output_root}")
    ledgers = verify_pair(run_a, run_b)
    rng = random.Random(seed)
    order = [0, 1]
    rng.shuffle(order)
    runs = [Path(run_a).resolve(), Path(run_b).resolve()]
    submissions = ["A", "B"]
    private_map: Dict[str, Any] = {
        "pair_id": pair_id,
        "problem_id": problem_id or str(ledgers[0].get("problem", {}).get("sha256")),
        "replicate_id": replicate_id or str(seed),
        "protocol_hash": protocol["protocol_hash"],
        "mapping": {},
        "redactions": {},
    }
    packet_hashes: Dict[str, Dict[str, str]] = {endpoint: {} for endpoint in ENDPOINTS}
    for submission, index in zip(submissions, order):
        p1, p2, redactions = _build_packets(runs[index], ledgers[index], submission)
        for endpoint, packet in (("formulation", p1), ("outcome", p2)):
            path = output_root / "public" / endpoint / f"submission_{submission}.json"
            write_json(path, packet)
            packet_hashes[endpoint][submission] = sha256_path(path)
        private_map["mapping"][submission] = {
            "run": str(runs[index]),
            "protocol_condition": ledgers[index].get("protocol_condition"),
        }
        private_map["redactions"][submission] = redactions
    manifest = {
        "schema_version": "blind_pair_manifest_v2",
        "pair_id": pair_id,
        "problem_id": private_map["problem_id"],
        "replicate_id": private_map["replicate_id"],
        "protocol_hash": protocol["protocol_hash"],
        "packet_hashes": packet_hashes,
        "status": "blinded",
    }
    write_json(output_root / "public" / "manifest.json", manifest)
    write_json(output_root / "private" / "mapping.json", private_map)
    instructions = (
        "# Anonymous Modeling Evaluation\n\n"
        "Score each submission independently on the frozen 0-4 anchors in the protocol. "
        "Do not infer method identity. Every dimension score must cite the packet filename, "
        "a JSON pointer, and an exact quote. Complete formulation and outcome sheets in "
        "separate contexts; do not inspect the private directory.\n"
    )
    instructions_path = output_root / "public" / "judge_instructions.md"
    instructions_path.write_text(instructions, encoding="utf-8")
    return manifest


def score_template(protocol_path: str | Path, pair_dir: str | Path, endpoint: str, judge_id: str) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    if endpoint not in ENDPOINTS:
        raise EvaluationError(f"Invalid endpoint: {endpoint}")
    manifest = read_json(Path(pair_dir) / "public" / "manifest.json")
    if manifest.get("protocol_hash") != protocol.get("protocol_hash"):
        raise EvaluationError("Pair was prepared under a different evaluation protocol.")
    dimensions = protocol["dimensions"][endpoint]
    submissions = {}
    for label in ("A", "B"):
        packet = read_json(Path(pair_dir) / "public" / endpoint / f"submission_{label}.json")
        propagation = []
        if endpoint == "outcome":
            for requirement in packet.get("requirement_index", []):
                if isinstance(requirement, dict) and requirement.get("id"):
                    propagation.append({
                        "requirement_id": requirement["id"],
                        "discovered_in_p1": True,
                        "retained_in_specification": None,
                        "implemented_correctly": None,
                        "execution_supported": None,
                        "result_supported": None,
                        "paper_supported": None,
                        "integrity_ok": None,
                        "implemented_evidence": {},
                        "attribution": "",
                    })
        submissions[label] = {
            "dimension_scores": {dimension: {"score": None, "evidence": []} for dimension in dimensions},
            "overall_score": None,
            "strengths": [],
            "defects": [],
            "propagation": propagation,
        }
    return {
        "schema_version": SCORE_SCHEMA,
        "pair_id": manifest["pair_id"],
        "judge_id": judge_id,
        "endpoint": endpoint,
        "protocol_hash": protocol["protocol_hash"],
        "packet_hashes": manifest["packet_hashes"][endpoint],
        "evidence_schema": {
            "packet": "submission_A.json | submission_B.json",
            "json_pointer": "/path/to/evidence",
            "quote": "exact text from resolved value",
        },
        "submissions": submissions,
        "preference": "",
        "confidence": None,
    }


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise EvaluationError(f"Invalid JSON pointer: {pointer}")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise EvaluationError(f"JSON pointer does not resolve: {pointer}")
    return current


def _evidence_issue(packet: Dict[str, Any], item: Any, expected_file: str) -> str:
    if not isinstance(item, dict):
        return "evidence must be an object"
    if item.get("packet") != expected_file:
        return f"packet must be {expected_file}"
    try:
        pointer = item["json_pointer"]
        quote = str(item["quote"]).strip()
        resolved = _resolve_pointer(packet, pointer)
    except (KeyError, IndexError, ValueError, TypeError, EvaluationError) as exc:
        return str(exc)
    if not quote or quote not in json.dumps(resolved, ensure_ascii=False):
        return f"evidence quote is not at {pointer}"
    return ""


def defect_attribution(item: Dict[str, Any]) -> str:
    if item.get("integrity_ok") is False:
        return "integrity_issue"
    if item.get("discovered_in_p1") is False:
        return "elicitation_failure"
    if item.get("retained_in_specification") is False:
        return "specification_retention_failure"
    if item.get("implemented_correctly") is False:
        return "implementation_failure"
    if item.get("execution_supported") is False or item.get("result_supported") is False:
        return "result_validation_failure"
    if item.get("paper_supported") is False:
        return "writing_overclaim"
    return "none"


def validate_score(protocol_path: str | Path, pair_dir: str | Path, score_path: str | Path) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    pair = Path(pair_dir)
    manifest = read_json(pair / "public" / "manifest.json")
    score = read_json(score_path)
    issues: List[str] = []
    endpoint = score.get("endpoint")
    if score.get("schema_version") != SCORE_SCHEMA:
        issues.append("invalid score schema")
    if score.get("pair_id") != manifest.get("pair_id") or score.get("protocol_hash") != protocol.get("protocol_hash"):
        issues.append("score is not bound to this pair and protocol")
    if not str(score.get("judge_id", "")).strip():
        issues.append("judge_id is required")
    if endpoint not in ENDPOINTS:
        issues.append("invalid endpoint")
        return {"status": "failed", "issues": issues}
    expected_hashes = manifest.get("packet_hashes", {}).get(endpoint, {})
    if score.get("packet_hashes") != expected_hashes:
        issues.append("score packet hashes do not match the frozen anonymous packets")
    dimensions = protocol["dimensions"][endpoint]
    for label in ("A", "B"):
        packet_path = pair / "public" / endpoint / f"submission_{label}.json"
        packet = read_json(packet_path)
        submission = score.get("submissions", {}).get(label, {})
        entries = submission.get("dimension_scores", {})
        if set(entries) != set(dimensions):
            issues.append(f"submission {label} has incorrect dimensions")
        for dimension in dimensions:
            entry = entries.get(dimension, {})
            value = entry.get("score")
            if not isinstance(value, (int, float)) or not 0 <= value <= 4:
                issues.append(f"submission {label} {dimension} score must be in [0,4]")
            evidence = entry.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                issues.append(f"submission {label} {dimension} requires evidence")
                continue
            for evidence_item in evidence:
                problem = _evidence_issue(packet, evidence_item, f"submission_{label}.json")
                if problem:
                    issues.append(f"submission {label} {dimension} invalid evidence: {problem}")
        overall = submission.get("overall_score")
        if not isinstance(overall, (int, float)) or not 0 <= overall <= 4:
            issues.append(f"submission {label} overall_score must be in [0,4]")
        elif all(isinstance(entries.get(dimension, {}).get("score"), (int, float)) for dimension in dimensions):
            expected_overall = mean(float(entries[dimension]["score"]) for dimension in dimensions)
            if abs(float(overall) - expected_overall) > 1e-6:
                issues.append(f"submission {label} overall_score must equal the dimension mean {expected_overall:.6f}")
        if endpoint == "outcome":
            propagation = submission.get("propagation", [])
            if not isinstance(propagation, list):
                issues.append(f"submission {label} propagation must be a list")
                propagation = []
            p1_ids = {
                str(item.get("id")) for item in packet.get("requirement_index", [])
                if isinstance(item, dict) and item.get("id")
            }
            propagation_ids = [str(item.get("requirement_id", "")) for item in propagation if isinstance(item, dict)]
            missing_p1 = p1_ids - set(propagation_ids)
            if missing_p1:
                issues.append(f"submission {label} propagation omits P1 requirements: {sorted(missing_p1)}")
            if len(propagation_ids) != len(set(propagation_ids)):
                issues.append(f"submission {label} propagation requirement IDs must be unique")
            for index, item in enumerate(propagation):
                if not isinstance(item, dict) or not str(item.get("requirement_id", "")).strip():
                    issues.append(f"submission {label} propagation[{index}] requires requirement_id")
                    continue
                for key in (
                    "discovered_in_p1", "retained_in_specification", "implemented_correctly",
                    "execution_supported", "result_supported", "paper_supported", "integrity_ok",
                ):
                    value = item.get(key)
                    if value is not True and value is not False and value is not None:
                        issues.append(f"submission {label} propagation[{index}].{key} must be true, false, or null")
                discovered = item.get("discovered_in_p1")
                if discovered is not True and discovered is not False:
                    issues.append(f"submission {label} propagation[{index}].discovered_in_p1 must be resolved")
                integrity_ok = item.get("integrity_ok")
                if integrity_ok is not True and integrity_ok is not False:
                    issues.append(f"submission {label} propagation[{index}].integrity_ok must be resolved")
                if item.get("discovered_in_p1") is True:
                    for key in (
                        "retained_in_specification", "implemented_correctly",
                        "execution_supported", "result_supported", "paper_supported",
                    ):
                        resolved = item.get(key)
                        if resolved is not True and resolved is not False:
                            issues.append(f"submission {label} propagation[{index}].{key} must be resolved")
                expected = defect_attribution(item)
                if item.get("attribution") != expected:
                    issues.append(f"submission {label} propagation[{index}] attribution must be {expected}")
                if item.get("implemented_correctly") is True:
                    gates = item.get("implemented_evidence", {})
                    if gates.get("code_parses") is not True or packet.get("deterministic_checks", {}).get("all_python_parses") is not True:
                        issues.append(f"submission {label} propagation[{index}] implemented=met lacks required evidence")
                    for key in ("invocation", "successful_execution", "result_evidence"):
                        problem = _evidence_issue(packet, gates.get(key), f"submission_{label}.json")
                        if problem:
                            issues.append(f"submission {label} propagation[{index}] {key}: {problem}")
    if score.get("preference") not in {"A", "B", "tie"}:
        issues.append("preference must be A, B, or tie")
    confidence = score.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        issues.append("confidence must be in [0,1]")
    return {"status": "failed" if issues else "passed", "issues": issues, "score": score}


def freeze_score(protocol_path: str | Path, pair_dir: str | Path, score_path: str | Path) -> Dict[str, Any]:
    result = validate_score(protocol_path, pair_dir, score_path)
    if result["issues"]:
        raise EvaluationError("Invalid score: " + "; ".join(result["issues"]))
    score = result["score"]
    destination = Path(pair_dir) / "private" / "scores" / score["endpoint"] / f"{score['judge_id']}.json"
    if destination.exists():
        raise EvaluationError(f"Refusing to overwrite frozen score: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(score_path, destination)
    return {"status": "frozen", "path": str(destination), "sha256": sha256_path(destination)}


def reveal_pair(protocol_path: str | Path, pair_dir: str | Path) -> Dict[str, Any]:
    protocol = load_protocol(protocol_path)
    pair = Path(pair_dir)
    manifest = read_json(pair / "public" / "manifest.json")
    if manifest.get("protocol_hash") != protocol.get("protocol_hash"):
        raise EvaluationError("Protocol mismatch.")
    required = int(protocol["expected_independent_judges_per_endpoint"])
    score_index: Dict[str, List[Dict[str, str]]] = {}
    judge_sets: Dict[str, set[str]] = {}
    for endpoint in ENDPOINTS:
        records = []
        judges = set()
        for path in sorted((pair / "private" / "scores" / endpoint).glob("*.json")):
            score = read_json(path)
            judges.add(str(score.get("judge_id")))
            records.append({"path": str(path), "sha256": sha256_path(path)})
        if len(judges) < required:
            raise EvaluationError(f"{endpoint} has {len(judges)} independent judges; {required} required.")
        score_index[endpoint] = records
        judge_sets[endpoint] = judges
    mapping = read_json(pair / "private" / "mapping.json")
    reveal = {
        "schema_version": "revealed_pair_v2",
        "pair_id": manifest["pair_id"],
        "problem_id": manifest.get("problem_id"),
        "replicate_id": manifest.get("replicate_id"),
        "protocol_hash": protocol["protocol_hash"],
        "mapping": mapping["mapping"],
        "frozen_scores": score_index,
        "judge_ids": {key: sorted(value) for key, value in judge_sets.items()},
        "status": "revealed_after_score_freeze",
    }
    destination = pair / "revealed.json"
    if destination.exists():
        raise EvaluationError("Pair is already revealed.")
    write_json(destination, reveal)
    return reveal


def _mean_scores(paths: Iterable[Path], endpoint: str) -> Dict[str, float]:
    values: Dict[str, List[float]] = {"A": [], "B": []}
    for path in paths:
        score = read_json(path)
        if score.get("endpoint") != endpoint:
            continue
        for label in values:
            values[label].append(float(score["submissions"][label]["overall_score"]))
    if not all(values.values()):
        raise EvaluationError(f"No scores available for endpoint {endpoint}")
    return {label: mean(items) for label, items in values.items()}


def _interval_alpha(judge_values: Sequence[Dict[str, Any]], endpoint: str) -> float | None:
    dimensions = FORMULATION_DIMENSIONS if endpoint == "formulation" else OUTCOME_DIMENSIONS
    matrix: List[List[float]] = []
    for submission in ("A", "B"):
        for dimension in dimensions:
            matrix.append([
                float(score["submissions"][submission]["dimension_scores"][dimension]["score"])
                for score in judge_values
            ])
    if not matrix or len(judge_values) < 2:
        return None
    observed = mean(
        (row[left] - row[right]) ** 2
        for row in matrix
        for left in range(len(row))
        for right in range(left + 1, len(row))
    )
    pooled = [value for row in matrix for value in row]
    expected_pairs = [
        (pooled[left] - pooled[right]) ** 2
        for left in range(len(pooled))
        for right in range(left + 1, len(pooled))
    ]
    expected = mean(expected_pairs) if expected_pairs else 0.0
    return 1.0 if expected == 0 and observed == 0 else (None if expected == 0 else 1 - observed / expected)


def aggregate(revealed_pair_dirs: Sequence[str | Path], output: str | Path) -> Dict[str, Any]:
    replicate_rows = []
    agreement_rows = []
    for value in revealed_pair_dirs:
        pair = Path(value)
        reveal = read_json(pair / "revealed.json")
        row = {
            "pair_id": reveal["pair_id"],
            "problem_id": reveal.get("problem_id") or reveal["pair_id"],
            "replicate_id": reveal.get("replicate_id") or reveal["pair_id"],
        }
        for endpoint in ENDPOINTS:
            paths = list((pair / "private" / "scores" / endpoint).glob("*.json"))
            anonymous = _mean_scores(paths, endpoint)
            condition_scores = {
                reveal["mapping"][label]["protocol_condition"]: score
                for label, score in anonymous.items()
            }
            row[endpoint] = condition_scores
            row[f"{endpoint}_paired_difference_qdm_minus_mm"] = (
                condition_scores["qdm_full"] - condition_scores["mm_agent_native"]
            )
            judge_values = [read_json(path) for path in paths]
            if len(judge_values) >= 2:
                diffs = []
                for submission in ("A", "B"):
                    scores = [float(item["submissions"][submission]["overall_score"]) for item in judge_values]
                    for left in range(len(scores)):
                        for right in range(left + 1, len(scores)):
                            diffs.append(abs(scores[left] - scores[right]))
                agreement_rows.append({
                    "pair_id": reveal["pair_id"], "endpoint": endpoint,
                    "mean_absolute_difference": mean(diffs),
                    "krippendorff_alpha_interval": _interval_alpha(judge_values, endpoint),
                })
        replicate_rows.append(row)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in replicate_rows:
        grouped.setdefault(str(row["problem_id"]), []).append(row)
    problem_rows = []
    for problem_id, rows in sorted(grouped.items()):
        problem_row: Dict[str, Any] = {"problem_id": problem_id, "replicate_count": len(rows)}
        for endpoint in ENDPOINTS:
            condition_scores = {
                condition: mean(row[endpoint][condition] for row in rows)
                for condition in ("qdm_full", "mm_agent_native")
            }
            problem_row[endpoint] = condition_scores
            problem_row[f"{endpoint}_paired_difference_qdm_minus_mm"] = (
                condition_scores["qdm_full"] - condition_scores["mm_agent_native"]
            )
        problem_rows.append(problem_row)
    mean_differences = {
        endpoint: mean(row[f"{endpoint}_paired_difference_qdm_minus_mm"] for row in problem_rows)
        if problem_rows else math.nan
        for endpoint in ENDPOINTS
    }
    bootstrap_ci: Dict[str, Any] = {}
    rng = random.Random(0)
    for endpoint in ENDPOINTS:
        differences = [row[f"{endpoint}_paired_difference_qdm_minus_mm"] for row in problem_rows]
        if len(differences) < 2:
            bootstrap_ci[endpoint] = None
            continue
        samples = sorted(mean(rng.choices(differences, k=len(differences))) for _ in range(10000))
        bootstrap_ci[endpoint] = [samples[249], samples[9749]]
    result = {
        "schema_version": "paired_protocol_aggregate_v2",
        "analysis_unit": "problem",
        "problem_count": len(problem_rows),
        "replicate_count": len(replicate_rows),
        "replicates": replicate_rows,
        "problems": problem_rows,
        "mean_paired_differences": mean_differences,
        "problem_bootstrap_95_percent_ci": bootstrap_ci,
        "judge_agreement": agreement_rows,
        "warning": "Replicates and judge items are not treated as independent sample units.",
    }
    write_json(output, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Frozen blind protocol-level evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("init-protocol")
    command.add_argument("--output", required=True)
    command.add_argument("--expected-judges", type=int, default=2)
    command = sub.add_parser("prepare-pair")
    command.add_argument("--protocol", required=True)
    command.add_argument("--run-a", required=True)
    command.add_argument("--run-b", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--pair-id", required=True)
    command.add_argument("--seed", type=int, required=True)
    command.add_argument("--problem-id", default="")
    command.add_argument("--replicate-id", default="")
    command = sub.add_parser("score-template")
    command.add_argument("--protocol", required=True)
    command.add_argument("--pair-dir", required=True)
    command.add_argument("--endpoint", choices=ENDPOINTS, required=True)
    command.add_argument("--judge-id", required=True)
    command.add_argument("--output", required=True)
    command = sub.add_parser("freeze-score")
    command.add_argument("--protocol", required=True)
    command.add_argument("--pair-dir", required=True)
    command.add_argument("--score", required=True)
    command = sub.add_parser("reveal")
    command.add_argument("--protocol", required=True)
    command.add_argument("--pair-dir", required=True)
    command = sub.add_parser("aggregate")
    command.add_argument("--pair-dir", action="append", required=True)
    command.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init-protocol":
            result = freeze_protocol(args.output, args.expected_judges)
        elif args.command == "prepare-pair":
            result = prepare_pair(
                args.protocol, args.run_a, args.run_b, args.output, args.pair_id,
                args.seed, args.problem_id, args.replicate_id,
            )
        elif args.command == "score-template":
            result = score_template(args.protocol, args.pair_dir, args.endpoint, args.judge_id)
            write_json(args.output, result)
        elif args.command == "freeze-score":
            result = freeze_score(args.protocol, args.pair_dir, args.score)
        elif args.command == "reveal":
            result = reveal_pair(args.protocol, args.pair_dir)
        else:
            result = aggregate(args.pair_dir, args.output)
    except (EvaluationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
