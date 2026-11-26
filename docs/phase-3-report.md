# Phase 3 开发报告

## 1. Runtime 架构

```text
app/simulation/
  config.py       SimulationConfig、SimulationLimits
  models.py       SimulationEvent、ReliabilitySample、EntitySimulationResult、SimulationResult
  errors.py       SimulationValidationError、SimulationRuntimeError
  rng.py          SHA-256 派生的每设备可靠性/业务随机流
  engine.py       SimulationRuntime、run_simulation
app/api/
  simulation_routes.py  POST /api/processes/{id}/simulate
```

职责：

- `engine.py`：验证输入、创建实体、推进事件队列、执行节点、抽样、故障维修、
  安全限制和结果构建。
- `config.py`：集中最大设备数、最大事件数、最大节点访问次数、最大仿真天数。
- `rng.py`：为每台设备派生独立随机流。
- `models.py`：结构化事件、抽样、实体结果和仿真结果。
- `simulation_routes.py`：从 ProcessStore / ReliabilityStore 读取精确绑定版本并运行。

Runtime 不修改 Process IR 或 Reliability IR。所有可靠性参数来自 Phase 2 的
Reliability IR。

## 2. 核心数据结构

设备运行状态：

- entity_id、current_node_id、current_status
- node_enter_time、node_elapsed_time
- failure_count、repair_count
- ever_failed、currently_failed
- attributes、node_visits、history
- pending_completion_time
- 独立 reliability RNG、独立 business RNG

事件：

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

独立可靠性抽样列表字段：

- entity_id、node_id、time
- lambda、exposure_time
- reliability_probability、random_value
- failure_occurred、partial

仿真结果字段：

- Process IR / Reliability IR 绑定信息
- random_seed、entity_count、simulation_end
- event_count、reliability_sample_count
- total_failure_count、completed_count、stopped_count
- entities（含每设备 history）
- reliability_samples
- events（全量日志）

## 3. 事件推进机制

- 使用 `heapq` 最小堆，键为 `(time, scheduling_order, kind, entity_id, node_id)`。
- 同一时间事件按单调递增调度序号处理，保证稳定顺序。
- 所有实体在 `t=0` 按实体 ID 顺序进入 start。
- task 进入后调度完成事件；start/decision/end 在同一时刻立即完成。
- 多设备共享队列，但每台设备有独立状态和 pending completion。
- 队列头时间超过 `simulation_end` 时退出主循环，随后处理部分暴露。

## 4. 随机抽样机制

可靠性：

```text
R(Δt) = exp(-λΔt)
U = reliability_rng.random()
failure = U >= R(Δt)
```

- λ 单位为每自然日，Δt 为实际暴露自然日。
- `participates=false` 不抽样。
- λ=0 时 R=1，不发生故障。
- 每次抽样记录 lambda、暴露时间、R、随机数、故障结果和 partial 标记。
- 抽样时间点是暴露区间结束；不伪造区间内精确故障时刻。

部分暴露：

- 如果 task 完成时间超过仿真结束时间，实际暴露 = `end - enter`。
- 仍然执行一次区间抽样并记录。
- 设备保留在该 task，记录实际 `node_elapsed_time`。
- 部分区间发生故障时记录故障计数，但不进入维修路径。

随机流：

```text
seed = int(SHA-256("rfa-sim/1|<base_seed>|<entity_id>|<stream>")[:16])
```

企业业务结果使用 `business` 流，可靠性抽样使用 `reliability` 流。增加业务抽样
不会改变可靠性抽样序列。

## 5. 多设备独立性

- 每台设备创建独立的 `_EntityRuntime`。
- `attributes`、`node_visits`、`history`、计数器全部独立。
- 业务流程 outcomes 的属性值使用深拷贝写入设备，避免嵌套可变对象共享。
- 每台设备两个独立 RNG，无共享可变状态。
- 一台设备故障或停止只影响自身；其他设备继续在事件队列中推进。
- 已用 40 台设备和业务分叉验证同一仿真时间存在不同节点状态。

## 6. 故障与维修机制

故障发生时：

1. `failure_count += 1`
2. `ever_failed = true`
3. `currently_failed = true`
4. 记录 `reliability_failure` 和 `node_failed`
5. 存在 failure 出口时进入故障流程并记录 `failure_routed`、`repair_started`

无 failure 出口：

- 默认 `require_failure_exit`：启动前返回配置错误 `missing_failure_exit`。
- 显式 `stop_entity`：只停止故障设备，原因 `failure_without_exit`。

维修：

- duration、status、effects 全部来自 Process IR。
- 故障进入 failure 出口后标记维修待完成。
- 在 `currently_failed` 由 true 变为 false，或维修路径到达 end 时结算一次维修。
- 若自故障以来没有显式增加 `repair_count`，Runtime 自动加 1。
- 若 Process IR 已显式 `increment_counter repair_count`，以显式效果为准，不重复计数。
- 记录 `repair_completed`。
- 是否清除 `currently_failed` 由 Process IR effects 决定；`ever_failed`
  不被任何效果重置。
- `failure_count` 与 `repair_count` 独立统计。

## 7. API

### POST `/api/processes/{process_id}/simulate`

请求：

```json
{
  "process_version": 1,
  "entity_count": 10,
  "simulation_end": 30,
  "random_seed": 2026,
  "failure_policy": "require_failure_exit"
}
```

- `process_version` 可省略，默认使用最新版本。
- Reliability IR 必须精确绑定该 Process IR 的版本和内容哈希。
- `failure_policy`：`require_failure_exit` 或 `stop_entity`。

主要错误：

- 404：流程或版本不存在。
- 409 `reliability_not_bound`：该流程版本没有绑定可靠性配置。
- 400 `simulation_invalid`：Process/Reliability 验证失败或缺少 failure 出口。
- 400 `max_entities_exceeded` / `max_simulation_days_exceeded` / 其他运行错误。
- 422：请求 Schema 非法。

## 8. 自动化测试结果

- 原有测试：96
- 新增测试：43
- 当前总计：139 passed
- 前端辅助逻辑：9 passed
- Vite 生产构建：成功

新增覆盖：

- 单设备完整流程。
- 多设备独立状态与事件历史。
- 同时间不同节点。
- 同种子结果逐字段复现。
- λ=0、指数概率、未参与节点跳过。
- 业务随机流与可靠性随机流隔离。
- failure 出口与维修恢复。
- 无 failure 出口拒绝运行和 `stop_entity` 隔离。
- `ever_failed` 永久、failure/repair 计数。
- 仿真结束部分暴露与非完成设备保留。
- decision、循环、`max_node_visits`。
- 最大事件、最大设备、最大仿真时间。
- 非法 Process IR、Reliability IR、版本不匹配、未知节点、非法 λ。
- API 保存流程、保存可靠性、运行、复现和错误路径。

## 9. 真实运行案例

使用示例 `examples/reliability_maintenance_flow.json`：

- Process IR：`设备运行与故障维修流程`
- `operation` task：duration = 2 天
- `repair` task：duration = 1 天，维修后恢复 operational
- Reliability IR：`operation participates=true, λ=0.5`；`repair participates=false`
- 设备数量：10
- 仿真结束：30 天
- random_seed：2026
- failure_policy：默认 `require_failure_exit`

实际 API 运行输出摘要：

```text
process proc_ae3969fe4067 v1 sha256:cfda2f57ad76
reliability rel_59a95e9293e6 r1
summary {'entity_count': 10, 'event_count': 163, 'reliability_sample_count': 10,
         'total_failure_count': 9, 'completed_count': 10, 'stopped_count': 0}
```

实际事件片段：

```text
entity_0001 2.0 reliability_sample node operation lambda 0.5 exposure 2.0
  R 0.367879 U 0.577021 fail True partial False
entity_0001 2.0 reliability_failure node operation
  {'failure_count': 1, 'ever_failed': True, 'partial': False}
entity_0001 2.0 failure_routed node operation
  {'edge_id': 'e_operation_repair', 'target': 'repair'}
entity_0001 3.0 repair_completed node repair
  {'repair_count': 1, 'auto_incremented': False, 'explicit_effect_increment': True, 'currently_failed': False}
entity_0001 3.0 entity_completed node end {}
```

设备最终状态（前四台）：

```text
entity_0001 final end status operational fail 1 repair 1 ever_failed True
entity_0002 final end status operational fail 1 repair 1 ever_failed True
entity_0003 final end status operational fail 1 repair 1 ever_failed True
entity_0004 final end status operational fail 1 repair 1 ever_failed True
```

该事件由真实 Runtime 计算产生，不是手工构造的静态结果。

## 10. 尚未解决的问题

- 仿真结果尚未持久化到实验记录。
- 前端尚未增加仿真运行面板，目前使用 HTTP API。
- 仅支持指数分布可靠性模型。
- 当前故障区间抽样只记录区间结束时的结果，不估计区间内故障时刻。
- 维修计数在缺少显式效果时采用自动补 1 策略；复杂多阶段维修仍建议在
  Process IR 中显式维护计数。
- 项目仍无 Git 提交。

## 11. 阶段结论

**Phase 3 已达到进入 Phase 4 的条件。**

真实离散事件 Runtime、多设备独立性、可靠性抽样、故障维修、部分暴露、随机复现、
安全限制和 API 均已实现并有自动化测试覆盖。尚未实现的是指标评价、实验比较和
仿真结果持久化，这些属于后续阶段范围。




