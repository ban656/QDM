from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qdm.evaluation.protocol_v2 import (
    defect_attribution,
    freeze_protocol,
    load_protocol,
    score_template,
    validate_score,
    write_json,
)
from qdm.formalization import SCHEMA_VERSION, validate_package
from qdm.harness.core import (
    HarnessError,
    advance_phase,
    build_blueprint_request,
    build_formalization_request,
    init_harness,
    load_ledger,
    record_model_call,
    register_artifact,
)


def valid_formalization() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "problem_id": "problem-1",
        "source_anchors": [{
            "id": "SRC-1", "source": "problem", "locator": "paragraph 1",
            "quote_or_description": "Allocate resources under a budget.",
        }],
        "requirements": [{
            "id": "REQ-1", "statement": "Maximize utility within budget.",
            "type": "goal", "priority": "primary", "verification": "objective is reported",
            "source_anchor_ids": ["SRC-1"],
        }],
        "boundaries": [{
            "id": "BND-1", "statement": "Two resources only", "inside_or_outside": "inside",
            "consequence": "Other resources are excluded",
        }],
        "operational_targets": [{
            "id": "TGT-1", "target": "utility", "metric": "objective value",
            "success_predicate": "feasible value is produced",
        }],
        "observables": [{
            "id": "OBS-1", "name": "cost", "acquisition_method": "problem statement", "unit": "currency",
        }],
        "variables": [{
            "id": "VAR-1", "symbol": "x", "meaning": "allocation", "role": "decision",
            "unit": "units", "domain": "nonnegative real",
        }],
        "relations": [{
            "id": "REL-1", "expression_or_rule": "u=x", "applicability": "linear utility",
            "evidence": "stated simplification",
        }],
        "constraints": [{
            "id": "CON-1", "statement": "cost <= budget", "type": "hard", "scope": "all solutions",
            "source": "SRC-1", "executable_check": "cost <= budget + tolerance",
            "failure_action": "reject solution",
        }],
        "assumptions": [{
            "id": "ASM-1", "statement": "utility is linear", "justification": "test fixture",
            "consequence_if_false": "use nonlinear utility",
        }],
        "uncertainties": [{
            "id": "UNC-1", "type": "parameter", "source": "cost estimate",
            "affected_items": "CON-1", "analysis_or_mitigation": "sensitivity analysis",
        }],
        "identifiability": {
            "status": "identified", "confounders": [], "non_identifiable_items": [],
            "resolution_or_consequence": "all parameters are supplied",
        },
        "validation_requirements": [{
            "id": "VAL-1", "target": "budget feasibility", "method": "recompute total cost",
            "pass_fail_predicate": "total cost <= budget + tolerance", "failure_action": "fail run",
        }],
        "traceability": [{
            "id": "TR-1", "requirement_id": "REQ-1",
            "specification_item_ids": ["TGT-1", "CON-1"],
            "validation_requirement_ids": ["VAL-1"],
        }],
        "unresolved_items": [],
        "closure": {
            "status": "frozen", "blocking_item_ids": [], "non_blocking_item_ids": [],
            "closure_rationale": "All blocking information is explicit.",
        },
    }


class FormalizationTests(unittest.TestCase):
    def test_valid_package_passes(self) -> None:
        self.assertEqual([], validate_package(valid_formalization()))

    def test_unresolved_blocker_prevents_freeze(self) -> None:
        package = valid_formalization()
        package["unresolved_items"] = [{
            "id": "OPEN-1", "question": "Unknown budget", "classification": "blocker",
            "consequence": "Feasibility cannot be checked", "disposition": "obtain value",
        }]
        package["closure"]["blocking_item_ids"] = ["OPEN-1"]
        issues = validate_package(package)
        self.assertTrue(any("cannot contain unresolved blockers" in issue for issue in issues))


class HarnessV2Tests(unittest.TestCase):
    def test_native_condition_requires_trace_before_specification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            problem = root / "problem.txt"
            problem.write_text("Model the system.", encoding="utf-8")
            run = root / "run"
            init_harness(
                run, problem, [], "No supplied data.", "model", "reviewer",
                protocol_condition="mm_agent_native",
            )
            with self.assertRaises(HarnessError):
                advance_phase(run, "specification")
            trace = run / "native" / "trace.json"
            trace.parent.mkdir(parents=True)
            trace.write_text(json.dumps({"events": ["native planning"]}), encoding="utf-8")
            request = run / "native" / "request.md"
            response = run / "native" / "response.md"
            request.write_text("Run the native baseline protocol on the frozen problem.", encoding="utf-8")
            response.write_text("Native protocol response with sufficient detail. " * 4, encoding="utf-8")
            call = record_model_call(
                run, "answerer", "native_protocol", request, response, "model", "model", "",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00",
                None, None, telemetry_status="unavailable",
            )
            record = register_artifact(run, "protocol_trace", trace, {
                "protocol_name": "baseline-native", "capture_method": "event export",
                "source_call_ids": [call["call_id"]],
            })
            trace.write_text("changed", encoding="utf-8")
            self.assertTrue((run / record["path"]).is_file())
            self.assertNotEqual(trace.resolve(), (run / record["path"]).resolve())
            ledger = advance_phase(run, "specification")
            self.assertEqual("specification", ledger["phase"])
            formalization_request = run / "neutral" / "request.md"
            build_formalization_request(run, formalization_request)
            package = valid_formalization()
            package["problem_id"] = ledger["problem"]["sha256"]
            formalization_response = run / "neutral" / "formalization.json"
            formalization_response.write_text(json.dumps(package), encoding="utf-8")
            reporter_call = record_model_call(
                run, "reporter", "formalization_reporting", formalization_request,
                formalization_response, "reviewer", "reviewer", "",
                "2026-01-01T00:00:02+00:00", "2026-01-01T00:00:03+00:00",
                None, None, telemetry_status="unavailable",
            )
            formalization_record = register_artifact(run, "formalization", formalization_response, {
                "source_call_id": reporter_call["call_id"],
                "source_artifact_sha256": record["sha256"],
            })
            advance_phase(run, "blueprint")
            blueprint_request = run / "native" / "blueprint_request.md"
            build_blueprint_request(run, blueprint_request)
            request_text = blueprint_request.read_text(encoding="utf-8")
            self.assertIn(record["sha256"], request_text)
            self.assertIn(formalization_record["sha256"], request_text)
            self.assertNotIn("Maximize utility within budget", request_text)


class EvaluationProtocolTests(unittest.TestCase):
    def test_protocol_hash_and_evidence_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protocol_path = root / "protocol.json"
            protocol = freeze_protocol(protocol_path, 2)
            self.assertEqual(protocol["protocol_hash"], load_protocol(protocol_path)["protocol_hash"])
            pair = root / "pair"
            packet_hashes = {"formulation": {}, "outcome": {}}
            for endpoint in ("formulation", "outcome"):
                for label in ("A", "B"):
                    packet = {"fact": f"evidence-{endpoint}-{label}"}
                    path = pair / "public" / endpoint / f"submission_{label}.json"
                    write_json(path, packet)
                    import hashlib
                    packet_hashes[endpoint][label] = hashlib.sha256(path.read_bytes()).hexdigest()
            write_json(pair / "public" / "manifest.json", {
                "pair_id": "p1", "protocol_hash": protocol["protocol_hash"],
                "packet_hashes": packet_hashes,
            })
            score = score_template(protocol_path, pair, "formulation", "judge-1")
            for label in ("A", "B"):
                for entry in score["submissions"][label]["dimension_scores"].values():
                    entry["score"] = 3
                    entry["evidence"] = [{
                        "packet": f"submission_{label}.json",
                        "json_pointer": "/fact", "quote": f"evidence-formulation-{label}",
                    }]
                score["submissions"][label]["overall_score"] = 3
            score["preference"] = "tie"
            score["confidence"] = 0.8
            score_path = root / "score.json"
            write_json(score_path, score)
            self.assertEqual("passed", validate_score(protocol_path, pair, score_path)["status"])

    def test_defect_attribution_precedence(self) -> None:
        self.assertEqual("elicitation_failure", defect_attribution({"discovered_in_p1": False}))
        self.assertEqual("implementation_failure", defect_attribution({
            "discovered_in_p1": True, "retained_in_specification": True,
            "implemented_correctly": False,
        }))


if __name__ == "__main__":
    unittest.main()
