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

### Orchestration decision: reuse one control loop

**Frame:** an unfinished task can carry a mistaken interpretation forward along
with useful history. Session length alone does not establish this failure.

**Ideal final result:** work resumes from verified state without inheriting an
unsupported belief, another coordinator, or replay of a completed assignment.

**Conflict and resources:** continuity needs retained evidence, while reconsidering
a false premise needs distance from the previous reasoning. Existing artifacts,
checks, transcript references, Retro, original TRIZ and the current session owner
provide the resources. Herder, when present, or the current executor already owns
task admission, continuation, budgets and stop decisions.

**Resolution:** separate persistent evidence from working context and trim the
second controller. Expose TRAZ as a callable workflow or thin skill backed by the
archive and CLI. It owns no scheduler, queue or agent retry loop. The current owner
may request:

- A fresh, read-only reviewer for one consequential unresolved contradiction.
- A fresh executor when an open task keeps relying on a refuted premise, repeats
  equivalent failed attempts without new evidence, or cannot reconcile its state.

A routine fix stays with the current executor. A fresh session is conditional on
an observed reason, not history length. The owner bounds review and transfer work,
keeps one writer, and preserves user stops, permissions and remaining budgets.
Neither reviewer nor executor starts a recursive review loop.

| Operation | What changes | What it does not establish |
| --- | --- | --- |
| Account switch | Authorized execution identity or available allowance | Fresh context or corrected reasoning |
| Model switch | The model used for subsequent work | Removal of inherited context or an independent verdict |
| Fresh context | The working history supplied to a new session | Better results or freedom from model-level errors |

The same model can receive fresh context; a different model is not a prerequisite.
No effectiveness claim for either choice has been established here.

Transfer the original goal and constraints, task/checkpoint identifiers, artifact
versions, facts with evidence references, observed attempt results, explicitly
unverified hypotheses, the remaining question or next action, acceptance criteria,
owner and control limits. Do not fork the full history as trusted beliefs. A
reviewer must inspect relevant primary evidence rather than only its predecessor's
summary. A fresh executor continues only unfinished work.

**Check:** repeated events must not duplicate execution; a transfer must retain one
writer, stops and budgets; hypotheses must remain distinguishable from facts.
Use existing receipts or focused mechanism checks, then observe the next natural
task. Do not replay a completed production task to validate an ordinary correction.
Count review and transfer costs before claiming improvement.

**Implementation boundary:** archive, accounting, action records and scoped context
are implemented CLI capabilities. Conditional caller instructions can request scoped
context, but do not prove actual use. Automatic event-driven invocation, review
selection and session transfer through the existing owner remain integration work.
Installing a skill or querying context does not create that integration.

### Secondary problems and limits

Compression does not replace a backup. Preserved transcripts can contain secrets;
keep the corpus outside source control with private local permissions. Missing
fields remain unknown. A syntactically valid evaluation is still a reported result,
not independent evidence that a real user task improved. Version and configuration
changes can invalidate historical recommendations. Large-corpus storage capacity
does not imply that this first importer has been benchmarked at terabyte scale.

### Test that can reject this design

For a separate prospective evaluation, compare a baseline agent, original TRIZ,
TRAZ without matrix and TRAZ with matrix under frozen task manifests and matched
budgets. Use new task lineages rather than replaying completed production work as
a prerequisite for an ordinary fix. Count failed tasks and total costs including
retrospective analysis, verification and human rework. If the matrix adds no
benefit, keep the corpus and evidence workflow and revise or remove matrix lookup.

## Method source

Applied the original [peiman/triz method](https://github.com/peiman/triz/blob/main/docs/triz-method-skill.md).
The design and software parameter catalogue here are original project hypotheses.
No performance claim is inherited from the source project's own experiments.
