---
description: Ask Codex to review a Claude QDM answer before updating feature_table.
argument-hint: "<answer file or pasted answer>"
---

# QDM Answer Review

You are Claude Code.  You have produced or received a QDM answer.  Before the
state is updated, use the `qdm-codex-questioner` skill to ask Codex to review
it as the current-run questioner.

Input:

$ARGUMENTS

If `codex-plugin-cc` is installed, call:

```text
/codex:adversarial-review
```

Request `gpt-5.5` explicitly.  Do not accept an unrecorded model.  Record both
requested and provider-reported actual model fields; if actual differs, keep it
and explain the provider mapping in `codex_model_note`.

with this request:

```text
Review this QDM answer before it enters `feature_table`.

Check:
- Did the answer only address the target field?
- Are claims traceable to the problem statement, formulas, units, or explicit assumptions?
- Are uncertain claims correctly marked `assumption_based`?
- Are there conflicts that should block progress?
- Are `feature_updates` specific enough to import?
- Are `algorithm_modules` reusable partial modules, not whole route guesses?

Return JSON:
{
  "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
  "stage": "answer_review",
  "codex_model_requested": "gpt-5.5",
  "codex_model_actual": "",
  "codex_model_note": "",
  "reason": "",
  "impasse_type": "none | information | structural | formula | algorithmic | numerical | narrative",
  "invalidated_items": [],
  "rollback_target": "",
  "next_question": "",
  "required_edits": [],
  "confidence": 0.0
}
```

If `/codex:*` is unavailable, write the same request to:

```text
<auto_workspace>/codex_workspace/questioner/requests/review_answer_request.md
```

and write the normalized JSON decision to:

```text
<auto_workspace>/codex_workspace/questioner/decisions/review_answer_decision.json
```
