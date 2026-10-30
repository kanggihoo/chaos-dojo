# chaos-lab

A lab for rebuilding the same backend environment on demand, injecting failures and load, and comparing how different solutions behave under the same conditions.

## Experiments

**Problem**:
A family of failure situations around one piece of business behaviour, such as "an external API gets slow or dies".
_Avoid_: kata, drill, case

**Scenario**:
One runnable variant of a problem with its own workload, faults and checks, such as baseline, api-slow or api-down.
_Avoid_: test case, kata variant

**Impl**:
One solution to a problem that can be run against any of its scenarios, such as naive or timeout.
_Avoid_: strategy, variant, solution

**Run**:
One invocation of one scenario against one impl, together with its preserved result bundle.
_Avoid_: experiment, session

**Repeat**:
One independent execution inside a run, in its own fresh environment; a run holds five.
_Avoid_: iteration, trial

**Cohort**:
The group a request belongs to by why it was sent: warmup, measured, or recovery probe.
_Avoid_: phase (a phase is a time span, not a request group)

## Verdicts

**Completion**:
Whether a repeat ran all its phases to the end.

**Measurement validity**:
Whether a repeat's numbers can be trusted, independent of what they show.
_Avoid_: success, health

**Correctness**:
Whether a repeat kept every invariant the problem declares.
_Avoid_: validity

**SLO**:
Whether a repeat met the problem's declared target for in-budget successes and their latency.
_Avoid_: performance pass

**Ambiguous outcome**:
A stored result whose request the client never saw confirmed, such as an order saved after the client timed out; reported separately, neither a violation nor a pass.
_Avoid_: phantom order

**Time-to-recovery**:
The time from a fault's removal to the start of the first run of consecutive in-budget successes.
_Avoid_: MTTR
