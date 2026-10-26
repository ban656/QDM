---
description: Prepare a structured handoff from Claude Code to Codex.
argument-hint: "<what should Codex inspect?>"
---

# QDM Handoff To Codex

Prepare a concise handoff for Codex using the project's problem-driven modeling
state.

Include:

- current Codex role: questioner or evolver
- current stage: question / blueprint / code / result / paper / evolution
- relevant files with paths
- current blocker or decision
- what Codex should decide
- expected JSON output

If `codex-plugin-cc` is available, send the handoff with the most appropriate
command:

- `/codex:review` for ordinary review
- `/codex:adversarial-review` for challenge
- `/codex:rescue` for stuck/rollback cases
- `/codex:transfer` only when Codex should take over implementation

If unavailable, write the handoff to:

```text
<auto_workspace>/codex_workspace/questioner/requests/handoff_to_codex.md
```

For post-run structural distillation, write instead to:

```text
<auto_workspace>/codex_workspace/evolver/requests/handoff_to_codex.md
```

User request:

$ARGUMENTS
