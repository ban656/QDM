---
name: qdm-codex-bridge
description: Route Claude Code requests to the correct QDM Codex role. Use qdm-codex-questioner for current-run questions, reviews, and impasse gates; use qdm-codex-evolver for post-run structural distillation.
---

# QDM Codex Bridge

This project uses Claude Code as the independent answer/modeling agent and
Codex as two separated roles:

- `qdm-codex-doubt-gate`: current-run self-doubt and bottleneck trigger gate.
- `qdm-codex-questioner`: current-run questioner, reviewer, and impasse gate.
- `qdm-codex-evolver`: post-run structural distiller and reusable-pattern proposer.

Use this bridge when you need to decide which Codex skill should handle a QDM
request.

## Required External Plugin

For live Codex calls inside Claude Code, install the official plugin:

```text
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
/codex:setup
```

## Required Codex Model

All QDM Codex calls must request the fixed reviewer model `gpt-5.5`.  Do not
rely on the plugin default model.  If the plugin exposes a model flag or setup
selector, explicitly select `gpt-5.5` before `/codex:review`,
`/codex:adversarial-review`, `/codex:rescue`, or `/codex:transfer`.

Record both `codex_model_requested` and provider-reported
`codex_model_actual` in the response log or normalized JSON decision.  If the
actual model name differs from `gpt-5.5`, keep the reported name and explain the
provider mapping in `codex_model_note`; do not relabel it or fail solely because
of the mismatch.

In benchmark-auto mode, if `/codex:*` commands or provider telemetry are not
available, stop the run. Write the intended request only as a failure artifact;
do not create a normalized decision or distillation and do not mark the run
paper-eligible.

## Role Split

- Claude Code: answer narrow questions, propose modeling structures, implement code when asked.
- Codex doubt gate: decide when Claude's uncertainty, bottleneck, weak
  algorithm choice, or unsupported simplification must be sent to Codex before
  continuing.
- Codex questioner: challenge whether the current state can proceed, validate feature tables, and detect rollback needs.
- Codex evolver: distill reusable structures after the run is complete.
- Human in benchmark-auto mode: provides problem files and launches the run only.

## Routing

Use `qdm-codex-questioner` when:

1. A QDM answer is produced.
2. A modeling-tree `BLUEPRINT` is produced.
3. Formula/code/result execution appears inconsistent.
4. A rollback, re-question, or module abandonment decision is needed.

Use `qdm-codex-doubt-gate` before the questioner call when:

1. Claude is unsure whether an answer, formula, constraint, algorithm, or result
   is defensible.
2. Claude reaches a bottleneck, repeated code failure, unstable numeric result,
   or unclear formula-to-code mapping.
3. Claude proposes random search, greedy assignment, heuristic scheduling,
   grid-only search, hand-pruned variables, or an unsupported statement such as
   "only this UAV can contribute".
4. A raw Codex review contains material risks but the normalized decision is
   about to be recorded as unconditional `continue`.

Use `qdm-codex-evolver` when:

1. A complete solution, paper draft, or failure summary exists.
2. Blind-review feedback is available.
3. The run should produce reusable question/modeling patterns.

## Workspace Split

```text
<auto_workspace>/codex_workspace/questioner/
  Current-run requests, responses, decisions, logs.

<auto_workspace>/codex_workspace/evolver/
  Post-run requests, responses, distillations, library update proposals.
```

Do not mix these outputs.  The separation is part of the benchmark audit.
