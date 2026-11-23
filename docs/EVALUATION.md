# Evaluation and learning contract

The essential question is whether a specific intervention improves a comparable task
while preserving its required result and constraints. Frequency, confident prose,
passing syntax checks and a merged patch do not answer that question.

## Define the experiment before the result

Record the following before running a candidate:

- A falsifiable mechanism and bounded applicability.
- A frozen task set and acceptance criteria, including required correctness and
  completion checks.
- A baseline version and an intervention version. Record which single change, or
  explicitly named bundle of changes, is being compared.
- Model, harness, tools, environment, seed when controllable, and relevant resource
  limits. Preserve unknown values rather than guessing them.
- One primary benefit metric, protected metrics and allowed tolerances.
- Sample size or budget, stopping rule, and how failures and missing measurements
  will be counted.
- The validator, evidence artifacts, and the lineage of the task set.

Avoid changing the acceptance conditions after seeing candidate results. A revised
experiment is a new version with its own results.

## Comparable runs

Prefer paired runs of the same task from equivalent clean snapshots. Randomize run
order where possible so warm caches, network conditions and quota windows do not
consistently benefit one variant. Repeat stochastic runs. When exact replay is
impossible, record the mismatch and treat the conclusion as observational.

Include unsuccessful runs. Faster abandonment is not a speed improvement. Report
task success separately from latency and cost, and compare accepted successful runs
without hiding the unsuccessful denominator. Completion requires external acceptance
evidence; an assistant's final statement is not enough.

Count total task cost, including retrospective analysis, retrieval, verification,
delegation, storage processing and human rework. Keep one-time setup and repeated
cost separate. For a reusable change, report the observed number of reuses and the
break-even assumption instead of amortizing across imagined future use.

Use explicit metric directions and units. A positive latency delta is harmful; a
positive correctness delta is beneficial. Do not average unlike units into an
unexplained score. A protected hard constraint takes precedence over an attractive
mean improvement elsewhere.

## What v0.1 can establish

The current evidence interface accepts structured comparison records, checks their
declared metrics and updates a local evidence view. This is useful bookkeeping and
deterministic acceptance logic. The supplied measurements and validator assertions
remain caller-provided evidence; the program cannot authenticate arbitrary JSON or
prove that a claimed benchmark actually ran.

The [synthetic record](../examples/evaluation-example.json) shows the implemented
format. Replace its explicit fixture identifiers with real evidence before using a
production store. Required fields include `evaluation_id`, `proposal_id`,
`change_ref`, exact `scope`, a reported verifier reference, a frozen holdout manifest,
start time, primary metric, and paired results with separate overhead measurements.

The supported primary metrics are `latency_seconds`, `tokens` and `cost`. Each pair
must supply `correctness` and `completion` as fractions from zero to one, plus all
three resource metrics and their overhead fields. An unknown resource can be `null`,
but the primary metric and its overhead must be known. The primary metric must
match the proposal's improving parameter when that parameter has a supported metric.

Support requires strictly lower total primary consumption including overhead,
candidate correctness and completion equal to one on every declared task, and no
reported regression in the protected parameter. Equality does not establish a
benefit. A protected parameter without an implemented validator, such as
`context_relevance`, leaves the proposal unsupported. The present validator is
deliberately narrower than the twenty-parameter research catalogue.

The record identifies the exact project, harness, model, environment and task family.
Known proposal context must match. Supplied holdout IDs must be disjoint from the
discovery/source IDs, and the declared freeze time must precede or equal the start.
These consistency checks cannot discover a copied task under a different ID or
verify that a holdout was actually concealed from the proposer.

The positive state is named `supported_by_reported_evidence`. It is never called
independently verified. Reimporting the same evaluation ID and content is idempotent;
reusing the ID for different content is rejected. Repeated task IDs do not increase
the distinct-task count. A regression revokes support for the same proposal, exact
scope and change revision, and a later success does not erase that regression. A
revised intervention needs a new `change_ref`.

Synthetic examples test the software path. They are not real performance findings and
must not be mixed into a production learning corpus. An accepted comparison means
that the supplied record passed its declared gates. It does not mean statistical
significance, broad generalization or independently verified causal improvement.

## Independent validation

The next evaluation layer must execute a frozen harness and retain its artifacts.
Record task identity, inputs, outputs, environment and intervention hashes, validator
version, measurements, failures and comparison results. Keep the evidence grader
separate from the implementation agent; an independently executed check is stronger
than an independent agent reading the same unsupported claims.

The proposer must not edit its own acceptance rubric, task answers, baseline outputs
or held-out test set. When feasible, blind the evaluator to treatment labels. A
separate model alone does not remove shared blind spots or data leakage.

## Development, validation and holdout

Maintain three roles for archived sessions:

1. **Discovery:** identify patterns and generate hypotheses.
2. **Validation:** choose between mechanisms and tune their scopes or thresholds.
3. **Frozen holdout:** estimate generalization after choices are fixed.

Keep sessions from the same task lineage or near-duplicate attempts in the same
partition. A random split of individual messages leaks task solutions. Record split
membership and lineage before fitting. Once a holdout result influences a design
decision, that set becomes development data; obtain a new holdout for the next claim.

The raw archive is not deleted when records change roles. Raw retention preserves
provenance; access restrictions and separate manifests protect evaluation integrity.
The v0.1 store does not yet enforce isolated holdout access.

## Evaluate the matrix itself

Compare these variants under the same task and resource policy:

| Variant | Instructions and resources |
|---|---|
| A | Baseline agent and existing tools |
| B | Baseline plus original TRIZ method |
| C | TRAZ method and evidence retrieval, without matrix suggestions |
| D | Same as C, with the experimental matrix |

The C versus D comparison measures the matrix's incremental value. A versus D alone
cannot tell whether improvements come from better instructions, evidence retrieval,
extra compute or the matrix. A budget-matched control helps isolate the effect of
extra deliberation. Count method overhead in every variant.

## Promotion and retirement policy

Retain the distribution of outcomes and applicability, not only a mean or win count.
Multiple independent tasks support a broader claim than many replays of one task.
Do not turn an arbitrary fixed success count into universal confidence. Publish sample
counts, failures, effect sizes and uncertainty for whatever estimator is actually used.

An intervention can be retained for a narrow context, kept experimental, rejected,
or retired after environmental drift. Reevaluate after significant model, tool or
project changes. Keep negative evidence. Reverting an intervention changes active
behavior; it must not erase the record that explains the reversal.
