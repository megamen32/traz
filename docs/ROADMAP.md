# Roadmap and acceptance

The initial deliverable is an inspectable local prototype. Each extension should
remove a demonstrated bottleneck, improve a measured result or reduce unnecessary
work. An unused component is a candidate for removal.

The archive, accounting, action registry and scoped-context CLI below are
implemented. Conditional caller instructions can request that context, but do not
establish automatic event handling or observed use. Automatic lifecycle calls and
handoffs of active sessions are still integration work. The target
is one existing control loop, owned by Herder or the current executor, with TRAZ
as a callable workflow or skill and evidence store. TRAZ adds no scheduler, queue
or independent agent retry loop.

## v0.1: preserve and inspect

Provide the method, provisional parameter catalogue, sparse hypothesis matrix,
transcript import, deterministic observations, and structured comparison records.
Use synthetic fixtures to verify behavior and a local interface for convenient
uploads. Keep the archive out of Git. Show unknowns and unsupported formats honestly.

**Acceptance:** a user can import a supported transcript, retrieve its preserved
content, inspect traceable signals, and record an experiment whose outcome affects
the local evidence view. A repeated import does not count as new experimental
support. Repository tests prove software behavior, not learning effectiveness.

## v0.2: connect and account

Explicit local source manifests now connect existing session files. Collection
captures stable bytes, keeps immutable snapshots and logical lineage, reuses
cached analysis and records missing, changing or partially parsed sources.
Codex accounting cross-checks final counters against unique response records.
Observed time, recorded turn duration, active work and billed cost stay distinct.

**Acceptance:** repeated collection creates no duplicate snapshot for identical
bytes, changing files are retried within a fixed bound, old archives survive source
disappearance, and a parser metadata refresh cannot alter cited events. These
checks establish software behavior, not the causal effectiveness of a lesson.

## v0.3: retain concrete interventions

Immutable action revisions connect a source-cited proposal to an actual artifact
and owner. Implementation, local checks, consumer connection and use have separate
reported receipts. Explicit local hash observations verify artifact bytes only.
Bounded context selects applicable active revisions and excludes drift, retirement
and scoped regressions without starting or replaying an agent session.

**Acceptance:** a verified artifact can be retrieved for an appropriate new task
while its causal efficacy remains unknown. A foreign project, missing constraint,
changed file or retired revision cannot silently receive the advice. Imported
receipts cannot promote themselves to observed verification.

## Next: connect interventions to real consumers

Have the existing owner invoke retrospective analysis through a narrow evidence
contract. Start with operator-selected cases and bounded review budgets. Review
hypotheses for causal plausibility and owner of the proposed change. Do not create
a new universal rule from every warning.

Connect scoped context to the actual consumer before an applicable new task. For
an unfinished task, a fresh reviewer or executor requires an observed reason such
as a consequential contradiction or repeated failure without new evidence, not a
long history. Transfer verified artifacts, source-backed facts and remaining work;
keep hypotheses explicit, one writer active, and stops and budgets intact. Account
switching, model switching and clearing context are separate operations, as defined
in [TRIZ_DESIGN.md](TRIZ_DESIGN.md).

**Acceptance:** a concrete intervention has a real source trace, a reproducible
change, local acceptance evidence and a verified consumer path. Preserve the first
use and any failure on a new natural task. Comparative efficacy and measured savings
are separate claims; they are not a prerequisite for using a routine verified fix.
An ordinary correction uses existing receipts or focused checks without replaying
the completed assignment. Fresh context or another model is not evidence of a
better outcome by itself.

## Then: automate experiments and scoped retrieval

Integrate the existing test or agent runner. Freeze development and holdout task
manifests. Capture environment and intervention versions. Import independent
validator outputs, retain negative outcomes, and evaluate candidate recommendations
in their actual task/model context.

Retrieve a small relevant set before a new task. Measure whether retrieval saves
more time and cost than it adds. Expire or revise applicability when context drifts.

**Acceptance:** controlled comparisons show a useful effect on new task lineages,
with no material protected-metric regression. The effect includes learning overhead.

## Only with evidence: integrate existing supervision

Use the existing supervisor's lifecycle events to invoke bounded, incremental
collection and selected analysis. Keep scheduling, queues, retries, continuations,
resource budgets and stop enforcement in that owner. Add no TRAZ-owned scheduler,
queue or orchestration loop. Resume interrupted invocations through the owner's
existing mechanisms and deduplicate their effects using task and checkpoint
identifiers. Measure corpus-scale storage behavior before expanding collection.

Introduce automatic deployment of scoped interventions only after the acceptance
and rollback path works reliably for that intervention class. A fresh reviewer is
read-only; transferring execution preserves one writer and the remaining task.
Neither operation automatically starts another review or repeats completed work.

**Acceptance:** unattended collection survives interruption without source deletion
or evidence duplication; repeated events create no duplicate executor; user stops
and budgets survive handoffs; failed experiments do not promote changes; rollback
is observed to work. Measure the full supervision cost before claiming that this
integration saves effort. These are acceptance targets, not established results.

## Research milestones

1. Refine the parameter vocabulary using actual ambiguous classifications.
2. Measure inter-reviewer agreement and record disagreements.
3. Test TRAZ with and without the matrix under matched budgets.
4. Compare learned suggestions with original TRIZ and ordinary engineering fixes.
5. Publish only consented or synthetic cases, with provenance and failed outcomes.

The matrix may remain sparse, become context-indexed, or be removed if it adds no
measurable value. Its existence is not the success criterion of the project.
