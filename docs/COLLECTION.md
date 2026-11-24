# Connecting native session files

TRAZ can remember explicit local transcript paths and collect their current stable
snapshots on demand. Connection configuration, raw snapshots and collection history
stay in the private corpus outside Git. A connection is not a background watcher.

## Connect and collect

Make a private copy of [the example manifest](../examples/sources-example.json).
Replace the placeholder paths with exact absolute paths on the machine running
TRAZ, assign a stable source ID and the correct project, then run:

    python -m traz --root /path/to/private-corpus connect /path/to/private-sources.json
    python -m traz --root /path/to/private-corpus collect
    python -m traz --root /path/to/private-corpus sources

The connect command saves the manifest. The collect command copies, archives,
indexes and analyzes the listed files. Repeat collect to resume from the saved
connections. Use collect --no-analyze when only archive and index work is wanted.
No collection frequency or scheduled task is created.

Source fields:

| Field | Meaning |
| --- | --- |
| id | Stable connection ID, unique within the manifest |
| name | Optional display name |
| path | Exact absolute local file path, never a URL or a command |
| format | Existing importer format; defaults to auto |
| project | Evidence scope; defaults to default |
| session_id | Optional explicit native session identity when the transcript lacks it |

Paths are literal. The collector does not expand globs, enumerate directories,
search computers, fetch remote URLs, or execute commands. A remote transcript must
already be accessible as an authorized local file or be collected on its owner host.
Do not commit a manifest containing private paths into the public repository.

## What counts as a stable snapshot

The collector opens only a regular file and records device, inode, size,
nanosecond modification time and change time. It copies exactly the initially
observed size into a private staging file using bounded chunks. It then compares
the open file's metadata and the current path's metadata with the original
observation.

If the file grew, shrank or was replaced during the copy, that temporary copy is
discarded. One retry is allowed. If both attempts observe change, the source is
reported as deferred; no new archive or completed snapshot is claimed. Other
explicit sources still run. This check does not lock the native writer and does
not prove that an agent session has finished.

Once a stable copy is available, its content hash identifies an immutable archive.
The connected source advances to that snapshot only after successful archival.
A duplicate snapshot must also pass archive integrity verification before reuse.
Source files are never deleted, moved, truncated or rewritten by collection.

## Identity and resuming

The same bytes have one snapshot ID. Different snapshots of the same native
session retain the same logical_session_id. Existing analyzer proposal IDs use
that logical identity, so appending another copy of the same failure does not
create a new independent case. If a format has no native session identity, supply
session_id explicitly when that relationship is known; the collector does not
invent it from similar text.

An unchanged snapshot reuses its stored analysis for the same analyzer version.
A new analyzer version can analyze it again without changing the original bytes.
An analysis failure does not roll back successful archival. The error is retained,
and the next collection can retry analysis.

A later missing source retains its connection, previous archive and last successful
snapshot reference. Omitting a source from a replacement manifest marks it as no
longer configured; it does not remove its connection history or data.
Changing a parser hint does not silently overwrite an existing snapshot's parsing
or its evidence. Reindexing is a separate operation.

## Coverage is explicit

Every requested source has a result: archived, unchanged, deferred or failed.
Each archived result also reports parser status, warnings and analysis status.

- archive_complete: all requested stable byte snapshots were archived or verified.
- parse_complete: archive coverage is complete and no parser reported a partial
  or unparsed transcript.
- analysis_complete: requested analysis ran or reused a cache with complete parse
  coverage. It is null when analysis was not requested.
- complete: the requested operation has no unresolved source, parse or analysis
  failure.

Complete coverage means the operation covered its input. It does not establish
correct task completion, a causal diagnosis or the effectiveness of a proposed fix.
Supported-format metadata may be intentionally omitted from behavioral events
while remaining intact in the raw archive.

## Storage and performance

The saved manifest is sources.json in the private corpus with mode 0600.
SQLite retains source bindings, last snapshot and analysis references, and a
per-run manifest and coverage report. Back up this database along with raw objects,
their provenance manifests and the connection configuration.

Copying uses 1 MiB chunks and does not load a complete source into RAM. Capturing a
new source temporarily requires space for an uncompressed snapshot in addition to
the resulting archive. Whole-document JSON parsing and downstream analysis have
their own limits; collection does not remove them. A large raw archive is not proof
that every record was indexed or that multi-terabyte processing has been tested.

## Python interface

    from traz.collect import collect, connections, load_manifest, save_manifest
    from traz.storage import Store

    with Store("/path/to/private-corpus") as store:
        save_manifest(store, manifest)
        report = collect(store, load_manifest(store), analyze_sessions=True)
        retained_connections = connections(store)

The collect function also persists the supplied validated manifest itself. It
returns a bounded summary with source IDs, snapshot IDs, coverage and errors.
Original transcript content is not copied into the collection report.
