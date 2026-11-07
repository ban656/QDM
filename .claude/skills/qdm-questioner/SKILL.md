---
name: qdm-questioner
description: Prepare and interpret calls to the isolated QDM questioner for the current run. The questioner asks narrow clarification questions, reviews each answer, challenges the blueprint and the results, and decides continue/local_fix/re_question/rollback/abandon_module/stop.
---

# QDM Questioner

Use this skill whenever the modeler needs the questioner in a benchmark run.
Use it only inside `qdm-benchmark-harness`; never import an answer or advance a
phase outside the harness.

## Isolation

The questioner is a separate session started with

```bash
python -m qdm.harness.claude_peer <request-file> <response-file>
```

It reads only the request file. Put into the request the full problem text,
the current written planning draft, a compact view of the feature table, and
the question history, plus the answer or artifact under review. Never put the
modeler's reasoning, scratch notes, or conversation into the request: the
questioner must work from what is written.

Record the requested model and the provider-reported actual model of every
call as `questioner_model_requested` and `questioner_model_actual`.

The questioner does not act as solver, paper writer, or code author.

## Workspace

Write only under:

```text
<run-dir>/questioner_workspace/
  requests/*.md      request packets
  responses/*.md     raw questioner responses
  decisions/*.json   normalized decisions
  logs/*.jsonl       optional call log
```

## When To Use

1. before each interview round, to obtain one to three questions on the field
   with the highest priority (stage `question_generation`)
2. after each answer, before its feature-table updates are imported
   (stage `answer_review`)
3. after the blueprint is drafted (stage `blueprint_review`)
4. after execution, on the results and the frozen claims (stage `result_review`)
5. when formulas, code, or results look inconsistent, or the run may need
   rollback or module abandonment

## Output Schema

Normalize the questioner's review into this JSON schema:

```json
{
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
  "confidence": 0.0
}
```

## Decision Meaning

- `continue`: current state is clear enough for the next stage.
- `local_fix`: repair the current artifact without reopening earlier stages.
- `re_question`: ask the specified narrow question before proceeding.
- `rollback`: invalidate listed items and return to the rollback target.
- `abandon_module`: stop using the named module and record why.
- `stop`: end the run because a declared stop condition is reached.

## Prompt Discipline

Ask for evidence, not taste. The questioner checks whether the specification,
variables, formulas, constraints, objective, algorithm choice, and result
interpretation are grounded in the problem statement, and whether decisions
written in different places of the draft can hold together.

The questioner should not propose a whole new modeling route unless the
current state is structurally invalid and a rollback target is necessary.

## Hard Review Gates

Do not approve placeholder structure. A feature-table field is not clear if
its `items` only records a round label such as `Round 6: constraints`.

For constraints, require a ledger-like representation: each hard constraint
identifies its text, scope, code or validation check, and failure action.

For algorithm choices, require the modeler to state:

```json
{
  "solver_family": "",
  "problem_structure": "",
  "why_this_solver": "",
  "why_not_random_or_greedy": "",
  "constraint_handling": "",
  "determinism": "",
  "global_or_local_claim": "",
  "acceptance_metric": "",
  "fallback_solver": ""
}
```

If the modeler uses random search, greedy assignment, heuristic scheduling,
grid-only search, or manual pruning, also require seed/determinism, budget,
multi-start or grid resolution, convergence/resolution check, baseline
comparison, failure condition, and rollback target.

When these fields are missing, return `local_fix`, `re_question`, or
`rollback`, not an unconditional `continue`.

## Normalization Integrity

The normalized decision must preserve material risks from the raw response. If
the raw response says the current plan is weak, risky, ambiguous,
oversimplified, may double-count, lacks convergence checks, or is not globally
optimal, the normalized decision must either:

1. use `local_fix`, `re_question`, or `rollback`; or
2. keep `continue` only with those risks copied into `required_edits` and tied
   to acceptance conditions.

Always preserve the current `round_id`, the SHA-256 of the exact raw response,
and the SHA-256 of the answer being reviewed. Missing provenance is a blocking
failure.
