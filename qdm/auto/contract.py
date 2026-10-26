"""Autonomous benchmark-mode contract for QDM-Agent.

This module writes the machine-readable contract and prompt packets that
Claude Code should follow when running fair benchmark mode.  It does not call
Claude Code or Codex directly.
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
    "max_total_agent_turns": 40,
}

CODEX_MODEL_REQUESTED = "gpt-5.5"

STAGE_SEQUENCE = [
    "problem_ingestion",
    "qdm_question_loop",
    "clarity_gate",
    "modeling_tree_blueprint",
    "blueprint_review",
    "implementation",
    "result_impasse_check",
    "writing_freeze",
    "paper_generation",
    "evolution_proposal",
]

CODEX_DECISION_SCHEMA = {
    "round_id": 0,
    "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
    "stage": "",
    "codex_model_requested": CODEX_MODEL_REQUESTED,
    "codex_model_actual": "",
    "codex_model_note": "",
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

CODEX_EVOLUTION_SCHEMA = {
    "source_problem_id": "",
    "codex_model_requested": CODEX_MODEL_REQUESTED,
    "codex_model_actual": "",
    "codex_model_note": "",
    "distillation_summary": "",
    "question_patterns": [],
    "modeling_patterns": [],
    "algorithm_modules": [],
    "validation_questions": [],
    "writing_patterns": [],
    "policy_updates": [],
    "anti_patterns": [],
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
        "claude_artifacts": os.path.join(output, "claude_workspace", "artifacts"),
        "claude_writing": os.path.join(output, "claude_workspace", "writing"),
        "claude_writing_audits": os.path.join(output, "claude_workspace", "writing", "audits"),
        "claude_final": os.path.join(output, "claude_workspace", "final"),
        "codex_workspace": os.path.join(output, "codex_workspace"),
        "codex_questioner": os.path.join(output, "codex_workspace", "questioner"),
        "codex_questioner_requests": os.path.join(output, "codex_workspace", "questioner", "requests"),
        "codex_questioner_responses": os.path.join(output, "codex_workspace", "questioner", "responses"),
        "codex_questioner_decisions": os.path.join(output, "codex_workspace", "questioner", "decisions"),
        "codex_questioner_logs": os.path.join(output, "codex_workspace", "questioner", "logs"),
        "codex_evolver": os.path.join(output, "codex_workspace", "evolver"),
        "codex_evolver_requests": os.path.join(output, "codex_workspace", "evolver", "requests"),
        "codex_evolver_responses": os.path.join(output, "codex_workspace", "evolver", "responses"),
        "codex_evolver_distillations": os.path.join(output, "codex_workspace", "evolver", "distillations"),
        "codex_evolver_library_updates": os.path.join(output, "codex_workspace", "evolver", "library_updates"),
        "codex_evolver_logs": os.path.join(output, "codex_workspace", "evolver", "logs"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def build_auto_contract(
    problem_path: str,
    title: str = "",
    protocol_condition: str = "qdm_full",
) -> Dict[str, Any]:
    problem_text = read_text(problem_path)
    contract = {
        "schema_version": "qdm_auto_benchmark_v2",
        "created_at": now(),
        "mode": "benchmark_auto",
        "protocol_condition": protocol_condition,
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
            "claude_code": "primary autonomous solver and answer agent",
            "codex_doubt_gate": "automatic trigger that sends Claude uncertainty, bottlenecks, weak algorithm choices, and unsupported simplifications to Codex questioner before continuing",
            "codex_questioner": "automatic questioner, reviewer, adversarial checker, and impasse gate for the current problem",
            "codex_evolver": "post-run structural distiller that extracts reusable question/modeling patterns",
        },
        "codex_skills": {
            "requested_model": CODEX_MODEL_REQUESTED,
            "model_recording_rule": "request the fixed reviewer model, record provider-reported actual model, and do not relabel actual mismatches",
            "doubt_gate_skill": {
                "scope": "current_run_trigger_before_questioner",
                "skill_file": ".claude/skills/qdm-codex-doubt-gate/SKILL.md",
                "workspace": "codex_workspace/questioner/",
                "outputs": [
                    "requests/doubt_gate_*.md",
                    "responses/doubt_gate_*.md",
                    "decisions/doubt_gate_*.json",
                ],
                "triggers": [
                    "solver uncertainty",
                    "bottleneck or repeated code failure",
                    "weak formula-to-code traceability",
                    "random greedy heuristic grid-only optimizer",
                    "unsupported manual pruning",
                    "raw Codex risk about to be normalized away",
                ],
            },
            "questioner_skill": {
                "scope": "current_run_only",
                "skill_file": ".claude/skills/qdm-codex-questioner/SKILL.md",
                "workspace": "codex_workspace/questioner/",
                "outputs": [
                    "requests/*.md",
                    "responses/*.md",
                    "decisions/*.json",
                    "logs/*.jsonl",
                ],
                "forbidden": [
                    "must not write evolution library updates",
                    "must not produce post-run reusable patterns",
                    "must not overwrite Claude solver artifacts",
                ],
            },
            "evolver_skill": {
                "scope": "cross_run_learning_after_solution",
                "skill_file": ".claude/skills/qdm-codex-evolver/SKILL.md",
                "workspace": "codex_workspace/evolver/",
                "outputs": [
                    "requests/*.md",
                    "responses/*.md",
                    "distillations/*.json",
                    "library_updates/*.json",
                    "logs/*.jsonl",
                ],
                "forbidden": [
                    "must not change current-run accept/reject decisions",
                    "must not repair current formulas or code",
                    "must not overwrite questioner decisions",
                ],
            },
        },
        "workspace_layout": {
            "contracts": {
                "path": "contracts/",
                "owner": "shared_read_only",
                "purpose": "benchmark contract, prompt packet, and schemas",
            },
            "claude_workspace": {
                "path": "claude_workspace/",
                "owner": "claude_code",
                "purpose": "solver state, question history, implementation artifacts, final paper",
            },
            "codex_workspace": {
                "path": "codex_workspace/",
                "owner": "codex",
                "purpose": "parent directory for separated questioner and evolver workspaces",
            },
            "codex_questioner_workspace": {
                "path": "codex_workspace/questioner/",
                "owner": "codex_questioner",
                "purpose": "current-run questions, reviews, impasse decisions, and rollback gates",
            },
            "codex_evolver_workspace": {
                "path": "codex_workspace/evolver/",
                "owner": "codex_evolver",
                "purpose": "post-run structural distillation and reusable pattern proposals",
            },
        },
        "write_policy": {
            "claude_code_may_write": ["claude_workspace/"],
            "codex_questioner_may_write": ["codex_workspace/questioner/"],
            "codex_evolver_may_write": ["codex_workspace/evolver/"],
            "shared_read_only": ["contracts/"],
            "forbidden": [
                "claude_code must not overwrite codex_workspace artifacts",
                "codex_questioner must not write codex_workspace/evolver",
                "codex_evolver must not write codex_workspace/questioner",
                "codex must not overwrite claude_workspace solver artifacts",
                "final artifacts must be produced from claude_workspace with codex decisions cited by path",
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
                "rule": "material risks in raw Codex responses must become local_fix/re_question/rollback or explicit required_edits with acceptance conditions",
            },
            "traceability_gate": {
                "required": True,
                "rule": "Before implementation, load constraint_spec.json and produce claude_workspace/tradeoff_ledger.md. The ledger must list every equation/variable/constraint from the spec and confirm it is preserved in the code, or document why not. A ledger with zero equations traced is invalid.",
            },
        },
        "codex_decision_schema": CODEX_DECISION_SCHEMA,
        "codex_evolution_schema": CODEX_EVOLUTION_SCHEMA,
        "stop_conditions": [
            "clarity_gate_ready_and_blueprint_accepted",
            "final_paper_generated",
            "max_total_agent_turns_reached",
            "max_impasse_rollbacks_reached",
            "unrecoverable_schema_failure",
            "codex_plugin_unavailable",
            "telemetry_unavailable",
            "writing_freeze_failed",
        ],
        "required_artifacts": {
            "harness_ledger": "harness/ledger.json",
            "harness_events": "harness/events.jsonl",
            "state": "claude_workspace/state/modeling_state.json",
            "question_history": "claude_workspace/logs/question_history.jsonl",
            "codex_questioner_requests": "codex_workspace/questioner/requests/*.md",
            "codex_questioner_responses": "codex_workspace/questioner/responses/*.md",
            "codex_questioner_decisions": "codex_workspace/questioner/decisions/*.json",
            "codex_evolver_requests": "codex_workspace/evolver/requests/*.md",
            "codex_evolver_responses": "codex_workspace/evolver/responses/*.md",
            "codex_evolver_distillations": "codex_workspace/evolver/distillations/*.json",
            "codex_evolver_library_updates": "codex_workspace/evolver/library_updates/*.json",
            "frozen_numbers": "claude_workspace/writing/frozen_numbers.json",
            "solution_package_for_writer": "claude_workspace/writing/solution_package_for_writer.md",
            "result_consistency_report": "claude_workspace/writing/audits/result_consistency_report.md",
            "blueprint": "claude_workspace/final/modeling_blueprint.json",
            "formalization": "claude_workspace/final/formalization_package.json",
            "code": "claude_workspace/final/code/",
            "results": "claude_workspace/final/results.md",
            "paper": "claude_workspace/final/paper.md",
            "evolution_proposal": "claude_workspace/final/evolution_proposal.json",
            "run_summary": "claude_workspace/final/run_summary.json",
            "tradeoff_ledger": "claude_workspace/tradeoff_ledger.md",
        },
    }
    if protocol_condition == "mm_agent_native":
        contract["required_artifacts"].pop("question_history", None)
        contract["required_artifacts"].pop("codex_questioner_decisions", None)
        contract["required_artifacts"]["protocol_trace"] = "claude_workspace/final/native_protocol_trace.json"
        contract["stop_conditions"][0] = "native_protocol_trace_and_formalization_frozen"
    elif protocol_condition == "qdm_self_ask":
        # Self-ask ablation: a single agent with no questioner, no reviewer,
        # and no evolver. The answerer asks itself clarifying questions in its
        # own full context, fills every field in one round, and self-declares
        # the decision (single-round ablation semantics).
        contract["roles"] = {
            "claude_code": (
                "self-asking solver: asks itself clarifying questions (free-form, "
                "no prescribed types, no context isolation), answers them itself, "
                "fills the full feature table in one round, and self-declares the "
                "decision; no external questioner, reviewer, or evolver exists"
            ),
        }
        contract["codex_skills"] = {"disabled": True}
        for label in (
            "codex_questioner_requests", "codex_questioner_responses",
            "codex_questioner_decisions", "codex_evolver_requests",
            "codex_evolver_responses", "codex_evolver_distillations",
            "codex_evolver_library_updates", "evolution_proposal",
        ):
            contract["required_artifacts"].pop(label, None)
        contract["stop_conditions"] = [
            "clarity_gate_ready_and_blueprint_accepted",
            "final_paper_generated",
            "max_total_agent_turns_reached",
            "max_impasse_rollbacks_reached",
            "unrecoverable_schema_failure",
            "telemetry_unavailable",
            "writing_freeze_failed",
        ]
        contract["quality_gates"].pop("normalization_integrity", None)
    return contract


def _build_self_ask_auto_prompt(contract: Dict[str, Any]) -> str:
    """Autonomous prompt for the qdm_self_ask ablation: single-agent, no Codex."""
    return f"""# Protocol-Level Autonomous Benchmark Run — qdm_self_ask Ablation

You are Claude Code running condition `qdm_self_ask` in fully autonomous
benchmark mode. You are the ONLY agent in this run: there is no Codex
questioner, no reviewer, and no evolver. Human input is restricted to
launching this run and providing the problem. Do not call any `/codex:*`
command and do not ask the human to approve intermediate answers, formulas,
code repairs, or final selection.

## Contract

```json
{json.dumps(contract, ensure_ascii=False, indent=2)}
```

## Required Loop

1. Use `qdm-benchmark-harness` and initialize its append-only ledger with
   `--protocol-condition qdm_self_ask --experiment-mode one_shot`. No reviewer
   model is configured: pass the answerer model and a reporter model.
2. `issue-question` once. The generated self-ask prompt asks you to clarify the
   problem by asking yourself whatever questions you consider necessary —
   free-form, no prescribed types, in your own full context (no isolation) —
   and to fill every required feature field in ONE response.
3. Produce the raw answer JSON: every required field substantive with
   `clear`/`assumption_based` discipline, `self_asked_questions` recording the
   questions you asked yourself and your answers, `self_declared_decision`
   with `self_declared: true` (status `continue` only when both gates would
   pass), and `questions_for_codex` empty. Record the answerer call with stage
   `question_answer`.
4. `ingest-self-answer` with the self-declared decision file. There is no
   reviewer call. Any status other than `continue` means the single-round
   interview gate failed: record the ablation as an interview-gate failure and
   `stop-run`; never repair with a second elicitation round.
5. Advance sequentially: specification (constraint spec + method-neutral P1 via
   the neutral reporter, never fed back to you), blueprint (NO review),
   implementation (code + Traceability Ledger at
   `claude_workspace/tradeoff_ledger.md`), execution (`run-code` with frozen
   data inputs; results + freeze, NO result review), writing (writing freeze
   adapter, then paper from frozen numbers), complete. Do not call
   `make-review-request`; do not generate any evolution artifact.
6. Run the harness audit and the repository audit, then `seal` if they pass.

## Output Discipline

Every decision must be reproducible from files. Keep all solver artifacts in
`claude_workspace/`. The run summary's `codex_plugin_cc_available` is false
and `decision_method` is `qdm-benchmark-harness-self-ask`: never claim Codex
participation that did not happen.
"""


def build_claude_auto_prompt(contract: Dict[str, Any]) -> str:
    condition = contract.get("protocol_condition", "qdm_full")
    if condition == "qdm_self_ask":
        return _build_self_ask_auto_prompt(contract)
    protocol_loop = (
        "Use the native MM-Agent protocol. Do not call the QDM issue-question command. "
        "Record every native model turn with stage native_protocol, freeze the complete "
        "pre-solution trace, and emit method-neutral P1 without feeding P1 back to the solver."
        if condition == "mm_agent_native"
        else
        "Ask and answer QDM structural questions one live call at a time until both gates pass. "
        "Then freeze the constraint specification and method-neutral P1 before blueprint generation."
    )
    return f"""# Protocol-Level Autonomous Benchmark Run

You are Claude Code running condition `{condition}` in fully autonomous benchmark mode.

Human input is restricted to launching this run and providing the problem.  Do
not ask the human to approve intermediate answers, rollback decisions, modeling
routes, formulas, code repairs, or final selection.

Use Codex through `codex-plugin-cc` with requested reviewer model
`{CODEX_MODEL_REQUESTED}` when available.  Do not rely on plugin defaults or
accept an unrecorded model.  In every normalized decision or distillation JSON,
record `codex_model_requested`, `codex_model_actual`, and, when they differ,
`codex_model_note`.  Provider routing may report an actual model name different
from the requested model; preserve that name instead of relabeling it.  The call
is invalid only if the requested model was not fixed or the actual model was not
    recorded. If `/codex:*` commands or provider telemetry are unavailable, write
    the intended request only as a failure artifact and stop. Never create a
    normalized fallback decision. Unavailable live review is a blocking failure,
    not a valid final run.

Codex has two separated skills:

- Doubt gate skill: trigger current-run Codex review when Claude is unsure,
  stuck, using a weak solver, or about to normalize away a risk.  Write under
  `codex_workspace/questioner/`.
- Questioner skill: current-run clarification, review, impasse detection, and
  rollback decisions.  Write only under `codex_workspace/questioner/`.
- Evolver skill: post-run structural distillation and reusable pattern
  proposals.  Write only under `codex_workspace/evolver/`.

## Contract

```json
{json.dumps(contract, ensure_ascii=False, indent=2)}
```

## Required Loop

1. Use `qdm-benchmark-harness` and initialize its append-only ledger.
2. {protocol_loop}
3. At each stage boundary, call Codex for automatic review:
   - answer review: `/codex:adversarial-review`
   - blueprint review: `/codex:adversarial-review`
   - impasse or stuck state: `/codex:rescue`
   Every live Codex call must request `{CODEX_MODEL_REQUESTED}` explicitly and
   record both requested and provider-reported actual model fields.
   Before proceeding, also trigger the doubt gate whenever Claude is unsure,
   reaches a bottleneck, proposes random/greedy/heuristic/grid-only search, or
   uses unsupported pruning such as "only X can contribute".
4. Store questioner packets under `codex_workspace/questioner/`:
   - requests: `requests/*.md`
   - raw responses: `responses/*.md`
   - normalized decisions: `decisions/*.json`
5. Apply Codex questioner decisions automatically according to status.
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
   - Missing fields require `local_fix`, `re_question`, or `rollback`.
7. Generate final blueprint, code/results when possible, and implementation
   artifacts under `claude_workspace/final/`.  Before finalizing the code, load
   `claude_workspace/final/constraint_spec.json` and produce a Traceability Ledger
   at `claude_workspace/tradeoff_ledger.md` that traces every equation, variable,
   and constraint from the spec into the code.  If something is simplified or
   omitted, the ledger must document the trade-off reason.
8. Before writing paper claims, run the writing freeze adapter:
   `python qdm/writing/freeze.py --workspace <output dir>`.
   It must create:
   - `claude_workspace/writing/frozen_numbers.json`
   - `claude_workspace/writing/solution_package_for_writer.md`
   - `claude_workspace/writing/audits/result_consistency_report.md`
9. Write `claude_workspace/final/paper.md` only from the solution package and
   frozen numbers, as a full-depth engineering report built from the run's
   own artifacts: each problem task answered as its own chapter (task
   description, modeling analysis, formulas, modeling process with
   numerical/algorithmic implementation detail, results with tables and
   chart specifications), with engineering detail and depth carried to the
   level of the implemented model (state-space equations, discretization,
   observation models, algorithm parameters, uncertainty measures, exact
   run numbers).
10. After final artifacts exist, call the Codex evolver for structural
   distillation.  Store evolver packets under `codex_workspace/evolver/`:
   - requests: `requests/*.md`
   - raw responses: `responses/*.md`
   - distillations: `distillations/*.json`
   - proposed library updates: `library_updates/*.json`

## Output Discipline

Every important decision must be reproducible from files.  Keep Claude Code
solver artifacts in `claude_workspace/`, Codex questioner artifacts in
`codex_workspace/questioner/`, and Codex evolver artifacts in
`codex_workspace/evolver/`.  Write a final
`claude_workspace/final/run_summary.json` explaining all turns, rollbacks,
failed modules, Codex availability, requested/actual Codex model, freeze
status, and stop condition.
"""


def build_codex_questioner_request(stage: str, context: str = "") -> str:
    return f"""# QDM Auto Codex Questioner Review

Act as Codex inside QDM-Agent benchmark mode.  You are not a human supervisor;
you are the current-run questioner/reviewer/impasse gate.  Return only a JSON
decision matching the questioner schema.

Requested reviewer model: `{CODEX_MODEL_REQUESTED}`.  Record both
`codex_model_requested` and provider-reported `codex_model_actual`.  If the
actual name differs, keep the actual name and explain the provider mapping in
`codex_model_note`; do not relabel it.

This request belongs in `codex_workspace/questioner/requests/`.  The raw Codex
answer belongs in `codex_workspace/questioner/responses/`, and the normalized
JSON decision belongs in `codex_workspace/questioner/decisions/`.

Do not distill reusable cross-run patterns here.  That belongs to the evolver
skill after the current run has final artifacts.

Stage: `{stage}`

Context:

{context}

Decision schema:

```json
{json.dumps(CODEX_DECISION_SCHEMA, ensure_ascii=False, indent=2)}
```
"""


def build_codex_evolver_request(context: str = "") -> str:
    return f"""# QDM Auto Codex Evolver Distillation

Act as Codex inside QDM-Agent benchmark mode.  You are the post-run structural
evolver, not the current-run solver and not the current-run questioner.

Requested reviewer model: `{CODEX_MODEL_REQUESTED}`.  Record both
`codex_model_requested` and provider-reported `codex_model_actual`.  If the
actual name differs, keep the actual name and explain the provider mapping in
`codex_model_note`; do not relabel it.

Your job is to inspect the completed solution, question history, blueprint,
results, paper draft, and questioner decisions, then distill reusable
question/modeling structures for future tasks.

This request belongs in `codex_workspace/evolver/requests/`.  The raw Codex
answer belongs in `codex_workspace/evolver/responses/`, and the normalized
distillation JSON belongs in `codex_workspace/evolver/distillations/`.

Do not change the current run's accept/reject decisions, formulas, code, or
final results.  Only propose reusable future-facing structures.

Context:

{context}

Distillation schema:

```json
{json.dumps(CODEX_EVOLUTION_SCHEMA, ensure_ascii=False, indent=2)}
```
"""


def build_workspace_readme(contract: Dict[str, Any], workspace: str) -> str:
    return f"""# QDM Auto Benchmark Workspace

Title: {contract["title"]}

This workspace is for fully autonomous benchmark execution.

Human decisions are forbidden during intermediate modeling.  All question
selection, acceptance, rollback, blueprint revision, code repair, and final
selection must be made by the Claude/Codex agent pair and recorded in files.

Workspace ownership:

```text
contracts/          shared read-only contract and prompt packets
claude_workspace/   Claude Code state, logs, solver artifacts, final outputs
codex_workspace/questioner/
                    Codex current-run questions, reviews, decisions
codex_workspace/evolver/
                    Codex post-run distillation and pattern proposals
claude_workspace/writing/
                    Frozen numbers and writer package before paper text
```

Start Claude Code in this project and use:

```text
/qdm:auto-benchmark {os.path.abspath(contract["problem"]["path"])}
```

or paste `contracts/claude_auto_prompt.md` into Claude Code.

After a run, audit the workspace:

```powershell
python qdm/auto/audit.py --workspace {os.path.abspath(workspace)}
```
"""


def write_auto_workspace(
    problem: str,
    output: str,
    title: str = "",
    protocol_condition: str = "qdm_full",
) -> Dict[str, str]:
    dirs = ensure_auto_workspace(output)
    contract = build_auto_contract(problem, title=title, protocol_condition=protocol_condition)
    contract_path = os.path.join(dirs["contracts"], "auto_contract.json")
    prompt_path = os.path.join(dirs["contracts"], "claude_auto_prompt.md")
    questioner_template_path = os.path.join(dirs["contracts"], "codex_questioner_request_template.md")
    evolver_template_path = os.path.join(dirs["contracts"], "codex_evolver_request_template.md")
    write_json(contract_path, contract)
    write_text(prompt_path, build_claude_auto_prompt(contract))
    write_text(questioner_template_path, build_codex_questioner_request("<stage>", "<context>"))
    write_text(evolver_template_path, build_codex_evolver_request("<context>"))
    write_text(os.path.join(dirs["root"], "README.md"), build_workspace_readme(contract, output))
    return {
        "contract": contract_path,
        "claude_prompt": prompt_path,
        "codex_questioner_template": questioner_template_path,
        "codex_evolver_template": evolver_template_path,
        "workspace": output,
        "claude_workspace": dirs["claude_workspace"],
        "codex_workspace": dirs["codex_workspace"],
        "codex_questioner_workspace": dirs["codex_questioner"],
        "codex_evolver_workspace": dirs["codex_evolver"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare QDM autonomous benchmark workspace.")
    parser.add_argument("--problem", required=True, help="UTF-8 problem text file.")
    parser.add_argument("--output", required=True, help="Auto benchmark workspace.")
    parser.add_argument("--title", default="", help="Run title.")
    parser.add_argument(
        "--protocol-condition",
        choices=["qdm_full", "mm_agent_native", "qdm_self_ask"],
        default="qdm_full",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = write_auto_workspace(args.problem, args.output, args.title, args.protocol_condition)
    print(json.dumps(paths, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
