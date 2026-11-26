# Reliability IR v1.0

Reliability IR 与 Process IR 完全独立。Process IR 只定义业务流程；Reliability IR
只定义 task 节点的可靠性配置。λ、`participates`、`distribution` 等字段不允许写入
Process IR。

## 1. 文档结构

```json
{
  "schema_version": "reliability-ir/1.0",
  "reliability_id": "rel_0123456789ab",
  "process_id": "proc_0123456789ab",
  "process_version": 3,
  "process_hash": "sha256:...",
  "revision": 1,
  "created_at": "2026-11-20T12:00:00Z",
  "nodes": [
    {
      "node_id": "inspection",
      "participates": true,
      "distribution": "exponential",
      "lambda": 0.02,
      "lambda_unit": "per_day"
    },
    {
      "node_id": "repair",
      "participates": false
    }
  ]
}
```

保存请求中的 `ReliabilitySpec` 不包含 `process_id`、`reliability_id`、`revision`
和 `created_at`，这些字段由服务端生成。`process_id` 来自 URL。

## 2. 节点配置

| 字段 | 类型 | 说明 |
|---|---|---|
| node_id | string | 引用 Process IR 的 task 节点 ID |
| participates | boolean | 是否参与可靠性计算 |
| distribution | `exponential` | 第一版只支持指数分布 |
| lambda | number 或 null | 故障率 λ，单位每自然日 |
| lambda_unit | `per_day` | 固定单位，防止单位歧义 |

规则：

- `participates=true` 时必须提供 λ。
- `participates=false` 时不需要 λ。
- 不参与抽样的节点仍正常执行原有的业务流程和持续时间。
- λ 可以为 0，表示无随机故障。
- λ 必须是有限的非负数；负数、NaN、Infinity、布尔值均非法。
- 不参与抽样时允许保留历史 λ，避免用户切换开关时静默丢失配置。
- start、decision、end 节点不能配置可靠性，也不能参与抽样。

## 3. 数学模型

```text
R(t) = exp(-λt)
```

- λ：每自然日故障率。
- t：实际暴露时间，单位为自然日。
- R(t)：给定暴露时间内的可靠度。

用户只输入 λ。可靠度 R 由模型计算，不允许同时独立设置 λ 和 R。Phase 2 只实现
指数分布，不包含 Weibull 等分布。

## 4. 验证规则

验证器 `validate_reliability` 只检查配置和绑定关系，不依赖仿真结果，也不抽样。

| 错误码 | 含义 |
|---|---|
| `reliability_process_version_mismatch` | 配置绑定的流程版本与目标文档不一致 |
| `reliability_process_hash_mismatch` | 配置绑定的内容哈希与目标文档不一致 |
| `reliability_duplicate_node` | 同一节点存在重复配置 |
| `reliability_unknown_node` | 配置引用了当前流程中不存在的节点 |
| `reliability_invalid_node_type` | 非 task 节点被配置为参与可靠性 |
| `reliability_missing_config` | task 节点没有显式配置参与或不参与 |
| `reliability_missing_lambda` | 参与计算的节点缺少 λ |
| `reliability_invalid_lambda` | λ 非法 |
| `reliability_unsupported_distribution` | 使用了不支持的分布 |

Schema 层会先拒绝未知字段、非法分布、重复节点和非法 λ，并返回 HTTP 422。

## 5. 存储

- 每个流程一个独立文件：`data/reliability/{process_id}.reliability.json`。
- 文件结构：

```json
{
  "store_schema_version": "reliability-store/1.0",
  "process_id": "proc_0123456789ab",
  "revisions": []
}
```

- 每次配置变化追加一个 revision；内容未变化不重复创建。
- 所有历史 revision 保留，可用于历史实验。
- Reliability 文件不包含 duration、outcomes、edges 等 Process IR 字段。

## 6. 版本绑定

Reliability IR 通过三元组绑定 Process IR：

- `process_id`
- `process_version`
- `process_hash`

行为：

- 保存可靠性配置时必须是当前最新 Process IR 版本，且 hash 必须完全匹配。
- Process IR 创建新版本后，旧 Reliability IR 不会自动绑定到新版本。
- 查询新版本时，如果没有对应 revision，状态为 `stale`，旧 revision 只在
  `stale_revisions` / 历史接口中可见。
- 查看历史 Process IR 版本时，可读取其精确绑定的历史可靠性配置。
- 不能通过旧版本请求写入可靠性配置，否则返回 HTTP 409。

## 7. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/processes/{id}/reliability` | 获取指定/最新版本的可靠性配置 |
| PUT | `/api/processes/{id}/reliability` | 保存最新版本绑定配置 |
| POST | `/api/processes/{id}/reliability/validate` | 验证配置与绑定 |
| GET | `/api/processes/{id}/reliability/history` | 可靠性 revision 历史 |

GET 返回：

```json
{
  "process": {
    "process_id": "proc_0123456789ab",
    "version": 3,
    "content_hash": "sha256:..."
  },
  "reliability": null,
  "status": "stale",
  "stale_revisions": [],
  "revision_count": 1
}
```

`status` 取值：`bound`、`missing`、`stale`。

## 8. 前端

右侧节点属性检查器的“可靠性”标签页：

- 点击 task 节点显示可靠性配置。
- 提供参与开关。
- 开启后显示 λ 输入框；关闭后隐藏。
- 显示 λ 单位、指数分布和 `R(t) = exp(-λt)` 说明。
- 显示当前绑定的 Process IR 版本和内容哈希。
- 显示无配置、过期配置、历史版本、未保存修改等状态提示。
- 保存后重新加载流程时恢复配置。

非 task 节点显示不可参与抽样的说明，不显示 λ 输入。
