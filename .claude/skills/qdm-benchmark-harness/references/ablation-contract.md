# QDM Question-Mechanism Ablation Contract

This is a secondary mechanism ablation, not the primary test of the paper's
claim. The primary test compares `qdm_full` with `mm_agent_native` under
`protocol-v2-contract.md`.

## Controlled Difference

Compare `adaptive_questions` with `one_shot`. Change only the interview
strategy. Keep the problem, data, answer model, random seed, constraint-spec,
blueprint, implementation, execution, result review, writing, and audits the
same.

## One-Shot Run

Initialize with:

```powershell
python -m qdm.harness.cli init `
  --experiment-mode one_shot `
  --output <run-dir> --problem <problem-file> `
  --answer-model <model> --reviewer-model <model> `
  [--data <file> ... | --no-data-reason <text>]
```

Then call `issue-question` once. The generated prompt requests every feature
field in one response. Do not split the prompt, request clarification, import a
second answer, or switch back to adaptive questioning.

Use one independent `answer_review` decision for the complete one-shot answer.
If any required field remains partial, conflicting, unsupported, low
confidence, or open, record the ablation as an interview-gate failure. Do not
repair it with another elicitation round.

After the interview gate, use the normal harness contract without changes.

## Reporting

Report the pair as different experiment modes, not as replicates of one mode.
At minimum compare completion, required-field coverage, gate pass/fail,
constraint count, downstream execution success, result consistency, and final
task coverage. Report calls, tokens, and time as efficiency outcomes when
available; missing token telemetry must remain missing rather than estimated.
