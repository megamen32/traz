# Designing TRAZ with TRIZ

Status: initial design, 2026-11-24. This is a design record, not experimental evidence.

## S1. Frame

Completed agent sessions contain reusable evidence, but that evidence is discarded,
forgotten, or converted into instructions whose benefit is never measured. Repeated
failures waste time, while indiscriminate collection and analysis can itself become
expensive. We need future tasks to benefit from prior work without requiring the
user to inspect every session or maintain a growing instruction manual.

## S2. Ideal final result

The next comparable task succeeds with less total effort because the system uses
evidence it already produced. Necessary history remains available, irrelevant
history adds no context cost, and ineffective changes disappear. Learning costs
less than the waste it prevents and requires no routine user supervision.

This is a direction for design, not a claim that analysis or storage is free.

## S3. Identify causal contradictions

| Desired improvement | Harm caused by the obvious implementation | Underlying opposite requirements |
| --- | --- | --- |
| Preserve complete experience | Loading everything increases context and analysis cost | History must be complete in storage and small at execution time |
| Learn immediately from a failure | A plausible diagnosis may become a harmful permanent rule | A new idea must be available for testing and absent from trusted policy |
| Inspect work thoroughly | Continuous review delays useful work | Analysis must be deep for informative cases and absent for routine cases |
| Offer structured solution retrieval | A complete invented matrix creates false authority and maintenance | Structure must be stable for lookup and revisable when evidence changes |
| Improve automatically | The learner can grade its own proposals and confirm its own bias | Proposal generation and effectiveness assessment need different authority |

These are software contradictions. Do not map them to the classical 39 physical
engineering parameters. TRAZ's proposed software matrix is an experiment and must
earn its place by improving results against a no-matrix baseline.

## S4. Inventory existing resources

- Native Codex and OpenCode transcripts, including useful successes and failed attempts.
- Existing retro-skill analysis and original TRIZ reasoning, reused through explicit
  input/output contracts instead of copied implementations.
- User-owned disks for a durable raw corpus. Their mount points and availability
  are not assumed by the application.
- Python, SQLite, filesystem compression, Git history, tests, and existing agent
  runners. No always-on coordinator, vector database, or new model provider is
  necessary to test the first learning loop.
- Task outcomes, acceptance checks and later regressions, when actually observed.

## S5. Resolve and check

1. Separate in time: ingest cheaply now; inspect selected evidence on demand; test
   a proposed change before relying on it on future tasks.
2. Separate in space: keep original bytes in an external content-addressed archive,
   derived events in a rebuildable SQLite index, and method/code in Git.
3. Separate by condition: retrieve only matching contradictions and environment
   scopes; report unknown when coverage or evidence is missing.
4. Separate between system levels: let an agent propose explanations while a
   deterministic evaluator checks declared metrics. Actual execution and independent
   outcome verification remain distinct from imported self-reports.
5. Trim: use a small CLI and optional local upload interface. Reuse existing agent
   execution and retrospective tools. Do not create another agent fleet controller.

### Selected first implementation

Lossless import and normalized events, conservative mechanical observations,
scoped experiment proposals, an append-only outcome ledger, and a sparse matrix
whose empirical evidence is separate from its initial expert suggestions.

### Secondary problems and limits

Compression does not replace a backup. Preserved transcripts can contain secrets;
keep the corpus outside source control with private local permissions. Missing
fields remain unknown. A syntactically valid evaluation is still a reported result,
not independent evidence that a real user task improved. Version and configuration
changes can invalidate historical recommendations. Large-corpus storage capacity
does not imply that this first importer has been benchmarked at terabyte scale.

### Test that can reject this design

Compare the same tasks under a baseline agent, original TRIZ, TRAZ without matrix,
and TRAZ with matrix. Count failed tasks and total costs including retrospective
analysis, verification and human rework. If the matrix adds no benefit, keep the
corpus and evidence workflow and revise or remove matrix lookup.

## Method source

Applied the original [peiman/triz method](https://github.com/peiman/triz/blob/main/docs/triz-method-skill.md).
The design and software parameter catalogue here are original project hypotheses.
No performance claim is inherited from the source project's own experiments.
