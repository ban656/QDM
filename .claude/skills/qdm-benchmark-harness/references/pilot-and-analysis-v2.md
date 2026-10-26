# Pilot, Metrics, and Threat Controls v2

## Confirmatory Metrics

Primary endpoint per problem:

```text
Delta_P1 = mean_judges(P1 score for qdm_full)
         - mean_judges(P1 score for mm_agent_native)
```

Average seed replicates within the problem before computing the cross-problem
estimate. Report the mean paired difference and a problem-level bootstrap 95%
confidence interval.

Secondary endpoints:

- P2 overall paired difference;
- each frozen P1 and P2 dimension;
- requirement survival rate from P1 to blueprint, implementation, execution,
  results, and paper;
- defect attribution proportions;
- terminal completion rate and failure stage;
- valid execution, validation-pass, and supported-claim rates;
- calls, wall time, and tokens when actually available.

Do not select dimensions after seeing method labels. Mark all dimension-level
tests exploratory unless a multiplicity procedure is frozen before the main run.

## Pilot Scope

Run a protocol pilot before the confirmatory five-year dataset. Use at least two
problems with different structures and two paired replicates per problem. The
pilot checks feasibility and measurement only; do not use its effect direction
to rewrite the hypothesis, and do not pool pilot outcomes into confirmatory
statistics after changing any protocol component.

Pilot acceptance criteria:

- 100% of pairs have identical P0 except `protocol_condition`;
- 100% of terminal outcomes, including failures, are retained;
- 100% of frozen P1 packages either validate or are explicitly represented as
  missing/invalid in the blind packet;
- zero method mappings, run paths, or condition labels remain in public packets;
- every accepted score passes packet-hash and evidence-pointer validation;
- at least two distinct judge IDs score both endpoints;
- mean absolute judge difference is at most 1 point and interval
  Krippendorff alpha is at least 0.67, where estimable;
- no downstream solver reads the neutral P1 reporting artifact;
- repository and harness audits agree on run status.

If a criterion fails, revise the protocol and restart the pilot with new
replicates. Do not patch already frozen runs.

## Threat Controls

- Construct validity: separate P1, propagation, P2, and cost; never use question
  count as a proxy for constraint clarity.
- Measurement intervention: the same neutral reporter serializes native
  pre-solution evidence for both methods and its P1 output is not returned to
  either solver.
- Capability confounding: pair only identical problem/data/model/tool/seed and
  total-budget envelopes.
- Survivorship bias: include `complete` and `stopped` outcomes.
- Leakage: random A/B labels, public/private separation, redaction log, and
  reveal only after score freeze.
- Pseudoreplication: problems are `n`; seeds, judges, calls, questions, and
  requirements are nested observations.
- Judge drift: use frozen anchors and independent contexts; report agreement.
- Telemetry bias: token fields are optional and never imputed.
- Selective reporting: retain every initialized paired replicate and publish
  exclusions with P0 or contamination evidence.

Expert human blind review is not a validity requirement for every item. For a
KBS submission, a predeclared human calibration subset of roughly 10-20% of
problems is useful for checking whether automated judges preserve rank order and
apply the anchors similarly; keep it separate from the primary automated score
unless the combination rule is frozen in advance.

