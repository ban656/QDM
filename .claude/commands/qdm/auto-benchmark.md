---
description: Run QDM-Agent through the verifiable benchmark harness.
argument-hint: "<problem file> <output dir> [--data <path> ... | --no-data-reason <text>]"
---

# QDM Auto Benchmark

Use the `qdm-benchmark-harness` skill for this run and follow it exactly.

Input:

$ARGUMENTS

1. Parse the problem, output directory, and complete dataset list.
2. Initialize `python -m qdm.harness.cli init`.
3. Run one live question/answer/reviewer round at a time.
4. Request `gpt-5.5` for each live Codex review and preserve the provider-reported actual model.
5. Stop when provider telemetry or `/codex:*` is unavailable. Never create fallback or simulated decisions.
6. Let the harness enforce every phase transition, source-response hash, artifact registration, and reviewer approval binding.
7. Run only registered code through the harness with frozen inputs. Runtime file-read traces must prove that every declared input was opened; never substitute supplied data with synthetic or hard-coded values.
8. Run both harness audit and `qdm/auto/audit.py` before completion.
9. Derive counts, tokens, timestamps, and eligibility from the harness ledger. Never hand-edit them.

The following historical scaffolds are forbidden for a paper-eligible run:
`batch_runner.py`, `run_2021_batch.py`, `qdm_answers_*.py`, and
`qdm_*_rep*.py`.
