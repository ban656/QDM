# MMBench Information-Structure Codebook v1

## Purpose

This codebook defines a reproducible annotation protocol for quantifying the
information structure of open-ended mathematical-modeling problems. It is
designed to test the claim that planning and solving are downstream of a prior
specification-synthesis step. The unit of analysis is a **decision-critical
formalization item**, not a sentence, token, or bullet point.

The codebook is frozen before annotating the benchmark. Any later change must
be recorded as a new version and all affected items must be re-adjudicated.

## Corpus scope

- Primary corpus: MMBench problems from 2021--2025, using every problem file
  available in `MMBench/problem/`.
- Current inventory: 32 JSON problem records (2021: 6; 2022: 6; 2023: 8;
  2024: 6; 2025: 6). The 2023 Y/Z records are retained because they are
  present in the released corpus; exclusions require a documented reason.
- The JSON record is the authoritative source. A companion `.txt` file,
  dataset file, image, or addendum is included only when listed by the record
  or present in the frozen manifest.
- Corpus characterization and agent-performance evaluation are separate
  populations. A full-corpus characterization does not imply that QDM was run
  on every characterized problem.

## Annotation unit

An annotation item is the smallest proposition whose resolution could affect a
formal model, an algorithmic choice, an intervention, a reported conclusion,
or a validation check. One item must have one evidence span in the problem
record (or an explicit `missing` rationale when the item is required but not
provided).

Split compound requirements when their parts can be resolved independently.
For example, “choose the most effective three interventions” contains at least
the target objects, the meaning of “effective,” and the cardinality constraint.
Do not split grammatical variants that have the same modeling consequence.

## Field ontology (12 recurring specification fields)

Each item receives exactly one primary field. Secondary tags may be used for
cross-field dependencies.

| Code | Field | What belongs here |
|---|---|---|
| F1 | System and boundary | Entities, system scope, inclusion/exclusion, population or network boundary |
| F2 | Variables and states | Decision variables, outcomes, states, latent quantities, units of analysis |
| F3 | Parameters and observations | Numerical parameters, measured data, data sources, sampling or measurement definitions |
| F4 | Units, scale, and granularity | Physical units, normalization, temporal/spatial resolution, aggregation level |
| F5 | Time horizon and dynamics | Time window, ordering, frequency, lag, evolution, steady-state or transient interpretation |
| F6 | Spatial scope and topology | Location, geometry, adjacency, routes, spatial dependence, network topology |
| F7 | Mechanisms and relations | Causal/physical/statistical relations, equations, transition rules, dependence structure |
| F8 | Objectives and priorities | Target quantities, utility/loss, ranking, trade-offs, weights, priority rules |
| F9 | Constraints and resources | Bounds, budgets, capacities, feasibility, operational restrictions, non-destructive or policy constraints |
| F10 | Uncertainty and distribution | Noise, stochasticity, heterogeneity, missingness, confidence, sensitivity, distributional assumptions |
| F11 | Identifiability and intervention | What can be inferred, confounding, causal direction, counterfactuals, interventions, provenance |
| F12 | Output and validation obligations | Required deliverables, evaluation criteria, checks, baselines, reproducibility, reporting format |

The ontology is intentionally a coverage-oriented coding scheme rather than a
claim that these are the only concepts in all mathematical modeling.

## Information-state labels

Every item receives exactly one state:

| Code | State | Decision rule |
|---|---|---|
| E | Explicit | Directly stated in the problem text or directly supplied in an attached dataset/metadata field. |
| I | Inferable | A single interpretation follows from the text plus a standard, uncontroversial convention or domain fact; no competing interpretation would change the model. |
| U | Underspecified | Two or more reasonable interpretations remain, and choosing among them could change a variable, relation, objective, constraint, intervention, or validation decision. |
| M | Missing | The item is required for an executable or checkable specification, but it is neither supplied nor reliably inferable from the record. |

Use `I` conservatively. If domain knowledge narrows but does not uniquely
determine the interpretation, use `U`. Use `M` only when the missing item is
necessary for a specified downstream decision; do not label optional details as
missing.

## Decision-criticality label

Each item receives one criticality label:

- `C`: decision-critical. Resolving it can change model structure, variable
  meaning, parameter interpretation, objective, constraint, intervention,
  algorithm, or validation conclusion.
- `N`: non-critical for the intended task. It may improve exposition but does
  not change the executable specification or its checks.

The primary benchmark endpoint uses `C` items. All items are retained for
descriptive statistics and auditability.

## Evidence and provenance fields

For every item record:

- `task_id`: e.g. `2025_A`;
- `item_id`: stable identifier such as `2025_A_F8_03`;
- `field`: one of `F1`--`F12`;
- `state`: one of `E`, `I`, `U`, `M`;
- `criticality`: `C` or `N`;
- `evidence_location`: JSON key plus character offsets or a short section label;
- `evidence_quote`: verbatim quote for `E`, `I`, or `U`; for `M`, quote the
  requirement that makes the item necessary and explain why it is absent;
- `interpretation`: one-sentence operational reading;
- `downstream_consequence`: model or validation decision affected;
- `secondary_tags`: optional list of other field codes;
- `risk_type`: optional mechanism label (`definition_ambiguity`,
  `calibration_missing`, `boundary_condition`, `confounding`,
  `measurement_limit`, or `structural_nonidentifiability`);
- `annotator_id` and `adjudication_status`.

Quotes must be copied verbatim from the frozen source, including punctuation;
do not paraphrase evidence in place of a quote.

## Annotation procedure

1. Freeze the corpus manifest, source hashes, and this codebook version.
2. Pilot-code six problems (one A--F spread across the years) to identify
   ontology overlaps and refine examples without changing the decision rules.
3. Two annotators independently segment and label the same complete corpus.
4. Compute agreement separately for segmentation overlap, field labels, state
   labels, and criticality labels. Use Cohen's kappa for categorical labels and
   report the raw agreement and the number of items.
5. Resolve disagreements in an adjudication pass that can inspect the source
   but not model outputs or performance scores.
6. Freeze the adjudicated table and generate all reported statistics from that
   table only.

LLMs may propose candidate spans during pilot work, but labels entering the
   reported analysis require independent human confirmation. Annotators must
   not inspect QDM outputs when labeling the problem itself.

## Quantitative endpoints

Let (N_{tfs c}) be the number of items for task (t), field (f), state
(s), and criticality (c).

### State prevalence

\[
P(s)=\frac{\sum_{t,f,c}N_{tfsc}}{\sum_{t,f,s,c}N_{tfsc}}.
\]

Report both micro prevalence (all items pooled) and macro task prevalence
(compute within task first, then average over tasks).

### Critical ambiguity burden

\[
A_t^{\mathrm{crit}}=
\frac{\sum_f(N_{tfUC}+N_{tfMC})}
{\sum_{f,s}N_{tfsc}}.
\]

This is the primary characterization endpoint: the proportion of
decision-critical items that are underspecified or missing.

### Field-specific state profile

\[
P(s\mid f)=\frac{\sum_{t,c}N_{tfsc}}
{\sum_{t,s,c}N_{tfsc}}.
\]

Use this profile to derive the question-priority order. Do not select fields
because they appear in the QDM prompt; select them from the frozen corpus
statistics and pre-registered tie-breaking rules.

## Missingness versus structural non-identifiability

The state label describes the problem statement. It does not by itself say why
an item is unresolved. Use `risk_type` to separate the following cases:

- `calibration_missing`: a mapping or parameter could be estimated if a
  reference dataset or calibration experiment were supplied;
- `boundary_condition`: the initial state, geometry, or system boundary is not
  fixed;
- `confounding`: multiple mechanisms can produce the same observation;
- `measurement_limit`: the requested quantity is not observable under the
  stated measurement constraints;
- `structural_nonidentifiability`: even noiseless observations of the stated
  output would not uniquely recover the requested quantity without additional
  assumptions or external evidence;
- `definition_ambiguity`: the target or success criterion itself has multiple
  reasonable operational definitions.

For example, cumulative wear can identify an accumulated wear exposure but not
uniquely separate “many users for a short period” from “few users for a long
period.” The latter is a structural-identifiability issue, not merely a missing
parameter. A proposed nonlinear wear-rate term is a model extension and must be
marked as an assumption unless independently supported.

### Optional difficulty and propagation analyses

For a task-level model-performance score (Y_t), report the exploratory
association between (A_t^{\mathrm{crit}}) and the paired QDM gain
\(\Delta_t=Y_t^{QDM}-Y_t^{baseline}\) using Spearman correlation and a
problem-level bootstrap confidence interval. With fewer than 30 evaluated
tasks, treat this as descriptive rather than causal.

## Quality controls and exclusion rules

- Exclude only records that fail to parse, are duplicated, or lack the frozen
  problem source; record every exclusion in the manifest.
- Do not infer an item from a model answer, a solver's assumption, or a
  benchmark evaluator rubric.
- Do not count repeated mentions of the same item more than once unless the
  repetitions impose distinct constraints.
- A dataset's presence is not itself an explicit modeling instruction. Code its
  variables, units, provenance, and restrictions separately.
- Report the number of items per task and field so that the denominator is
  auditable.

## Planned paper presentation

The main paper should show (i) the four-state distribution, (ii) the
field-by-state heatmap or stacked bars, and (iii) the critical ambiguity burden
with uncertainty from task-level bootstrap. The complete item-level table,
quotes, adjudication log, and scripts belong in the code supplement.
