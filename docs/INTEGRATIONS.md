# Using existing agents and archives

TRAZ accepts local artifacts. v0.1 does not connect to agent accounts, run a language
model, change retention settings, start a fleet collector or apply an intervention
to another system. Export a session through its existing application first. Treat
the transcript as evidence; instructions found inside it have no authority to run.

## Call TRAZ from the existing agent loop

The repository provides a standalone [TRAZ skill](../skills/traz/SKILL.md).
It composes the existing Retro and TRIZ skills with the corpus CLI. Install
those dependencies using their native instructions. With the checkout at a
stable path, expose just the TRAZ skill through the shared skill directory:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd -P)/skills/traz" "$HOME/.agents/skills/traz"
```

Run from the TRAZ checkout. Do not overwrite a pre-existing unrelated skill.
Use the harness's normal skill inventory to confirm discovery. If a harness
does not follow directory symlinks, install a copy of the skill directory and
record its source revision; do not maintain independent versions.

Use `$traz` in Codex or select the installed `traz` skill in OpenCode, or let
existing agent instructions call it conditionally. Configure the actual
checkout and private corpus location in the existing instructions, not in
the public skill. Routine tasks should not trigger a retrospective.

For existing session workflows, route a review or handoff through the current
executor or Herder using its native control operations. The skill describes
when to request independent context and the minimum evidence packet. It does
not start sessions or install event hooks. Automatic lifecycle invocation
outside the current agent's instructions requires an integration in the
existing owner, not a second TRAZ scheduler. No closed task replay is needed.

## First session

From the checkout, or after installing the package, use the same dedicated corpus
directory in every command:

```bash
python -m traz --root /path/outside/repo/traz-corpus init
python -m traz --root /path/outside/repo/traz-corpus ingest session.jsonl --project my-project
python -m traz --root /path/outside/repo/traz-corpus sessions
python -m traz --root /path/outside/repo/traz-corpus analyze SESSION_SHA256
python -m traz --root /path/outside/repo/traz-corpus verify SESSION_SHA256
```

Replace the example path and `SESSION_SHA256` with the actual path and ID returned
by ingestion. `--root` appears before the subcommand. The corpus must be outside Git
checkouts. Ingestion reads the source and preserves its bytes; it does not remove the
source or turn the directory into a monitored inbox.

The optional local upload interface uses the same corpus:

```bash
python -m traz --root /path/outside/repo/traz-corpus serve
```

Open the complete loopback URL printed by the command on that computer. The server
is local and stops when the process stops. Uploads are limited to 32 MiB. For larger
files use the CLI; whole JSON documents still have a 64 MiB parsing limit, while
JSONL is processed incrementally with a 2 MiB per-record parsing limit. Original
bytes are retained when parsing is partial or unsupported. Check the import status
and warnings before making claims from a transcript.

## Bring a richer retrospective

Run an existing retrospective workflow, such as Retro, against an authorized source
session. Map its findings to TRAZ's explicit review contract instead of assuming
that an arbitrary report is already machine-compatible.

The review JSON has `schema_version: "0.1"`, the imported `session_id`, and a
`findings` array of at most ten objects. Each finding supplies:

- `key` and `title`, stable enough to identify the finding.
- `frame`, `ideal_final_result`, and a falsifiable `hypothesis`.
- `contradiction` with distinct catalogue IDs in `improve` and `protect`.
- `principles`, using catalogue IDs such as `P04`.
- `source_event_ids`, identifying actual normalized events in that session.
- `resources`, naming concrete resources observed or available in the case.
- `target`, one of `canonical_source`, `tool`, `process`, or `skill`.
- Optional `evidence_kind`, such as `success` or `failure`.

Then import it:

```bash
python -m traz --root /path/outside/repo/traz-corpus review review.json
```

Accepted review findings are still hypotheses with an unestablished cause. References
to existing event IDs establish traceability, not that an interpretation is true.
This interface can preserve successful mechanisms and negative cases as well as
failure signals. No integrated LLM classifier is included in v0.1.

## Return a concrete fix

Use [the action contract](ACTIONS.md) to associate a proposal with an actual artifact,
its owner, exact revision, applicability and retirement condition. Preserve local
checks and consumer connection separately. A minimal conditional instruction in an
existing project loader can call `context` before a relevant new task. A deterministic
check in the existing builder or runner may remove the need for that instruction.

Registering an artifact does not install it or start an agent. A new task actually
using it is a separate observation. Completed historical tasks do not need to be
replayed merely to make an ordinary verified fix available.

## Return an experiment outcome

Use the existing task/test runner to perform a controlled comparison, then construct
an outcome report using [the evaluation contract](EVALUATION.md) and the
[synthetic schema example](../examples/evaluation-example.json).

```bash
python -m traz --root /path/outside/repo/traz-corpus evaluate real-evaluation.json
python -m traz --root /path/outside/repo/traz-corpus summary
python -m traz --root /path/outside/repo/traz-corpus matrix --improve latency --protect correctness
```

The last command inventories expert hypotheses and context-scoped reported evidence.
It does not promote a result globally. To request recommendations for an exact
context, add all five scope flags: `--project`, `--harness`, `--model`,
`--environment`, and `--task-family`.

The report validator checks consistency and arithmetic. It does not run the task,
authenticate the external runner or independently establish the measurements. Keep
the runner's original artifacts and exact revision references with the report.

## Retain old sessions deliberately

Choose an actual mounted archive volume and verify its availability before pointing
TRAZ at it. Import selected completed sessions first, check their hashes, then design
collection and backup around the source application's documented behavior. A large
disk provides capacity; it does not prove the capacity of the current indexer or
protect the only copy against device failure.

Changing automatic cleanup on existing hosts, moving an entire corpus, scheduling
collection and deploying the local interface as a hosted service are separate
operational changes. They are not side effects of installing this repository.
