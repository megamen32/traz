# Turn a retrospective into a usable change

A TRAZ output is a scoped intervention at the owner of the problem. It may be a
code change, executable check, tool contract, step in an existing process, or a
short skill. If an existing fix already covers the cause and is connected to its
consumer, record that fix instead of creating duplicate work.

## Design with TRIZ

**Frame:** preserving a diagnosis does not make its remedy available to the next
task. Requiring a comparative experiment before recording a normal verified bug
fix also creates avoidable work.

**Ideal final result:** the existing tool or process prevents the known failure
under the relevant conditions. The next agent needs neither the full historical
transcript nor a repeated assignment from the user. Obsolete safeguards can be
retired while retaining their evidence.

**Contradictions and separation:**

| Conflict | Mechanism |
|---|---|
| Use a concrete fix now while its future savings are unknown | Separate artifact integrity, local checks, connection, actual use and causal efficacy |
| Keep the lesson permanently while keeping working context small | Store full evidence; retrieve bounded advice only for an applicable task |
| Verify protection without repeating completed work | Check the mechanism using existing receipts or a focused regression; observe later natural tasks |
| More instructions can prevent mistakes but also burden the agent | Put deterministic invariants in existing code and gates; use advice for decisions that remain |

**Resources:** source-cited proposals, Git, existing tests and runners, the existing
instruction loader, and the local SQLite corpus. No additional scheduler is needed.

**Check the solution:** unrelated projects receive no cards; missing constrained
context does not match; artifact drift and retirement exclude a revision; imported
claims never become observed tests; retrieval never resumes a historical session.

## Record the concrete artifact

`action FILE` imports this versioned record. Replace the illustrative values with
an existing proposal and the exact bytes and owner of the actual artifact:

```json
{
  "schema_version": "0.1",
  "proposal_id": "p_existing_proposal",
  "change_ref": "git:actual-commit",
  "owner": "existing-package-builder",
  "artifact": {
    "kind": "check",
    "locator": "/actual/path/to/package-check.py",
    "sha256": "actual-64-character-sha256"
  },
  "applicability": {
    "project": "my-project",
    "task_family": "package-release"
  },
  "instruction": "Run the existing package gate before promoting a release.",
  "trigger": "Preparing a package for promotion.",
  "retirement": "Review when the package layout or release gate changes."
}
```

Artifact kinds are `code`, `check`, `process`, `skill`, and `guidance`. Registering
one never installs a skill, modifies its owner, executes its contents or applies a
patch. The artifact hash and the canonical record define the immutable revision.
The proposal supplies source-session and event provenance.

`project` and `task_family` are required exact applicability fields. Optional
`harness`, `model` and `environment` constrain matching when present. A missing
required or declared value is not a wildcard. A deterministic package check need
not invent a model restriction, but empirical claims still require the experiment
ledger's exact five-field scope. Applicability is a declared engineering boundary,
not evidence that an effect transfers across models.

```bash
python -m traz --root /path/to/private/corpus action /path/to/action.json
python -m traz --root /path/to/private/corpus action-verify ACTION_ID /actual/path/to/package-check.py
python -m traz --root /path/to/private/corpus actions
```

`action-verify` hashes only the explicit local path supplied by the current caller.
It never follows an imported locator as an instruction to execute or access it.
This observes **artifact integrity only**, not correctness, test execution,
deployment or future use. A failed hash observation does not rewrite the artifact.

## Preserve checks and delivery receipts

An imported receipt is a claim with a reference to its underlying evidence:

```json
{
  "schema_version": "0.1",
  "receipt_id": "unique-receipt-for-this-observation",
  "action_id": "a_returned_by_action",
  "kind": "local_check",
  "reference": "/actual/path/to/test-receipt.json",
  "details": "The missing-file fixture was rejected. No full release was rebuilt."
}
```

```bash
python -m traz --root /path/to/private/corpus action-receipt /path/to/receipt.json
```

Supported receipt kinds are `materialized`, `local_check`, `connected`, `used` and
`retired`. They are append-only and imported as **reported**, regardless of what the
document asserts. Reusing an ID with different contents is rejected. Retiring a
revision preserves its history and removes it from future context.

These facts are independent:

| Fact | Required evidence | Insufficient evidence |
|---|---|---|
| Artifact present | Exact bytes at the checked path | A proposal describing a file |
| Local mechanism checked | Actual test receipt with its scope and result | Artifact hash alone |
| Connected | Identified consumer invokes this revision in the relevant path | File exists in Git or SQLite |
| Used | A new task's receipt identifies the revision it used | Context was merely retrieved |
| Efficacy supported | Comparable outcomes meeting the existing evaluation contract | One successful run or a local test |

The action registry does not change the meaning of `evaluate`, remove holdout
requirements, or promote a proposal to a universal rule. A normal verified fix can
be used under its ordinary engineering acceptance criteria without a historical
replay or an experiment claiming that the agent became faster.

## Supply advice to a new task

```bash
python -m traz --root /path/to/private/corpus context \
  --project my-project --task-family package-release
```

This produces at most five advisory cards within a 6,000-character compact JSON
budget. Cards have `mandatory: false`. Their source evidence, implementation
receipts and efficacy status remain distinct. Context rechecks paths previously
bound by explicit artifact verification; missing or changed bytes are excluded.
Reported regressions exclude the revision in their exact evidence scope.
If an incomplete request is compatible with a known regression, the card is
withheld until the missing context resolves that conflict.

The existing runner or instruction loader must actually call this command before
the relevant **new** task. Installing TRAZ or registering a card does not create
that integration. Prefer an existing deterministic gate when it can enforce the
invariant without additional agent context. A conditional project instruction can
request context when judgment is still necessary. Do not inject the whole corpus
or query it before every trivial task.

Retrieval is read-only with respect to sessions and external artifacts. It creates
no agent, fork, continuation, deferred message, watcher or timer. Human-stop and
other admission controls remain owned by the existing runner. Record a blocked
correction as pending work rather than bypassing them.

## Observe the next natural task

Record the version actually used, acceptance result, counterexamples and measured
costs when a relevant task arrives normally. A failed safeguard is useful evidence
and may justify retirement. Use the separate experiment ledger only for claims
that require a comparative efficacy estimate. Do not manufacture before/after
numbers or replay completed production work merely to fill the ledger.
