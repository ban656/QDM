---
name: qdm-codex-doubt-gate
description: Use when Claude Code is uncertain about a mathematical modeling answer, sees a bottleneck, suspects an algorithm/constraint/formula/result may be weak, or is tempted to simplify with random, greedy, heuristic, grid-only, or unsupported pruning. This skill turns self-doubt into a mandatory Codex questioner checkpoint before proceeding.
---

# QDM Codex Doubt Gate

Use this skill to convert solver uncertainty into a recorded Codex questioner
checkpoint.  The purpose is not to ask Codex for a full solution.  The purpose
is to force the current answer, bottleneck, simplification, or algorithm choice
to survive adversarial questioning before the run continues.

Every live Codex call triggered by this gate must request the fixed reviewer
model `gpt-5.5`.  Record both the requested model and the provider-reported
actual model in the response log or decision JSON.  If the actual model differs
from `gpt-5.5`, keep that reported value and explain the provider mapping in
`codex_model_note`; do not relabel it or fail solely because of the mismatch.

## Trigger Conditions

Invoke this gate immediately when any of the following is true:

1. The solver is unsure whether the current modeling answer is correct.
2. The solver reaches a bottleneck, repeated failed implementation, unstable
   numeric result, or unclear formula-to-code mapping.
3. A hard constraint is being summarized rather than represented as an explicit
   checkable item.
4. The solver proposes random search, greedy assignment, heuristic scheduling,
   grid-only search, hand-pruned variables, or "only X can contribute" without
   a documented proof or validation plan.
5. The solver cannot state why the chosen solver family matches the problem
   structure.
6. The blueprint says "continue" but the raw Codex review contains risk words
   such as weak, risky, may miss, ambiguous, pure random, greedy, not globally
   optimal, oversimplified, double-count, or convergence.

## Required Packet

Write a request under:

```text
<auto_workspace>/codex_workspace/questioner/requests/doubt_gate_*.md
```

Include:

```text
Stage:
Artifact under doubt:
Exact doubtful claim or bottleneck:
Relevant constraints:
Current proposed algorithm or formula:
Why Claude is unsure:
What would count as enough evidence to continue:
Requested Codex decision: continue | local_fix | re_question | rollback | abandon_module | stop
Codex model requested: gpt-5.5
Codex model actual:
Codex model note:
```

Store the raw response under:

```text
<auto_workspace>/codex_workspace/questioner/responses/doubt_gate_*.md
```

Store the normalized JSON under:

```text
<auto_workspace>/codex_workspace/questioner/decisions/doubt_gate_*.json
```

For benchmark runs, include `round_id` and `raw_response_sha256` and submit the
decision through `qdm-benchmark-harness`. A missing live-call record is a stop
condition, not permission to synthesize a decision.

## Algorithm Choice Gate

If the doubt involves an optimizer, the request must ask Codex to check this
schema:

```json
{
  "solver_family": "",
  "problem_structure": "",
  "why_this_solver": "",
  "why_not_random_or_greedy": "",
  "constraint_handling": "",
  "determinism": "",
  "global_or_local_claim": "",
  "acceptance_metric": "",
  "fallback_solver": ""
}
```

If the chosen method uses random, greedy, heuristic, grid-only, or manual
pruning, also require:

```json
{
  "seed_or_determinism": "",
  "budget": "",
  "multi_start_or_grid_resolution": "",
  "convergence_or_resolution_check": "",
  "baseline_comparison": "",
  "failure_condition": "",
  "rollback_target": "algorithm_implications"
}
```

Missing fields are not cosmetic.  They require `local_fix`, `re_question`, or
`rollback`, not unconditional `continue`.

## Constraint Ledger Gate

If the doubt involves constraints, Codex must check that each hard constraint is
represented as a ledger item:

```json
{
  "id": "",
  "text": "",
  "type": "hard | soft | assumption",
  "scope": [],
  "checked_by": "",
  "failure_action": ""
}
```

Do not mark `constraints` as clear if `items` only contains a round label such
as `Round 6: constraints`.

## Decision Normalization Rule

Do not compress a risky raw review into a harmless `continue`.

If the raw Codex response names a material risk, the normalized decision must
either:

1. set `status` to `local_fix`, `re_question`, or `rollback`; or
2. keep `status: continue` only when every material risk is copied into
   `required_edits` with an explicit acceptance condition.

## After The Decision

Apply the Codex questioner decision before doing more implementation:

- `continue`: proceed and cite the decision path in the next artifact.
- `local_fix`: repair the current artifact and rerun the gate if the risk was
  algorithmic, formulaic, or numerical.
- `re_question`: ask the narrow question before updating state.
- `rollback`: invalidate affected state fields and return to the rollback
  target.
- `abandon_module`: record the abandoned module and use a fallback.
- `stop`: write the stop condition in `run_summary.json`.
