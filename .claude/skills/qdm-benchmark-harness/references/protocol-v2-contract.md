# Protocol-Level Benchmark Contract v2

## Research Contrast

The primary comparison is:

```text
same base agent + mm_agent_native protocol
versus
same base agent + qdm_full protocol
```

Both conditions solve the complete problem. Question counts are cost measures,
not experimental treatments and not sample units. The unit of analysis is the
problem; random seeds are nested replicates within a problem.

## Frozen Objects

### P0: Capability Envelope

Freeze at `init`: problem and data hashes; answerer, reviewer, and neutral
reporter models; tool and external-knowledge permissions; random seed; total
agent-call, blueprint-revision, and code-repair budgets. Paired runs must have
identical P0 values. The sole intended difference is `protocol_condition`.

### P1: Problem Formalization Package

Before solution design, register a frozen
`problem_formalization_package_v2` artifact. It contains atomic sourced
requirements, boundaries and exclusions, operational targets, observables,
variables, relations, executable hard/soft constraints, assumptions and their
failure consequences, uncertainty, identifiability/confounding, validation
predicates, complete traceability, unresolved-item classification, and closure.

The schema is method-neutral. It records what the protocol made explicit; it
must not prescribe QDM questions to the native baseline. A package with an
unresolved blocker cannot freeze.

For `qdm_full`, bind P1 to the latest frozen `constraint_spec`. For
`mm_agent_native`, first register the complete pre-solution native
`protocol_trace`, then bind P1 to that trace. The P1 reporter is a measurement
adapter: its output is frozen and must never be fed back to the solver.

Generate the reporter request with `make-formalization-request`; do not author
it manually. After P1 is frozen and the harness advances, generate the solver's
request with `make-blueprint-request`. That request reads the method's original
frozen source, not the neutral P1 artifact.

```powershell
python -m qdm.formalization template `
  --problem-id <id> --output <formalization.json>
python -m qdm.formalization validate `
  --input <formalization.json>
```

### P2: Solution Bundle

P2 is the frozen blueprint, code snapshot, execution manifest, results, frozen
claims, and paper. Existing execution and claim-binding gates remain mandatory.

## Initialization

```powershell
python -m qdm.harness.cli init `
  --protocol-condition qdm_full --experiment-mode adaptive_questions `
  --output <run> --problem <problem> --answer-model <model> `
  --reviewer-model <model> --reporter-model <model> --seed <seed> `
  --max-total-agent-calls <n> --tool-policy <tool-policy.json> `
  [--data <asset> ... | --no-data-reason <reason>]
```

Initialize the baseline with identical arguments except
`--protocol-condition mm_agent_native`. Do not call `issue-question` in that
condition. Execute native MM-Agent, register its pre-solution trace during
`interview`, then advance to `specification`. Record every native model turn
with role `answerer` and stage `native_protocol`; bind the trace through
`metadata.source_call_ids` so native calls consume the same total-call budget.

## Artifact Sequence

```text
qdm_full:        QDM interview -> constraint_spec -> formalization (P1)
mm_agent_native: native trace   -> formalization (P1)
both:            blueprint -> implementation -> execution -> writing -> complete
```

All registered artifacts are copied into immutable harness snapshots. Start a
new replicate after any code, prompt, protocol, model, or evaluation change.

If a run cannot continue, preserve it as an experimental outcome instead of
discarding it:

```powershell
python -m qdm.harness.cli stop-run `
  --output <run> --category <failure-category> --reason <evidence-based-reason>
```

Never replace a stopped run to improve completion statistics. A new replicate
may be added, but the stopped replicate remains in the analysis set.

## Review Requests

Do not write blueprint/result review requests by hand:

```powershell
python -m qdm.harness.cli make-review-request `
  --output <run> --stage blueprint_review `
  --destination <run>/codex_workspace/questioner/requests/blueprint.md
```

Use `result_review` analogously. Hash-only requests are invalid in v2.
