# Native session accounting

The metrics command reads accounting records from an archived native Codex
transcript. It is independent of behavioral observations, proposals and acceptance
evaluations. A high token count does not by itself establish waste, task quality,
provider billing or a need for a new rule.

    python -m traz --root /path/to/private-corpus metrics SNAPSHOT_ID

The Python interface is read-only:

    from traz.metrics import metrics
    result = metrics(store, snapshot_id)

The reader verifies the archived source hash and streams raw records through the
parser's public records view. It does not replace events, renumber event IDs or
change existing evidence. It preserves the input's JSON or JSONL framing.
Other transcript formats return unknown with an explicit unsupported-format reason.

## Tokens

Two Codex accounting channels are supported:

1. The cumulative total_token_usage inside event_msg token_count records.
2. Per-response usage and cumulative thread_token_usage inside token_usage_record
   records. Optional turn_token_usage is checked for within-turn counter decreases.

Every observed counter set must supply five nonnegative integer values:

| Counter | Meaning used by this reader |
| --- | --- |
| input_tokens | Reported input, including cached input |
| cached_input_tokens | Subset of input_tokens served from cache |
| output_tokens | Reported output, including reasoning output |
| reasoning_output_tokens | Subset of output_tokens attributed to reasoning |
| total_tokens | input_tokens plus output_tokens |

Cached input must not exceed input, and reasoning output must not exceed output.
Boolean values, negative values, missing fields, floats and inconsistent totals
are rejected as accounting evidence.

Derived fields are:

- uncached_input_tokens = input_tokens minus cached_input_tokens.
- non_reasoning_output_tokens = output_tokens minus reasoning_output_tokens.
- cache_share_of_input = cached_input_tokens divided by input_tokens; null when
  reported input is zero.

Neither cache nor reasoning is added to total_tokens again. A cache share is a
share of reported input tokens; it is not a percentage discount or money saved.
Monetary cost stays null because this transcript does not establish actual
provider prices, account contracts or invoices.

### Cumulative values are never summed

Repeated cumulative records describe the same running total. The reader takes the
last counter set from each independently monotonic cumulative channel. If both
channels are present, their final values must agree.

Where per-response usage exists, the reader independently sums each response_id
once and compares all five resulting counters against the final cumulative values.
An exact replay of a known response's accounting does not add usage or create a
false reset. A conflicting duplicate response, a decreasing cumulative counter,
disagreement between cumulative endpoints, or a mismatch with the per-response sum
invalidates aggregates.

The last_token_usage field is deliberately not accumulated. Explicit token_count
updates with info=null provide no usage measurement, such as a rate-limit-only
update. They are neither an error nor evidence of zero usage.

## Scope

The reader tracks native session_meta IDs and token_usage_record thread IDs.
More than one native thread, conflicting native/thread identity or an unidentifiable
scope prevents an aggregate. A token_usage_record session_id is recorded as a
separate exporter/provider namespace. Variation in that field alone is not treated
as proof of multiple native threads.

Counts describe the observed native thread snapshot. They do not include child
threads, other agents or external services merely because those systems helped
with the task. Native counters can include a prior cumulative history already
reported by the exporter; without per-response agreement this remains explicitly
unverified by the second accounting channel.

## Incomplete and conflicting evidence

The result separates a supported total from qualified observations:

| Field or status | Interpretation |
| --- | --- |
| tokens.status = reported_consistent | Complete raw parse, one scope, internally valid cumulative counts and matching independent per-response sum |
| tokens.status = reported_cumulative | Complete raw parse and valid cumulative counts, with no per-response cross-check available |
| tokens.status = unknown | Insufficient coverage, scope or accounting |
| tokens.status = conflicting | At least one contradictory accounting observation |
| tokens.totals | Aggregate available only when the required checks above pass |
| tokens.observed_reported_totals | Internally consistent observed counters; on partial raw input these require the per-response check to match |
| coverage.raw_complete | Raw records were read without malformed, oversized, unreadable or invalid required record shapes |
| coverage.token_measurements_complete | Complete raw coverage and all required accounting checks pass |

An oversized or malformed line is still preserved in the source archive. It makes
raw coverage incomplete. In that case tokens.totals remains null, even when the
successfully parsed counters agree. Observed_reported_totals may retain those
matching observations, with a scope explanation, so a report can describe what
was registered without claiming full session or system consumption.

Resets, conflicting duplicates, inconsistent counters and mixed native scopes do
not expose either form of aggregate. A matched arithmetic cross-check by itself
does not override the other failed conditions. Reasons retain source line
references when available.

The reader reports valid raw record count, malformed record count and parser
warnings separately. Valid record count excludes lines the parser could not read.
Warnings and reason lists are bounded; their full counts are reported.

## Time

The observed span is the difference between the minimum and maximum timezone-aware
raw record timestamps. Timestamps are normalized to UTC for comparison. Missing
and invalid timestamps are counted, and incomplete raw coverage is marked.
This is an observed transcript span, not a measurement of active work.

The reader also sums native task_complete duration_ms once per turn_id. Identical
completion observations are deduplicated. Conflicting duration or timing markers
for the same turn prevent a trusted duration sum. Failed turns remain included
when their durations were recorded.

Recorded durations can include tool execution, waits and overlapping turns. They
must not be added to the observed span, interpreted as model thinking time or
subtracted from the span to infer human waiting. Both active_seconds and
human_wait_seconds remain null.

On incomplete raw coverage, recorded_turn_duration_ms remains null. The separate
observed_recorded_turn_duration_ms can retain the sum of valid observed turn
durations when there are no timing contradictions or scope ambiguity. This is a
partial observation, not an estimate for the missing records.

## Processing limits

JSONL processing holds one bounded raw record plus identifiers and small counter
sets for unique responses and turns. Memory grows with the number of unique
response and turn IDs, not with all transcript text. Whole-document JSON retains
the parser's existing size limit.

Hash verification adds a streaming archive read before accounting. No network
requests, provider pricing lookups, transcript commands or agent executions occur.
These accounting checks validate internal consistency of reported records; they
do not independently prove that a provider performed or billed the reported work.
