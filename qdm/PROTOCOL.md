# QDM Interview Protocol

## 1. Overview

Question-driven mathematical modeling proceeds in staged clarification instead
of one-shot generation. An open problem is decomposed into eleven structured
feature fields, each field is clarified through an interactive round between a
solver and a questioner, and modeling begins only when two gates — the clarity
gate and the question gate — are both satisfied.

Every round is recorded: the question text, the solver's raw answer, the
reviewer's raw response, and the normalized decision are files bound by
SHA-256 hashes inside an append-only harness ledger.

## 2. Roles

| Role | Agent | Responsibility |
|------|-------|----------------|
| Solver | Claude Code | Writes planning drafts, answers the questioner's questions, builds the model, implements code, writes the paper |
| Questioner | Codex | Receives the full problem text at every call (question generation and answer review), plus the solver's drafts, the answer under review, and the current feature table; asks narrow clarification questions; reviews every answer; decides whether the state may proceed |
| Evolver | Codex | After the run completes, distills reusable question and modeling patterns |
| Harness | Code | Enforces phase order, binds hashes, validates artifacts, runs audits |

The solver never self-approves. Every acceptance decision comes from the
questioner's recorded verdict.

## 3. Workspace Layout

```text
<run-dir>/
├── contracts/                  frozen contract, tool policy, prompt packets
├── claude_workspace/
│   ├── state/modeling_state.json   solver-side source of truth
│   ├── codex_to_claude/            issued question prompts (round_XXX_<field>.md)
│   ├── claude_to_codex/            solver answer files
│   ├── planning/                   solver planning drafts shared with the questioner
│   ├── logs/                       question history
│   └── final/                      constraint spec, blueprint, code, results, paper
├── codex_workspace/
│   ├── questioner/requests/        review request packets
│   ├── questioner/responses/       raw Codex responses
│   ├── questioner/decisions/       normalized JSON decisions
│   └── evolver/                    post-run distillation
└── harness/                        ledger.json, events.jsonl, snapshots, executions
```

## 4. The Interview Loop

One interview round consists of five steps:

1. **Planning draft.** The solver writes a draft of its current understanding
   and proposed modeling structure for the fields under discussion
   (`claude_workspace/planning/`). The draft is honest about what is fixed by
   the problem statement, what is inferred, and what is assumed.

2. **Question generation.** The solver calls Codex with the **full problem
   text**, the planning drafts, a compact view of the current feature table,
   and the question history. Codex returns one to three narrow clarification
   questions. The raw question text is recorded and the call is logged with
   stage `question_generation`.

3. **Question binding.** The harness issues the round:
   `issue-question --question-file <codex question> --field <primary field>`.
   The question file becomes the round prompt; its SHA-256 is bound to the
   pending round.

4. **Answer.** The solver answers only what was asked, in the answer schema
   (Section 6). The answer may update any feature fields the question touched.
   The answer call is recorded with stage `question_answer`.

5. **Review.** The solver calls Codex with the **full problem text**, the
   answer body and its SHA-256, and the current feature table. Codex reviews
   the answer against the problem statement and the current state, and returns
   a decision (Section 5). The review call is recorded with stage
   `answer_review`. The normalized decision, the raw response SHA-256, and the
   reviewed answer SHA-256 are bound together, and the harness ingests the
   round.

The loop repeats until both gates pass (Section 7). The questioner's decision
is the authority for import; a self-declared `clear` status is not sufficient.

## 5. Decision Semantics

The questioner returns exactly one of six statuses:

| Status | Meaning |
|--------|---------|
| `continue` | The current state is clear enough to proceed to the next stage |
| `local_fix` | Repair the current artifact per `required_edits`; the round is rejected and re-issued for the same field |
| `re_question` | Ask the narrow question in `next_question` before proceeding |
| `rollback` | Invalidate the listed items and return to `rollback_target` |
| `abandon_module` | Stop using the named module and record why |
| `stop` | End the run because a declared stop condition is reached |

Material risks identified in the raw review must be preserved in
`required_edits` or force a non-`continue` status.

## 6. Answer Schema

```json
{
  "round_id": 1,
  "target_field": "problem_boundary",
  "direct_answer": "",
  "feature_updates": [
    {
      "field": "problem_boundary",
      "status": "missing | partial | assumption_based | conflict | clear",
      "summary": "",
      "items": [],
      "evidence": [],
      "open_questions": [],
      "confidence": 0.0
    }
  ],
  "algorithm_modules": [],
  "assumptions": [],
  "questions_for_codex": []
}
```

Field status discipline:

- `clear` requires a substantive summary, structured items, traceable evidence
  (not only a generic label), no unresolved open questions, and confidence at
  least 0.75.
- `assumption_based` marks plausible claims not fixed by the statement; the
  assumption and its failure consequence must be stated.
- `conflict` marks incompatible evidence in the statement.
- `assumption_based` entries may be promoted to `clear` only when later
  evidence resolves them.

The eleven required feature fields are: `problem_boundary`, `variables`,
`time_structure`, `space_structure`, `relations`, `constraints`, `objectives`,
`data_support`, `uncertainty`, `algorithm_implications`,
`validation_requirements`. `writing_claims` is optional.

## 7. Gates

**Clarity gate.** Ready when at least 85% of the required fields are `clear`
and no blocker remains. A `clear` field is blocked if it lacks a summary,
structured items, non-generic evidence, or carries open questions or confidence
below 0.75.

**Question gate.** Ready when the weighted support score over the required
fields reaches 0.80 and every required field is entry-ready (same checks as the
clarity gate).

Both gates must pass before the interview phase may end. The harness refuses to
advance until the recorded questioner decisions and the gate state agree.

## 8. Post-Interview Sequence

```text
interview -> specification -> blueprint -> implementation -> execution -> writing -> complete
```

1. **Specification.** The solver converts the clarified state into a formal
   constraint specification (`qdm_constraint_spec_v1`): variables with ranges
   and units, hard/soft constraints with referenced variables, objectives with
   direction, time and space structure, algorithm sketch. A neutral reporter
   produces the method-neutral problem formalization package (P1) from the
   frozen specification. P1 is measurement-only and never fed back to the
   solver.

2. **Blueprint.** The solver generates the modeling blueprint from its own
   frozen source (the constraint specification): variables, equations,
   constraints, objectives, data structure, algorithm plan with module fusion
   decisions, validation plan, implementation plan. Codex reviews the blueprint
   with a content-bearing, SHA-bound review packet before it may proceed.

3. **Implementation.** Before writing code, the solver loads the constraint
   specification and produces a Traceability Ledger
   (`claude_workspace/tradeoff_ledger.md`) that traces every equation,
   variable, and constraint into the code, documenting any simplification or
   omission with its reason. The code artifact is registered; its
   `materialized_files` manifest must match the response exactly.

4. **Execution.** The harness runs the registered code snapshot with runtime
   file-read tracing. The program prints a provenance JSON: `synthetic_data_used`
   and `consumed_inputs` (empty for a declared no-data problem, with synthetic
   scenarios truthfully labeled). It writes `claude_workspace/final/results.md`
   and lists it with its SHA-256. Results and frozen claims are registered, and
   Codex approves them with a results-bound review before writing may begin.

5. **Writing.** The writing freeze adapter extracts frozen numbers from the
   results and builds the solution package (frozen claims plus the full
   structured results of the run); the paper is written only from the frozen
   numbers and the solution package. The paper must be a **full-depth
   engineering report written from the run's own artifacts**: every task of
   the problem answered as its own chapter (task description, modeling
   analysis, mathematical formulas in LaTeX, modeling process with
   numerical/algorithmic implementation detail, results with tables, and
   chart specifications), engineering detail and depth carried to the level
   of the implemented model — state-space equations, discretization schemes,
   observation models, algorithm parameters, uncertainty measures, and the
   exact numbers produced by the run. The paper must contain Abstract,
   Model/Methods, Results, and Limitations sections with no placeholder
   markers; every number must be a frozen number. No separate
   consistency-check report is generated; the paper is reviewed once for
   completeness and then delivered. The evolver then distills reusable
   patterns.

6. **Complete.** The harness generates the run summary from the ledger. Both
   the harness audit and the repository audit must pass, and only then may the
   run be sealed as paper-eligible.

## 9. Review Convergence Policy (blueprint / result review)

The solver independently grades every reviewer opinion before acting on it.

- **Blocking (must revise)**: issues that change the modeling direction —
  equations, constraints, algorithm family, identifiability claims,
  validation gates, or material risks in the raw review.
- **Non-blocking (record and proceed)**: format, notation, documentation,
  engineering, or minor parameterization items that do not change the
  modeling direction. Record them as known items with an implementation
  contract (tradeoff ledger) and proceed to the next stage; do not enter a
  revision loop for these.
- The reviewer is asked once per artifact revision. When the harness requires
  an `approved` token for a reviewer call and the reviewer's intent is
  approval (non-blocking issues only), the normalized decision records that
  intent with the issues preserved; the solver never fabricates an approval
  the reviewer did not intend.
- A revision cycle is entered only for blocking issues. Successive reviews
  that surface only non-blocking items are the signal to stop revising.

## 10. Audit Requirements

- Every model call records requested and provider-reported actual model,
  timestamps, request and response hashes, and — when the provider exposes them
  — call ID and token usage. Missing token telemetry is not a validity failure;
  a missing live reviewer is.
- Every artifact registration is immutable; code runs from snapshots.
- Declared data inputs must be proven consumed by runtime-observed file reads.
- The run summary derives counts, tokens, and eligibility from the ledger; they
  are never hand-edited.
- A run that cannot continue is preserved as a stopped outcome with an
  evidence-based reason; it is never discarded or replaced.
