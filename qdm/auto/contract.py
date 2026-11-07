"""Autonomous benchmark-mode contract for QDM.

This module writes the machine-readable contract and the prompt packet that the
modeler (a Claude Code session) follows in a benchmark run.  It does not call
any model itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Any, Dict


DEFAULT_LIMITS = {
    "max_question_rounds": 20,
    "max_impasse_rollbacks": 3,
    "max_blueprint_revisions": 3,
    "max_code_repair_rounds": 5,
    "max_total_agent_calls": 70,
}

STAGE_SEQUENCE = [
    "problem_ingestion",
    "qdm_question_loop",
    "clarity_gate",
    "constraint_specification",
    "modeling_blueprint",
    "blueprint_review",
    "implementation",
    "result_review",
    "writing_freeze",
    "paper_generation",
]

QUESTIONER_DECISION_SCHEMA = {
    "round_id": 0,
    "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
    "stage": "",
    "questioner_model_requested": "",
    "questioner_model_actual": "",
    "raw_response_sha256": "",
    "reviewed_answer_sha256": "",
    "reason": "",
    "impasse_type": "none | information | structural | formula | algorithmic | numerical | narrative",
    "invalidated_items": [],
    "rollback_target": "",
    "next_question": "",
    "required_edits": [],
    "confidence": 0.0,
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def sanitize(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value.strip())
    return value.strip("_") or "qdm_auto_run"


def ensure_auto_workspace(output: str) -> Dict[str, str]:
    dirs = {
        "root": output,
        "contracts": os.path.join(output, "contracts"),
        "claude_workspace": os.path.join(output, "claude_workspace"),
        "claude_state": os.path.join(output, "claude_workspace", "state"),
        "claude_logs": os.path.join(output, "claude_workspace", "logs"),
        "claude_planning": os.path.join(output, "claude_workspace", "planning"),
        "claude_writing": os.path.join(output, "claude_workspace", "writing"),
        "claude_writing_audits": os.path.join(output, "claude_workspace", "writing", "audits"),
        "claude_final": os.path.join(output, "claude_workspace", "final"),
        "questioner_workspace": os.path.join(output, "questioner_workspace"),
        "questioner_requests": os.path.join(output, "questioner_workspace", "requests"),
        "questioner_responses": os.path.join(output, "questioner_workspace", "responses"),
        "questioner_decisions": os.path.join(output, "questioner_workspace", "decisions"),
        "questioner_logs": os.path.join(output, "questioner_workspace", "logs"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def build_auto_contract(problem_path: str, title: str = "") -> Dict[str, Any]:
    problem_text = read_text(problem_path)
    return {
        "schema_version": "qdm_auto_benchmark_v2",
        "created_at": now(),
        "mode": "benchmark_auto",
        "title": title or sanitize(os.path.basename(problem_path)),
        "problem": {
            "path": os.path.abspath(problem_path),
            "text": problem_text,
        },
        "fairness_rule": {
            "human_allowed": [
                "provide_problem",
                "provide_attachments",
                "launch_run",
                "inspect_final_outputs",
            ],
            "human_forbidden": [
                "accept_or_reject_intermediate_answer",
                "choose_next_question",
                "choose_modeling_route",
                "approve_rollback",
                "repair_formula_or_code",
                "select_final_result",
            ],
        },
        "roles": {
            "modeler": "writes the planning drafts, answers every question, and writes the specification, blueprint, code and paper",
            "questioner": "a separate model call that sees the problem, the written draft, the specification and the question history but not the modeler's reasoning; asks the questions and reviews every answer, the blueprint and the results; writes no artifact",
        },
        "workspace_layout": {
            "contracts": {
                "path": "contracts/",
                "owner": "shared_read_only",
                "purpose": "benchmark contract and prompt packet",
            },
            "claude_workspace": {
                "path": "claude_workspace/",
                "owner": "modeler",
                "purpose": "modeling state, question history, planning drafts, implementation artifacts, final paper",
            },
            "questioner_workspace": {
                "path": "questioner_workspace/",
                "owner": "questioner",
                "purpose": "question and review requests, raw questioner responses, normalized decisions",
            },
        },
        "write_policy": {
            "modeler_may_write": ["claude_workspace/"],
            "questioner_may_write": ["questioner_workspace/"],
            "shared_read_only": ["contracts/"],
            "forbidden": [
                "the modeler must not overwrite questioner_workspace artifacts",
                "the questioner must not overwrite claude_workspace artifacts",
                "final artifacts are produced from claude_workspace with questioner decisions cited by path",
            ],
        },
        "stage_sequence": STAGE_SEQUENCE,
        "limits": DEFAULT_LIMITS,
        "quality_gates": {
            "constraint_ledger": {
                "required": True,
                "rule": "feature_table.constraints.items must contain explicit constraint items with id/text/type/scope/checked_by/failure_action; round-label-only placeholders are invalid",
            },
            "algorithm_choice_gate": {
                "required": True,
                "required_fields": [
                    "solver_family",
                    "problem_structure",
                    "why_this_solver",
                    "why_not_random_or_greedy",
                    "constraint_handling",
                    "determinism",
                    "global_or_local_claim",
                    "acceptance_metric",
                    "fallback_solver",
                ],
                "extra_fields_for_heuristics": [
                    "seed_or_determinism",
                    "budget",
                    "multi_start_or_grid_resolution",
                    "convergence_or_resolution_check",
                    "baseline_comparison",
                    "failure_condition",
                    "rollback_target",
                ],
                "heuristic_terms": [
                    "random",
                    "greedy",
                    "heuristic",
                    "grid-only",
                    "manual pruning",
                    "only can contribute",
                ],
            },
            "normalization_integrity": {
                "required": True,
                "rule": "material risks in raw questioner responses must become local_fix/re_question/rollback or explicit required_edits with acceptance conditions",
            },
            "traceability_gate": {
                "required": True,
                "rule": "Before implementation, load constraint_spec.json and produce claude_workspace/tradeoff_ledger.md. The ledger must list every equation/variable/constraint from the spec and confirm it is preserved in the code, or document why not. A ledger with zero equations traced is invalid.",
            },
        },
        "questioner_decision_schema": QUESTIONER_DECISION_SCHEMA,
        "stop_conditions": [
            "final_paper_generated",
            "max_total_agent_calls_reached",
            "max_impasse_rollbacks_reached",
            "unrecoverable_schema_failure",
            "questioner_unavailable",
            "writing_freeze_failed",
        ],
        "required_artifacts": {
            "harness_ledger": "harness/ledger.json",
            "harness_events": "harness/events.jsonl",
            "state": "claude_workspace/state/modeling_state.json",
            "question_history": "claude_workspace/logs/question_history.jsonl",
            "questioner_requests": "questioner_workspace/requests/*.md",
            "questioner_responses": "questioner_workspace/responses/*.md",
            "questioner_decisions": "questioner_workspace/decisions/*.json",
            "frozen_numbers": "claude_workspace/writing/frozen_numbers.json",
            "solution_package_for_writer": "claude_workspace/writing/solution_package_for_writer.md",
            "blueprint": "claude_workspace/final/modeling_blueprint.json",
            "code": "claude_workspace/final/code/",
            "results": "claude_workspace/final/results.md",
            "paper": "claude_workspace/final/paper.md",
            "run_summary": "claude_workspace/final/run_summary.json",
            "tradeoff_ledger": "claude_workspace/tradeoff_ledger.md",
        },
    }


def build_claude_auto_prompt(contract: Dict[str, Any]) -> str:
    return f"""# QDM Autonomous Benchmark Run

You are the modeler in a fully autonomous QDM benchmark run.

Human input is restricted to launching this run and providing the problem.  Do
not ask the human to approve intermediate answers, rollback decisions, modeling
routes, formulas, code repairs, or final selection.

The questioner is a separate model call made with
`python -m qdm.harness.claude_peer <request> <response>`.  It starts from the
request file alone: it sees the problem, your written planning draft, the
specification and the question history, never your reasoning.  Record the
requested and provider-reported model of every questioner call.  If the
questioner cannot be called, write the intended request as a failure artifact
and stop; never write a questioner decision yourself.

## Contract

```json
{json.dumps(contract, ensure_ascii=False, indent=2)}
```

## Required Loop

1. Use the `qdm-benchmark-harness` skill and initialize its append-only ledger.
2. Interview, one round at a time, until both gates pass:
   - write a planning draft under `claude_workspace/planning/` that separates
     what the statement fixes, what you infer and what you assume;
   - call the questioner (stage `question_generation`) for one to three
     questions on the highest-priority field, and issue them with
     `issue-question --question-file`;
   - answer only what was asked (stage `question_answer`);
   - call the questioner to review the answer (stage `answer_review`) and
     apply its decision exactly as returned.
3. Freeze the constraint specification, write the blueprint from it, and have
   the questioner review the blueprint with `make-review-request`.
4. Implement the blueprint.  Before finalizing the code, load
   `claude_workspace/final/constraint_spec.json` and produce a Traceability
   Ledger at `claude_workspace/tradeoff_ledger.md` that traces every equation,
   variable, and constraint into the code; document every simplification or
   omission with its reason.
5. Run the code through `run-code` with the frozen inputs, register the
   results and the freeze, and have the questioner review the results.
6. Maintain quality gates:
   - `feature_table.constraints.items` must contain explicit checkable
     constraints, not only round labels.
   - Every optimization module must document solver family, problem structure,
     constraint handling, determinism, global/local claim, acceptance metric,
     and fallback.
   - Random, greedy, heuristic, grid-only, or manually pruned methods require
     seed/determinism, budget, restart or resolution policy,
     convergence/resolution check, baseline comparison, failure condition, and
     rollback target.
7. Before writing paper claims, run the writing freeze adapter:
   `python qdm/writing/freeze.py --workspace <output dir>`.
   It must create:
   - `claude_workspace/writing/frozen_numbers.json`
   - `claude_workspace/writing/solution_package_for_writer.md`
8. Write `claude_workspace/final/paper.md` only from the solution package and
   frozen numbers, as a full-depth report built from the run's own artifacts:
   each problem task answered as its own chapter (task description, modeling
   analysis, formulas, modeling process with numerical/algorithmic
   implementation detail, results with tables and chart specifications).
9. Advance to complete, run the harness audit and the repository audit, then
   `seal`.

## Output Discipline

Every important decision must be reproducible from files.  Keep modeler
artifacts in `claude_workspace/` and questioner packets in
`questioner_workspace/`.  The run summary is generated by the harness from the
ledger; never edit it by hand.
"""


def build_questioner_request(stage: str, context: str = "") -> str:
    return f"""# QDM Questioner Request

You are the questioner of a QDM run.  You see the problem, the modeler's written
draft, the current specification and the question history; you do not see the
modeler's reasoning.  Ask about, or review, what is written.  Return only a JSON
decision matching the schema below.

Stage: `{stage}`

Context:

{context}

Decision schema:

```json
{json.dumps(QUESTIONER_DECISION_SCHEMA, ensure_ascii=False, indent=2)}
```
"""


def build_workspace_readme(contract: Dict[str, Any], workspace: str) -> str:
    return f"""# QDM Benchmark Workspace

Title: {contract["title"]}

This workspace is for a fully autonomous benchmark run.  All question
selection, acceptance, rollback, blueprint revision, code repair, and final
selection are made by the modeler and the questioner and recorded in files.

```text
contracts/              shared read-only contract and prompt packet
claude_workspace/       modeler state, logs, drafts, artifacts, final outputs
questioner_workspace/   questioner requests, raw responses, decisions
harness/                ledger, events, snapshots, executions
```

Start Claude Code in the repository and run:

```text
/qdm:auto-benchmark {os.path.abspath(contract["problem"]["path"])}
```

After a run, audit the workspace:

```bash
python qdm/auto/audit.py --workspace {os.path.abspath(workspace)}
```
"""


def write_auto_workspace(problem: str, output: str, title: str = "") -> Dict[str, str]:
    dirs = ensure_auto_workspace(output)
    contract = build_auto_contract(problem, title=title)
    contract_path = os.path.join(dirs["contracts"], "auto_contract.json")
    prompt_path = os.path.join(dirs["contracts"], "claude_auto_prompt.md")
    questioner_template_path = os.path.join(dirs["contracts"], "questioner_request_template.md")
    write_json(contract_path, contract)
    write_text(prompt_path, build_claude_auto_prompt(contract))
    write_text(questioner_template_path, build_questioner_request("<stage>", "<context>"))
    write_text(os.path.join(dirs["root"], "README.md"), build_workspace_readme(contract, output))
    return {
        "contract": contract_path,
        "claude_prompt": prompt_path,
        "questioner_template": questioner_template_path,
        "workspace": output,
        "claude_workspace": dirs["claude_workspace"],
        "questioner_workspace": dirs["questioner_workspace"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a QDM autonomous benchmark workspace.")
    parser.add_argument("--problem", required=True, help="UTF-8 problem text file.")
    parser.add_argument("--output", required=True, help="Benchmark workspace.")
    parser.add_argument("--title", default="", help="Run title.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = write_auto_workspace(args.problem, args.output, args.title)
    print(json.dumps(paths, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
