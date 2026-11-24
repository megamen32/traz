# TRAZ

**Theory of Resolving Agentic Contradictions**

[Русский](README.ru.md) · [Method](docs/METHOD.md) · [Design with TRIZ](docs/TRIZ_DESIGN.md) · [Evaluation](docs/EVALUATION.md)

Preserve agent sessions. Find reusable evidence. Test changes. Let outcomes improve
future recommendations.

TRAZ is an experimental, local tool and method for improving software and agent
workflows. Its unit of learning is a scoped, testable intervention with source
evidence, rather than an ever-growing list of instructions. A useful intervention
can change a tool, code, workflow, check, or skill.

## What works today

- Lossless transcript import with content-addressed gzip archives, SHA-256 integrity
  checks, an SQLite event index and recovery manifests.
- Codex rollout JSONL, OpenCode JSON exports, normalized JSON/JSONL and plain text.
  Unsupported and malformed records remain in the original archive and are reported.
- A local upload interface, or a CLI that can be used by an existing agent runner.
- Connected, explicit local transcript sources: stable snapshot capture, collection
  receipts, deduplication and bounded retry when a source changes during copying.
- Codex usage accounting that cross-checks final cumulative counters against unique
  response records, separates cached input, and leaves billed money unknown.
- Conservative observations of repeated calls, repeated reads and explicit linked
  tool failures. These are investigation signals, not automatic causal diagnoses.
- Structured retrospective import with source-event citations, an ideal final
  result, a contradiction, resources and a proposed intervention. This is the
  integration boundary for existing retrospective agents and tools.
- A provisional catalogue of 20 software/agent parameters and 12 mechanisms, with
  a sparse directed matrix. Empty cells mean unknown; initial cells are hypotheses.
- An append-only experiment ledger. Paired reported results include analysis and
  verification overhead. Supported results influence recommendations only in their
  exact tested scope; a regression revokes support for that change and scope.

**v0.2 validates reported evidence.** It does not run an independent benchmark,
call an LLM, deploy fixes, alter installed skills, or prove that real tasks improved.
The code is ready for those integrations without pretending they already exist.

## Quick start

Requires Python 3.11 or later. There are no third-party runtime dependencies.

```bash
git clone https://github.com/megamen32/traz.git
cd traz
python3 -m traz --root /path/to/private/traz-corpus init
python3 -m traz --root /path/to/private/traz-corpus serve
```

Open the complete loopback URL printed by `serve`, including its token fragment.
Select one or more transcript files and their project scope. The interface archives
and analyzes each upload. It is a local development interface, not a public service.

The corpus path must be outside every Git checkout. Choose an actual mounted disk
path for long-term storage. TRAZ does not assume a disk exists, format disks, change
retention on agent hosts, or delete original sessions. By default it uses
`$XDG_DATA_HOME/traz`, falling back to `~/.local/share/traz`; `TRAZ_HOME` overrides it.

Optional installation in an existing virtual environment:

```bash
python3 -m pip install .
traz --help
```

### CLI workflow

```bash
python3 -m traz --root /path/to/private/traz-corpus ingest /path/to/session.jsonl --project my-project
python3 -m traz --root /path/to/private/traz-corpus sessions
python3 -m traz --root /path/to/private/traz-corpus analyze SESSION_SHA256
python3 -m traz --root /path/to/private/traz-corpus metrics SESSION_SHA256
python3 -m traz --root /path/to/private/traz-corpus proposals
python3 -m traz --root /path/to/private/traz-corpus evaluation-template PROPOSAL_ID > /path/to/experiment.json
```

The generated template is deliberately not evidence: metrics are empty and
`_template: true` prevents accidental acceptance. Define the holdout and acceptance
criteria, run the comparison, record actual measurements and artifact references,
then remove the template marker and import the completed report.

```bash
python3 -m traz --root /path/to/private/traz-corpus evaluate /path/to/experiment.json
python3 -m traz --root /path/to/private/traz-corpus evaluations
python3 -m traz --root /path/to/private/traz-corpus matrix --improve latency --protect correctness
python3 -m traz --root /path/to/private/traz-corpus verify
python3 -m traz --root /path/to/private/traz-corpus export SESSION_SHA256 /path/to/restored-session.jsonl
```

Matrix output without scope is an inventory. To retrieve a scoped recommendation,
provide **all five** flags: `--project`, `--harness`, `--model`, `--environment`,
`--task-family`. Model, harness and environment values should identify their tested
versions. A different configuration is a different claim.

For structured retrospective findings use `review /path/to/review.json`.
See [the retrospective input contract](docs/INTEGRATIONS.md).

### Connect existing session files

Copy [the example source manifest](examples/sources-example.json), choose explicit
local paths and project scopes, and run:

```bash
python3 -m traz --root /path/to/private/traz-corpus connect /path/to/sources.json
python3 -m traz --root /path/to/private/traz-corpus collect
python3 -m traz --root /path/to/private/traz-corpus sources
```

`collect` can be invoked again by an existing runner. It archives new stable bytes,
reuses unchanged snapshots and keeps the native session lineage. It does not create
a watcher or schedule. Exit status 1 means incomplete collection, parsing or
analysis; inspect `coverage.archive_complete` separately from analysis coverage.
Missing sources retain their previous archives and collection receipts.

[Collection](docs/COLLECTION.md) and [metrics](docs/METRICS.md) describe the limits.
After a parser upgrade, `refresh-metadata SESSION_SHA256` refreshes coverage only
if **every indexed event is identical**. A change that would repoint a review's
evidence is refused. Raw originals and authored reviews remain unchanged.

### Run the complete synthetic demonstration

```bash
python3 examples/demo.py
python3 -m unittest discover -s tests -v
```

The demo imports a synthetic retry transcript, records a positive reported
comparison, records a regression and verifies that the earlier support is revoked.
It uses a disposable corpus. The numbers are fixtures and establish no real-world
performance claim.

## TRAZ designed with TRIZ

The [design record](docs/TRIZ_DESIGN.md) follows the original method's sequence:
frame the deficiency, write the ideal final result, expose causal contradictions,
inventory existing resources, then solve and check.

The main contradiction is that history must be complete for learning and small
for execution. We separate original storage from retrieved working context. New
ideas remain available for experiments while trusted behavior stays separate.
Existing transcripts, retro-skill, agent runners, Git and tests supply the resources.

The classical engineering matrix is not forced onto software. TRAZ's software
matrix is a new hypothesis. The evaluation plan compares the method both with and
without that matrix. If lookup adds no value, the archive and evidence workflow
remain useful and the matrix can be revised or removed.

## Architecture and boundaries

The first version uses Python, the filesystem and SQLite. It needs no coordinator
daemon, external database or model subscription. The optional HTTP server binds to
`127.0.0.1`, protects API access with a per-run token and never executes transcript
contents. Do not expose it through a public reverse proxy.

Original transcripts may contain credentials or private information. The application
keeps local corpus permissions private and refuses corpus directories inside Git
checkouts. It does not claim automatic redaction. Review and sanitize any derived
material before deliberately sharing it elsewhere.

The upload interface accepts files up to 32 MiB. JSONL import streams records with
a 2 MiB per-record parsing limit; complete JSON parsing is limited to 64 MiB.
Larger records remain archived with explicit warnings. Analysis currently loads one
session's derived events in memory. This is not a terabyte-scale performance claim.

Back up the **entire corpus**, including SQLite and manifests. Original bytes can
rebuild derived transcript events, but authored reviews and experiment outcomes
need their own preserved records. Compression is not a backup.

## Development priorities

1. Add independently executed, versioned paired experiments and frozen task sets.
2. Add an existing runner's session-complete trigger for the connected local sources.
3. Expand scoped retrospective reviews while retaining counterevidence and source links.
4. Measure retrieval and matrix value against budget-matched baselines.
5. Only then add scoped automatic application and rollback of proven interventions.

See [architecture](docs/ARCHITECTURE.md), [roadmap](docs/ROADMAP.md) and
[provenance](docs/PROVENANCE.md). TRAZ uses original project code under the
[MIT license](LICENSE); upstream sources are referenced rather than vendored.
