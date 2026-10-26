---
description: Ask Codex to distill reusable question/modeling structures from a completed solution.
argument-hint: "<solution, blueprint, review feedback, or output directory>"
---

# QDM Evolver-Guided Distillation

You are Claude Code.  Use the `qdm-codex-evolver` skill after a modeling run,
solution draft, failure summary, or blind review feedback is available.

Input:

$ARGUMENTS

If `codex-plugin-cc` is installed, call:

```text
/codex:review
```

Request `gpt-5.5` explicitly.  Do not accept an unrecorded model.  Record both
requested and provider-reported actual model fields; if actual differs, keep it
and explain the provider mapping in `codex_model_note`.

with this request:

```text
Act as the QDM evolver, not the current-run questioner and not the solver.

Watch the completed solution and distill reusable structures:
- Which question should have been asked earlier?
- Which variable/formula/constraint structure is reusable?
- Which algorithm module is transferable as a partial module?
- Which validation question should enter the standard checklist?
- Which anti-pattern caused wasted work or rollback?

Return JSON compatible with `qdm/evolution/library.py import`:
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

If `/codex:*` is unavailable, write the same request to:

```text
<auto_workspace>/codex_workspace/evolver/requests/distill_request.md
```

Write the normalized JSON distillation to:

```text
<auto_workspace>/codex_workspace/evolver/distillations/distillation.json
```
