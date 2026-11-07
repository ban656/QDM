---
name: qdm-benchmark-harness
description: Run a QDM mathematical-modeling benchmark through the verifiable harness, with an isolated questioner, recorded calls, immutable provenance, and strict audit failure. Use for any run whose results are reported.
---

# QDM Benchmark Harness

Run every reported benchmark through `python -m qdm.harness.cli`. Treat a
non-zero exit as a blocking failure. Read
[references/harness-contract.md](references/harness-contract.md) before starting
or resuming a run, and the `qdm-questioner` skill before the first questioner call.

## Roles

- **Modeler** (this session): writes the planning drafts, answers every
  question, and writes the specification, blueprint, code and paper.
- **Questioner**: a separate session started with
  `python -m qdm.harness.claude_peer <request> <response>`. It reads only the
  request file, so it sees the problem, the written draft, the specification
  and the question history, never the modeler's reasoning. It asks the
  questions and reviews every answer, the blueprint and the results. It writes
  no artifact.

## Non-Negotiable Rules

- Generate each answer only after `issue-question` creates the current prompt.
- Never prewrite answers, feature tables, questioner decisions, code, or papers in a batch script.
- Always record requested/actual model, timestamps, raw request, and raw response. Record provider call ID and token counts when available; otherwise set `telemetry_status=partial` or `unavailable` and leave unavailable values empty.
- Use only permitted role/stage pairings. The modeler (`answerer`) never reviews its own artifact; the questioner never writes one.
- Never invent call metadata. Missing token telemetry is not a validity failure; an unavailable questioner is.
- Keep problem data in the frozen data manifest. Do not replace supplied data with random, synthetic, or hard-coded values.
- Let the harness advance phases. Do not create or accept downstream artifacts before the corresponding gate passes.
- Preserve old runs as history. Start a new run after any protocol, prompt, model, or code change.

## Review Convergence Policy (PROTOCOL.md section 9)

Before acting on any questioner opinion, grade it into exactly two classes. Do
not enter a revision cycle for anything but a blocking issue.

**Blocking (must revise)**: the opinion changes the modeling direction:
equations or formula relations; constraints or their referenced variables;
algorithm family, solver structure or scenario design; identifiability claims;
validation gates whose definition changes the accept/reject rule of a headline
claim.

**Non-blocking (record and proceed)**: format, notation, documentation,
engineering, or minor parameterization that does not change the modeling
direction, such as schema validity of a presentation field, unit or convention
wording that does not change an equation, documentation precision, or naming.

Record every non-blocking item in `claude_workspace/tradeoff_ledger.md` with
the issue and the resolution chosen, then proceed. When a review surfaces only
non-blocking items, record the call with `record-call --review-classification
non_blocking_only`; the issues stay in the raw response and the tradeoff
ledger. This is a proceed-on-non-blocking-review, never a fabricated
"approved". Only blocking issues create a new artifact version.

## Execution Loop

1. Initialize the harness with the problem and every supplied dataset or an explicit no-data reason.
2. Write a planning draft under `claude_workspace/planning/`.
3. Call the questioner for one to three questions (stage `question_generation`) and issue them with `issue-question --question-file <file> --field <field>`.
4. Produce one raw answer from the issued request and record its call (stage `question_answer`).
5. Send the answer and current state to the questioner for review (stage `answer_review`). Save the raw response, normalize its decision with `round_id` and `raw_response_sha256`, and record the call.
6. Ingest the answer through the harness. Apply `local_fix`, `re_question`, `rollback`, `abandon_module`, or `stop` exactly as returned.
7. Repeat until both protocol gates pass.
8. Advance sequentially through specification, blueprint, implementation, execution, writing, and complete. Generate content-bearing blueprint and result review packets with `make-review-request`; hash-only review prompts are invalid.
9. Register every artifact before advancing. Generated file artifacts must be the exact recorded model response. Code directories must match the response's `materialized_files` manifest; registration creates immutable snapshots.
10. Before generating code, load `claude_workspace/final/constraint_spec.json`. For every equation, constraint, and variable in the spec, verify the code implements it, and record any simplification or omission in the Traceability Ledger `claude_workspace/tradeoff_ledger.md`. Run only the latest registered implementation through `run-code` with frozen dataset inputs. Treat runtime-observed file reads, not source-code keywords or self-reported provenance, as evidence of data consumption.
11. Run the harness audit and the repository audit, then run `seal`. Only the seal command may set `paper_eligible=true`.

## Status Discipline

Use `clear` only when a field has a substantive summary, structured items,
traceable evidence, confidence of at least 0.75, and no blocking open question.
Use `assumption_based` for plausible but unsupported values. Allow later
evidence to downgrade any prior status. The questioner's decision, not the
modeler's self-declared status, is the authority for import.

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
