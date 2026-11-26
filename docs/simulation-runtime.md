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

- 使用 `heapq` 事件队列，键为 `(time, scheduling_order, kind, entity_id, node_id)`。
- 同一时刻事件按调度顺序稳定处理，不使用集合遍历决定结果。
- 设备创建后按实体 ID 顺序在 `t=0` 调度 start 事件。
- task 节点进入后调度完成事件；start、decision、end 在同一时刻立即完成。
- 多设备共享一个事件队列，但状态、历史、计数器和 RNG 全部独立。
- 当队列头时间超过 `simulation_end` 时停止主循环，并处理当前 task 的部分暴露。

## 4. 节点执行语义

- 进入任意节点：递增访问次数，应用 `status_on_enter` 和 `on_enter`。
- task：
  - 按 `duration` 推进并调度完成。
  - 若该节点参与可靠性计算，在暴露区间结束进行区间抽样。
  - 故障时不再执行业务 outcomes 和 `on_complete`，直接走故障处理。
  - 无故障时抽样业务 outcomes，再应用 `on_complete` 和 `status_on_complete`。
- decision：立即完成，按优先级选择匹配的 conditional 出口，否则使用 default。
- end：标记实体完成。
- 循环由 Process IR 回边表达，Runtime 使用 `guards.max_node_visits` 终止超限实体。

## 5. 可靠性区间抽样

对 `participates=true` 的 task 节点：

```text
R(Δt) = exp(-λΔt)
U 为可靠性随机流上的 [0, 1) 均匀随机数
未故障：U < R(Δt)
故障：  U >= R(Δt)
```

- λ 单位为每自然日，Δt 单位为自然日。
- λ=0 时 R=1，随机故障不可能发生。
- 不参与节点不抽样。
- 每次抽样记录 entity_id、node_id、lambda、exposure_time、
  reliability_probability、random_value、failure_occurred、partial。
- 不在区间内伪造精确故障时刻，故障在区间结束时记账。

### 部分暴露

仿真在 task 完成前结束时：

- 实际暴露时间 = `simulation_end - node_enter_time`。
- 仍然执行一次区间抽样。
- 设备保留在该节点，`node_elapsed_time` 记录实际执行时间。
- 如果部分区间抽样发生故障，记录故障和计数器，但因为仿真已结束，不进入维修分支。

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
  "simulation_end": 30,
  "random_seed": 2026,
  "failure_policy": "require_failure_exit"
}
```

- `process_version` 可省略，默认最新版本。
- 只使用与该 Process IR 版本和内容哈希精确绑定的 Reliability IR。
- 缺少绑定可靠性配置返回 HTTP 409 `reliability_not_bound`。
- 配置或 IR 无效返回 HTTP 400 `simulation_invalid` 和 issue 列表。
- 运行上限错误返回 HTTP 400 及具体错误码。

响应包含：

- 流程与可靠性版本绑定。
- 实体最终状态和每设备事件历史。
- 全量事件日志。
- 结构化可靠性抽样列表。
- 失败、完成、停止、事件和抽样计数。
