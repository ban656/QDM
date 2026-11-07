from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qdm.harness.core import (
    HarnessError,
    advance_phase,
    audit_harness,
    ingest_answer,
    init_harness,
    issue_question,
    load_ledger,
    record_model_call,
    register_artifact,
    run_code,
    save_ledger,
    seal_eligibility,
    sha256_path,
)


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.problem = self.root / "problem.txt"
        self.problem.write_text("Model the allocation of two resources under a budget.", encoding="utf-8")
        self.output = self.root / "run"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def init(self) -> None:
        init_harness(
            self.output, self.problem, [], "No supplied dataset; theoretical test case.",
            "answer-model", "questioner-model",
        )

    def force_execution_with_registered_code(self, script: Path) -> None:
        ledger = load_ledger(self.output)
        ledger["phase"] = "execution"
        ledger.setdefault("artifacts", {})["code"] = [{
            "kind": "code",
            "path": script.relative_to(self.output).as_posix(),
            "sha256": sha256_path(script),
            "bytes": script.stat().st_size,
            "registered_at": "2026-01-01T00:00:00+00:00",
            "metadata": {},
        }]
        save_ledger(self.output, ledger)

    def test_init_requires_data_or_reason(self) -> None:
        with self.assertRaises(HarnessError):
            init_harness(self.output, self.problem, [], "", "answer-model", "questioner-model")

    def test_zero_token_call_is_rejected(self) -> None:
        self.init()
        pending = issue_question(self.output)
        request = self.output / pending["request_path"]
        response = self.output / "claude_workspace" / "raw_answer.json"
        response.write_text("{" + "x" * 100 + "}", encoding="utf-8")
        with self.assertRaises(HarnessError):
            record_model_call(
                self.output, "answerer", "question_answer", request, response,
                "answer-model", "answer-model", "provider-1",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00", 0, 0,
                pending["round_id"],
            )

    def test_unavailable_telemetry_does_not_require_tokens(self) -> None:
        self.init()
        pending = issue_question(self.output)
        request = self.output / pending["request_path"]
        response = self.output / "claude_workspace" / "raw_answer.json"
        response.write_text("{" + "\"answer\":\"" + "x" * 100 + "\"}", encoding="utf-8")
        call = record_model_call(
            self.output, "answerer", "question_answer", request, response,
            "answer-model", "answer-model", "",
            "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00",
            None, None, pending["round_id"], "unavailable",
        )
        self.assertIsNone(call["total_tokens"])
        self.assertEqual("unavailable", call["telemetry_status"])

    def test_init_creates_contract_and_prevents_precomputed_paper(self) -> None:
        self.init()
        self.assertTrue((self.output / "contracts" / "auto_contract.json").is_file())
        paper = self.output / "claude_workspace" / "final" / "paper.md"
        paper.parent.mkdir(parents=True, exist_ok=True)
        paper.write_text("# Premature paper\n", encoding="utf-8")
        with self.assertRaises(HarnessError):
            register_artifact(self.output, "paper", paper, {"source_call_id": "call_0001"})

    def test_issue_question_syncs_history_log(self) -> None:
        self.init()
        issue_question(self.output)
        history = self.output / "claude_workspace" / "logs" / "question_history.jsonl"
        self.assertTrue(history.is_file())
        self.assertEqual(1, len(history.read_text(encoding="utf-8").splitlines()))

    def test_data_backed_run_rejects_code_that_never_reads_data(self) -> None:
        dataset = self.root / "data.csv"
        dataset.write_text("x,y\n1,2\n", encoding="utf-8")
        init_harness(
            self.output, self.problem, [dataset], "", "answer-model", "questioner-model",
        )
        script = self.output / "claude_workspace" / "final" / "code" / "model.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "# open(data) -- a comment is not data use\n"
            "import json, os\n"
            "inputs = json.loads(os.environ['QDM_DATA_MANIFEST'])\n"
            "print(json.dumps({'provenance': {'synthetic_data_used': False, "
            "'consumed_inputs': inputs}, 'results': {'value': 1}}))\n",
            encoding="utf-8",
        )
        self.force_execution_with_registered_code(script)
        with self.assertRaises(HarnessError):
            run_code(self.output, script, [dataset], 10)

    def test_data_backed_run_records_actual_file_read(self) -> None:
        dataset = self.root / "data.csv"
        dataset.write_text("x,y\n1,2\n", encoding="utf-8")
        init_harness(self.output, self.problem, [dataset], "", "answer-model", "questioner-model")
        script = self.output / "claude_workspace" / "final" / "code" / "model.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "import json, os\n"
            "inputs = json.loads(os.environ['QDM_DATA_MANIFEST'])\n"
            "with open(inputs[0]['path'], encoding='utf-8') as handle:\n"
            "    rows = len(handle.readlines()) - 1\n"
            "print(json.dumps({'provenance': {'synthetic_data_used': False, "
            "'consumed_inputs': inputs}, 'results': {'rows': rows}}))\n",
            encoding="utf-8",
        )
        self.force_execution_with_registered_code(script)
        manifest = run_code(self.output, script, [dataset], 10)
        self.assertEqual("passed", manifest["status"])
        self.assertEqual(str(dataset.resolve()), manifest["observed_data_reads"][0]["path"])

    def test_code_registration_snapshots_repairable_source(self) -> None:
        self.init()
        ledger = load_ledger(self.output)
        ledger["phase"] = "implementation"
        save_ledger(self.output, ledger)
        code_dir = self.output / "claude_workspace" / "final" / "code"
        code_dir.mkdir(parents=True, exist_ok=True)
        script = code_dir / "model.py"
        script.write_text(
            "import json\nprint(json.dumps({'provenance': {'synthetic_data_used': False, "
            "'consumed_inputs': []}, 'results': {'value': 1}}))\n",
            encoding="utf-8",
        )
        request = self.output / "claude_workspace" / "logs" / "implementation_request.md"
        response = self.output / "claude_workspace" / "logs" / "implementation_response.json"
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text("Implement the registered model from the frozen blueprint.", encoding="utf-8")
        response.write_text(json.dumps({
            "materialized_files": [{"path": "model.py", "sha256": sha256_path(script)}]
        }), encoding="utf-8")
        call = record_model_call(
            self.output, "answerer", "implementation", request, response,
            "answer-model", "answer-model", "implementation-snapshot",
            "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:02+00:00", 100, 100,
        )
        record = register_artifact(
            self.output, "code", code_dir, {"source_call_id": call["call_id"]}
        )
        self.assertNotEqual(code_dir.resolve(), (self.output / record["path"]).resolve())
        script.write_text("raise RuntimeError('edited after registration')\n", encoding="utf-8")
        ledger = load_ledger(self.output)
        ledger["phase"] = "execution"
        save_ledger(self.output, ledger)
        manifest = run_code(self.output, script, [], 10)
        self.assertEqual("passed", manifest["status"])
        self.assertIn("harness/code_snapshots/code_0001", manifest["script"])

    def test_role_stage_mismatch_is_rejected(self) -> None:
        self.init()
        pending = issue_question(self.output)
        request = self.output / pending["request_path"]
        response = self.output / "claude_workspace" / "review.txt"
        response.write_text("A reviewer response that is deliberately long enough for validation." * 2, encoding="utf-8")
        with self.assertRaises(HarnessError):
            record_model_call(
                self.output, "answerer", "answer_review", request, response,
                "answer-model", "answer-model", "provider-invalid-role",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00", 10, 10,
                pending["round_id"],
            )

    def test_audit_rejects_manually_completed_ledger(self) -> None:
        self.init()
        ledger = load_ledger(self.output)
        ledger["phase"] = "complete"
        save_ledger(self.output, ledger)
        issues = audit_harness(self.output)
        self.assertTrue(any("sequential phase transitions" in issue for issue in issues))

    def test_seal_refuses_repository_audit_failure(self) -> None:
        self.init()
        ledger = load_ledger(self.output)
        ledger["phase"] = "complete"
        save_ledger(self.output, ledger)
        failed = SimpleNamespace(returncode=1, stdout="[FAIL] missing evidence", stderr="")
        with patch("qdm.harness.core.audit_harness", return_value=[]), patch(
            "qdm.harness.core.subprocess.run", return_value=failed
        ):
            with self.assertRaisesRegex(HarnessError, "Repository audit failed"):
                seal_eligibility(self.output)

    def test_live_round_is_bound_to_answer_and_review_hashes(self) -> None:
        self.init()
        pending = issue_question(self.output)
        request = self.output / pending["request_path"]
        answer = self.output / "claude_workspace" / "raw_answer.json"
        answer_payload = {
            "round_id": pending["round_id"],
            "target_field": pending["field"],
            "direct_answer": "The boundary remains partial pending stakeholder scope.",
            "feature_updates": [{
                "field": pending["field"], "status": "partial", "summary": "Partial boundary",
                "items": [{"id": "pb1"}], "evidence": ["Problem sentence 1"],
                "open_questions": ["Which stakeholders are included?"], "confidence": 0.6,
            }],
            "algorithm_modules": [], "assumptions": [], "follow_up_questions": [],
        }
        answer.write_text(json.dumps(answer_payload), encoding="utf-8")
        answer_call = record_model_call(
            self.output, "answerer", "question_answer", request, answer,
            "answer-model", "answer-model-v1", "provider-answer-1",
            "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:02+00:00", 100, 80,
            pending["round_id"],
        )

        review_request = self.output / "questioner_workspace" / "requests" / "round_001.md"
        review_response = self.output / "questioner_workspace" / "responses" / "round_001.md"
        review_request.parent.mkdir(parents=True, exist_ok=True)
        review_response.parent.mkdir(parents=True, exist_ok=True)
        answer_hash = hashlib.sha256(answer.read_bytes()).hexdigest()
        review_request.write_text(
            f"Review answer SHA-256 {answer_hash}. Preserve all material risks. " * 3,
            encoding="utf-8",
        )
        review_response.write_text("The partial status is appropriate. Continue to the next narrow question." * 3, encoding="utf-8")
        review_call = record_model_call(
            self.output, "questioner", "answer_review", review_request, review_response,
            "questioner-model", "questioner-model", "provider-review-1",
            "2026-01-01T00:00:03+00:00", "2026-01-01T00:00:05+00:00", 120, 50,
            pending["round_id"],
        )
        decision = self.output / "questioner_workspace" / "decisions" / "round_001.json"
        decision.parent.mkdir(parents=True, exist_ok=True)
        decision.write_text(json.dumps({
            "round_id": pending["round_id"], "status": "continue",
            "questioner_model_requested": "questioner-model", "questioner_model_actual": "questioner-model",
            "raw_response_sha256": hashlib.sha256(review_response.read_bytes()).hexdigest(),
            "reviewed_answer_sha256": answer_hash,
            "stage": "answer_review", "impasse_type": "none",
            "reason": "Partial status is honest", "invalidated_items": [],
            "rollback_target": "", "next_question": "", "required_edits": [], "confidence": 0.9,
        }), encoding="utf-8")

        result = ingest_answer(self.output, answer, answer_call["call_id"], decision, review_call["call_id"])
        self.assertEqual("imported", result["status"])
        self.assertEqual([], audit_harness(self.output))

        answer.write_text(answer.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertTrue(any("hash mismatch" in issue for issue in audit_harness(self.output)))


if __name__ == "__main__":
    unittest.main()
