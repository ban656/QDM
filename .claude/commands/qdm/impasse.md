---
description: Ask Codex whether the current modeling state can continue or must rollback.
argument-hint: "<state, blueprint, result, or failure context>"
---

# QDM Impasse Gate

You are Claude Code.  Use the `qdm-codex-questioner` skill when the workflow
may have reached a point where continuing would compound an earlier modeling
error.

Context:

$ARGUMENTS

If `codex-plugin-cc` is installed, call:

```text
/codex:rescue
```

Request `gpt-5.5` explicitly.  Do not accept an unrecorded model.  Record both
requested and provider-reported actual model fields; if actual differs, keep it
and explain the provider mapping in `codex_model_note`.

with this request:

```text
Act as the QDM impasse detector.

Decide whether the current state can continue or whether it needs local repair,
re-questioning, rollback, or module abandonment.

Check impasse types:
- information: missing data or ambiguous statement blocks modeling
- structural: variables/time/space/constraints/objectives do not close
- formula: equations are inconsistent, dimensionally invalid, or under-specified
- algorithmic: solver assumptions do not match the problem class
- numerical: code runs but violates constraints, units, scale, or physical meaning
- narrative: results cannot be explained in the original domain

Return JSON:
{
  "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
  "stage": "impasse_gate",
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
<auto_workspace>/codex_workspace/questioner/requests/impasse_request.md
```

and write the normalized JSON decision to:

```text
<auto_workspace>/codex_workspace/questioner/decisions/impasse_decision.json
```
