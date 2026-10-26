---
name: qdm-codex-evolver
description: Use Codex as the post-run QDM structural evolver. This skill reads completed modeling runs and distills reusable question patterns, modeling structures, algorithm modules, validation checks, writing patterns, policy updates, and anti-patterns for future tasks.
---

# QDM Codex Evolver

Use this skill only after a modeling run has produced final artifacts or has
stopped with a recorded failure.

This skill is for cross-run learning.  It must not change the current run's
accept/reject decisions, formulas, code, final results, or rollback history.

## Role

Codex acts as:

- structural distiller
- pattern extractor
- anti-pattern recorder
- validation-checklist improver
- future question-policy proposer

Request `gpt-5.5` for every live Codex evolver call.  Do not accept
distillation with an unrecorded model.  Record both `codex_model_requested` and
the provider-reported `codex_model_actual` in the response log or normalized
distillation.  If the actual model differs from `gpt-5.5`, keep that reported
value and explain the provider mapping in `codex_model_note`; do not relabel it
or fail solely because of the mismatch.

Codex does not act as:

- current-run questioner
- current-run impasse gate
- code repair agent
- final result selector

## Workspace

Write only under:

```text
<auto_workspace>/codex_workspace/evolver/
```

Required subpaths:

```text
requests/*.md          distillation request packets
responses/*.md         raw Codex responses
distillations/*.json   normalized evolution outputs
library_updates/*.json proposed imports for the pattern library
logs/*.jsonl           optional call log
```

Do not write under:

```text
<auto_workspace>/codex_workspace/questioner/
<auto_workspace>/claude_workspace/
```

## Inputs

Read, when available:

- `claude_workspace/state/modeling_state.json`
- `claude_workspace/logs/question_history.jsonl`
- `codex_workspace/questioner/decisions/*.json`
- `claude_workspace/final/modeling_blueprint.json`
- `claude_workspace/final/results.md`
- `claude_workspace/final/paper.md`
- `claude_workspace/final/run_summary.json`

## Output Schema

Normalize Codex output into this JSON schema:

```json
{
  "source_problem_id": "",
  "codex_model_requested": "gpt-5.5",
  "codex_model_actual": "",
  "codex_model_note": "",
  "distillation_summary": "",
  "question_patterns": [],
  "modeling_patterns": [],
  "algorithm_modules": [],
  "validation_questions": [],
  "writing_patterns": [],
  "policy_updates": [],
  "anti_patterns": []
}
```

The schema is compatible with:

```text
python qdm/evolution/library.py import --library <library> --answer <distillation.json>
```

## Distillation Targets

Extract only reusable structures:

- a question that should have been asked earlier
- a variable/formula/constraint structure that transfers to future problems
- a partial algorithm module worth borrowing
- a validation question that catches a concrete failure mode
- a writing pattern that improves mathematical-modeling papers
- a policy update for the question gate or modeling tree
- an anti-pattern that caused wasted work, false confidence, or rollback

## Prompt Discipline

The evolver should describe why a pattern is reusable and when it should be
triggered.  It should avoid turning one problem's domain-specific details into
a universal rule.
