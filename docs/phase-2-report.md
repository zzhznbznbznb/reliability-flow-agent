# Phase 2 开发报告

## 1. 完成范围

Phase 2 实现了独立的 Reliability IR、节点可靠性配置、验证、持久化、版本绑定
和前端可靠性面板。没有实现仿真 Runtime、随机故障抽样、维修仿真、指标计算或实验
比较。

## 2. Reliability IR 实际 Schema

版本：`reliability-ir/1.0`

持久化文档：

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

节点字段：

| 字段 | 规则 |
|---|---|
| node_id | 必须引用 Process IR 节点 |
| participates | true / false |
| distribution | 第一版只允许 `exponential` |
| lambda | 参与时必填，非负有限数字，允许 0 |
| lambda_unit | 固定 `per_day` |

`start`、`decision`、`end` 节点不能配置可靠性。`task` 节点必须显式配置参与或
不参与。

## 3. 数据存储方式

- Process IR：`data/processes/{process_id}.json`（Phase 1，不变）。
- Reliability IR：`data/reliability/{process_id}.reliability.json`。
- 可靠性文件结构：

```json
{
  "store_schema_version": "reliability-store/1.0",
  "process_id": "proc_0123456789ab",
  "revisions": []
}
```

- 每次配置变化追加 revision，内容未变化不会重复创建。
- 写入使用临时文件 + 原子替换。
- 历史 revision 全部保留。
- 不包含业务流程字段，不依赖 Process IR 文件内部保存可靠性参数。

## 4. Process IR 版本绑定机制

每个 Reliability revision 绑定：

- `process_id`
- `process_version`
- `process_hash`（Process IR 规范化内容哈希）

规则：

- 保存可靠性配置时只能绑定最新 Process IR 版本和其精确 hash。
- Process IR 更新后，旧 Reliability revision 不会自动复用或自动迁移。
- 最新版本没有匹配配置时，GET 返回 `status = "stale"` 和旧 revision 摘要。
- 查看历史 Process IR 版本时，可以读取绑定该版本的历史可靠性配置。
- 对旧版本发起可靠性保存返回 HTTP 409，避免误绑定。
- 历史版本可靠性配置只用于历史实验，不会被当作当前有效配置。

## 5. 参数验证规则

Schema 层（HTTP 422）：

- 未知字段。
- 非 `exponential` 分布。
- 非 `per_day` 单位。
- 参与节点缺少 λ。
- λ 为负数、NaN、Infinity 或布尔值。
- 重复节点配置。

语义验证层：

| 错误码 | 含义 |
|---|---|
| `reliability_process_version_mismatch` | Process IR 版本不匹配 |
| `reliability_process_hash_mismatch` | Process IR 内容哈希不匹配 |
| `reliability_duplicate_node` | 节点配置重复 |
| `reliability_unknown_node` | 引用了不存在或已删除的节点 |
| `reliability_invalid_node_type` | 非 task 节点参与可靠性 |
| `reliability_missing_config` | task 节点缺少参与配置 |
| `reliability_missing_lambda` | 参与节点缺少 λ |
| `reliability_invalid_lambda` | λ 非法 |
| `reliability_unsupported_distribution` | 不支持的分布 |

验证不执行仿真，不进行故障抽样，不修改输入模型。

## 6. API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/processes/{id}/reliability` | 获取指定或最新版本的可靠性配置 |
| PUT | `/api/processes/{id}/reliability` | 保存最新 Process IR 绑定的配置 |
| POST | `/api/processes/{id}/reliability/validate` | 验证配置和绑定 |
| GET | `/api/processes/{id}/reliability/history` | 可靠性 revision 历史 |

GET 状态：

- `bound`：当前请求的 Process IR 版本有精确绑定配置。
- `missing`：从未保存过可靠性配置。
- `stale`：存在旧 revision，但当前 Process IR 版本没有绑定配置。

浏览器交互使用 `frontend/src/api.js` 中的 `getReliability` 和
`saveReliability`。

## 7. 前端实际功能

右侧节点属性检查器“可靠性”标签页：

- 只有 task 节点显示可靠性配置。
- start、decision、end 显示“不参与抽样”说明。
- 参与开关：
  - 开启显示 λ 输入框。
  - 关闭隐藏 λ 输入框。
- 显示分布类型 `exponential`、单位 `per_day` 和 `R(t) = exp(-λt)`。
- 显示当前绑定的 Process IR 版本、内容哈希和可靠性 revision。
- 显示状态提示：
  - 流程未保存。
  - 正在查看历史版本。
  - 流程有未保存修改。
  - 当前版本无配置。
  - 旧配置已过期且不会自动绑定。
- 保存后提示绑定版本，重新加载流程后从独立 Reliability IR 恢复。
- 关闭参与时保留已有 λ，不静默丢弃。

为保持 Phase 1 视觉风格，只增加了可靠性面板内部样式，没有改动三栏布局、流程图
视觉和 Agent 面板。

## 8. 自动化测试结果

后端：

```text
96 passed
```

新增覆盖：

- Reliability IR Schema、别名、默认指数分布和单位。
- Process IR / Reliability IR 字段隔离。
- 参与节点必须有 λ，不参与节点无需 λ。
- λ = 0 合法；负数、NaN、Infinity、布尔值非法。
- 非 task 节点参与可靠性被拒绝。
- 未知节点、删除节点和缺失 task 配置。
- process_id / version / hash 绑定。
- 新 Process IR 版本不自动复用旧配置。
- revision 追加、历史保留、幂等保存。
- API 保存、读取、验证、历史、409 和 404。
- 旧版本可靠性配置仍然可读。

前端辅助逻辑：

```text
9 passed
```

覆盖参与开关参数校验、λ 输入、保存 payload 构建、其他节点配置保留、删除节点过滤
和配置读取。Vite 生产构建成功。

## 9. 尚未解决的问题

- 未引入浏览器级 E2E 框架；前端交互通过辅助逻辑测试和 Vite 构建验证。
- Reliability IR 只支持指数分布。
- 可靠性配置必须绑定最新 Process IR，不能为历史版本补写新可靠性配置。
- 未实现故障抽样、Runtime、维修过程、指标和实验管理。
- 项目当前没有 Git 提交，全部文件仍为 untracked。

## 10. 是否可以进入 Phase 3

可以。Reliability IR 的独立 Schema、验证、存储、版本绑定、API 和前端配置流程
均已可用，且 Phase 1 原有 53 个测试继续通过。Phase 3 可以在不修改 Process IR
语义的前提下实现随机故障抽样和仿真 Runtime。

