---
name: reliability-flow-modeling
description: Understand natural-language business process and reliability modeling requests for reliability-flow-agent, including Process IR, Reliability IR, simulation, and evaluation workflows.
---

# Reliability Flow Modeling

This project converts natural-language business process requirements into a
Process IR model. Reliability IR is separate; the project's Python Runtime is
the authoritative simulation engine, and Evaluation reports results from that
runtime.

## Current Process IR contract

Use the existing `process-ir/1.0` structure. A complete model has these
top-level fields:

```json
{
  "schema_version": "process-ir/1.0",
  "name": "Process name",
  "description": "",
  "status_catalog": [],
  "start_node_id": "start",
  "end_node_ids": ["end"],
  "nodes": [],
  "edges": [],
  "guards": {"max_node_visits": 10000}
}
```

Only the process `name` is structurally required by Pydantic; the semantic
validator additionally requires a start node, at least one end node, valid
references, and a connected path. Do not omit semantic requirements just
because a field has a schema default.

### Nodes

Supported `type` values are exactly `start`, `task`, `decision`, and `end`.
Each node has `id`, `type`, and `name`; optional fields are `description`,
`position`, `duration`, `status_on_enter`, `status_on_complete`, `on_enter`,
`on_complete`, and `outcomes`.

- IDs for nodes, edges, outcomes, and statuses must match
  `^[A-Za-z][A-Za-z0-9_-]{0,63}$`.
- `task.duration` is a non-negative number and is semantically required.
  Duration is measured in natural days.
- Non-task nodes must not have `duration`.
- `position`, if supplied, has numeric `x` and `y`.
- `outcomes` are only allowed on task nodes. Do not invent outcome sampling,
  status changes, or effects unless the requirement describes them.
- Process IR contains business-flow data, not reliability parameters. Never
  add `lambda`, `participates`, `reliability`, `distribution`, or
  `lambda_unit` to it.

### Edges and flow structure

Edges use `id`, `from`, `to`, `kind`, optional `label`, `priority`, and
`condition`. Supported kinds are exactly `normal`, `conditional`, `default`,
and `failure`.

- Include exactly one `start` node and set `start_node_id` to its ID. It has no
  incoming edge and exactly one `normal` outgoing edge.
- List every `end` node ID in `end_node_ids`. End nodes have no outgoing edge
  and must have an incoming edge.
- Every node must be reachable from the start and able to reach an end.
- A `decision` has at least two outgoing edges, at least one `conditional`
  edge, and a `default` fallback. It must not use `normal` or `failure` edges.
- A `conditional` edge requires `condition`; other edge kinds must not carry a
  condition.
- A task with one outgoing edge uses `normal`. Multiple task exits may be
  `conditional + default` or `normal + failure`. Conditional task exits require
  a default fallback.
- A default edge means the fallback path; do not use it to imply a business
  outcome the user did not specify.
- Cycles require an exit and a `decision` in the cycle. A cycle exit condition
  that uses an attribute must have that attribute written within the cycle.

Condition operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`,
`exists`, `is_null`, `and`, `or`, and `not`. A comparison uses `field` and,
except for `exists` and `is_null`, `value`. Logical conditions use
`conditions`; `not` has exactly one child.

Supported condition fields are `entity_id`, `currently_failed`,
`ever_failed`, `failure_count`, `repair_count`, `current_status`,
`attributes.<name>`, and `node_visits.<node_id>`. Do not invent attributes to
make a branch work. Attribute conditions must refer to attributes written by
task outcomes or effects; an unwritten attribute produces a backend warning.
Condition depth is limited to 8, with at most 64 conditions.

`status_catalog`, effects, and task outcomes are optional model features, not
implicit defaults. If a business rule needs one and the requirement does not
specify it, ask instead of fabricating it.

## Natural language to Process IR

1. Extract the explicitly named process steps and preserve their user-given
   order. Map each described activity to a `task`; add `start`, `end`, or
   `decision` nodes only as required by the described flow and the IR contract.
2. Record each explicit duration as a numeric `task.duration` in natural days.
   Ask for a missing task duration rather than guessing it. Convert another
   unit only when the user's unit is clear, and explain the conversion.
3. Translate stated sequential relationships into `normal` edges. For each
   branch, identify the decision point, each stated predicate, its destination,
   and a fallback. Ask if the predicate, its data source, or the fallback is
   unclear. Do not invent business outcomes, probabilities, attributes, or
   effects.
4. `start_node_id` and `end_node_ids` describe the graph's structural start and
   ends; they are not fields for custom business start/end conditions. Ask
   when a user-described start or completion rule cannot be represented
   unambiguously using the stated nodes and edges.
5. Do not fabricate missing business parameters. If one or more task durations
   are missing, ask one consolidated question that lists every task whose
   duration is needed. Do not silently default to `0` or `1` day, and do not
   submit a candidate Process IR that is known to be missing a required
   duration. The same rule applies to branch predicates, fallback behavior,
   outcomes, effects, and reliability parameters.
6. Before calling the validator, check that IDs and references agree, all
   edges use supported fields and kinds, all tasks have durations, the start
   and end references match their node types, and the graph can reach an end.
   The Skill's schema contract above is authoritative: do not use the
   validator to discover the schema or probe candidate fields.
7. Submit the complete proposed object as `spec` to
   `validate_process_model` once it is ready. In the web Agent, the host
   captures this validated `spec` as the candidate Process IR for the user to
   review. Never submit an empty object, partial model, placeholder, or
   speculative/unsupported fields. Do not call a save, update, Runtime, or
   Evaluation tool during this Process IR generation phase.
8. Treat the real response as authoritative:
   - A 200 response with `valid: false` is a semantic validation result. Read
     its `issues` and correct only errors that can be resolved without
     inventing user requirements.
   - A 422 response is a Schema/input error. Read its returned `issues` and
     correct the object shape or field values when the intended meaning is
     clear.
   - If an issue exposes missing or ambiguous business meaning, ask the user.
   - After a specific correction, call `validate_process_model` again with the
     complete corrected object. Never report success if the tool failed or the
     returned `valid` is not `true`.
9. Once validation succeeds, present the process structure, complete Process
   IR JSON, returned `content_hash`, and any warning-severity issues. The
   validation response contains `valid`, `content_hash`, and `issues`; do not
   invent a separate `warnings` field.

## Web session context and existing models

The web host may prepend a `[reliability-flow-agent session context]` block to
the user request. Treat it as real data:

- `current_process_spec_json` is the user's current canvas draft. If the user
  asks to modify "this process" or "当前流程", use that spec as the base and
  preserve unspecified parts.
- A non-empty `current_process_id` means the canvas is an already saved model.
  Do not treat it as a brand-new process. Do not overwrite it. Produce a full
  candidate spec and explain what changed; the user decides whether to apply
  and save.
- If there is no current spec, or the user explicitly asks for a new process,
  create a new independent model.
- Use `list_process_models` / `get_process_model` when the user refers to
  another saved model and you need its real process_id, version, or hash.
- Use `get_process_ir_schema` only when the current contract is unclear. The
  schema in this Skill remains authoritative; do not probe unsupported fields.

## Reliability IR workflow

Reliability IR is a separate configuration bound to one exact saved Process IR
version and content hash. It is not part of Process IR.

1. Use `get_reliability_ir_schema` to read the real `reliability-ir/1.0` schema.
2. Reliability configuration can only be validated against a saved Process IR.
   Use `get_process_model` to obtain the exact `process_id`, `version`, and
   `content_hash`. If the user's Process IR candidate has not been saved yet,
   explain that the user must review and save it first; do not invent a version
   or hash.
3. Only `task` nodes are configurable. Every task node must explicitly set
   `participates`; participating nodes require a finite non-negative `lambda`
   per natural day. Do not add distributions or parameters outside the schema.
4. Build the complete ReliabilitySpec with `process_version`, `process_hash`,
   and `nodes`, then call `validate_reliability_model` with `process_id` and
   `spec`. Read its real `valid` and `issues`; correct only when the user's
   intent is clear and do not invent missing reliability parameters.
5. After validation, summarize each task node's participation, lambda, and
   binding to Process IR vN/hash. Ask the user to confirm before the host saves
   anything. Never save, overwrite, or simulate from a tool.
6. If the user has not supplied a lambda for a participating node, ask for it.
   Do not guess failure rates, repair durations, or entity counts.

## Request completeness and conversational behavior

- A request that names only steps and order is usually incomplete: every task
  still needs a duration, and decisions need predicates plus a fallback. Ask a
  short, concrete question listing exactly what is missing. Do not produce a
  placeholder model just to look complete.
- If the user supplies some durations but not others, validate a candidate only
  after all required durations are known. Ask for the remaining ones in one
  message.
- A single vague request such as "帮我创建一个装备保障流程" is not enough.
  Ask about the concrete steps, their order, task durations, branch conditions,
  and whether any equipment reliability parameters should be configured.
- Examples of acceptable questions:
  - "我识别到任务准备、执行任务、任务结束三个节点。请分别给出每个任务的持续时间（天）。"
  - "检查后需要区分哪些情况？例如正常结束、发现故障进入维修。请说明判断依据和默认分支。"
  - "哪些设备或任务节点需要参与可靠性计算？请提供故障率 λ（次/天）。"
- When the user asks to modify the current process, keep all unspecified parts
  unchanged and produce a full candidate. When the user asks for a new process
  while a saved or dirty model is open, treat it as a new independent candidate
  unless they explicitly ask to modify the current one.
- Reliability repair time is not a Reliability IR field in this project. Model
  repair as an ordinary process `task` with its own duration, and ask the user
  for that duration if it is missing.
- Never persist anything, never call save/update endpoints, never start a
  simulation, and never invent validation or simulation numbers. The web host
  only captures candidates and requires explicit user confirmation.
- You have no file, shell, bash, PowerShell, read, write, edit, grep, or find
  tools. Do not claim to create files or run commands.

## Capabilities and later phases

For questions about current API capabilities, call `get_project_capabilities`
and limit claims to its returned categories, operations, and schemas. Do not
introduce unrelated products, schemas, versions, or comparisons not present
in the tool result.

If the user discusses simulation, keep Reliability IR separate and use only
units declared by its schema. Distinguish entity count from independent
experiment repetitions and request a simulation end time if missing. Do not
run a simulation until the user explicitly confirms it; this session does not
expose a simulation tool.

Skill instructions guide model behavior; they are not an authorization or
security boundary. Tool access must be restricted by the host, and side-effect
permissions must be enforced by the backend.
