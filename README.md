# Question-Driven Modeling (QDM)

Code and results for *Specify Before You Plan: Recognizing Interpretive Uncertainty in LLM-Based Mathematical Modeling* (submitted to Pattern Recognition Letters).

QDM resolves the decisions an open-ended modeling statement leaves open before planning. A modeler writes an eleven-field specification; an isolated questioner, which sees the written draft but not the modeler's reasoning, asks what remains open; the modeler answers every question itself. Only after the clarity and support gates pass is the problem decomposed, solved and written up.

## Reproduce the reported numbers

```bash
python scripts/reproduce_numbers.py
```

Standard library only, no API calls. It reads `results/*.csv` and recomputes the audit (Table 1), the MMBench scores and sign tests, the AI Scientist reviewer scores (Fig. 2), the per-run statistics and questioner models (Tables S1–S2), and the controlled experiment (Fig. 3).

## Repository layout

| Path | Contents |
|---|---|
| `qdm/` | QDM implementation: specification and question policy (`mechanism/`), run harness (`harness/`), autonomous run contract and audit (`auto/`), writing freeze (`writing/`) |
| `.claude/` | Claude Code commands (`/qdm:*`) and skills that drive a QDM run |
| `evaluation/` | MMBench whole-paper scoring and AI Scientist review |
| `controlled/` | Controlled questioning experiment (conditions A–D): runner, blinding and tracing scripts |
| `results/` | Per-item and per-paper results behind every reported number |
| `examples/` | Three papers written end to end by QDM (2023_A, 2023_C, 2022_C) |
| `docs/` | Audit codebook and labeling criteria |

### Results files

| File | One row per |
|---|---|
| `audit_items.csv` | audited decision-critical item of the 110 MMBench problems (layer, state E/U/M) |
| `mmbench_scores.csv` | paper × scoring run (AE, MR, PS, RBA) |
| `ai_scientist_review.csv` | paper (reviewer scores, decision, length) |
| `qdm_runs.csv` | QDM run (questioning rounds, model calls, questioner model per round) |
| `controlled_questions.csv` | question in the controlled experiment (condition, model, round, label) |
| `controlled_requirements.csv` | final definition (settled / placeholder / absent requirements) |

The complete run records, all 30 evaluated papers and the item-level annotations will be released upon publication.

## Running QDM

QDM runs inside [Claude Code](https://code.claude.com/docs/en/overview). From the repository root:

```bash
python -m qdm.auto.contract --problem <problem file> --output runs/<task>
```

then start Claude Code in the repository and run `/qdm:auto-benchmark <problem file>`. After a run, `python qdm/auto/audit.py --workspace runs/<task>` checks the workspace. Tests: `python -m pytest qdm/tests`.

## External resources

- **MMBench problems and the MM-Agent baseline**: [usail-hkust/LLM-MM-Agent](https://github.com/usail-hkust/LLM-MM-Agent) (commit `74d84f3`). Set `MMBENCH_DIR` to its `MMBench` folder, or place the repository at `external/LLM-MM-Agent`.
- **AI Scientist reviewer**: [SakanaAI/AI-Scientist](https://github.com/SakanaAI/AI-Scientist); set `AI_SCIENTIST_DIR`.
- **API access** is read from environment variables (`QDM_API_BASE`, `QDM_API_KEY`, `QDM_API_KEY_GPT`, `QDM_DS_KEY`); no keys are stored in this repository.

## License

MIT
