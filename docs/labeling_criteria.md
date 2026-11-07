# Labeling criteria

## Unified rules (apply to all problems; take precedence over the general wording in the sections below)

Task 1:
- Question form does not change the judgment. If a question asserts in its premise that written content is problematic (e.g., "given that X makes Y automatically ...", "X ... yet Y ...", "but if X is used to ..., then ... is circular"), the question type is `ASSERT`; then apply the three checks to decide whether it is `DEFECT`.
- Whenever a question quotes the draft text or draft symbols, or contains a contrastive connective such as but / yet / while / given that / although / however / whereas, you must open the context file and check before judging the question type; do not judge from wording alone.

Task 2:
- If a value is preceded by "e.g." / "for example" / "such as", and nowhere else in the definition is the same value given without these words, label `PLACEHOLDER`. This also applies to non-numeric values such as data sources and functional forms.
- A threshold or parameter that is only named, with no value or rule ("a declared threshold", "delta_min declared"), is labeled `PLACEHOLDER`.
- Alternatives given as "X or Y", "X and/or Y", or separated by slashes, with no primary option specified, are labeled `PLACEHOLDER`.
- A swept parameter counts as `SETTLED` only if a value set or explicit lower and upper bounds are given.
- The need list must be written before reading any definition, based only on the problem statement and the audit items.

Task 3:
- Whether a conflict holds depends only on the definition text. Problems that would appear only from model run results (e.g., a threshold that is not reached under the actual numbers) are not reported.

Group and generating model have been hidden in all materials. While labeling, do not open any `KEY*.json`, and do not guess which group a material comes from.
Every judgment must include a quotation from the source text, copied verbatim, not paraphrased. Join non-contiguous quotations with `...`.

---

## Task 1: Does the question point out a defect in written content

Materials: `questions_<problem>.md`; each question has a context file `ctx/Xnnnn.md` containing the modeler's initial analysis, the definition draft, and the questions asked earlier in the session, as of the time of the question.

### Order of judgment

1. **First judge the question type** (look only at the question itself):
   - `ASK_CHOICE`: asks how some not-yet-decided matter should be decided, or offers several options for the other side to choose from.
   - `ASK_INFO`: requests data, facts, or external information.
   - `ASSERT`: asserts that something already written is problematic.
2. If the question type is `ASSERT`, check the three conditions below; label `DEFECT` only if all three hold:
   - The criticized object is **already written in the draft, the problem statement, or the initial analysis**, and the corresponding source text can be found in the context file or the problem statement;
   - The question names a **second concrete thing**, relative to which the criticized object is problematic;
   - The asserted problem is one of the following: the two cannot both hold; it makes some comparison or conclusion degenerate, biased, predetermined, or circular; it conflates two things that the conclusion needs to distinguish; the evidence used to estimate some quantity actually measures a different quantity.
3. Label everything else `OTHER`.

### Cases that are not DEFECT

- Explaining why a pending choice matters, e.g., "since the results depend on this choice", "this can flip whether richness helps", "this determines N*". Saying a choice matters is not saying that what is written is wrong.
- Asking about two things side by side without saying that one is problematic because of the other.
- Only saying that something is "not defined / not given", without pointing out its conflict with another thing. This is "pending", not a "defect".

### Self-check

Before labeling `DEFECT`, restate it in one sentence: "X in the draft (or problem statement, or analysis) is problematic because Y". If this restatement would distort the original meaning of the question, label `OTHER` instead.

### Output (one line per question)

```
qid | type(ASK_CHOICE/ASK_INFO/ASSERT) | label(DEFECT/OTHER) | target_in_question | target_source(source text + location draft/problem/analysis) | second_thing_in_question | defect_words_in_question | restatement
```

For non-`DEFECT` questions, fill in only the first three columns.

---

## Task 2: How the final definitions handle the ambiguous items of the problem statement

Materials: `defs/<problem>__m<k>.md`. Each file contains the problem statement, the audit item table, and 4 definitions P/Q/R/S. Compare within each file separately; do not compare across files.

Consider only audit items whose State is `U` or `M`.

### First, decompose the items

For each U/M item, **reading only the problem statement and the audit items, without looking at any definition**, first write down "what must be decided for this item so that subsequent computation can proceed", one need per line, each with a quotation from the problem statement or the audit item as its basis.

- Input items (things to be chosen before computation, e.g., comparison baseline, metric, threshold, mechanism form, boundary, time horizon, data source): what must be decided is a concrete value or rule.
- Output items (things the problem asks the model to compute, e.g., shape, threshold species count, sensitivity, recommendation): what must be decided is how to derive it from model results; the answer itself is not required in advance.
- If the problem statement does not contain enough information to determine the item: what must be decided is "cannot be determined, and on what the conclusion is conditional".

The decomposition is used uniformly for all 4 definitions and is not changed during labeling.

### Then judge need by need

For each definition and each need:

- `SETTLED`: an input item is given a concrete value or rule (a number, an explicit comparison object, a formula or functional form, an explicit criterion), so a modeler can compute by following it without making further choices; an output item states the steps for deriving it from model results; an undeterminable item states "cannot be determined" and the conditions of the conclusion.
- `PLACEHOLDER`: acknowledges that something must be decided here, but does not decide it. E.g., "a declared/specified X", "to be determined", giving X or Y without choosing, "an appropriate threshold", only listing options.
- `ABSENT`: not mentioned anywhere.

Cases that earn no credit: a statement addressed to a different need; intent without content ("will be calibrated", "chosen carefully"); mere length.

### Output

```
file | item | need_id | need(what must be decided) | basis_quote | P | Q | R | S
```

Each of the `P`, `Q`, `R`, `S` cells is written as: `label | quotation | reason (name which words make it SETTLED or PLACEHOLDER)`.

---

## Task 3: Conflicts within the final definitions

Same `defs` files. For each definition: find two sentences that cannot both hold literally, or one sentence that makes a comparison required by the definition itself degenerate or predetermined, or where the evidence for some quantity actually measures a different quantity.

- Before reporting, search the rest of the definition for text that would let both sentences hold, such as scope restrictions, exceptions, or conventions. If found, do not report.
- Judge only from what is written in the definition; do not supply any assumption for it, whether the assumption would resolve the conflict or aggravate it.
- For anything involving arithmetic or formulas, write out the derivation step by step and check it yourself.
- Do not report redundancy, vagueness, missing items, choices not yet made, style issues, or disagreement with the problem statement.

### Output

```
file | def(P/Q/R/S) | quote_a | quote_b | type(contradiction/degenerate_comparison/estimand_evidence_mismatch) | case(concrete failure example) | checked_text(passages you checked when looking for a resolution)
```

For a definition with no conflict, also write a line, marked "none".
