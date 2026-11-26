# 架构设计（Phase 1 / Phase 2 / Phase 3）

## 1. 范围

Phase 1 实现业务流程层：

- 通用 Process IR Schema。
- 流程结构与语义验证。
- 版本化流程存储与内容哈希。
- 由 Process IR 自动生成流程图。
- Process IR 的 HTTP API。
- React Flow 自由布局流程编辑器。
- 离线命令式 Agent 面板。

Phase 2 在业务流程层之上增加独立的可靠性配置层：

- Reliability IR Schema。
- task 节点参与开关和指数分布 λ。
- 可靠性配置验证。
- 与 Process IR 的版本号和内容哈希精确绑定。
- 独立的可靠性 revision 存储。
- 右侧可靠性标签页的保存和重新加载。

Phase 3 增加离散事件仿真层：

- 多设备独立运行。
- task 持续时间推进。
- 指数分布可靠性区间抽样。
- 故障出口、维修流程和状态恢复。
- 每设备独立事件历史。
- 独立业务/可靠性随机流与随机种子复现。
- 集中安全上限和不可推进检测。

评价指标、实验比较和完整 LLM Agent 尚未进入本阶段。

## 2. 分层结构

```text
浏览器
  React 19 + React Flow + Dagre
        │  JSON API
        ▼
FastAPI
  app/api/process_routes.py
        │
        ├── app/domain/process_ir.py       Process IR Schema
        ├── app/domain/validation.py       结构、条件、循环验证
        ├── app/domain/versioning.py       规范化内容哈希
        ├── app/domain/reliability_ir.py   Reliability IR Schema
        ├── app/domain/reliability_validation.py 可靠性配置与绑定验证
        ├── app/processes/store.py         版本化 Process IR 持久化
        ├── app/reliability/store.py       独立 Reliability IR revision 持久化
        ├── app/simulation/engine.py       离散事件仿真 Runtime
        ├── app/simulation/rng.py          每设备独立随机流
        ├── app/api/reliability_routes.py  可靠性配置 API
        ├── app/api/simulation_routes.py   仿真 API
        └── app/diagram/                   自动布局与 SVG 导出
```

关键原则：

- 后端不包含任何具体设备或行业流程模板。
- Process IR 不包含 λ、可靠性参与标记或可靠性分布。
- 前端画布不维护第二套流程结构；节点、连线和坐标全部来自 Process IR。
- 所有结构编辑先更新 Process IR 草稿，再更新画布。

## 3. Process IR 与 Reliability IR 分离

Process IR 使用 Pydantic `extra="forbid"`。任何 `lambda`、`participates`、`reliability` 等字段都会导致 Schema 校验失败。

Phase 1 的业务语义字段包括：

- 节点类型、名称、持续时间、位置。
- 条件表达式。
- 业务结果 outcomes。
- 节点效果 on_enter / on_complete。
- 状态目录 status_catalog。

这些字段都属于流程或业务语义，不属于可靠性抽样参数。

## 4. 前端技术评估与选择

候选方案：

1. 原生 SVG/Canvas 编辑器。
2. Streamlit。
3. React + React Flow（XYFlow）。

选择 React Flow，原因：

- 原生支持节点拖拽、缩放、平移、连线、选择、删除。
- 自定义业务节点和自定义回边路径可控。
- Controls、MiniMap、fitView 直接满足画布操作要求。
- 相比自行实现 Canvas 编辑器，交互可靠性更高。
- 不引入后端技术变更，FastAPI 继续作为唯一 API。

参考 `wind-maintenance-studio` 的视觉语言：

- 浅色工作台。
- 白色卡片节点和左侧色条。
- 蓝色选中描边。
- 左侧流程/助手，右侧属性检查器。
- 回边使用虚线。

但没有复用其 SysML 概念，也没有复用其静态 SVG 图。

## 5. 画布与 Process IR 同步

Process IR 的每个节点包含可选 `position: {x, y}`。

- 初始加载时，如果缺少坐标，前端执行 Dagre 自动布局并写入草稿。
- 用户拖动节点后，`onNodeDragStop` 将新坐标写回 Process IR。
- 自动布局会重新计算坐标并写回 Process IR。
- 新建、删除节点和连接只修改 Process IR。
- 保存时提交完整 Process IR，坐标随版本一起持久化。
- 右侧属性修改同样提交 Process IR。

因此画布和 Process IR 不存在独立保存的不一致图形数据。

## 6. 流程图生成机制

存在两条同源输出：

1. React Flow 交互画布：由 Process IR 实时映射。
2. 服务端 SVG：`app/diagram/layout.py` 和 `app/diagram/svg.py` 根据 Process IR 生成。

服务端布局规则：

- 存在全部节点坐标时按坐标渲染。
- 否则使用从左到右的分层布局。
- 回边检测使用 DFS，并结合目标节点是否位于源节点左侧。
- 循环回边使用虚线并路由到节点下方。
- decision 使用菱形/判别视觉。
- 所有文本进行 XML 转义，不生成脚本。

SVG 主要用于导出、测试和快速预览；交互编辑器使用 React Flow。

## 7. 版本与内容哈希

- 每次保存生成 `ProcessDocument` 快照。
- 内容哈希基于规范化 JSON：
  - 节点和边按 ID 排序。
  - 状态目录按 ID 排序。
  - 排除 process_id、version、content_hash、created_at。
  - 坐标属于内容，因此移动节点会产生新的内容哈希。
- 内容未变化时不会创建新版本。
- 历史版本保存在同一流程文件的 `versions` 数组中。
- 更新请求必须携带 `base_version`；版本不匹配返回 HTTP 409，避免静默覆盖。
- 实验版本后续可引用稳定的 `process_id + version + content_hash`。

## 7.1 Reliability IR 与绑定

Reliability IR 独立于 Process IR 存储：

- 每个流程一个 `data/reliability/{process_id}.reliability.json`。
- 文件内保存多个 revision，每个 revision 绑定
  `process_id + process_version + process_hash`。
- `participates`、`distribution`、`lambda`、`lambda_unit` 只存在于 Reliability IR。
- Process IR 的 `extra="forbid"` 继续拒绝这些字段。

版本一致性规则：

- 保存可靠性配置前，服务端读取最新 Process IR，要求版本和内容哈希完全匹配。
- Process IR 产生新版本后，旧可靠性 revision 状态变为 `stale`，不会自动绑定。
- 历史可靠性 revision 永久保留，可通过历史接口和指定 Process IR 版本读取。
- 不允许用旧版本绑定写入可靠性配置；冲突返回 HTTP 409。
- 保存时要求每个 task 节点都有显式配置，参与节点必须有合法 λ。

## 8. API

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/processes/validate` | 校验未保存的 Process IR |
| POST | `/api/processes/preview.svg` | 从当前草稿生成 SVG |
| GET | `/api/processes` | 流程列表 |
| POST | `/api/processes` | 创建流程 v1 |
| GET | `/api/processes/{id}` | 获取最新或指定版本 |
| PUT | `/api/processes/{id}` | 基于 base_version 创建新版本 |
| GET | `/api/processes/{id}/versions` | 版本历史 |
| GET | `/api/processes/{id}/diagram.svg` | 已保存版本的 SVG |
| GET | `/api/processes/{id}/reliability` | 指定/最新版本的可靠性配置 |
| PUT | `/api/processes/{id}/reliability` | 保存最新版本绑定的可靠性配置 |
| POST | `/api/processes/{id}/reliability/validate` | 验证可靠性配置和绑定 |
| GET | `/api/processes/{id}/reliability/history` | 可靠性 revision 历史 |
| POST | `/api/processes/{id}/simulate` | 运行离散事件仿真 |

## 8.1 仿真层

Runtime 使用保存后的 `ProcessDocument` 和与其精确绑定的
`ReliabilityDocument`，不重新定义流程或可靠性参数。

- 一个全局稳定事件队列，多设备状态完全独立。
- 每设备两个 RNG：可靠性流、业务流。
- task 暴露区间结束做一次指数可靠性区间抽样。
- 故障只能通过 `failure` 出口处理；否则必须有显式 `stop_entity` 策略。
- 仿真结束保留未完成设备，并对其当前 task 的部分暴露时间抽样。
- 安全上限集中在 `SimulationLimits`。

详细说明见 `docs/simulation-runtime.md`。

## 9. 验证策略

验证器只报告问题，不修改模型。错误和警告都包含 code、message、node_id、edge_id、field。

核心检查：

- 节点/连接 ID 唯一。
- 连接端点存在。
- start / end 引用一致。
- 节点可达且可到达 end。
- task 持续时间。
- decision 多出口、条件出口和 default 兜底。
- 条件结构、字段白名单和属性引用。
- 循环有出口、包含 decision，并检查退出条件依赖的状态是否在循环内被更新。
- 无条件自循环。
- 非法状态引用和不支持的效果。

运行时还会使用 `guards.max_node_visits` 作为最终安全上限。

## 10. 当前限制

- Agent 目前是离线命令解析，不是完整 LLM 自然语言理解。
- Reliability IR 只支持指数分布。
- 可靠性配置只能保存到最新 Process IR 版本。
- 评价指标、实验比较和完整 LLM Agent 尚未实现。
- 仿真结果当前由 API 直接返回，尚未持久化为实验记录。
- 前端暂未增加仿真运行面板，仿真通过 HTTP API 使用。
- 前端打包体积较大，主要来自 React Flow；当前可接受。
- 服务端 SVG 和 React Flow 的节点尺寸存在轻微渲染差异。
- 未实现多用户并发编辑和鉴权。

Reliability IR 的完整 Schema、验证和绑定说明见 `docs/reliability-ir.md`。
