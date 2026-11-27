# Process IR v1.0

## 1. 文档结构

```json
{
  "schema_version": "process-ir/1.0",
  "name": "设备支援流程",
  "description": "业务流程说明",
  "status_catalog": [],
  "start_node_id": "start",
  "end_node_ids": ["end"],
  "nodes": [],
  "edges": [],
  "guards": {
    "max_node_visits": 10000
  }
}
```

保存后由服务端增加：

```json
{
  "process_id": "proc_0123456789ab",
  "version": 1,
  "content_hash": "sha256:...",
  "created_at": "2026-11-19T12:00:00Z"
}
```

## 2. 节点

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 唯一稳定 ID，匹配 `^[A-Za-z][A-Za-z0-9_-]{0,63}$` |
| type | start / task / decision / end | 节点类型 |
| name | string | 业务名称，不限定行业 |
| description | string | 可选说明 |
| position | `{x, y}` 或 null | 画布自由布局坐标，属于 Process IR |
| duration | number 或 null | 仅 task 必填，单位自然日，非负 |
| status_on_enter | string 或 null | 引用 status_catalog |
| status_on_complete | string 或 null | 引用 status_catalog |
| on_enter | Effect[] | 进入节点时执行的通用效果 |
| on_complete | Effect[] | 完成节点时执行的通用效果 |
| outcomes | Outcome[] | 仅 task 可用，用于业务结果抽样 |

### 示例

```json
{
  "id": "inspection",
  "type": "task",
  "name": "设备检测",
  "description": "检测设备状态",
  "position": {"x": 720, "y": 230},
  "duration": 0.2,
  "status_on_enter": "operational",
  "outcomes": [
    {
      "id": "pass",
      "name": "合格",
      "weight": 0.95,
      "attributes": {"inspection_passed": true}
    },
    {
      "id": "fail",
      "name": "不合格",
      "weight": 0.05,
      "attributes": {"inspection_passed": false}
    }
  ]
}
```

业务结果使用独立业务随机流，不属于可靠性 λ 抽样。

## 3. 连接

JSON 使用 `from` / `to`：

```json
{
  "id": "e_result_repair",
  "from": "inspection_result",
  "to": "repair",
  "kind": "conditional",
  "label": "不合格",
  "priority": 10,
  "condition": {
    "op": "eq",
    "field": "attributes.inspection_passed",
    "value": false
  }
}
```

连接类型：

| kind | 说明 |
|---|---|
| normal | 普通顺序出口 |
| conditional | 条件出口，必须有 condition |
| default | 兜底出口，不能有 condition |
| failure | 故障出口，不能有 condition |

规则：

- 每个节点最多一个 normal、一个 failure、一个 default。
- decision 至少两个出口，至少一个 conditional，必须有 default。
- 条件出口不能与 default 混用 normal/failure。
- task 的多出口组合只支持 `conditional + default` 或 `normal + failure`。
- start 只能有一个 normal 出口，end 不能有出口。

## 4. 条件表达式

```json
{"op": "eq", "field": "attributes.inspection_passed", "value": true}
```

操作符：

- `eq`, `ne`
- `gt`, `gte`, `lt`, `lte`
- `in`, `not_in`
- `exists`, `is_null`
- `and`, `or`, `not`

可用字段：

- `entity_id`
- `currently_failed`
- `ever_failed`
- `failure_count`
- `repair_count`
- `current_status`
- `attributes.<name>`
- `node_visits.<node_id>`

限制：

- 最大嵌套深度 8。
- 最多 64 个子条件。
- 逻辑条件只能使用 conditions。
- 比较条件的 value 不能是 NaN / Infinity。
- `in` / `not_in` 的 value 必须是数组。

## 5. 效果 Effect

```json
{"op": "set_attribute", "name": "inspection_passed", "value": true}
{"op": "increment_counter", "name": "repair_count", "by": 1}
{"op": "set_state", "name": "currently_failed", "value": false}
{"op": "set_status", "value": "operational"}
```

- `set_attribute` 写入业务属性。
- `increment_counter` 支持 failure_count、repair_count 或 attributes.*。
- `set_state` 支持 currently_failed 和 current_status。
- `set_status` 引用状态目录。

维修行为不在 Runtime 中写死，而由流程节点的 status 和 effect 定义。

## 6. 状态目录

```json
[
  {"id": "operational", "name": "可运行", "counts_as_available": true},
  {"id": "under_repair", "name": "维修中", "counts_as_available": false},
  {"id": "retired", "name": "已退役", "counts_as_available": false}
]
```

Phase 1 只定义和验证引用，设备完好状态语义在评价阶段使用。

## 7. 循环

循环通过回边表达。例如：

```text
检测 -> 判断 -> 维修 -> 检测
```

验证器要求：

- 循环至少有一个离开强连通分量的出口。
- 循环内至少有一个 decision 节点。
- 若退出条件只依赖自定义 attributes，这些属性必须由循环内节点写入。
- `guards.max_node_visits` 必须在 1 到 1,000,000 之间。

运行时仍必须使用访问次数上限和仿真终止时间作为最终安全网。

## 8. 内容哈希和版本

哈希基于规范化 JSON，包含：

- 名称、说明。
- 状态目录。
- 节点、连接、条件、效果、结果。
- 画布坐标。
- guards。

不包含：

- process_id。
- version。
- content_hash。
- created_at。

节点和边按 ID 排序后计算，因此仅调整数组顺序不会改变哈希。

## 9. Schema 拒绝的字段

以下字段不会出现在 Process IR 中：

- `lambda`
- `participates`
- `reliability`
- `distribution`
- `lambda_unit`

出现这些字段会返回 Schema 校验错误。

## 嵌套流程块（process-ir/1.1）

嵌套块使用 `type: "subprocess"` 节点和内联 `subflow`：

- `subflow` 拥有自己的 `start_node_id`、`end_node_ids`、`nodes`、`edges` 和 `guards`。
- 所有节点和连接 ID 在整个 ProcessDocument 内全局唯一。
- 父连接只能连接父层节点或 subprocess 容器；子流程连接只能连接同一子流程内部节点。
- 父连接通过 `subflow_exit` 指定从哪个子流程 end 返回。
- 多出口子流程必须为每个 end 提供父连接映射。
- `subprocess` 节点不能设置 `duration` 或 `outcomes`；内部 task 的 duration 推进仿真时间。
- 展开/收起属于前端状态，不进入 IR，也不参与内容哈希。
- `process-ir/1.0` 单层流程继续兼容；包含 subprocess 的模型使用 `process-ir/1.1`。
