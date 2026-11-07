# QDM Auto Benchmark Mode

This directory defines the fully autonomous benchmark contract. No human takes
an intermediate modeling decision in a benchmark run.

Workspace ownership:

```text
contracts/              shared read-only contract and prompt packet
claude_workspace/       modeler state, logs, drafts, artifacts, final outputs
claude_workspace/writing/
                        frozen numbers and writer package
questioner_workspace/   questioner requests, raw responses, decisions
```

The split keeps the modeler's work separate from the questioner's, so the run
can be audited afterward.

Allowed human actions:

- provide the problem and attachments
- launch the run
- inspect final outputs

Forbidden during benchmark runs:

- deciding whether an answer is accepted
- choosing the next question
- choosing or rejecting a modeling route
- approving rollback
- repairing formulas/code
- selecting the final result

Roles:

```text
Modeler:
  the Claude Code session running the benchmark; answers every question and
  writes the specification, blueprint, code and paper

Questioner:
  a separate session (qdm/harness/claude_peer.py) that sees the problem, the
  written draft, the specification and the history, not the modeler's
  reasoning; asks the questions and reviews answers, blueprint and results
```

The questioner must be a live call. A run that cannot call it stops; a
questioner decision written by the modeler fails the audit.

Before `paper.md` is written, the run must execute:

```bash
python qdm/writing/freeze.py --workspace runs/demo
```

The paper writer may use only `claude_workspace/writing/frozen_numbers.json`
and `claude_workspace/writing/solution_package_for_writer.md` for numerical
claims.

Prepare a workspace:

```bash
python -m qdm.auto.contract --problem path/to/problem.txt --output runs/demo --title demo
```

Then open Claude Code and run:

```text
/qdm:auto-benchmark path/to/problem.txt
```

Audit a completed run:

```bash
python qdm/auto/audit.py --workspace runs/demo
```

For a workspace that only contains the generated contract, use
`--allow-incomplete` to check the scaffold without requiring final outputs.
