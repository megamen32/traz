# Provenance and research status

TRAZ is an independently authored prototype for resolving agent-work problems and
recording intervention evidence. Its method and seed catalogue are proposals. No
claim of general learning effectiveness is established by the initial commit.

## Primary references

### peiman/triz

- [Repository](https://github.com/peiman/triz)
- [Method](https://github.com/peiman/triz/blob/main/docs/triz-method-skill.md)
- [Reported blind experiment](https://github.com/peiman/triz/blob/main/docs/triz-skill-blind-test.md)

The software route supplies the methodological starting point: state an ideal
result, identify the causal conflict, inventory resources, and try separation or
removal of unnecessary functions. The upstream method explicitly avoids applying
its classical engineering matrix to software.

TRAZ investigates a different, provisional software vocabulary and sparse retrieval
table. This is an experimental departure. Any results reported by the upstream
author belong to that project's tested setup; they are not independent validation
of TRAZ or a forecast of its effect size.

### netresearch/retro-skill

- [Repository and current description](https://github.com/netresearch/retro-skill)
- [Learning contract](https://github.com/netresearch/retro-skill/blob/main/skills/retro/references/learning-contract.md)

Retro is relevant as an existing retrospective workflow and potential adapter. Its
documented separation of observation, intervention and outcome informs the boundary
between evidence collection and claims of improvement. TRAZ does not reimplement or
claim all of Retro's detectors, destinations or integrations.

These references were inspected while creating the prototype on 2026-11-24. Remote
default branches can change; pin exact revisions when implementing an adapter or
reproducing a comparison. The initial repository does not vendor upstream prose,
code, experiment data or private transcripts.

## Seed-data provenance

`traz/data/parameters.json` is a provisional measurement vocabulary. Several
dimensions overlap, and some require a task-specific rubric. They are not assumed
to be independent, universally desirable to maximize, or sufficient to describe all
agent tasks.

`traz/data/principles.json` contains twelve software-oriented mechanisms proposed
for this project. Connections to TRIZ are conceptual, not claims that the new names
are a canonical replacement for classical principles.

`traz/data/matrix.json` is a sparse collection of expert hypotheses. Every initial
cell has unknown confidence and an empty empirical evidence list. A cell's existence
must never be displayed as a measured success rate. Missing cells are intentionally
unfilled.

## Evidence and publication

Examples and test fixtures are synthetic unless explicitly labeled otherwise. A
synthetic experiment can demonstrate how the parser or acceptance logic behaves;
it cannot establish real-world benefit.

Future empirical claims should identify the tested revision, task provenance,
environment, comparison, cost accounting, uncertainty and known counterexamples.
Private raw sessions remain outside this repository. Publishing a derived case
requires an explicit check of its intended audience and the rights to its content.

There is no claim that TRAZ is the first work on software TRIZ, agent retrospective
analysis, evaluation-driven optimization or continual learning. Its useful
contribution must be established through the implementation and experiments.
