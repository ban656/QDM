---
name: qdm-benchmark-harness
description: Run publication-grade protocol-level mathematical-modeling benchmarks with frozen P0/P1/P2 objects, QDM-full versus native MM-Agent comparison, blinded paired evaluation, recorded calls, immutable provenance, and strict audit failure. Use for KBS experiments, year-by-year evaluation, QDM ablations, or any run intended for paper statistics.
---

# QDM Benchmark Harness

Run every paper-eligible benchmark through
`python -m qdm.harness.cli`. Treat a non-zero exit as a
blocking failure. Read [references/harness-contract.md](references/harness-contract.md)
before starting or resuming a run.
For the primary QDM-versus-MM-Agent comparison, also read
[references/protocol-v2-contract.md](references/protocol-v2-contract.md) and
[references/evaluation-v2-contract.md](references/evaluation-v2-contract.md).
Before the pilot, also freeze the criteria in
[references/pilot-and-analysis-v2.md](references/pilot-and-analysis-v2.md).
For `one_shot` ablations, also read
[references/ablation-contract.md](references/ablation-contract.md).
For the `qdm_self_ask` self-ask ablation, also read
[references/self-ask-ablation-contract.md](references/self-ask-ablation-contract.md).

## Non-Negotiable Rules

- In QDM conditions, generate each answer only after `issue-question` creates the current prompt. In `mm_agent_native`, never call the QDM question command.
- Never prewrite answers, feature tables, reviewer decisions, code, or papers in a batch runner.
- Never use `batch_runner.py`, `run_2021_batch.py`, `qdm_answers_*.py`, or `qdm_*_rep*.py` for a paper-eligible run.
- Always record requested/actual model, timestamps, raw request, and raw response. Record provider call ID and token counts when available; otherwise set `telemetry_status=partial` or `unavailable` and leave unavailable values empty.
- Use only permitted role/stage pairings. The answerer solves, the neutral reporter serializes P1 without feeding it back, the reviewer reviews, and the evolver distills. A role may not self-review its own artifact.
- Never invent call metadata. Missing token telemetry is not a validity failure. An unavailable reviewer is a validity failure when the selected mode requires reviewer decisions.
- Keep problem data in the frozen data manifest. Do not replace supplied data with random, synthetic, or hard-coded values.
- Let the harness advance phases. Do not create or accept downstream artifacts before the corresponding gate passes.
- Preserve old runs as history. Start a new replicate after any protocol, prompt, model, or code change.
- In `qdm_self_ask` runs, reviewer calls, `make-review-request`, Codex questioner packets, and evolution artifacts are forbidden by design: use `ingest-self-answer` and skip the review stages (see references/self-ask-ablation-contract.md).
- Treat `protocol_condition`, not question count, as the primary experimental treatment.
- Freeze method-neutral P1 before blueprint generation. Never feed the neutral reporting adapter output back into either solver.
- Keep anonymous A/B mappings private until all required formulation and outcome scores are frozen.

## Review Convergence Policy (strict grading, PROTOCOL.md §9)

Before acting on ANY reviewer (Codex) opinion, grade it yourself into exactly
two classes. Do not enter a revision cycle for anything but a blocking issue.

**Blocking (must revise)** — the opinion changes the modeling direction:
- equations / formula relations
- constraints (hard or soft) or their referenced variables
- algorithm family / solver structure / scenario design axes
- identifiability claims
- validation gates whose definition changes the accept/reject rule of a
  headline claim (e.g., the statistic behind M* or the primary criterion)

**Non-blocking (record and proceed)** — format, notation, documentation,
engineering, or minor parameterization that does not change the modeling
direction:
- artifact format / schema validity of presentation (e.g., invalid JSON
  structure of a field such as a trace matrix)
- parameter unit or convention wording that does not change the equation
  (e.g., SD vs variance naming; which convention the source froze wins)
- documentation precision (e.g., exact definition of a normalization
  denominator, failure-behavior wording, trace-entry wording)
- wording reconciliation that does not change the accept/reject rule
- naming of fields or sections

For every non-blocking item: record it in
`claude_workspace/tradeoff_ledger.md` with the issue text and the resolution
chosen, then proceed to the next stage. Never start a revision round for it.

Proceed rule: when a review surfaces ONLY non-blocking items, record it and
proceed — there is no "final review" concept and no convergence version
number. The reviewer may declare `all_issues_non_blocking=true` itself, or the
solver records its own graded classification (PROTOCOL.md §9: the solver
grades every opinion) via `record-call --review-classification
non_blocking_only`, with the grading written to a normalized decision file
under `codex_workspace/questioner/decisions/` and the issues preserved in the
raw response and the tradeoff ledger. The call is recorded with
`approval_mode=non_blocking_only`; this is a proceed-on-non-blocking-review,
never a fabricated "approved". Only blocking issues pin a new artifact
version; format-class opinions never consume a revision round. The advance
gates accept an `approved` call bound to the latest artifact or any
`non_blocking_only` call covering the chain (later registrations resolve its
issues).

Do not exceed `limits.max_blueprint_revisions` silently: a cap hit mid-review
loop is resolved only by the documented ledger override precedent
(`blueprint_revisions_override` with `authorized_by` recorded), mirroring the
2025_A rep_02 precedent in this experiment series.

## Execution Loop

1. Initialize the harness with the problem and every supplied dataset or an explicit no-data reason.
2. Issue exactly one question.
3. Produce one raw answer from the issued request and record its live call.
4. Send the answer and current state to the live Codex questioner.
5. Save the raw Codex response, normalize its decision with `round_id` and `raw_response_sha256`, and record the reviewer call.
6. Ingest the answer through the harness. Apply `local_fix`, `re_question`, `rollback`, `abandon_module`, or `stop` exactly as returned.
7. In `adaptive_questions`, repeat until both protocol gates pass. In `one_shot`, permit exactly one all-field elicitation and fail the run if that single answer does not pass both gates.
8. Advance sequentially through specification, blueprint, implementation, execution, writing, and complete. Freeze P1 in specification. Generate content-bearing blueprint/result review packets with `make-review-request`; hash-only review prompts are invalid.
9. Register every artifact before advancing. Generated file artifacts must be the exact recorded model response. Code directories must match the response's `materialized_files` manifest; registration creates immutable snapshots.
10. Before generating code, load `claude_workspace/final/constraint_spec.json` (or `constraint_spec.json`). For every equation, constraint, and variable in the spec, verify the code implements it. If the code simplifies or omits something from the spec, document the trade-off in a **Traceability Ledger** — saved as `claude_workspace/tradeoff_ledger.md` — with the format defined in `MMAgent/skills/stage3_modeling/SKILL.md`. The harness audit must check that the ledger exists and is non-empty. Run only the latest registered implementation through `run-code` with frozen dataset inputs. The harness maps the editable source path to its immutable snapshot. Treat runtime-observed file reads, not source-code keywords or self-reported provenance, as evidence of data consumption.
11. Run harness audit and the repository audit, then run `seal`. Only the seal command may set `paper_eligible=true`.

## Status Discipline

Use `clear` only when a field has a substantive summary, structured items,
traceable evidence, confidence of at least 0.75, and no blocking open question.
Use `assumption_based` for plausible but unsupported values. Allow later
evidence to downgrade any prior status. Treat a reviewer decision as the
authority for import, not the answerer's self-declared status.

## Data Discipline

For data-backed problems, require a `data_support` field tied to manifest paths,
a blueprint `data_structure`, an execution trace proving runtime reads from each
declared asset, `synthetic_data_used=false`, non-empty results produced by the
registered code, and frozen claims bound to those results. Never hard-code
replacements for available observations.

## Completion Discipline

Require a non-placeholder paper containing Abstract, Model/Methods, Results,
and Limitations. Derive run-summary counts from the harness ledger. Do not
manually set `paper_eligible=true`; derive eligibility from successful audits.
