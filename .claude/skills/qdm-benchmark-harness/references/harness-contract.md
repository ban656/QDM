# Harness Contract

## Command Sequence

Initialize with data:

```powershell
python -m qdm.harness.cli init `
  --output <run-dir> --problem <problem-file> --data <dataset-path> `
  --answer-model <actual-answerer-family> --reviewer-model <reviewer> `
  --reporter-model <neutral-p1-reporter> --protocol-condition qdm_full `
  --seed <seed> --max-total-agent-calls <n> --tool-policy <policy.json>
```

For a problem with no supplied data, replace `--data` with a defensible
`--no-data-reason`.

Run one interview round:

```powershell
python -m qdm.harness.cli issue-question --output <run-dir>
python -m qdm.harness.cli record-call <answerer-call-fields>
python -m qdm.harness.cli record-call <reviewer-call-fields>
python -m qdm.harness.cli ingest-answer <round-artifact-fields>
```

Use stage `question_answer` for the answerer and `answer_review` for the
reviewer. Both calls must carry the current `round_id`. The reviewer request
must include the exact SHA-256 of the raw answer response.

The normalized reviewer decision must contain:

```json
{
  "round_id": 1,
  "status": "continue | local_fix | re_question | rollback | abandon_module | stop",
  "codex_model_requested": "gpt-5.5",
  "codex_model_actual": "provider-reported-name",
  "raw_response_sha256": "sha256-of-raw-review-response",
  "reviewed_answer_sha256": "sha256-of-raw-answer-response",
  "reason": "",
  "invalidated_items": [],
  "rollback_target": "",
  "next_question": "",
  "required_edits": [],
  "confidence": 0.0
}
```

Advance and register artifacts in this order:

```text
interview -> specification
  register constraint_spec; use make-formalization-request; register and freeze P1
specification -> blueprint
  use make-blueprint-request; register blueprint; record a content-bound blueprint_review approval
blueprint -> implementation
  register code
implementation -> execution
  run-code; register its execution-produced final/results.md; register a results-bound freeze;
  record an SHA-bound result_review approval
execution -> writing
  register paper and evolution
writing -> complete
  harness generates run_summary
```

Use `status` after every stage. After completion, run `audit`, the repository
audit, and then `seal`; rerun both audits after sealing.

Every implementation must print a JSON object containing:

```json
{
  "provenance": {
    "synthetic_data_used": false,
    "consumed_inputs": [
      {"path": "absolute-manifest-path", "sha256": "manifest-sha256"}
    ]
  },
  "results": {}
}
```

`results` must be non-empty. The harness injects runtime file-read tracing and
rejects an execution when a declared input was merely listed but never opened.
The implementation must write `claude_workspace/final/results.md`, list it in
the printed `artifacts` array, and include its SHA-256. Register that
execution-produced file as the canonical `results` artifact. Register `freeze` with metadata
`{"source_results_sha256":"<latest-results-sha256>"}`.

For `blueprint_review` and `result_review`, use `make-review-request`. The
request must contain the actual reviewed artifacts, rubric, and hashes. The raw
reviewer response must contain:

```json
{
  "status": "approved",
  "reviewed_artifact_sha256": "<sha256 from the request>",
  "issues": []
}
```

For `result_review`, also include the results and freeze SHA-256 values in both
the request and response as `reviewed_results_sha256` and
`reviewed_freeze_sha256`.

A generated file (`constraint_spec`, `blueprint`, single-file `code`, `paper`,
or `evolution`) must be the exact raw response registered for its source call.
For a code directory, the raw implementation response must contain a
`materialized_files` array listing every relative file path and SHA-256; the
harness rejects any difference. Registration copies the accepted code into
`harness/code_snapshots/code_NNNN`; `run-code` executes that immutable snapshot
even when invoked with the corresponding editable source-script path.

If `run-code` fails in execution, preserve that failed execution artifact. A
new live `implementation` call may generate and register a revised code
artifact while the run remains in execution; then invoke `run-code` again.
Every revision and execution attempt remains in the ledger and contributes to
`code_repair_rounds` and `failed_execution_attempts`.

For a declared no-data theoretical problem, keep `consumed_inputs` empty and
state truthfully whether simulation or synthetic scenarios were used.

## Live Call Requirements

Every call requires request and response files inside the run directory,
monotonic timestamps, and requested/provider-reported model names. When the
provider exposes a call ID and token usage, record them with
`telemetry_status=verified`. Otherwise use `partial` or `unavailable`, omit the
missing values, and never insert estimates. Missing token telemetry is not a
blocking failure; a missing live reviewer remains blocking when review is part
of the selected experiment mode.

## New Replicate Conditions

Start a new replicate after any protocol, policy, gate, prompt, harness, skill,
model/provider, problem, dataset, or frozen implementation change.
