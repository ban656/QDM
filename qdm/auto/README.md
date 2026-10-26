# QDM Auto Benchmark Mode

This directory defines the fair, fully autonomous benchmark contract.

The development workflow can be human-supervised.  The benchmark workflow
cannot use humans for intermediate modeling decisions.

Workspace ownership:

```text
contracts/          shared read-only contract and schemas
claude_workspace/   Claude Code state, logs, artifacts, final outputs
codex_workspace/questioner/
                    Codex current-run questions, reviews, impasse decisions
codex_workspace/evolver/
                    Codex post-run distillation and reusable pattern proposals
claude_workspace/writing/
                    Frozen numbers, writer package, paper consistency audits
```

This split is part of the benchmark protocol.  It keeps the primary solver's
work separate from Codex's current-run questioner and post-run evolver so the
run can be audited afterward.

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

Agent roles:

```text
Claude Code:
  primary autonomous solver / answer agent

Codex questioner:
  current-run questioner, reviewer, adversarial checker, impasse gate

Codex evolver:
  post-run structural distiller and reusable pattern proposer
```

Benchmark runs must use live `codex-plugin-cc`.  Simulated Codex decisions are
allowed only for dry-run development and fail the strict audit.

Before `paper.md` is written, the run must execute:

```powershell
python qdm/writing/freeze.py `
  --workspace runs/demo
```

The paper writer may use only `claude_workspace/writing/frozen_numbers.json`
and `claude_workspace/writing/solution_package_for_writer.md` for numerical
claims.

Prepare a workspace:

```powershell
python qdm/auto/contract.py `
  --problem path/to/problem.txt `
  --output runs/demo `
  --title demo
```

Then open Claude Code and run:

```text
/qdm:auto-benchmark path/to/problem.txt
```

Audit a completed run:

```powershell
python qdm/auto/audit.py `
  --workspace runs/demo
```

For a workspace that only contains the generated contract, use
`--allow-incomplete` to check the scaffold without requiring final outputs.
