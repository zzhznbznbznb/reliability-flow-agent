# Fault Lifecycle Technical Design Specification

Status: design-only. No implementation is included in this document.

The project adopts exactly one fault lifecycle:

```text
NORMAL → LATENT → DETECTED → REPAIRING → NORMAL
NORMAL → DETECTED → REPAIRING → NORMAL   # direct detection at a detection node
```

The second path is not a separate lifecycle model. It is the same lifecycle
with the LATENT state skipped when a detection node's own completion-time
sample directly confirms the fault.

The previous immediate-failure execution mode is not retained. Existing
Process IR and Reliability IR data must remain readable, but all new reliability
fault behavior is unified under this lifecycle.

---

## 0. Design Decision Status

### 0.1 Confirmed decisions

The following decisions are confirmed and are binding for this specification:

1. Only the unified fault lifecycle is used. The previous immediate-failure
   runtime mode is not retained.
2. A latent fault does not immediately interrupt normal business execution.
3. Only a node explicitly configured with fault-detection capability can
   discover a fault, whether the fault is a pre-existing LATENT fault or a new
   fault confirmed by that same node's completion-time sample.
4. After a fault is detected, the detection node still executes its full
   configured duration.
5. Detection-node completion effects are executed before failure routing.
6. After detection, the failure edge takes priority over normal outgoing routes.
7. Once the Runtime confirms a fault, subsequent reliability exposure and
   sampling are suspended, including faults directly detected at a detection
   node.
8. Actual business elapsed time continues to accumulate.
9. Business End Availability and Fault-Free End Availability are displayed as
   separate metrics.
10. A node with fault-detection enabled must have a failure outgoing edge.
11. A potential-fault occurrence node is not required to have a failure edge.
12. The first version cannot determine the exact physical fault occurrence
    time; only the sampling interval can be represented.
13. A detection node can also directly detect a new fault confirmed by its own
    completion-time reliability sample. Such a fault transitions
    NORMAL → DETECTED directly and does not pass through LATENT.

### 0.2 Decisions still to be confirmed

These items are not confirmed by this revision and must not be treated as
fixed implementation decisions:

1. Whether the first version allows fault detection only on task nodes.
2. Whether `currently_failed` excludes LATENT.
3. Whether `failure_policy` is removed entirely or retained with redefined
   API-compatibility semantics.
4. Whether Process IR is upgraded to `process-ir/1.1`.
5. Whether ProcessStore universally adopts `exclude_none=True`.
6. Whether one `fault_id` may have multiple repair attempts.

The rest of this document specifies the mechanism but marks these six items as
pending where they affect implementation.

---

## 1. Current Architecture and Required Module Changes

### 1.1 Verified current implementation facts

Read-only review confirms:

- `app/domain/process_ir.py`
  - `ProcessNode` has no fault detection capability.
  - Node types are `start`, `task`, `decision`, `end`.
  - `failure` already exists as an edge kind.
  - `ProcessNode` uses `extra="forbid"`.
  - `NodeOutcome` attributes are business attributes.
- `app/domain/reliability_ir.py`
  - Reliability nodes have `participates`, `distribution`, `lambda`,
    `lambda_unit`.
  - No detection capability exists in Reliability IR.
- `app/domain/validation.py`
  - Task multi-exit rules allow `normal + failure`.
  - Decision nodes cannot use failure edges.
  - No fault detection validation exists.
- `app/domain/versioning.py`
  - Process content hash uses `model_dump(..., exclude_none=True)`.
  - `schema_version` is present in canonical content and therefore participates
    in the content hash.
  - `process_id`, `version`, `content_hash`, and `created_at` are excluded.
- `app/processes/store.py`
  - `_write` uses `model_dump(mode="json", by_alias=True)` without
    `exclude_none=True`.
- `app/simulation/engine.py`
  - Reliability sampling occurs at task completion.
  - A failed sample immediately sets `currently_failed`, emits
    `reliability_failure`, and routes through the failure edge or stops.
  - Runtime validates that every participating node with `lambda > 0` has a
    failure edge.
  - Partial exposure is sampled at simulation end.
  - Business outcomes are applied as attributes before `on_complete` and can
    later influence normal/conditional routing through conditions.
- `app/simulation/models.py`
  - `ReliabilitySample` has no fault ID or occurrence interval fields.
  - `EntitySimulationResult` has `failure_count`, `repair_count`,
    `ever_failed`, `currently_failed`.
- `app/evaluation/models.py` and `app/evaluation/evaluator.py`
  - Failures are derived from reliability samples.
  - `currently_failed` determines bad end state.
  - `end_availability` is status-based.
  - No latent/detected/detection-delay metrics exist.
- `app/experiments/` is empty.
- No Experiment Manager or Experiment API exists.
- Current tests extensively assert immediate failure behavior.

### 1.2 Modules requiring changes

| Module | Required change |
|---|---|
| `app/domain/process_ir.py` | Optional task detection capability; no node type change |
| `app/domain/validation.py` | Detection validation; remove occurrence-node failure-edge requirement |
| `app/domain/versioning.py` | Preserve old hashes; optional `None` field must remain excluded |
| `app/simulation/engine.py` | Replace immediate failure flow with lifecycle |
| `app/simulation/models.py` | Add fault state, IDs, events, interval metadata |
| `app/simulation/config.py` | Remove or redefine `failure_policy` |
| `app/api/simulation_routes.py` | Remove obsolete immediate policy semantics; additive result fields |
| `app/evaluation/models.py` | Add latent/detection/fault-free metrics |
| `app/evaluation/evaluator.py` | New aggregation, exposure and availability logic |
| `app/evaluation/explanations.py` | Explain latent/detection and three distinct metrics |
| `app/processes/store.py` | Pending decision on `exclude_none=True` |
| `app/reliability/store.py` | No semantic change; binding compatibility preserved |
| Tests | Rewrite immediate-failure tests; add lifecycle tests |
| Experiment Manager | Future versioned persistence of new events/fields |

Reliability IR Schema does not require modification.

---

## 2. Interval Sampling and Fault Occurrence Semantics

The Runtime uses interval-based reliability sampling. At the end of an eligible
exposure interval, it computes:

```text
R(Δt) = exp(-λ × Δt)
U = reliability_rng.random()
failure = U >= R(Δt)
```

The Runtime can only confirm whether a fault occurred after the interval
closes. It cannot identify the exact physical fault occurrence time inside the
interval.

### 2.1 Required distinctions

For every confirmed fault, whether it becomes LATENT or is directly DETECTED,
record all of the following:

```text
reliability_interval_start     # exposure interval start
reliability_interval_end       # exposure interval end
confirmed_time                 # sampling/confirmation time
```

Definitions:

- **Reliability exposure interval**: the interval over which the exponential
  reliability probability was applied.
- **Confirmation time**: the exact simulation event time at which the sample
  was evaluated and the fault was confirmed.
- **Runtime state effective time**: the confirmation time.
  - At an ordinary business node, NORMAL becomes LATENT only after the sample
    confirms failure.
  - At a detection node with no pre-existing LATENT fault, NORMAL becomes
    DETECTED directly at confirmation.
- **Physical fault occurrence time**: unknown; it lies somewhere within the
  exposure interval. The model must not claim a precise physical time.
- **Direct detection**: a detection node's completion-time sample both confirms
  the fault and detects it. The fault is never placed in LATENT.

### 2.2 Exposure accounting

The entire exposure interval that produced the confirmed fault remains counted
as reliability exposure.

Reason:

- The interval model assumes the fault could occur anywhere in the interval.
- Sampling is performed over the whole interval.
- Removing or truncating the interval at an unknown point would invent
  information the Runtime does not have.

Subsequent reliability exposure and sampling are suspended only after the
Runtime confirms the fault at `confirmed_time`. They are not suspended
retroactively at a guessed physical occurrence time. For direct detection at a
detection node, suspension begins after that node's completion-time sample.

### 2.3 Detection delay uncertainty

Detection delay cannot be exact because occurrence time is unknown.

For a detected fault:

```text
delay_min = max(0, detection_time - reliability_interval_end)
delay_max = max(0, detection_time - reliability_interval_start)
```

- These are bounds, not exact delay values.
- For direct detection at a detection node, `detection_time == interval_end`,
  so `delay_min = 0` and `delay_max = interval duration`.
- No default midpoint estimate is used as a formal metric.
- If a point estimate is ever displayed, it must be explicitly labelled as an
  estimate and must not replace the bounds.

For an undetected latent fault at simulation end:

```text
undetected_age_min = max(0, simulation_end - reliability_interval_end)
undetected_age_max = max(0, simulation_end - reliability_interval_start)
```

No detection delay is fabricated for an undetected fault.

---

## 3. Process IR Field Design and Schema Compatibility

### 3.1 Proposed field

Add an optional capability object on `ProcessNode`:

```python
class FaultDetectionCapability(StrictModel):
    enabled: bool = True
```

```python
class ProcessNode(StrictModel):
    ...
    fault_detection: FaultDetectionCapability | None = None
```

JSON:

```json
{
  "id": "inspection",
  "type": "task",
  "fault_detection": {
    "enabled": true
  }
}
```

### 3.2 Optionality and hash preservation

The field MUST be optional with default `None`.

Verified from current implementation:

- `canonical_process_content` uses `exclude_none=True`.
- Existing optional fields with `None`, such as `position`, are omitted from
  canonical content.
- Therefore a future `fault_detection=None` will be omitted from canonical
  content, preserving old canonical hashes.
- A default `False` field would be emitted for every old node and would change
  every existing Process content hash. It must not be used.

The actual `fault_detection` field does not exist yet, so direct end-to-end hash
verification with the new field cannot be performed until implementation.

### 3.3 Schema versioning

Pending decision.

Recommended:

- Existing documents remain `process-ir/1.0`.
- New documents that use fault detection become `process-ir/1.1`.
- `ProcessSpec.schema_version` accepts both `1.0` and `1.1`.
- Old documents are not auto-upgraded.

Verified implication:

- `schema_version` participates in the canonical content hash.
- Therefore rewriting an old document as `1.1` would change its hash.
- Old documents kept at `1.0` remain hash-stable.

Alternative: keep `1.0` for additive optional capability. This avoids a version
bump but is less explicit about the new semantic feature.

### 3.4 Node type restriction

Pending decision: whether fault detection is limited to task nodes in the first
version.

Recommended for the initial design:

- `task` may set `fault_detection`.
- `start`, `decision`, and `end` must not.
- A zero-duration task can represent an instantaneous detection point.

If confirmed otherwise, validation and Runtime entry hooks must support the
additional node types explicitly.

### 3.5 Effects and node types

No new node type is required.

No new effect is required for first version:

- Detection is a declarative node capability.
- Fault clearing is handled by the lifecycle during REPAIRING completion.
- Existing `set_state currently_failed=false` may remain as a repair effect,
  but lifecycle state clearing is authoritative.

Optional future extensions:

- Condition fields `latent_failed`, `detected_failed`, `fault_state`,
  `repairing`.
- Explicit fault-clearing effects if needed.

These are not part of first version.

### 3.6 Failure edge requirement

Confirmed:

- A fault-detection-enabled node must have a failure outgoing edge.
- An occurrence node is not required to have a failure edge.

Recommended validation:

```text
if node.fault_detection is enabled:
    exactly one failure edge is required
```

The current `missing_failure_exit` check for every participating λ>0 node is
obsolete for occurrence nodes and must be replaced by the detection-node rule.

---

## 4. Reliability IR Compatibility

No Reliability IR schema change is required.

- `participates` controls sampling eligibility.
- `lambda` remains per natural day.
- Detection is a Process IR behavior.
- `fault_detection` must not appear in Reliability IR.
- Existing Reliability documents remain valid.

Sampling requires both:

```text
node participates
AND entity fault_state == NORMAL
```

A LATENT, DETECTED, or REPAIRING entity is not sampled even if the node
participates.

### 4.1 Reliability sample fields

`ReliabilitySample` is simulation output, not Reliability IR. Extend it with:

```text
entity_id
node_id
time                    # confirmation/sample time
lambda
exposure_time
interval_start
interval_end
reliability_probability
random_value
failure_occurred
partial
fault_id                # set when failure_occurred
```

The interval is the only defensible physical occurrence information.

---

## 5. Fault State Machine and Entity State

### 5.1 States

```text
NORMAL
LATENT
DETECTED
REPAIRING
```

- `NORMAL`: no unresolved fault; reliability sampling is eligible.
- `LATENT`: Runtime has confirmed a potential fault at a normal business node;
  it has not been detected; business flow continues; sampling is suspended.
- `DETECTED`: a detection node has discovered the fault, either because the
  entity entered with an existing LATENT fault or because the detection node's
  own completion-time sample confirmed a new fault; failure handling has not
  necessarily started yet.
- `REPAIRING`: the entity has selected/entered the failure handling path after
  detection, but the current fault has not been cleared.

Transitions:

```text
NORMAL --sample failure at ordinary business node--> LATENT
NORMAL --sample failure at detection-node completion--> DETECTED
LATENT --detection-node entry--> DETECTED
DETECTED --failure edge selected at node completion--> REPAIRING
REPAIRING --active fault cleared--> NORMAL
```

REPAIRING does not imply that the entity is currently executing a literal
repair action. It is a lifecycle state covering the process-defined
fault-handling path.

### 5.2 Entity fields

Recommended additions:

```text
fault_state: NORMAL | LATENT | DETECTED | REPAIRING
active_fault_id: str | None
latent_failed: bool
detected_failed: bool
fault_interval_start: float | None
fault_interval_end: float | None
fault_confirmed_time: float | None
fault_occurrence_node_id: str | None
fault_detection_time: float | None
fault_detection_node_id: str | None
```

Existing fields:

- `failure_count`: increments once whenever a reliability sample confirms a fault,
  whether the entity enters LATENT or is directly DETECTED.
- `ever_failed`: true when any reliability fault is confirmed; never reset.
- `repair_count`: increments when a repair lifecycle completes.
- `repair_pending`: true while the entity is in the failure-handling path.
- `currently_failed`: pending decision.
  - Recommended: true only in DETECTED/REPAIRING, not LATENT.
  - Alternative: true for any unresolved fault including LATENT.
  - This decision must be fixed before Runtime implementation.

### 5.3 Fault ID

Each fault occurrence gets a stable `fault_id` linked across:

- reliability sample
- fault occurrence event
- detection event (immediate or later)
- fault handling start
- repair start / completion
- fault cleared event

Recommended deterministic format:

```text
fault_<entity_id>_<sequence>
```

A new fault ID is created only after the previous fault is cleared and the
entity returns to NORMAL and later fails a new sample. Only one active fault
exists per entity at a time. Direct detection at a detection-node completion
still creates exactly one `fault_id`; it is not treated as a separate
occurrence and detection fault.

Pending decision: whether one fault may have multiple repair attempts. If
supported, retain the same `fault_id` and add a `repair_attempt` counter.

---

## 6. Event Model

### 6.1 Retained events

- `node_entered`
- `node_completed`
- `edge_taken`
- `effects_applied`
- `business_outcome`
- `entity_completed`
- `entity_stopped`

`repair_started` and `repair_completed` are retained with clarified semantics
below.

### 6.2 New events

#### `fault_occurred`

Recorded at sample confirmation time for every confirmed reliability fault,
including both paths.

- Ordinary business node: the entity transitions NORMAL → LATENT.
- Detection node completion: the entity transitions NORMAL → DETECTED
  directly; the fault is never placed in LATENT.

```json
{
  "event_type": "fault_occurred",
  "entity_id": "entity_0001",
  "node_id": "transport",
  "time": 3.2,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "interval_start": 2.0,
    "interval_end": 3.2,
    "confirmed_time": 3.2,
    "lambda": 0.5,
    "exposure_time": 1.2,
    "reliability_probability": 0.5488,
    "random_value": 0.91,
    "failure_count": 1,
    "ever_failed": true,
    "entered_latent_state": true,
    "occurrence_context": "ordinary_business_node"
  }
}
```

For a fault confirmed by a detection node's own completion-time sample:

```json
{
  "event_type": "fault_occurred",
  "entity_id": "entity_0001",
  "node_id": "inspection",
  "time": 5.0,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "interval_start": 4.0,
    "interval_end": 5.0,
    "confirmed_time": 5.0,
    "lambda": 0.5,
    "exposure_time": 1.0,
    "reliability_probability": 0.6065,
    "random_value": 0.93,
    "failure_count": 1,
    "ever_failed": true,
    "entered_latent_state": false,
    "occurrence_context": "detection_node_completion"
  }
}
```

`confirmed_time` is exact. Physical occurrence time is not recorded.

#### `fault_detected`

Recorded when a detection occurs. There are two detection paths:

- `latent_at_entry`: the entity entered the detection node with an existing
  LATENT fault.
- `detection_node_sample`: the detection node's completion-time reliability
  sample confirmed a new fault at the same node.

For the `latent_at_entry` path:

```json
{
  "event_type": "fault_detected",
  "entity_id": "entity_0001",
  "node_id": "inspection",
  "time": 5.0,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "detection_path": "latent_at_entry",
    "detection_node_id": "inspection",
    "detection_time": 5.0,
    "occurrence_node_id": "transport",
    "interval_start": 2.0,
    "interval_end": 3.2,
    "delay_min": 1.8,
    "delay_max": 3.0
  }
}
```

For the `detection_node_sample` path, `fault_occurred` and `fault_detected`
have the same event time, ordered occurrence first:

```json
{
  "event_type": "fault_detected",
  "entity_id": "entity_0001",
  "node_id": "inspection",
  "time": 5.0,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "detection_path": "detection_node_sample",
    "detection_node_id": "inspection",
    "detection_time": 5.0,
    "occurrence_node_id": "inspection",
    "interval_start": 4.0,
    "interval_end": 5.0,
    "delay_min": 0.0,
    "delay_max": 1.0
  }
}
```

#### `reliability_sampling_suppressed`

Recorded when an otherwise eligible participating node is not sampled because
of LATENT/DETECTED/REPAIRING state.

```json
{
  "event_type": "reliability_sampling_suppressed",
  "entity_id": "entity_0001",
  "node_id": "storage",
  "time": 6.0,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "reason": "latent_fault",
    "actual_elapsed_time": 1.0
  }
}
```

#### `fault_handling_started`

Recorded when the detection node completes and the failure edge is selected.

```json
{
  "event_type": "fault_handling_started",
  "entity_id": "entity_0001",
  "node_id": "inspection",
  "time": 5.2,
  "data": {
    "fault_id": "fault_entity_0001_0001",
    "edge_id": "e_inspection_repair",
    "target": "repair"
  }
}
```

This is the DETECTED → REPAIRING transition.

#### `repair_started`

Recorded when the entity enters the first **task node** on the
failure-handling path after the failure edge. It means a repair/handling task
has begun, not merely that routing occurred. If the failure path never reaches
a task, no `repair_started` event is emitted.

```json
{
  "event_type": "repair_started",
  "entity_id": "entity_0001",
  "node_id": "repair",
  "time": 5.2,
  "data": {
    "fault_id": "fault_entity_0001_0001"
  }
}
```

#### `repair_completed`

Recorded when the active fault is cleared and REPAIRING returns to NORMAL.

#### `fault_cleared`

Recorded at the same time as `repair_completed`, identifying the cleared fault.

### 6.3 Removed immediate-failure events

`reliability_failure` must not be used for new lifecycle behavior. It may remain
only as historical data in old results.

`node_failed` and `failure_routed` are replaced by:

- `fault_occurred`
- `fault_detected`
- `fault_handling_started`

Keeping both old and new active semantics would be ambiguous.

---

## 7. Exact Event Ordering and Runtime Algorithm

### 7.1 Path A: detection node entered with an existing LATENT fault

For a task with fault detection enabled:

1. Entity enters the node.
2. Record `node_entered`.
3. Execute `status_on_enter` and `on_enter`.
4. Check whether the entity has an undetected LATENT fault.
5. Since LATENT exists:
   - record `fault_detected` with `detection_path=latent_at_entry`;
   - set state DETECTED;
   - set `detected_failed` according to the pending `currently_failed` decision;
   - preserve occurrence interval and compute delay bounds.
6. Execute the node's full configured duration.
7. Do not perform reliability sampling for this node. If the node participates,
   record `reliability_sampling_suppressed` with reason `detected_fault`.
8. Sample and apply business outcomes as business effects.
9. Execute `on_complete`.
10. Execute `status_on_complete`.
11. Record `node_completed`.
12. Select the failure edge, record `edge_taken` with kind `failure`, record
    `fault_handling_started`, set REPAIRING, and enter the failure target.
13. Do not evaluate or select normal/conditional/default outgoing routes.

### 7.2 Path B: detection node entered with no LATENT fault

This path applies when the entity enters the detection node in NORMAL state.
A detection node entered while REPAIRING does not detect new faults; it remains
part of the process-defined handling path.

1. Entity enters the node.
2. Record `node_entered`.
3. Execute `status_on_enter` and `on_enter`.
4. Check whether the entity has an undetected LATENT fault; confirm none exists.
5. Execute the node's full configured duration.
6. Perform completion-time reliability sampling if `participates=true` and the
   entity is still NORMAL.
7. If the sample confirms failure:
   - create `fault_id`;
   - `NORMAL → DETECTED` directly;
   - do not enter LATENT;
   - increment `failure_count`;
   - set `ever_failed=true`;
   - record `reliability_sample` with failure fields and interval bounds;
   - record `fault_occurred` with
     `entered_latent_state=false` and
     `occurrence_context=detection_node_completion`;
   - record `fault_detected` with
     `detection_path=detection_node_sample`, same event time, ordered after
     `fault_occurred`.
8. If the sample does not confirm failure, remain NORMAL.
9. Sample and apply business outcomes as business effects.
10. Execute `on_complete`.
11. Execute `status_on_complete`.
12. Record `node_completed`.
13. If this node directly produced a detected fault:
    - select the failure edge;
    - record `edge_taken` with kind `failure`;
    - record `fault_handling_started`;
    - set REPAIRING;
    - enter the failure target.
14. Otherwise select normal/conditional/default routing.

### 7.3 Business outcomes and sampling order

Business outcomes are **business effects**, not a routing mechanism. They apply
attributes and are sampled before `on_complete`, matching the existing Runtime.
Normal route conditions may read those attributes later, but business outcomes
do not select the failure edge.

Ordering rules:

- Path A: no reliability sampling; business outcomes execute after duration and
  before `on_complete`.
- Path B: reliability sampling executes first at node completion. If it confirms
  a fault, state becomes DETECTED before business outcomes execute.
- In both paths, business outcomes, `on_complete`, and `status_on_complete`
  execute before `node_completed` and before failure routing.
- Failure-edge priority is determined by DETECTED state, not by business
  outcomes.

### 7.4 Ordinary business task completion

```text
complete_ordinary_task(entity, node, time):
    elapsed = duration
    set node_elapsed_time = elapsed

    if state == NORMAL and node.participates:
        sample reliability over [node_enter_time, time]
        if failure:
            create fault_id
            state = LATENT
            failure_count += 1
            ever_failed = true
            record reliability_sample(failure=true, interval fields, fault_id)
            record fault_occurred(
                entered_latent_state=true,
                occurrence_context=ordinary_business_node
            )
            # continue; no failure routing
    elif node.participates:
        record reliability_sampling_suppressed(reason=state)

    sample/apply business outcomes
    apply on_complete
    apply status_on_complete

    if state == REPAIRING and fault clearing condition is met:
        complete_repair(...)

    record node_completed

    if node.type == end:
        entity.completed = true
        record entity_completed
        return

    select normal/conditional/default route
    enter target
```

### 7.5 Detection-node task completion pseudocode

```text
complete_detection_task(entity, node, time):
    elapsed = duration
    set node_elapsed_time = elapsed

    if state == DETECTED and detection_was_at_entry:
        # Path A
        if node.participates:
            record reliability_sampling_suppressed(reason="detected_fault")
    elif state == NORMAL:
        # Path B; state was NORMAL at entry
        if node.participates:
            sample reliability over [node_enter_time, time]
            if failure:
                create fault_id
                state = DETECTED
                failure_count += 1
                ever_failed = true
                record reliability_sample(failure=true, interval fields, fault_id)
                record fault_occurred(
                    entered_latent_state=false,
                    occurrence_context="detection_node_completion"
                )
                record fault_detected(
                    detection_path="detection_node_sample",
                    interval_start=node_enter_time,
                    interval_end=time,
                    detection_time=time
                )
    elif node.participates:
        record reliability_sampling_suppressed(reason=state)

    sample/apply business outcomes
    apply on_complete
    apply status_on_complete
    record node_completed

    if state == DETECTED:
        edge = failure edge
        record edge_taken
        record fault_handling_started
        state = REPAIRING
        repair_pending = true
        enter target
        return

    select normal/conditional/default route
    enter target
```

A fault confirmed by the detection node's own completion sample is already
DETECTED. It is not recorded as LATENT and does not wait for a later detection
node.

`repair_started` is emitted when the entity first enters a task node while
REPAIRING. It is not emitted at the initial failure-edge routing step.

### 7.6 Repair completion

```text
if state == REPAIRING and fault is cleared:
    state = NORMAL
    latent_failed = false
    detected_failed = false
    currently_failed = false
    active_fault_id = None
    repair_pending = false
    repair_count += 1
    record repair_completed
    record fault_cleared
    # reliability sampling is eligible again
```

Fault clearing is only allowed while REPAIRING. Detection-node `on_complete`
effects cannot clear a fault that was just detected at entry or directly
detected by its completion-time sample.

Clearing condition follows the existing repair lifecycle principle:

- Process IR effects/status complete the repair and clear the active fault; or
- the process-defined handling path reaches an end node with an active repair
  lifecycle.

This exact condition must be confirmed alongside `currently_failed` semantics.

Repair completion must not modify:

- `ever_failed`
- `failure_count`
- historical events
- previous fault IDs

### 7.7 Simulation end

For each entity with a pending task at simulation_end:

```text
actual_elapsed = simulation_end - node_enter_time
set node_elapsed_time = actual_elapsed

if state == NORMAL and node.participates:
    sample partial interval
    if failure:
        create latent fault
        record reliability_sample(partial=true, fault_id)
        record fault_occurred(
            entered_latent_state=true,
            occurrence_context="partial_exposure_at_simulation_end"
        )
        state = LATENT
        # No node completion occurred, so completion-time detection does not
        # run, even if the interrupted node has fault_detection enabled.
        # No repair and no failure routing at simulation end.
elif node.participates:
    record reliability_sampling_suppressed(reason=state)
```

A partial interval at simulation end is not a completed detection node. Even
when the interrupted node is detection-enabled, a newly confirmed fault remains
LATENT until a later detection node is actually entered in a future run.

The entity remains in its true final state:

- NORMAL → normal partial execution
- LATENT → unresolved latent
- DETECTED → detected but handling not started
- REPAIRING → repair not completed

No event after simulation_end is emitted.

---

## 8. Reliability Sampling and Exposure

| Entity state | Sample? | Reliability exposure credited | Actual elapsed |
|---|---:|---|---|
| NORMAL, participates=true | Yes | full eligible interval | elapsed |
| NORMAL, participates=false | No | 0 | elapsed |
| LATENT | No | 0 | elapsed |
| DETECTED | No | 0 | elapsed |
| REPAIRING | No | 0 | elapsed |

Rules:

- A detection node entered while NORMAL is sampled at completion. Its entire
  execution interval counts as reliability exposure. If that sample fails, the
  fault is directly DETECTED, not LATENT.
- A detection node entered while LATENT is not sampled; the existing fault is
  detected at entry. Its execution interval does not add new reliability
  exposure because sampling was already suspended.
- The interval that produces any confirmed fault remains fully counted.
- Sampling and reliability exposure are suspended only after `confirmed_time`.
- Actual business elapsed time always continues.
- `reliability_sampling_suppressed` records skipped sampling.
- Theoretical reliability metrics use sampled reliability exposure only.
- Actual elapsed metrics use event-derived business time independently.
- Never substitute actual elapsed for reliability exposure, or vice versa.

---

## 9. Failure-Edge Routing and Process Conditions

- Occurrence nodes do not route through failure edges.
- Detection nodes route through exactly one failure edge if:
  - a fault was detected at entry; or
  - the detection node's completion-time sample directly confirmed a fault.
- Detection node requires `normal + failure` exits; conditional/default cannot
  be used as the detected-fault route.
- If no latent fault is found at entry and the completion-time sample succeeds,
  the detection node uses normal routing.
- If the completion-time sample fails, the fault is directly DETECTED and the
  failure edge is used.
- If state is LATENT and the node is not a detection node, normal routing
  continues.
- If state is REPAIRING, process-defined repair routing continues until the
  fault is cleared.
- Existing conditions using `currently_failed` must follow the pending
  `currently_failed` decision. Latent state is tracked separately.
- First version does not add latent/detected condition fields. Conditional
  branching on fault state is a future extension.

---

## 10. Evaluation Metrics and Formulas

Three metrics are permanently distinct and must not be merged.

### 10.1 A. Overall Reliability / Never-Failed Rate

```text
never_failed_entity_count =
    count(entities where ever_failed == false)

overall_reliability = never_failed_rate =
    never_failed_entity_count / total_entity_count
```

- Any confirmed fault occurrence, including one directly detected at a
  detection node, makes the entity permanently “ever failed.”
- A successful repair does not restore it to never-failed.
- Multiple faults still count as one ever-failed entity.

### 10.2 B. Business End Availability

Business end status uses the existing status catalog only:

```text
business_end_state =
    unknown, if current_status is None or not in status_catalog
    good, if status.counts_as_available == true
    bad, if status.counts_as_available == false

business_end_availability =
    business_good_end_count / total_entity_count
```

- Unknown statuses are not good and are not excluded from the denominator.
- `business_availability_evaluable = false` if any unknown status exists.
- This metric is supplementary. It does not use event history and does not by
  itself represent freedom from faults.

### 10.3 C. Fault-Free End Availability

Formal reliability availability.

```text
fault_free_end_count =
    count(
        entities where fault_state == NORMAL
        AND business_end_state == good
    )

fault_free_end_availability =
    fault_free_end_count / total_entity_count
```

- LATENT, DETECTED, and REPAIRING are not fault-free.
- Repaired entities that return to NORMAL and have a good business status count
  as fault-free.
- Repaired entities still count as previously failed in metric A.
- Unknown business statuses are not fault-free and produce warnings.
- `fault_free_availability_evaluable = false` if any unknown status exists.

### 10.4 Metric distinction examples

| End state | Never-Failed A | Business B | Fault-Free C |
|---|---:|---:|---:|
| Never failed, status operational | Yes | Yes | Yes |
| Failed, repaired, status operational | No | Yes | Yes |
| LATENT, status operational | No | Yes | No |
| DETECTED, status under_repair | No | No | No |
| REPAIRING, status operational | No | Yes | No |
| Never failed, status retired | Yes | No | No |

### 10.5 Occurrence and detection metrics

```text
total_failure_count = count(fault_occurred)

latent_failure_count =
    count(fault_occurred where entered_latent_state == true)

directly_detected_failure_count =
    count(fault_occurred where entered_latent_state == false)

detected_failure_count = count(fault_detected)

undetected_latent_failure_count_at_end = count(LATENT at end)
detected_unrepaired_end_count = count(DETECTED at end)
repairing_end_count = count(REPAIRING at end)
unresolved_fault_end_count =
    undetected_latent_failure_count_at_end
    + detected_unrepaired_end_count
    + repairing_end_count
```

Identity:

```text
total_failure_count =
    latent_failure_count + directly_detected_failure_count

detected_failure_count =
    directly_detected_failure_count
    + latent_faults_detected_later
```

A directly detected fault occurs at a detection node's completion-time sample;
it increments failure occurrence and detection counts but not
`latent_failure_count` and not `undetected_latent_failure_count_at_end`.

- Failure counts belong to the occurrence node. A detection node that is also
  the occurrence node receives both occurrence and detection counts.
- A detection node that only detects a fault occurring elsewhere receives a
  detection count, not an occurrence failure count.
- Detection alone never adds a failure count.

### 10.6 Node metrics

```text
node_failure_count = count(fault_occurred at this node)
node_latent_failure_count =
    count(fault_occurred at this node where entered_latent_state == true)
node_directly_detected_failure_count =
    count(fault_occurred at this node where entered_latent_state == false)
node_detection_count = count(fault_detected at this node)
node_failure_frequency =
    node_failure_count / node_sample_count
```

- `node_sample_count = 0` → frequency N/A, not 0.
- A detection node can be both occurrence node and detection node for a direct
  fault; this is not double-counted as two faults.
- Theoretical reliability uses the node's sampled exposure only.
- Actual elapsed uses all business elapsed time, including suppressed periods.
- Suppressed intervals are not in the reliability exposure or failure-frequency
  denominator.

### 10.7 Detection delay metrics

For each detected fault:

```text
detection_time = exact fault_detected event time
delay_min = max(0, detection_time - interval_end)
delay_max = max(0, detection_time - interval_start)
```

- For `latent_at_entry`, detection_time is the later detection-node entry time.
- For `detection_node_sample`, detection_time equals the occurrence
  confirmation time and therefore also the interval end. The bounds are:
  `delay_min = 0`, `delay_max = interval duration`.
- The direct path still does not claim an exact physical occurrence time.

For undetected latent faults at end:

```text
undetected_age_min = max(0, simulation_end - interval_end)
undetected_age_max = max(0, simulation_end - interval_start)
```

No exact occurrence time and no exact detection delay are claimed. Midpoint
estimates are optional display-only values and are not formal metrics.

### 10.8 Target mapping

If existing evaluation targets remain:

- `overall_reliability_min` maps to metric A.
- `end_availability_min` maps to metric C, Fault-Free End Availability.
- Business End Availability remains supplementary unless a separate target is
  added.

---

## 11. Historical Process IR and Reliability IR Compatibility

### 11.1 Verified Process IR hash behavior

Read-only checks of the current implementation established:

1. **`schema_version` participates in canonical content hash.**
   - `canonical_process_content` does not remove `schema_version`.
   - Changing a document from `process-ir/1.0` to `process-ir/1.1` changes its
     hash.

2. **Old `process-ir/1.0` hashes remain unchanged if the schema version is not
   rewritten and the new field is absent or `None`.**
   - Old documents keep `schema_version=1.0`.
   - New code must not auto-upgrade old documents.
   - A new `1.1` document will have a new hash, which is expected.

3. **`fault_detection=None` will be excluded from canonical content.**
   - Verified mechanism: `model_dump(..., exclude_none=True)` removes existing
     `None` fields such as `position` from canonical content.
   - The actual `fault_detection` field does not exist yet, so direct execution
     with that field is not possible until implementation.

4. **ProcessStore will serialize `fault_detection: null` on re-save if the field
   is added as `None` and `exclude_none=True` is not adopted.**
   - Verified with existing `position: None`: `model_dump(mode="json",
     by_alias=True)` includes `"position": None`.
   - `_write` does not apply `exclude_none=True`.
   - This changes JSON shape but not canonical content hash, because canonical
     content excludes None.
   - Whether ProcessStore adopts `exclude_none=True` is pending decision.

5. **Old Reliability IR `process_hash` bindings remain valid if the old Process
   canonical content is unchanged.**
   - The binding is stored in Reliability IR and lookup uses the Process
     document’s `content_hash`.
   - Since old schema version and canonical content are unchanged, the old
     `content_hash` remains valid.
   - Direct end-to-end verification with the new field is not possible until
     the field is implemented; the mechanism is verified with existing None
     fields.

### 11.2 Compatibility rules

- Use optional `fault_detection: None`; do not use default `false`.
- Do not auto-upgrade old Process IR documents.
- Do not rewrite old content hashes.
- Do not delete old data.
- Old documents have no detection nodes; latent faults may remain undetected
  until simulation end.
- Existing failure edges on old occurrence nodes no longer trigger immediate
  failure. This is a deliberate behavior migration, not a data migration.
- Reliability IR Schema does not change.

### 11.3 Historical experiments

- Experiment Manager is not implemented; `data/experiments/` is empty.
- Future experiments must store schema versions, snapshots, fault events and
  IDs, final fault states, detection delay bounds, and suppressed sampling.
- Old immediate-failure results, if any appear later, must remain historical
  and must not be reinterpreted as latent lifecycle results.

---

## 12. Tests: Rewrite, Retain, Add

### 12.1 Must be rewritten

- `tests/test_simulation_runtime.py`
  - immediate failure route tests
  - `reliability_failure` assertions
  - missing-failure-exit test
  - immediate partial-failure tests
  - repair tests assuming failure routing at the sampled node
- `tests/test_simulation_api.py`
  - immediate failure-exit rejection assertions
- `tests/evaluation/helpers.py`
  - `failed_repaired_entity` and `partial_entity` construction
- `tests/evaluation/test_evaluation_overall.py`
  - currently_failed-based end availability
- `tests/evaluation/test_evaluation_nodes.py`
  - failure actual-elapsed reconstruction
- `tests/helpers.py`
  - `failure_process_dict` immediate layout
- `tests/test_examples.py` / `examples/reliability_maintenance_flow.json`
  - add a detection node and route handling through its failure edge

### 12.2 Retain and adapt

- Event ordering and multi-device independence.
- Decision and loop mechanics not tied to failure routing.
- λ=0, non-participating nodes, RNG independence, partial interval math.
- Process structural validation not involving failure-exit rules.
- Reliability IR Schema/store/API tests.
- Process hashing tests extended with old-document compatibility.
- Evaluation theoretical reliability tests using sampled exposure.

### 12.3 Add

- Optional detection field parsing and old-hash stability.
- Task-only validation (if confirmed).
- Detection-node failure-edge validation.
- Occurrence node without failure edge.
- Latent occurrence continues business execution.
- Detection at entry; full duration; effects; failure priority.
- Business outcomes execution on detection nodes.
- Detection node entered with LATENT: no sampling; failure priority after duration.
- Detection node entered NORMAL and sample succeeds: normal route.
- Detection node entered NORMAL and completion-time sample fails: direct
  NORMAL → DETECTED; never LATENT.
- Direct detection records one occurrence and one detection, with no duplicate
  events.
- Direct detection enters the failure handling lifecycle immediately.
- Detection node entered LATENT detects the existing fault at entry.
- Sampling suppression in LATENT/DETECTED/REPAIRING.
- Partial-exposure fault at simulation end remains LATENT even if the
  interrupted node has detection capability, because node completion did not
  occur.
- Repair completion clears active fault and re-enables sampling.
- Fault IDs across multiple cycles.
- Three distinct evaluation metrics.
- Detection delay min/max bounds.
- End states LATENT/DETECTED/REPAIRING.
- Event order:
  - ordinary node: sample → fault_occurred(entered_latent_state=true) →
    outcomes/effects → node_completed → normal route;
  - detection node direct path: sample → fault_occurred(false) →
    fault_detected(detection_node_sample) → outcomes/effects → node_completed →
    failure edge;
  - detection node entry path: fault_detected(latent_at_entry) → duration →
    outcomes/effects → node_completed → failure edge.
- Historical Process/Reliability binding compatibility.

---

## 13. Test Matrix

| Area | Case | Expected |
|---|---|---|
| Normal | No failure | NORMAL; business completes |
| Latent | Sample failure at completion | LATENT at confirmation; failure_count+1; ever_failed=true |
| Continuation | Ordinary tasks after latent | Business continues; no failure edge |
| Sampling | Participating task while LATENT | No sample; suppressed event |
| Detection entry | Detection node entered LATENT | fault_detected exactly once; DETECTED |
| Detection duration | Duration > 0 | Full duration executes |
| Detection completion | After DETECTED | outcomes/on_complete/status execute; then failure edge |
| Detection priority | DETECTED at entry | Normal/conditional route not evaluated |
| Detection no latent | No latent at entry, sample succeeds | Normal route |
| Direct detection | Detection node sample fails at completion | NORMAL → DETECTED directly; no LATENT |
| Direct detection events | Direct fault | One fault_occurred, one fault_detected |
| Direct detection routing | Direct fault | Failure edge preferred; REPAIRING |
| Latent at entry | Detection node entered LATENT | fault_detected at entry; no sampling |
| Latent later detection | LATENT fault reaches next detection node | Detected there |
| Repeated detection | Same fault loops past detection node | Only one detection event |
| Repair start | Failure edge selected | REPAIRING; fault_handling_started |
| Repair task start | First task on handling path | repair_started |
| Repair completion | Fault cleared | NORMAL; repair_completed; fault_cleared |
| Sampling resume | New task after repair | Sampling eligible |
| Multiple faults | New fault after repair | New fault_id; old history retained |
| Multi-device | Concurrent states | Independent states/events |
| End LATENT | Simulation ends in LATENT | unresolved latent; no detection |
| End DETECTED | Ends in DETECTED | unresolved detected |
| End REPAIRING | Ends in REPAIRING | unresolved repair |
| Partial NORMAL | Task truncated | Partial sample; latent possible |
| Partial detection node | Detection node truncated by simulation end | No completion-time detection; failure remains LATENT |
| Partial LATENT | Task truncated | No sample; suppressed |
| Validation | Detection on disallowed node type | Validation error (if task-only confirmed) |
| Validation | Detection task no failure edge | Validation error |
| Validation | Occurrence node no failure edge | Allowed |
| Metrics A | Repaired entity | Counts as ever failed; not never-failed |
| Metrics B | LATENT, status operational | Business good |
| Metrics B | DETECTED, status operational | Business based on status only |
| Detection metrics | Direct detection | total_failure_count +1; latent_failure_count unchanged; detected count +1 |
| Detection metrics | Direct detection node | occurrence node = detection node; node failure count +1 |
| Detection metrics | Latent later detected | latent count +1; detected count +1 |
| Detection metrics | Undetected latent at end | undetected latent count +1; no detection |
| Metrics C | Repaired NORMAL, status good | Fault-free |
| Metrics C | LATENT/DETECTED/REPAIRING | Not fault-free |
| Detection delay | Known interval/detection | min/max bounds; no exact claim |
| Compatibility | Old Process without field | Parses; old hash unchanged |
| Compatibility | Old Reliability binding | Still resolves |
| Compatibility | ProcessStore re-save | Pending null-shape decision |

---

## 14. Recommended Implementation Phases

### Phase A: Process IR and validation

- Add optional task detection capability (pending task-only decision).
- Validate detection node type and failure edge.
- Preserve old canonical hashes.
- Decide schema version and ProcessStore serialization policy.
- Add compatibility tests.

### Phase B: Runtime lifecycle

- Add fault state and fault IDs.
- Add interval metadata and generic fault occurrence events.
- Gate reliability sampling by NORMAL.
- Add detection at entry and full-duration completion, including direct
  detection of a completion-time sample failure.
- Add failure-edge priority after detection-node completion.
- Add suppressed sampling events.
- Implement fault clearing and repair events.
- Handle partial end states.
- Rewrite runtime tests.

### Phase C: Evaluation

- Add occurrence/detection/unresolved metrics.
- Implement metrics A, B, C distinctly.
- Add detection-delay bounds.
- Update actual-elapsed reconstruction not to use `reliability_failure`.
- Use sampled exposure only for theoretical metrics.
- Bump Evaluation schema version.
- Rewrite evaluation tests.

### Phase D: API and examples

- Resolve `failure_policy` decision.
- Add result fields additively.
- Update reliability example with a detection node.
- Update API docs and UI descriptors.
- Preserve old data readability.

### Phase E: Experiment Manager

- Persist fault events, IDs, states, delay bounds, schema versions.
- Preserve historical results with version dispatch.

---

## 15. Risks and Remaining Questions

### Pending decisions

1. First version detection only on task nodes.
2. `currently_failed` includes or excludes LATENT.
3. `failure_policy` removal versus redefinition.
4. Process IR version `1.0` additive versus `1.1` upgrade.
5. ProcessStore `exclude_none=True`.
6. Multiple repair attempts per `fault_id`.

### Implementation risks

- Old immediate-failure tests must be rewritten; this is a deliberate behavior
  break, not a compatibility-mode requirement.
- `reliability_maintenance_flow.json` must gain a detection node to trigger
  repair under the new lifecycle.
- Event ordering must be centralized to avoid contradictions between sampling,
  detection, outcomes, completion effects, and routing.
- Direct detection must record exactly one occurrence and one detection; it
  must not be counted as both LATENT and directly detected.
- Sampling suppression must not be confused with zero actual elapsed time.
- `actual_elapsed_time` and `reliability_exposure_time` will diverge during
  LATENT/DETECTED/REPAIRING; Evaluation must not substitute one for the other.
- Detection delay claims must remain interval-bound; the physical occurrence
  time is unknowable.
- Undetected latent faults at simulation end must not be counted as detected or
  repaired.
- ProcessStore may serialize new optional fields as `null` unless `exclude_none`
  is adopted; this does not change canonical hash but changes JSON shape.
- Old Reliability bindings can only be guaranteed if old Process canonical
  content is not rewritten.
- Experiment Manager is future work; new event/schema versions should be planned
  from the start.

---

## 16. Summary

The unified fault lifecycle requires:

- optional Process IR fault detection capability;
- no Reliability IR schema change;
- state-gated reliability sampling;
- sampling suspension only after Runtime confirms a fault;
- direct NORMAL → DETECTED detection for faults confirmed by a detection
  node's own completion sample;
- full detection-node duration/effects before failure routing;
- distinct occurrence, detection, repair and unresolved-fault events;
- interval-based detection-delay bounds;
- three distinct Evaluation metrics:
  - Never-Failed Rate,
  - Business End Availability,
  - Fault-Free End Availability;
- verified Process IR hash compatibility through optional `None` fields;
- rewritten immediate-failure tests;
- future versioned Experiment Manager persistence.

No implementation is included in this document.
