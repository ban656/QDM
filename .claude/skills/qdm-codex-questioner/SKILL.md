---
name: qdm-codex-questioner
description: Use Codex as the current-run QDM questioner, reviewer, and impasse gate for mathematical modeling. This skill asks narrow clarification questions, checks feature-table updates, challenges BLUEPRINTs, and decides continue/local_fix/re_question/rollback/abandon_module without doing post-run evolution.
---

# QDM Codex Questioner

Use this skill when Claude Code needs Codex to control the current modeling run.
For benchmark runs, use it only inside `qdm-benchmark-harness`; never import an
answer or advance a phase outside the harness.

This skill is for the active problem only.  It must not distill reusable
cross-run patterns or update the evolution library.

## Role

Codex acts as:

- narrow-question generator
- feature-table reviewer
- BLUEPRINT challenger
- impasse detector
- rollback gate

Request `gpt-5.5` for every live Codex questioner call.  Do not accept
decisions with an unrecorded model.  Record both `codex_model_requested` and the
provider-reported `codex_model_actual` in the response log or normalized
decision.  If the actual model differs from `gpt-5.5`, keep that reported value
and explain the provider mapping in `codex_model_note`; do not relabel it or
fail solely because of the mismatch.

Codex does not act as:

- final solver
- paper writer
- evolution-library maintainer
- post-run structural distiller

## Workspace

Write only under:

```text
<auto_workspace>/codex_workspace/questioner/
```

Required subpaths:

```text
requests/*.md      request packets sent to Codex
responses/*.md     raw Codex responses
decisions/*.json   normalized stage decisions
logs/*.jsonl       optional call log
```

Do not write under:

```text
<auto_workspace>/codex_workspace/evolver/
<auto_workspace>/claude_workspace/
```

## When To Use

Use the questioner at current-run stage boundaries:

1. after Claude answers a QDM clarification question
2. before importing feature-table updates
3. after a modeling-tree BLUEPRINT is drafted
4. when formulas, code, or results look inconsistent
5. when the run may need rollback or module abandonment

## Output Schema

Normalize Codex output into this JSON schema:

```json
{
  "round_id": 0,
  "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
  "stage": "",
  "codex_model_requested": "gpt-5.5",
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

Ask for evidence, not taste.  The questioner should focus on whether the
problem specification, variables, formulas, constraints, objective, algorithm
choice, and result interpretation are sufficiently grounded.

The questioner should not propose a whole new modeling route unless the current
state is structurally invalid and a rollback target is necessary.

## Hard Review Gates

Do not approve placeholder structure.  A feature-table field is not clear if
its `items` only records a round label such as `Round 6: constraints` or
`Round 8: algorithm_implications`.

For constraints, require a ledger-like representation.  Each hard constraint
should identify its text, scope, code check or validation check, and failure
action.

For algorithm choices, require the solver to state:

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

If the solver uses random search, greedy assignment, heuristic scheduling,
grid-only search, or manual pruning, also require seed/determinism, budget,
multi-start or grid resolution, convergence/resolution check, baseline
comparison, failure condition, and rollback target.

When these fields are missing, return `local_fix`, `re_question`, or
`rollback`.  Do not return unconditional `continue`.

## Normalization Integrity

The normalized decision JSON must preserve material risks from the raw Codex
response.  If the raw response says the current plan is weak, risky, ambiguous,
oversimplified, may miss cooperative effects, may double-count, lacks
convergence checks, or is not globally optimal, the normalized decision must
either:

1. use `local_fix`, `re_question`, or `rollback`; or
2. keep `continue` only with those risks copied into `required_edits` and tied
   to acceptance conditions.

For benchmark runs, also preserve the current `round_id`, SHA-256 of the exact
raw response, and SHA-256 of the answer being reviewed. Missing provenance is a
blocking failure.
