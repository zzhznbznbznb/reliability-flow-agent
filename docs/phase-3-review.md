# Phase 3 边界审查报告

本次审查只读检查 Runtime，并针对发现的问题做最小修复，不重构架构、不进入 Phase 4。

## 1. 仿真结束边界

审查结论：

- `_finish_at_simulation_end` 只处理完成时间晚于仿真结束时间的 task。
- 暴露时间使用 `simulation_end - node_enter_time`。
- 部分区间仍执行一次可靠性抽样，记录 `partial=true`。
- 部分区间故障只更新 failure_count、ever_failed、currently_failed，不进入 failure 出口。
- 设备保留在原 task，不标记 completed，也不丢弃。

补充测试 `test_partial_exposure_failure_is_recorded_without_routing`：

- 验证 exposure = 0.4。
- 验证 R = exp(-λ × 0.4)。
- 验证只有一个抽样事件且发生在仿真结束时刻。
- 验证所有历史事件时间不超过 simulation_end。
- 验证没有 failure_routed、repair_started、repair_completed、business_outcome。
- 验证该 task 没有 node_completed/entity_completed。
- 验证最终仍停留在 inspect，currently_failed=true。

## 2. 多阶段维修统计

发现的问题：

原规则在维修路径第一个 task 完成时自动增加 `repair_count`。如果显式
`increment_counter repair_count` 位于后续维修节点，会先自动加 1，再执行显式效果，
造成重复计数。

最小修复：

- 维修结算时点改为：
  - `currently_failed` 由 true 变为 false；或
  - 维修路径到达 end。
- 如果故障以来已经发生显式 `repair_count` 增加，则以显式效果为准，不自动增加。
- 如果已恢复但后续可达路径仍存在显式计数效果，则等待显式效果。
- 如果显式计数位于未实际走到的分支，则按当前路径正常自动结算一次。
- 每次维修只记录一次 `repair_completed`。

新增测试：

- `test_multistage_repair_does_not_double_count_with_late_explicit_effect`
- `test_multistage_repair_with_decision_loop_counts_once`
- `test_early_recovery_waits_for_late_explicit_counter`
- `test_repair_branch_without_explicit_effect_still_counts_once`
- 原有显式效果、无显式效果和永久 `ever_failed` 测试继续通过。

## 3. 随机流隔离

审查结论：

- 每设备有独立 reliability 和 business RNG。
- 两者种子由 SHA-256 分别派生，不共享可变状态。
- 可靠性抽样只使用 reliability RNG。
- 业务 outcomes 只使用 business RNG。

新增测试
`test_business_branch_on_another_node_does_not_shift_reliability_samples`：

- A：无业务 outcomes。
- B：在前置非可靠性节点增加业务 outcomes。
- 相同 Process 结构主体、相同设备数量、相同 seed。
- 验证每个设备在可靠性节点上的 random_value 和 reliability_probability 完全一致。
- 验证 B 有 business_outcome，A 没有。

## 4. 重复节点访问

审查结论：

- 每次 `_enter_node` 都重置 node_enter_time、node_elapsed_time 和 pending completion。
- 每次 task 完成都会重新调用可靠性抽样，RNG 继续前进。
- 不存在缓存上一次抽样结果的逻辑。

新增测试：

- `test_repeated_reliability_node_visits_get_independent_samples`
  - 同一节点访问两次。
  - 两次完整暴露各 1 天。
  - 两次抽样 random_value 不同。
  - 同种子重复运行结果一致。
- `test_repeated_reliability_node_full_then_partial_exposure`
  - 第一次完整暴露 1 天，partial=false。
  - 第二次进入后被仿真结束截断为 0.5 天，partial=true。
  - 两次抽样相互独立，最终保留第二次访问状态。

## 5. 修改文件

- `app/simulation/engine.py`
- `tests/test_simulation_runtime.py`
- `docs/simulation-runtime.md`
- `docs/phase-3-report.md`
- `docs/phase-3-review.md`
- `README.md`（测试数量）

## 6. 测试结果

```text
后端：139 passed
前端辅助逻辑：9 passed
Vite 生产构建：成功
```

## 7. 剩余限制

- 维修结算仍依赖 Process IR 明确表达 failure 出口和状态效果。
- 复杂维修若在恢复后、后续分支中才显式计数，会延迟到显式效果或以 end 兜底结算。
- 仿真结果仍未持久化为实验记录。
- 仅支持指数分布。
- 项目仍无 Git 提交。

## 8. 结论

**Phase 3 可以正式验收。**
