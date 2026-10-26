# QDM Self-Ask Ablation Contract (`qdm_self_ask`)

This ablation isolates the QDM question-driven mechanism. It is a secondary
mechanism ablation, not the primary test of the paper's claim (the primary
test compares `qdm_full` with `mm_agent_native` under
`protocol-v2-contract.md`).

## Controlled Difference

Compare `qdm_full` with `qdm_self_ask`. The ablation removes every external
agent role while keeping the rest of the pipeline identical:

| Mechanism | qdm_full | qdm_self_ask |
|-----------|----------|--------------|
| Questioner | Codex questioner, prescribed question types, context isolation from the solver | **None** — the answerer asks itself free-form questions in its own full context (no isolation) |
| Answer review (`answer_review`) | Live reviewer decision per round | **None** — `self_declared_decision` authored by the answerer |
| Blueprint review (`blueprint_review`) | Content-bound reviewer approval | **None** |
| Result review (`result_review`) | Results/freeze-bound reviewer approval | **None** |
| Evolver distillation | Post-run Codex distillation + library updates | **None** |
| Interview structure | Adaptive rounds until both gates pass | **Exactly one** all-fields self-ask round (single-round ablation semantics) |

Kept identical: problem, data manifest, answer model, seed, capability
envelope, clarity/question gates, constraint specification, method-neutral P1
reporter, blueprint generation, implementation + Traceability Ledger,
execution (`run-code` with runtime file-read tracing), results + freeze,
writing freeze adapter, paper, harness and repository audits, KBS anchored
evaluation.

## Self-Ask Run

Initialize with:

```powershell
python -m qdm.harness.cli init `
  --protocol-condition qdm_self_ask --experiment-mode one_shot `
  --output <run-dir> --problem <problem-file> `
  --answer-model <model> --reporter-model <model> `
  [--data <file> ... | --no-data-reason <text>]
```

`qdm_self_ask` forces `one_shot` and one question round; no reviewer model is
configured (pass the reporter model explicitly). Then:

1. `issue-question` once — the harness writes the self-ask prompt
   (`round_001_self_ask.md`). Do not pass `--question-file` (self-ask has no
   Codex-authored questions).
2. Produce one raw answer in the extended answer schema:
   - every required field substantive, `clear`/`assumption_based` discipline;
   - `self_asked_questions`: the questions you asked yourself and your own
     answers (this log is the ablation's measurement of self-questioning);
   - `self_declared_decision` with `self_declared: true` — `continue` only
     when both gates would pass;
   - `questions_for_codex` must be empty.
3. Record the answerer call with stage `question_answer` (request/response
   files inside the run dir, timestamps, requested/actual model, token
   telemetry when available).
4. `ingest-self-answer` with the self-declared decision file. No reviewer call
   exists. Any decision other than `continue` records the ablation as an
   **interview-gate failure**: preserve the run with `stop-run` (category
   `protocol_failure` or `execution_failure`) and never repair it with a
   second elicitation round.
5. Advance sequentially with **no review calls**: specification (constraint
   spec + neutral P1 via `make-formalization-request`, P1 never fed back) →
   blueprint (`make-blueprint-request` only; no `make-review-request`) →
   implementation (code + Traceability Ledger) → execution (`run-code`,
   results + freeze, no result review) → writing (freeze adapter + paper) →
   complete.
6. Run the harness audit and the repository audit, then `seal`. The run
   summary records `codex_plugin_cc_available=false` and
   `decision_method="qdm-benchmark-harness-self-ask"`; never claim Codex
   participation that did not happen.

The self-ask contract (`contracts/auto_contract.json` from
`python -m qdm.auto.contract --protocol-condition qdm_self_ask`)
omits all codex artifacts and the evolution proposal; the repository audit
skips Codex decision/distillation requirements for this condition.

## Reporting

Report the pair as different protocol conditions, not as replicates. At
minimum compare completion, interview-gate pass/fail, question-elicitation
volume (questioner question rounds vs exactly one self-ask round),
`self_asked_questions` count and content versus the QDM questioner's recorded
questions, required-field coverage, constraint count, blueprint acceptance,
downstream execution success, result consistency, final task coverage, and
KBS anchored scores. Report calls, tokens, and time as efficiency outcomes;
missing token telemetry must remain missing rather than estimated.
