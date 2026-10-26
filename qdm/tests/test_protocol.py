from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qdm.protocol import (
    FEATURE_FIELDS,
    feature_entry_issues,
    init_workspace,
    load_state,
    save_state,
    update_feature_entry,
    write_blueprint_prompt,
)


class ProtocolGateTests(unittest.TestCase):
    def test_open_question_blocks_self_declared_clear(self) -> None:
        entry = {
            "status": "clear",
            "summary": "A substantive field",
            "items": [{"id": "x"}],
            "evidence": ["Problem statement section 2"],
            "open_questions": ["What is the actual parameter value?"],
            "confidence": 0.9,
        }
        self.assertIn("1 unresolved open question(s)", feature_entry_issues("variables", entry))

    def test_data_support_requires_traceable_source(self) -> None:
        entry = {
            "status": "clear",
            "summary": "Data are available",
            "items": [{"id": "dataset"}],
            "evidence": ["Attachment table 1"],
            "open_questions": [],
            "confidence": 0.9,
        }
        self.assertTrue(any("traceable" in issue for issue in feature_entry_issues("data_support", entry)))
        entry["items"][0]["path"] = "dataset/table.csv"
        self.assertEqual([], feature_entry_issues("data_support", entry))

    def test_status_can_downgrade_after_new_evidence(self) -> None:
        entry = {
            "status": "clear", "summary": "old", "items": [], "evidence": [],
            "open_questions": [], "confidence": 0.9, "updated_by_round": [],
        }
        update_feature_entry(entry, {"status": "assumption_based", "summary": "unsupported"}, 2)
        self.assertEqual("assumption_based", entry["status"])

    def test_blueprint_is_blocked_before_gates_and_constraint_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            problem = root / "problem.txt"
            problem.write_text("Model a small system.", encoding="utf-8")
            workspace = root / "workspace"
            init_workspace(str(problem), str(workspace), "test")
            with self.assertRaises(RuntimeError):
                write_blueprint_prompt(str(workspace))

    def test_both_gates_require_traceable_data_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            problem = root / "problem.txt"
            problem.write_text("Model a small system.", encoding="utf-8")
            workspace = root / "workspace"
            init_workspace(str(problem), str(workspace), "test")
            state = load_state(str(workspace))
            for field, spec in FEATURE_FIELDS.items():
                if not spec["required"]:
                    continue
                item = {"id": field}
                if field == "variables":
                    item.update({"symbol": "x", "type": "parameter", "unit": "1"})
                state["feature_table"][field].update({
                    "status": "clear", "summary": f"Clear {field}", "items": [item],
                    "evidence": ["Problem section 1"], "open_questions": [], "confidence": 0.9,
                })
            save_state(str(workspace), state)
            state = load_state(str(workspace))
            self.assertFalse(state["clarity_gate"]["ready_for_modeling"])
            self.assertFalse(state["question_gate"]["ready_for_modeling"])

            state["feature_table"]["data_support"]["items"][0]["assumption"] = "No supplied dataset"
            save_state(str(workspace), state)
            state = load_state(str(workspace))
            self.assertTrue(state["clarity_gate"]["ready_for_modeling"])
            self.assertTrue(state["question_gate"]["ready_for_modeling"])


if __name__ == "__main__":
    unittest.main()
