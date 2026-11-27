# 离散事件仿真 Runtime（Phase 3）

## 1. 模块结构

```text
app/simulation/
  config.py     仿真参数与集中安全上限
  models.py     事件、设备结果、可靠性抽样、仿真结果
  errors.py     验证错误和运行错误
  rng.py        每设备独立随机流派生
  engine.py     离散事件引擎
app/api/
  simulation_routes.py  仿真 HTTP API
```

Runtime 只消费已经验证并保存的 `ProcessDocument` 和与其精确绑定的
`ReliabilityDocument`。Runtime 不修改两个 IR，也不把可靠性参数写回 Process IR。

## 2. 核心数据结构

实体运行状态 `_EntityRuntime`：

- `entity_id`
- `current_node_id`
- `current_status`
- `node_enter_time`
- `node_elapsed_time`
- `failure_count`
- `repair_count`
- `ever_failed`
- `currently_failed`
- `attributes`
- `node_visits`
- `history`
- `pending_completion_time`
- 独立可靠性 RNG
- 独立业务 RNG

仿真事件 `SimulationEvent`：

```json
{
  "seq": 12,
  "time": 2.0,
  "event_type": "reliability_sample",
  "entity_id": "entity_0001",
  "node_id": "operation",
  "data": {}
}
```

可靠性抽样 `ReliabilitySample` 单独保存为结构化列表，同时作为
`reliability_sample` 事件写入该设备历史。

## 3. 事件推进

- 使用 `heapq` 事件队列，键为 `(time, scheduling_order, kind, entity_id, node_id, token)`。
- 同一时刻事件按调度顺序稳定处理，不使用集合遍历决定结果。
- 设备创建后按实体 ID 顺序在 `simulation_start` 调度 start 事件。
- task 节点进入后调度完成事件；start、decision、end 在同一时刻立即完成。
- 多设备共享一个事件队列，但状态、历史、计数器和 RNG 全部独立。
- 当队列头时间超过 `simulation_end` 时停止主循环，并处理当前 task 的部分暴露。

## 4. 节点执行语义

- 进入任意节点：递增访问次数，应用 `status_on_enter` 和 `on_enter`。
- task：
  - 按 `duration` 推进并调度完成。
  - 若该节点参与可靠性计算，按所选 `failure_sampling` 模式抽样。
  - 故障时不再执行业务 outcomes 和 `on_complete`，直接走故障处理。
  - 无故障时抽样业务 outcomes，再应用 `on_complete` 和 `status_on_complete`。
- decision：立即完成，按优先级选择匹配的 conditional 出口，否则使用 default。
- end：标记实体完成。
- 循环由 Process IR 回边表达，Runtime 使用 `guards.max_node_visits` 终止超限实体。

## 5. 可靠性抽样

`SimulationConfig.failure_sampling` 支持两种模式。

### time_to_failure（默认，时间驱动）

对 `participates=true` 且 `λ > 0` 的 task 节点，进入节点时抽样故障时刻：

```text
U 为可靠性随机流上的 [0, 1) 均匀随机数
T_failure = -ln(1 - U) / λ
故障时刻 = 节点进入时刻 + T_failure
```

- 若 `T_failure <= task.duration`，在故障时刻调度真实的 `failure_node` 事件，
  并在该时刻记录抽样、触发故障计数、进入 `failure` 出口及维修流程。
- 若 `T_failure > task.duration`，任务正常完成，完成后记录一次“存活”抽样。
- λ=0 时不发生故障，但仍按每设备每次访问记录一次存活抽样。
- 仿真结束前未完成的 task 记录部分暴露的存活抽样。
- 抽样记录包含 `failure_time`（实际故障时刻；未故障为 null）。
- 故障时刻不再被推迟到任务完成时记账。

### interval_end（Phase 3 兼容）

```text
R(Δt) = exp(-λΔt)
U >= R(Δt) 视为故障
```

- 在 task 完成时对完整暴露区间抽样。
- 故障在区间结束时刻记账，不估计区间内故障时刻。
- 用于需要与 Phase 3 历史实验保持一致语义的场景。

### 公共语义

- λ 单位为每自然日，Δt 单位为自然日。
- 不参与节点不抽样。
- 每次抽样记录 entity_id、node_id、lambda、exposure_time、
  reliability_probability、random_value、failure_occurred、partial、
  failure_time。

### 部分暴露

仿真在 task 完成前结束时：

- 实际暴露时间 = `simulation_end - node_enter_time`。
- `time_to_failure` 模式记录存活抽样，设备保留在该节点。
- `interval_end` 模式执行区间抽样；若发生故障只记录故障计数，因为仿真已结束，
  不进入维修分支。
- 设备 `node_elapsed_time` 记录实际执行时间。

## 6. 随机数与可复现性

每个实体有两个独立随机流：

- `reliability`
- `business`

流种子：

```text
seed = int(SHA-256("rfa-sim/1|<base_seed>|<entity_id>|<stream>")[:16])
```

因此：

- 设备之间不共享 RNG 状态。
- 业务抽样与可靠性抽样互不影响。
- 相同 Process IR、Reliability IR、设备数量、仿真结束时间、随机种子和策略
  产生逐字段一致的结果。

## 7. 故障与维修

故障发生时：

1. `failure_count += 1`
2. `ever_failed = true`
3. `currently_failed = true`
4. 记录 `reliability_failure` 和 `node_failed`
5. 存在 failure 出口时进入故障处理流程并记录 `repair_started`
6. 没有 failure 出口时：
   - 默认策略 `require_failure_exit` 在仿真启动前拒绝运行。
   - `stop_entity` 策略只停止该设备，记录 `failure_without_exit`。

维修：

- 维修节点仍然由 Process IR 的 duration、status 和 effects 定义。
- 故障进入 failure 出口后标记维修待完成。
- 在以下时点之一结算一次维修：
  - `currently_failed` 由 true 变为 false。
  - 维修路径完成并到达 end。
- 若自故障以来没有显式增加 `repair_count`，Runtime 自动补 1。
- 若已有显式 `increment_counter repair_count`，以显式效果为准，不重复计数。
- 记录 `repair_completed`。
- 是否清除 `currently_failed` 由 Process IR 的 effects 决定；`ever_failed`
  不会被任何状态效果重置。

## 8. 安全上限

集中定义在 `SimulationLimits`：

| 限额 | 默认值 |
|---|---|
| max_entities | 10,000 |
| max_events | 1,000,000 |
| max_node_visits | 1,000,000 |
| max_simulation_days | 365,000 |

Runtime 还使用 Process IR 的 `guards.max_node_visits`，取两者较小值。

异常场景：

- 无匹配出口或无法推进：运行错误。
- 事件队列为空但设备未完成：`simulation_stuck`。
- 循环访问超限：停止该设备并记录 `max_node_visits_exceeded`。
- 事件上限：`max_events_exceeded`。

## 9. API

`POST /api/processes/{process_id}/simulate`

```json
{
  "process_version": 1,
  "entity_count": 10,
  "simulation_start": 0,
  "simulation_end": 30,
  "random_seed": 2026,
  "failure_policy": "require_failure_exit",
  "failure_sampling": "time_to_failure"
}
```

- `process_version` 可省略，默认最新版本。
- 时间窗口支持三种写法：
  - 只给 `simulation_end`：从 `simulation_start`（默认 0）执行到绝对结束时刻。
  - 给 `simulation_start + simulation_duration`：自动计算 `simulation_end`。
  - 同时给三者时必须满足 `simulation_end == simulation_start + simulation_duration`，否则返回 422。
- `failure_sampling`：`time_to_failure`（默认）或 `interval_end`。
- 只使用与该 Process IR 版本和内容哈希精确绑定的 Reliability IR。
- 缺少绑定可靠性配置返回 HTTP 409 `reliability_not_bound`。
- 配置或 IR 无效返回 HTTP 400 `simulation_invalid` 和 issue 列表。
- 运行上限错误返回 HTTP 400 及具体错误码。

响应包含：

- 流程与可靠性版本绑定。
- `runtime_semantic_version` 和 `failure_sampling`，用于标记结果语义。
- `simulation_start`、`simulation_end`、`simulation_duration`。
- 实体最终状态和每设备事件历史。
- 全量事件日志。
- 结构化可靠性抽样列表（含 `failure_time`）。
- 失败、完成、停止、事件和抽样计数。

## 嵌套流程执行（Runtime）

- Runtime 为每个实体维护 `scope_stack`。
- 进入 subprocess 节点时压栈并立即进入子流程 start；不额外消耗仿真时间。
- 子流程内部 task/decision/条件/循环按普通流程执行，task duration 推进全局仿真时间。
- 到达子流程 end 时弹栈，记录 `subprocess_completed` 和块的 `node_completed`，再按父连接的 `subflow_exit` 返回父流程。
- 父连接为 failure 时记录异常出口，并进入父流程维修/异常目标。
- 事件包含 `scope` 和 `depth`；内部 task 的可靠性抽样包含 `scope_path`。
- 内部 task 的可靠性、故障出口、维修和状态恢复沿用现有 Runtime 语义。
- 相同模型、种子和配置下嵌套执行结果可复现；前端展开状态不影响 Runtime。
