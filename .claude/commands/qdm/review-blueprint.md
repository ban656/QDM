---
description: Ask Codex to challenge a modeling-tree BLUEPRINT before coding.
argument-hint: "<BLUEPRINT file or pasted blueprint>"
---

# QDM Modeling Tree Blueprint Review

You are Claude Code.  Use the `qdm-codex-questioner` skill after producing a
modeling-tree `BLUEPRINT` and before generating code or final paper text.

Blueprint/context:

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
Challenge this modeling-tree BLUEPRINT before implementation.

Check:
- Are F/C/O/M identifiers stable and complete?
- Do equations have variables, units, meaning, and computable form?
- Do constraints and objectives match the problem statement?
- Is `algorithm_plan` implementable as modules?
- Does `algorithm_module_fusion` really fuse useful parts rather than choose a route?
- Does every optional module have baseline, trial metric, and rollback condition?
- Are validation checks strong enough to catch formula, algorithm, and numerical impasses?
- Is formula-code traceability possible?

Return JSON:
{
  "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
  "stage": "blueprint_review",
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
<auto_workspace>/codex_workspace/questioner/requests/review_blueprint_request.md
```

and write the normalized JSON decision to:

```text
<auto_workspace>/codex_workspace/questioner/decisions/review_blueprint_decision.json
```
