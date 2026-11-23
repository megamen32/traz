# TRAZ method

TRAZ investigates whether past agent work can improve future work at a lower total
cost. Its name comes from the Russian **Теория решения агентных задач**. The initial
parameter catalogue and matrix are research hypotheses, not an established theory.

## Start with the problem, not the matrix

Follow this sequence before choosing a mechanism. It adapts the software route in
[peiman/triz](https://github.com/peiman/triz/blob/main/docs/triz-method-skill.md).

1. **Frame.** Describe the missing benefit or observed harm without prescribing an
   implementation. Cite the session and events that establish it. Separate what
   happened from why someone thinks it happened.
2. **Ideal final result.** State what would be true if the harm disappeared while
   the useful work remained, with minimal added cost or attention. Write the result
   before proposing a component, rule, agent or matrix entry.
3. **Find the causal conflict.** Explain why improving one property currently
   worsens another. If the same property must take opposing values, specify where,
   when or under which condition each value is needed. If the causal explanation is
   unknown, inspect functions and causes first. A routine bug can receive its routine
   fix without an invented contradiction.
4. **Inventory resources.** Consider the existing transcript, tests, tools, storage,
   configuration, idle time and supervising agent. State which existing resource
   each candidate uses. Treat analysis and maintenance as costs, not free resources.
5. **Resolve and check.** Try separation in time, space, condition and system level.
   Remove unnecessary functions or move them to their proper owner. Check the result
   against the ideal and the protected properties, including new secondary harms.

The project's own application of these steps is in [TRIZ_DESIGN.md](TRIZ_DESIGN.md).

## A matrix is a retrieval aid

After describing the cause, optionally query a directed pair of an improving
parameter and a protected parameter. A cell offers mechanisms to consider and
conditions under which they may work. It does not diagnose the problem or require
the agent to apply a listed mechanism.

- An empty cell means **unknown**, not impossible or unsupported by TRIZ.
- Reversing a pair is a different question. Do not infer symmetry.
- An identical pair calls for separation of opposing requirements on one property,
  not a diagonal recommendation.
- Several parameters may interact. Record each protected constraint explicitly;
  a pairwise cell is a simplification, not a full model of the system.
- Similar parameter names do not establish a causal conflict.
- A good ordinary solution can be used without consulting the matrix.

The upstream TRIZ method deliberately skips its classical engineering matrix for
software. TRAZ's software matrix is therefore an **experimental extension**, not a
claim that the upstream method endorses it. A matrix-free TRAZ control is required
to establish whether this extension adds value.

## From evidence to an intervention

Keep the following states conceptually distinct:

| State | What it means | What it does not mean |
|---|---|---|
| Observation | A trace contains a repeat, error, correction, or successful outcome | Its cause is known |
| Hypothesis | A proposed cause and mechanism explain a bounded situation | The mechanism works |
| Implemented | An artifact or workflow has changed | The agent uses it |
| Applied | A future run actually used that version | The result improved because of it |
| Supported | A relevant comparison passed its declared acceptance conditions | It generalizes to every model or task |
| Refuted or retired | Evidence contradicted it, or its context no longer applies | The historical observation should be deleted |

The v0.1 importer and deterministic detectors provide traceable observations. The
evidence interface records declared comparisons. It does not independently establish
causation, execute a fleet-wide experiment or retrain model weights.

Learn from successes as well as failures. A successful alternative can suggest a
mechanism, but unrelated easy and hard tasks are not a valid before/after comparison.
A deliberate no-op is a useful result when no change is justified.

## Choose the owner of the problem

Before adding a rule, ask whether a tool, implementation, interface, configuration,
test, documentation or work allocation caused the friction. Prefer the smallest
change that removes the cause at its source. An agent instruction is appropriate
when the agent's decision procedure itself needs to change.

For example, repeated identical failed calls may indicate a stale endpoint, missing
state or an unbounded retry loop. A blanket ban on retries could break recovery from
transient faults. Test a scoped mechanism such as failure classification with bounded
retries and a measured fallback. Preserve necessary waiting for genuinely running
jobs. The observation alone cannot choose among these causes.

## Scope every learning

Associate outcomes with task family, project, model and configuration, harness and
version, tool/environment versions, intervention revision, time, and known constraints.
Unknown context stays unknown. A result on one model version is evidence for that
version, not automatic evidence for a successor.

Store applicability and counterexamples alongside successes. Later regression should
lower or retire the recommendation in that context. Removing a stale rule or a
redundant component is a first-class intervention. Preserve the previous version and
its evidence so that a change can be reviewed or reversed.

## Stop conditions

Stop analysis when a routine fix is clear, no consequential unexplained harm remains,
or the expected benefit of further analysis is below its budget. Do not turn every
session into a large retrospective. Unknown causes and inconclusive experiments are
valid outputs. Measure whether TRAZ itself adds needless work.
