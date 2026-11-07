---
description: Run QDM through the verifiable benchmark harness.
argument-hint: "<problem file> <output dir> [--data <path> ... | --no-data-reason <text>]"
---

# QDM Auto Benchmark

Use the `qdm-benchmark-harness` skill for this run and follow it exactly.

Input:

$ARGUMENTS

1. Parse the problem, output directory, and complete dataset list.
2. Initialize `python -m qdm.harness.cli init` with the modeler and questioner models.
3. Run one live question/answer/review round at a time. Every questioner call goes through `python -m qdm.harness.claude_peer`, a separate session that sees only its request file.
4. Record the requested and provider-reported model of every call.
5. Stop when the questioner cannot be called. Never write a questioner decision yourself.
6. Let the harness enforce every phase transition, source-response hash, artifact registration, and review binding.
7. Run only registered code through the harness with frozen inputs. Runtime file-read traces must prove that every declared input was opened; never substitute supplied data with synthetic or hard-coded values.
8. Run both the harness audit and `qdm/auto/audit.py` before completion.
9. Derive counts, tokens, timestamps, and eligibility from the harness ledger. Never hand-edit them.
