# Problem-Driven Modeling

This package is the new mainline for the framework you described: not end-to-end black-box solving, but staged problem clarification, tree-based modeling fusion, and human-anchored evaluation.

## Core idea

The workflow separates three roles:

1. `protocol.py` turns an open problem into a structured modeling state.
2. `mechanism/` asks the next best clarification question and stops when the specification is clear enough.
3. `evaluation/` compares agent papers against strong human papers in blind A/B review.
4. `evolution/` distills reusable question/modeling structures from completed solutions.
5. `auto/` defines the fully autonomous benchmark contract for fair comparison.



## Main objects

- `claude_workspace/state/modeling_state.json`: Claude Code's solver-side
  source of truth for one problem.
- `codex_workspace/questioner/decisions/*.json`: Codex questioner's current-run
  stage-boundary review and impasse-gate decisions.
- `codex_workspace/evolver/distillations/*.json`: Codex evolver's post-run
  reusable pattern distillations.
- `feature_table`: boundary, variables, time, space, relations, constraints, objectives, data, uncertainty, algorithm implications, validation, claims.
- `algorithm_modules`: candidate reusable algorithm parts extracted during clarification.
- `clarity_gate`: whether the current information is sufficient to enter synthesis.
- `question_gate`: which field should be clarified next.
- `modeling_blueprint`: the final fusion blueprint after clarification.

## Workflow

1. Initialize a workspace from the problem text.
2. Repeatedly ask the next narrow question.
3. Import Claude's JSON answer and update the feature table.
4. Stop when the clarity gate says the problem is ready for modeling.
5. Generate a synthesis blueprint that organizes variables, formulas, constraints, modules, and validation.
6. Evaluate the resulting paper or blueprint against strong human references using blind A/B comparison.
7. Let the Codex evolver distill reusable structures into a versioned pattern library for future tasks.

## What this package is not

- It is not a black-box solver.
- It is not a generic retrieval pipeline.
- It is not a benchmark built from restricted human papers.

## Execution Modes

```text
manual:
  Human may inspect and approve intermediate steps.  Use for development.

supervised:
  Agents run automatically but may ask for human confirmation on severe
  conflicts.  Use for demonstrations and diagnosis.

benchmark_auto:
  No human intermediate decisions.  Use for paper experiments and comparisons
  with end-to-end baselines such as MM-Agent.
```

In `benchmark_auto`, the human may provide the problem and launch the run, but
all question selection, answer acceptance, rollback, blueprint revision, code
repair, and final selection are made automatically by the Claude/Codex agent
pair and recorded as files.

Benchmark workspaces are partitioned:

```text
contracts/          shared read-only contract
claude_workspace/   Claude Code solver state and final artifacts
codex_workspace/    Codex review requests, responses, decisions, logs
  questioner/       current-run questions, reviews, impasse decisions
  evolver/          post-run distillations and library update proposals
claude_workspace/writing/
                    frozen_numbers.json, solution package, paper audits
```

The `auto/audit.py` helper checks that a benchmark workspace has the required
contract, live Codex decision files, frozen writing artifacts, final artifacts,
zero human interventions, and counter values within the declared limits.

## Suggested paper framing

The strongest story is:

`open problem -> autonomous question-driven clarification -> structural specification -> tree fusion -> impasse-aware implementation -> human-anchored evaluation -> questioner/evolver separated structural evolution`

That gives you a clean AAAI-style narrative centered on information sufficiency, modeling structure, and method fusion rather than raw generation.

## Voyager inheritance

The `evolution/` module inherits Voyager's useful abstraction:

```text
completed experience -> reusable skill library -> retrieval for future tasks
```

but adapts it to mathematical modeling:

```text
completed solution -> reusable question/modeling pattern -> future prompt context
```

It does not import Voyager's Minecraft environment, Mineflayer tools, or JS skill
code.  The solver does not self-modify.  Instead, the Codex evolver observes a
completed solution and proposes structural patterns under the configured
experiment protocol.
