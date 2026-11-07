# qdm package

| Module | Contents |
|---|---|
| `protocol.py` | Modeling state: the eleven-field feature table, interview history, clarity and question gates, constraint specification, blueprint prompts |
| `mechanism/` | Question policy: field priority and the prompt for one interview round |
| `harness/` | Verifiable run harness: phase order, recorded model calls, hash-bound artifacts, traced code execution, audits (`cli.py`); `claude_peer.py` starts the isolated questioner |
| `auto/` | Benchmark contract and prompt packet for an autonomous run (`contract.py`), repository audit of a finished run (`audit.py`) |
| `writing/` | Writing freeze: runs the registered code and freezes every number the paper may cite |
| `tests/` | Unit tests (`python -m pytest qdm/tests`) |

`PROTOCOL.md` specifies the interview loop, decision statuses, answer schema,
gates and the post-interview sequence.

## Roles

- **Modeler**: the Claude Code session that runs `/qdm:auto-benchmark`. It
  writes the planning drafts, answers every question, and writes the
  specification, blueprint, code and paper.
- **Questioner**: a separate Claude Code session started by
  `qdm/harness/claude_peer.py` for every question and review call. It reads
  only the request file (problem, written draft, specification, question
  history), so it never sees the modeler's reasoning. It writes no artifact.

## Run layout

```text
contracts/              shared read-only contract and prompt packet
claude_workspace/       modeler state, drafts, artifacts, final paper
questioner_workspace/   questioner requests, raw responses, decisions
harness/                ledger, event chain, snapshots, executions
```

No human takes an intermediate decision in a benchmark run: question
selection, answer acceptance, rollback, blueprint revision, code repair and
final selection are all recorded as files.
