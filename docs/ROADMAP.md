# Roadmap and acceptance

The initial deliverable is an inspectable local prototype. Each extension should
remove a demonstrated bottleneck, improve a measured result or reduce unnecessary
work. An unused component is a candidate for removal.

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

## Next: validate interventions from real sessions

Connect retrospective analysis through a narrow evidence contract. Start with
operator-selected cases and bounded review budgets. Review hypotheses for causal
plausibility and owner of the proposed change. Do not create a new universal rule
from every warning.

**Acceptance:** a first useful intervention has a real source trace, a reproducible
change, a relevant baseline, measured total cost, acceptance evidence and an honest
statement of remaining uncertainty.

## Then: automate experiments and scoped retrieval

Integrate the existing test or agent runner. Freeze development and holdout task
manifests. Capture environment and intervention versions. Import independent
validator outputs, retain negative outcomes, and evaluate candidate recommendations
in their actual task/model context.

Retrieve a small relevant set before a new task. Measure whether retrieval saves
more time and cost than it adds. Expire or revise applicability when context drifts.

**Acceptance:** controlled comparisons show a useful effect on new task lineages,
with no material protected-metric regression. The effect includes learning overhead.

## Only with evidence: continuous operation

Reuse existing session-complete signals and the supervisor's event system. Add
incremental collection, resumable jobs, resource budgets and measured corpus-scale
storage behavior. Introduce automatic deployment of scoped interventions only after
the experiment and rollback path works reliably for that intervention class.

**Acceptance:** unattended collection survives interruption without source deletion
or evidence duplication; failed experiments do not promote changes; rollback is
observed to work; supervision consumes less effort than it saves.

## Research milestones

1. Refine the parameter vocabulary using actual ambiguous classifications.
2. Measure inter-reviewer agreement and record disagreements.
3. Test TRAZ with and without the matrix under matched budgets.
4. Compare learned suggestions with original TRIZ and ordinary engineering fixes.
5. Publish only consented or synthetic cases, with provenance and failed outcomes.

The matrix may remain sparse, become context-indexed, or be removed if it adds no
measurable value. Its existence is not the success criterion of the project.
