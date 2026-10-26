"""Command-line interface for the verifiable QDM benchmark harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import (
    HarnessError,
    advance_phase,
    audit_harness,
    build_blueprint_request,
    build_formalization_request,
    build_review_request,
    ingest_answer,
    ingest_self_answer,
    init_harness,
    issue_question,
    record_model_call,
    register_artifact,
    run_code,
    seal_eligibility,
    stop_run,
    status_summary,
)


def json_arg(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("metadata must be a JSON object")
    return parsed


def json_file_arg(value: str) -> dict:
    path = Path(value)
    parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("tool policy must be a JSON object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verifiable QDM benchmark harness")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("init")
    command.add_argument("--output", required=True)
    command.add_argument("--problem", required=True)
    command.add_argument("--data", action="append", default=[])
    command.add_argument("--no-data-reason", default="")
    command.add_argument("--answer-model", required=True)
    command.add_argument(
        "--reviewer-model", default="",
        help="Reviewer model. Required except for qdm_self_ask, which has no reviewer.",
    )
    command.add_argument("--reporter-model", default="")
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("--max-total-agent-calls", type=int, default=40)
    command.add_argument("--tool-policy", type=json_file_arg, default={})
    command.add_argument("--max-question-rounds", type=int, default=20)
    command.add_argument(
        "--experiment-mode",
        choices=["adaptive_questions", "one_shot"],
        default="adaptive_questions",
    )
    command.add_argument(
        "--protocol-condition",
        choices=[
            "qdm_full", "mm_agent_native", "qdm_fixed_checklist",
            "qdm_no_closure", "qdm_no_traceability", "qdm_self_ask",
        ],
        default="qdm_full",
    )

    command = sub.add_parser("issue-question")
    command.add_argument("--output", required=True)
    command.add_argument("--field", default="")
    command.add_argument(
        "--question-file", default="",
        help="Path to a Codex-authored question text. When provided, the round prompt is this file "
             "instead of the policy-generated template (protocol v3).",
    )

    command = sub.add_parser("record-call")
    command.add_argument("--output", required=True)
    command.add_argument("--role", required=True)
    command.add_argument("--stage", required=True)
    command.add_argument("--request", required=True)
    command.add_argument("--response", required=True)
    command.add_argument("--model-requested", required=True)
    command.add_argument("--model-actual", required=True)
    command.add_argument("--provider-call-id", default="")
    command.add_argument("--started-at", required=True)
    command.add_argument("--finished-at", required=True)
    command.add_argument("--input-tokens", type=int)
    command.add_argument("--output-tokens", type=int)
    command.add_argument(
        "--telemetry-status",
        choices=["verified", "partial", "unavailable"],
        default="unavailable",
    )
    command.add_argument("--round-id", type=int)
    command.add_argument(
        "--review-classification",
        choices=["approved", "non_blocking_only"],
        default="approved",
        help="Solver's graded classification for review-stage calls (PROTOCOL.md section 9): "
             "approved requires status=approved in the raw response; non_blocking_only records a "
             "review whose issues are all format/notation/documentation and proceeds without a "
             "revision round.",
    )

    command = sub.add_parser("make-review-request")
    command.add_argument("--output", required=True)
    command.add_argument("--stage", choices=["blueprint_review", "result_review"], required=True)
    command.add_argument("--destination", required=True)

    command = sub.add_parser("make-formalization-request")
    command.add_argument("--output", required=True)
    command.add_argument("--destination", required=True)

    command = sub.add_parser("make-blueprint-request")
    command.add_argument("--output", required=True)
    command.add_argument("--destination", required=True)

    command = sub.add_parser("ingest-answer")
    command.add_argument("--output", required=True)
    command.add_argument("--answer", required=True)
    command.add_argument("--answer-call-id", required=True)
    command.add_argument("--decision", required=True)
    command.add_argument("--review-call-id", required=True)

    command = sub.add_parser(
        "ingest-self-answer",
        help="Import a qdm_self_ask round from the answerer's self-declared decision "
             "(no reviewer call).",
    )
    command.add_argument("--output", required=True)
    command.add_argument("--answer", required=True)
    command.add_argument("--answer-call-id", required=True)
    command.add_argument("--decision", required=True)

    command = sub.add_parser("register-artifact")
    command.add_argument("--output", required=True)
    command.add_argument("--kind", required=True)
    command.add_argument("--path", required=True)
    command.add_argument("--metadata", type=json_arg, default={})

    command = sub.add_parser("advance")
    command.add_argument("--output", required=True)
    command.add_argument("--to", required=True)

    command = sub.add_parser("run-code")
    command.add_argument("--output", required=True)
    command.add_argument("--script", required=True)
    command.add_argument("--input", action="append", default=[])
    command.add_argument("--timeout", type=int, default=300)

    command = sub.add_parser("audit")
    command.add_argument("--output", required=True)

    command = sub.add_parser("status")
    command.add_argument("--output", required=True)

    command = sub.add_parser("seal")
    command.add_argument("--output", required=True)

    command = sub.add_parser("stop-run")
    command.add_argument("--output", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument(
        "--category",
        choices=[
            "budget_exhausted", "protocol_failure", "model_failure", "tool_failure",
            "implementation_failure", "execution_failure", "integrity_failure",
        ],
        required=True,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            result = init_harness(
                args.output, args.problem, args.data, args.no_data_reason,
                args.answer_model, args.reviewer_model, args.max_question_rounds,
                args.experiment_mode, args.protocol_condition, args.seed,
                args.max_total_agent_calls, args.tool_policy, args.reporter_model,
            )
        elif args.command == "issue-question":
            result = issue_question(args.output, args.field, args.question_file)
        elif args.command == "record-call":
            result = record_model_call(
                args.output, args.role, args.stage, args.request, args.response,
                args.model_requested, args.model_actual, args.provider_call_id,
                args.started_at, args.finished_at, args.input_tokens, args.output_tokens,
                args.round_id, args.telemetry_status, args.review_classification,
            )
        elif args.command == "make-review-request":
            result = build_review_request(args.output, args.stage, args.destination)
        elif args.command == "make-formalization-request":
            result = build_formalization_request(args.output, args.destination)
        elif args.command == "make-blueprint-request":
            result = build_blueprint_request(args.output, args.destination)
        elif args.command == "ingest-answer":
            result = ingest_answer(args.output, args.answer, args.answer_call_id, args.decision, args.review_call_id)
        elif args.command == "ingest-self-answer":
            result = ingest_self_answer(args.output, args.answer, args.answer_call_id, args.decision)
        elif args.command == "register-artifact":
            result = register_artifact(args.output, args.kind, args.path, args.metadata)
        elif args.command == "advance":
            result = advance_phase(args.output, args.to)
        elif args.command == "run-code":
            result = run_code(args.output, args.script, args.input, args.timeout)
        elif args.command == "audit":
            issues = audit_harness(args.output)
            result = {"status": "failed" if issues else "passed", "issues": issues}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if issues else 0
        elif args.command == "seal":
            result = seal_eligibility(args.output)
        elif args.command == "stop-run":
            result = stop_run(args.output, args.reason, args.category)
        else:
            result = status_summary(args.output)
    except (HarnessError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
