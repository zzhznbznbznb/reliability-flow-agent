# reliability-flow-agent 统一论证流程总体架构设计

> 文档状态：架构审查与下一阶段设计（只读审查）  
> 审查日期：2026-11-20  
> 审查对象：`C:\Users\woain\Desktop\reliability-flow-agent`  
> 本次边界：不修改业务代码、Schema、API、前端、测试、配置或数据；只新增本文件。

---

## 0. 阅读说明

### 0.1 证据来源

本报告实际检查了：

- 后端入口与路由：`app/main.py`、`app/api/process_routes.py`、`app/api/reliability_routes.py`、`app/api/simulation_routes.py`。
- 领域模型与校验：`app/domain/process_ir.py`、`app/domain/reliability_ir.py`、`app/domain/validation.py`、`app/domain/reliability_validation.py`、`app/domain/versioning.py`。
- 存储：`app/processes/store.py`、`app/reliability/store.py`、`data/` 目录。
- 仿真：`app/simulation/engine.py`、`app/simulation/models.py`、`app/simulation/config.py`、`app/simulation/rng.py`、`app/simulation/errors.py`。
- 评价：`app/evaluation/models.py`、`app/evaluation/evaluator.py`、`app/evaluation/explanations.py`、`app/evaluation/__init__.py`。
- 前端：`frontend/src/App.jsx`、`frontend/src/api.js`、`frontend/src/components/AgentPanel.jsx`、`frontend/src/components/Inspector.jsx`、`frontend/src/components/Toolbar.jsx`、`frontend/src/reliability.js`。
- 测试：`tests/` 与 `tests/evaluation/`。
- 文档：`README.md`、`docs/architecture.md`、`docs/process-ir.md`、`docs/reliability-ir.md`、`docs/simulation-runtime.md`、`docs/phase-1-report.md`、`docs/phase-2-report.md`、`docs/phase-3-report.md`、`docs/phase-3-review.md`、`docs/fault-lifecycle-technical-design.md`、`docs/requirements-analysis/requirements-analysis.md`。
- 目录现实：`app/experiments/`、`app/nlp/`、`app/analysis/` 均为空目录；`data/experiments/` 只有 `.gitkeep`。

本报告不把 README、设计文档或目录名称当作“已实现”的证据；所有“已实现/部分实现”的判断都尽量落到代码或测试。

### 0.2 状态标签

| 标签 | 含义 |
|---|---|
| 已实现 | 有实际代码，并已接入产品调用链或已有直接 API/界面使用 |
| 部分实现 | 有实际代码，但只覆盖部分能力，或只在一个层面可用 |
| 只有设计/测试代码 | 设计文档中存在，或只有库级测试，没有进入实际产品链路 |
| 尚未实现 | 没有对应代码或数据能力 |
| 建议新增 | 本报告提出的架构设计，不代表已经确定需求或已经开发 |

### 0.3 核心结论摘要

1. 当前项目已经具备统一论证流程的“模型底座”和“真实仿真的执行底座”。
2. Evaluation 已经写成了独立评价库，但没有接入 API、没有接入前端，也没有进入实际实验链路。
3. Experiment、Candidate Scheme、Iteration、方案比较、推荐方案和报告导出均未实现。
4. 当前最需要补的不是仿真引擎，而是“方案—实验—迭代—比较—报告”的上层编排与追溯能力。
5. 故障生命周期机制目前是设计文档，不是已实现功能；它属于领域仿真能力，不应放进 Experiment Manager。
6. 现有 Process IR、Reliability IR、Runtime、Evaluation 的职责边界基本正确，应保留；需要新增的是上层论证管理层和少量精确版本读取能力。

---

## 1. 当前架构现状

### 1.1 模块清单与真实状态

| 模块 | 实际职责 | 状态 | 代码证据 | 说明 |
|---|---|---|---|---|
| Process IR | 描述业务流程结构：start/task/decision/end、边、条件、duration、status、effects、outcomes、guards、画布坐标 | 已实现 | `app/domain/process_ir.py:23-198`；`docs/process-ir.md:1-222` | 结构严格，`extra="forbid"`，可靠性字段被明确拒绝 |
| Process 校验 | 结构、条件、可达性、循环、duration、状态、效果等校验 | 已实现 | `app/domain/validation.py:361-793` | 保存前强制校验，错误和警告带定位信息 |
| Process 版本管理 | 版本追加、内容哈希、冲突检测、历史版本读取 | 已实现 | `app/processes/store.py:99-166` | 内容未变化不生成新版本；`base_version` 冲突返回 409 |
| Reliability IR | 每个 task 是否参与可靠性、指数分布 λ、单位 | 已实现 | `app/domain/reliability_ir.py:38-105` | 只支持指数分布；λ 可为 0；参与时必须配置 λ |
| Reliability 校验 | 校验节点类型、λ、Process 版本/hash 绑定、task 配置完整性 | 已实现 | `app/domain/reliability_validation.py:90-187` | 不执行仿真，不抽样 |
| Reliability 存储 | 独立 revision 追加、按 Process 版本/hash 精确绑定、历史保留 | 已实现 | `app/reliability/store.py:95-162` | 历史 revision 全部保留；新 Process 版本不会自动继承旧配置 |
| Reliability API | 读取、保存、校验、历史 | 已实现 | `app/api/reliability_routes.py:64-155` | 保存只允许绑定最新 Process 版本 |
| Study | 一次完整论证任务，管理共同目标和多个候选方案 | 尚未实现 | 无相关模块、Schema、API 或数据 | 本轮建议新增；不引入项目管理/权限 |
| Simulation Runtime | 真实离散事件仿真、多设备独立状态、事件历史、可靠性抽样、故障/维修 | 已实现 | `app/simulation/engine.py:125-176,639-698,700-761`；`app/simulation/models.py:30-82` | 有真实事件队列和随机流；不是 Mock |
| Simulation API | 从存储读取精确绑定的 Process/Reliability，执行仿真，返回原始结果 | 已实现 | `app/api/simulation_routes.py:41-87` | 结果为原始 JSON；不持久化；不调用 Evaluation |
| Evaluation 计算 | 整体/节点/设备指标、目标结果、警告、限制、解释文本 | 已实现（库级） | `app/evaluation/evaluator.py:320-846`；`app/evaluation/explanations.py:126-139` | 纯函数式评价；已有单元测试和 Runtime 集成测试 |
| Evaluation API/产品链路 | 将评价结果暴露给 API、前端或实验记录 | 尚未实现 | `app/main.py:45-47` 只注册三个 router；`app/api/` 没有 evaluation 路由 | 当前只有测试直接调用评价库 |
| Experiment 管理 | 保存一次实际仿真评估的输入、结果、评价和追溯关系 | 尚未实现 | `app/experiments/` 为空；`data/experiments/` 只有 `.gitkeep` | 没有 ExperimentStore、Experiment API、Experiment 数据 |
| Candidate Scheme | 命名、可比较、可追溯的完整候选方案 | 尚未实现 | 无相关模块、Schema、API 或数据 | 只有 Process 版本和 Reliability revision，不能等同于候选方案 |
| Iteration | 方案之间的派生关系和调整记录 | 尚未实现 | 无相关模块、Schema、API 或数据 | 迭代关系没有记录 |
| 方案比较/推荐/报告 | 对比评价指标、目标达成、推荐方案、导出报告 | 尚未实现 | 无相关模块、API 或前端 | 现有前端只导出 Process IR JSON |
| 前端流程建模 | 画布、节点/边编辑、Inspector、Agent 面板、版本、可靠性面板 | 已实现 | `frontend/src/App.jsx:511-839`；`Inspector.jsx:45-716`；`AgentPanel.jsx:34-141` | 三栏布局可用 |
| 前端仿真/评价/实验/比较/报告 | 仿真运行入口、评价结果、实验历史、对比、报告 | 尚未实现 | `frontend/src/api.js:40-90` 无仿真/评价/实验接口 | 仿真目前只能通过 HTTP API 使用 |
| Agent/LLM | 自然语言理解、需求澄清、工具调用 | 只有设计/命令模式 | `frontend/src/App.jsx:1038-1158` 是正则命令；`AgentPanel.jsx:34-46` 显示离线命令；`app/nlp/` 为空 | 还没有 LLM 客户端、Prompt、工具协议或对话状态管理 |
| 故障生命周期 | LATENT/DETECTED/REPAIRING 等统一生命周期 | 只有设计 | `docs/fault-lifecycle-technical-design.md:3` 明确 “design-only”；代码中没有 `latent`、`detection`、`fault_detected` 等实现 | 当前 Runtime 仍是“task 完成时抽样，故障后立即进入 failure 出口”的即时故障模式 |

### 1.2 当前真实调用链

#### 1.2.1 建模链路

```text
浏览器画布/Inspector/Agent
  -> frontend/src/api.js
  -> POST /api/processes/validate
  -> POST /api/processes 或 PUT /api/processes/{id}
  -> validate_process
  -> ProcessStore 追加 ProcessDocument
```

证据：

- 前端校验与保存：`frontend/src/App.jsx:597-621,789-839`。
- 校验 API：`app/api/process_routes.py:48-50`。
- 创建/更新：`app/api/process_routes.py:74-114`。
- 版本存储：`app/processes/store.py:99-149`。

#### 1.2.2 可靠性配置链路

```text
Inspector 可靠性标签页
  -> frontend/src/api.js:73-77 saveReliability
  -> PUT /api/processes/{id}/reliability
  -> validate_reliability
  -> ReliabilityStore 追加 revision
```

证据：

- 前端可靠性保存：`frontend/src/App.jsx:841-908`；`Inspector.jsx:131-159`。
- 保存 API 与绑定检查：`app/api/reliability_routes.py:132-155`。
- revision 存储：`app/reliability/store.py:95-130`。

#### 1.2.3 仿真链路

```text
外部 HTTP 调用
  -> POST /api/processes/{id}/simulate
  -> ProcessStore.get(process_id, version)
  -> ReliabilityStore.get(process_id, version, hash)
  -> SimulationConfig
  -> run_simulation
  -> SimulationResult 原始 JSON
```

证据：

- 仿真请求模型和绑定检查：`app/api/simulation_routes.py:24-69`。
- Runtime 入口：`app/simulation/engine.py:125-176`。
- 结果返回：`app/api/simulation_routes.py:87`。
- 结果结构：`app/simulation/models.py:66-82`。

关键事实：

- 仿真使用已保存的 `ProcessDocument` 和精确绑定的 `ReliabilityDocument`，不是草稿。
- 仿真结果是真实事件执行结果，有设备状态、事件历史、可靠性抽样、故障/维修记录。
- 仿真结果当前不保存到任何 Experiment 存储。
- 仿真 API 没有调用 `evaluate_simulation`。

#### 1.2.4 评价链路

```text
tests/ 或 Python 直接调用
  -> evaluate_simulation(process, reliability, result, targets)
  -> EvaluationResult
  -> build_explanation
```

证据：

- 评价主函数：`app/evaluation/evaluator.py:320-846`。
- 目标结果：`app/evaluation/evaluator.py:798-844`。
- 解释函数：`app/evaluation/explanations.py:126-139`。
- Runtime 集成测试：`tests/evaluation/test_evaluation_runtime_integration.py:14-33`。
- 目标状态测试：`tests/evaluation/test_evaluation_overall.py:240-310`。

关键事实：

- Evaluation 已经是独立、确定性、可测试的库。
- 它没有被 `app/main.py` 注册的路由引用，也没有被前端调用。
- 因此它目前是“只有库级代码和测试代码”，不是“已经进入产品流程”的功能。

### 1.3 存储现状

| 存储 | 文件/目录 | 现状 | 证据 |
|---|---|---|---|
| Process IR | `data/processes/{process_id}.json` | 已实现版本追加，保留历史 | `app/processes/store.py:84-114` |
| Reliability IR | `data/reliability/{process_id}.reliability.json` | 已实现 revision 追加，保留历史 | `app/reliability/store.py:80-130` |
| Experiment | `data/experiments/` | 尚未实现，只有 `.gitkeep` | 目录实际检查 |
| Scheme | 无 | 尚未实现 | 无对应目录/文件 |
| Iteration | 无 | 尚未实现 | 无对应目录/文件 |
| Report | 无 | 尚未实现 | 无对应目录/文件 |

### 1.4 测试验证现状

| 能力 | 测试状态 | 证据 | 说明 |
|---|---|---|---|
| Process IR/校验/版本 | 已测试 | `tests/test_process_ir.py`、`tests/test_validation.py`、`tests/test_store.py`、`tests/test_api.py` | 覆盖结构、版本、冲突、API |
| Reliability IR/绑定 | 已测试 | `tests/test_reliability_ir.py`、`tests/test_reliability_validation.py`、`tests/test_reliability_store.py`、`tests/test_reliability_api.py` | 覆盖 Schema、λ、绑定、revision、API |
| Runtime 真实执行 | 已测试 | `tests/test_simulation_runtime.py`、`tests/test_simulation_api.py` | 覆盖事件、随机流、故障、维修、部分暴露、复现 |
| Evaluation 计算 | 已测试 | `tests/evaluation/test_evaluation_overall.py`、`test_evaluation_nodes.py`、`test_evaluation_warnings_and_explanations.py` | 库级指标、目标、警告、解释 |
| Runtime + Evaluation 集成 | 只有库级测试 | `tests/evaluation/test_evaluation_runtime_integration.py:14-33` | 直接调用 `run_simulation` 和 `evaluate_simulation`，不经过 API |
| 仿真 + 评价 API 端到端 | 尚未测试 | 没有 evaluation 路由，因此没有对应 HTTP 测试 | 产品链路缺口 |
| Experiment/Scheme/Iteration | 尚未测试 | 没有对应模块 | 尚未实现 |
| 前端仿真/评价/比较/报告 | 尚未测试 | `frontend/tests/reliability.test.mjs` 只测试可靠性辅助逻辑 | 无前端仿真测试 |

### 1.5 文档与实现差异

| 文档表述 | 实际代码 | 结论 |
|---|---|---|
| `README.md:5,169` 说评价指标、实验比较尚未进入当前阶段/尚未实现 | 代码已有 `app/evaluation/` 和评价测试 | 文档滞后；评价是“库级已实现、产品未接入” |
| `docs/architecture.md:34,225` 说评价指标、实验比较尚未实现 | 同上 | 架构文档未更新 |
| `docs/requirements-analysis/requirements-analysis.md:218-224` 把实验保存、历史实验和比较列为 MVP/V1.1 | 代码没有 Experiment | 需求规划未实现 |
| `docs/fault-lifecycle-technical-design.md:3` 明确设计文档状态 | 当前 Runtime 仍是即时故障 | 不能把故障生命周期设计当作已实现 |
| `docs/fault-lifecycle-technical-design.md:1232,1402-1405` 说 Experiment Manager 未实现、Phase E 是未来 | `app/experiments/` 为空 | 与代码一致 |

---

## 2. 老板统一流程与当前项目的映射

### 2.1 总体映射表

| 统一流程环节 | 目标 | 当前项目对应能力 | 状态 | 证据 | 主要差距 |
|---|---|---|---|---|---|
| 指标建模 | 建立领域模型，定义参数、指标、约束 | Process IR、Reliability IR、校验、版本、绑定 | 部分实现 | `app/domain/process_ir.py:182-198`；`app/domain/reliability_ir.py:79-105`；`app/domain/validation.py:361-793`；`app/processes/store.py:99-166`；`app/reliability/store.py:95-162` | 评价指标、目标和约束没有建模位置；没有 Study、Candidate Scheme；自然语言建模只有命令 |
| 仿真评估 | 用真实模型执行仿真，得到量化结果并评价 | Runtime + Evaluation 库 | 部分实现 | `app/simulation/engine.py:125-176`；`app/api/simulation_routes.py:41-87`；`app/evaluation/evaluator.py:320-846` | Runtime 真实；Evaluation 未接入 API/前端；仿真结果不持久化 |
| 方案权衡与优化 | 多方案比较、参数调整、重新仿真、迭代、目标判断、推荐 | 只有 Process 版本和 Reliability revision 历史 + 手动 API 重跑 | 尚未实现 | `app/processes/store.py:151-166`；`app/reliability/store.py:152-162`；`app/experiments/` 为空；`data/experiments/.gitkeep` | 没有 Study、Candidate Scheme、Experiment、Iteration、比较、目标判定、DecisionRecord、推荐 |
| 结果查看与导出 | 展示指标、对比方案、推荐方案、评估报告 | 原始 SimulationResult JSON；Process IR JSON 导出；后端 SVG 接口 | 部分实现（仅原始输出） | `app/api/simulation_routes.py:87`；`app/simulation/models.py:66-82`；`frontend/src/App.jsx:1021-1032`；`app/api/process_routes.py:125-149` | 没有评价展示、方案对比、推荐方案、评估报告 |

### 2.2 指标建模阶段的映射

已实现：

- Process IR 能描述业务流程、分支、循环、持续时间、状态、效果和业务结果。
- Reliability IR 能描述 task 是否参与可靠性、指数分布 λ 和单位。
- 两者都有严格校验、内容哈希、版本/revision 和精确绑定。
- 前端能创建、编辑、校验、保存流程，并在 Inspector 中配置可靠性。

未实现/不足：

- 没有“评价计划”或“指标/目标/约束”的正式持久化位置。
- `EvaluationTargets` 只存在于 Python 模型和测试调用中，见 `app/evaluation/models.py:35-38`。
- 没有 Study 管理一次论证任务的共同目标和多个候选方案。
- 没有 Candidate Scheme 把“模型 + 可靠性参数 + 评价目标 + 仿真默认配置”组织成一个可比较方案。
- Agent 不是自然语言理解，只是规则命令，见 `frontend/src/App.jsx:1038-1158`。

### 2.3 仿真评估阶段的映射

已实现：

- Runtime 是真实离散事件仿真，不是 Mock。
- 使用 Process IR 的 duration、条件、effects、outcomes、status、guards。
- 使用 Reliability IR 的 λ 进行指数区间抽样。
- 有每设备独立随机流，见 `app/simulation/rng.py:18-24`。
- 结果包含设备级、可靠性抽样、事件历史、故障/维修计数，见 `app/simulation/models.py:30-82`。
- Evaluation 库能计算整体可靠性、结束可用性、节点指标、目标状态、警告和解释。

未实现/不足：

- Simulation API 只返回原始结果，不调用 Evaluation。
- 没有评价 API。
- 没有前端仿真/评价界面。
- 没有 Experiment 记录，无法追溯某次结果对应哪次运行。

### 2.4 方案权衡与优化阶段的映射

当前只有：

- Process 版本历史：`app/processes/store.py:151-166`。
- Reliability revision 历史：`app/reliability/store.py:152-162`。
- 可以修改参数后重新调用仿真 API。

这不等于方案权衡：

- Process 版本不是 Candidate Scheme；
- Reliability revision 不是 Candidate Scheme；
- 可以重复仿真不等于可以管理和比较方案；
- 没有实验记录、没有指标对比、没有目标判定、没有迭代关系、没有推荐。

### 2.5 结果查看与导出阶段的映射

当前有：

- 仿真 API 返回原始 JSON。
- 前端可以导出 Process IR JSON，见 `frontend/src/App.jsx:1021-1032`。
- 后端有 SVG 流程图接口，见 `app/api/process_routes.py:125-149`；但前端 `api.js` 未调用。
- Evaluation 有解释文本函数，见 `app/evaluation/explanations.py:126-139`；但没有展示链路。

当前没有：

- 评价指标展示；
- 方案对比；
- 推荐方案；
- 评估报告；
- 报告与模型版本/参数/结果的绑定导出。

---

## 3. 当前架构缺口

### 3.1 关键缺口列表

| 编号 | 缺口 | 状态 | 影响 | 证据 |
|---|---|---|---|---|
| G1 | Evaluation 未接入 API/前端 | 只有库/测试代码 | 用户无法在一次仿真后直接获得评价结果 | `app/main.py:45-47`；`app/api/` 无 evaluation 路由；`frontend/src/api.js:40-90` |
| G2 | SimulationResult 不持久化 | 尚未实现 | 无法追溯、无法比较、无法复现历史实验 | `app/api/simulation_routes.py:87`；`app/experiments/` 为空；`data/experiments/.gitkeep` |
| G3 | 没有 Candidate Scheme | 尚未实现 | 无法把模型+可靠性参数+目标组织成可比较方案 | 无相关代码/数据 |
| G4 | 没有 Experiment | 尚未实现 | 每次仿真只是临时响应，不是可管理实验 | `app/experiments/` 为空 |
| G5 | 没有 Iteration | 尚未实现 | 无法记录“从哪个方案调整到什么方案、为什么调整” | 无相关代码/数据 |
| G6 | 没有方案比较/推荐/报告 | 尚未实现 | 无法完成统一流程的后半段 | `docs/requirements-analysis/requirements-analysis.md:218-224` 仍是规划 |
| G7 | 同一 Process 版本只能读最新 Reliability revision | 部分实现/限制 | 无法方便地比较同一流程下不同 λ 方案 | `app/reliability/store.py:132-150` 返回最大 revision |
| G8 | 前端没有仿真、评价、实验、比较入口 | 尚未实现 | 产品用户无法完成闭环 | `frontend/src/api.js:40-90` 无相关接口；`App.jsx` 无仿真面板 |
| G9 | Agent 不是自然语言理解 | 部分实现/命令模式 | 用户仍需手工建模和按命令格式操作 | `frontend/src/App.jsx:1038-1158`；`AgentPanel.jsx:34-46`；`app/nlp/` 为空 |
| G10 | 故障生命周期尚未实现 | 只有设计 | 领域可靠性能力不完整，但不阻塞统一流程闭环 | `docs/fault-lifecycle-technical-design.md:3`；代码中无 latent/detection |
| G11 | 文档状态与代码不一致 | 部分实现/文档滞后 | 容易误判评价、实验能力已实现 | `README.md:169`；`docs/architecture.md:225`；对比 `app/evaluation/` |
| G12 | 没有 Study 统一管理共同目标/约束 | 尚未实现 | 多个方案缺少共同评价基准，难以严格比较 | 无相关代码/数据；本轮建议新增轻量 Study |

### 3.2 必须先解决的问题

在进入 Experiment/Scheme 阶段前，必须先解决：

1. Evaluation 的产品化接入：否则 Experiment 保存的只是原始仿真结果，不能形成“评估记录”。
2. 仿真结果的持久化边界：必须采用 metadata + artifact，保存完整 SimulationResult 和 EvaluationResult，不能只保存摘要。
3. 精确 Reliability revision 读取：Candidate Scheme 必须绑定精确 revision，不能依赖“最新 revision”。
4. Study 与评价目标/约束的归属：Study 定义共同目标，Scheme/Experiment 保存快照或精确版本，避免后续返工。
5. Candidate Scheme 的不可变规则：每次调整创建新 `scheme_id`，旧方案不可覆盖，必须记录 `parent_scheme_id`。
6. Runtime 语义版本：在积累实验数据前定义 `runtime_semantic_version`，并明确故障生命周期实施时点和新旧实验可比性策略。

### 3.3 不应误判的问题

以下问题不应被当作“统一流程必须先解决”的前置条件：

- 没有自动优化算法：不阻塞人工迭代闭环。
- 没有 LLM：可以用手工建模和规则 Agent 完成第一版闭环。
- 没有故障生命周期：这是领域仿真增强，不是 Experiment Manager 的职责，也不阻塞上层论证流程。
- 没有多用户、鉴权：不影响单用户本地论证闭环。

---

## 4. 总体分层架构

### 4.1 分层架构图

```text
┌──────────────────────────────────────────────────────────────┐
│ 1. 用户交互与 Agent 层                                        │
│    React 工作台、AgentPanel、建模画布、Inspector、结果面板     │
│    职责：展示、输入、对话、调用应用 API；不直接读写存储        │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP/JSON
┌──────────────────────────────▼───────────────────────────────┐
│ 2. 论证流程与方案迭代管理层（新增）                            │
│    Study / CandidateScheme / Experiment / Iteration           │
│    Comparison / Recommendation / DecisionRecord / Report      │
│    职责：组织、编排、持久化、追溯、比较、规则推荐              │
│    不负责：模型校验算法、仿真计算、评价公式                    │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
┌───────────────▼──────────────┐  ┌────────────▼────────────────┐
│ 3. 建模层                     │  │ 4. 仿真层                    │
│ Process IR                    │  │ Simulation Runtime           │
│ Reliability IR                │  │ 真实离散事件、随机流、事件    │
│ EvaluationPlan（建议新增）    │  │ 不负责方案/实验管理           │
│ 校验、版本、绑定              │  │                              │
└───────────────┬──────────────┘  └────────────┬────────────────┘
                │                              │
                │              ┌───────────────▼────────────────┐
                │              │ 5. 评价层                       │
                │              │ Evaluation                      │
                │              │ 指标、目标结果、警告、解释       │
                │              │ 不负责方案管理、不负责仿真       │
                │              └───────────────┬────────────────┘
                │                              │
┌───────────────▼──────────────────────────────▼────────────────┐
│ 6. 数据存储与版本追溯层                                        │
│ ProcessStore / ReliabilityStore / StudyStore / SchemeStore /   │
│ ExperimentStore / IterationStore / DecisionStore / ReportStore │
│ JSON 原子写入、版本/哈希、历史保留、引用完整性                 │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 各层职责与不负责事项

| 层 | 负责 | 不负责 | 当前模块 | 处理建议 |
|---|---|---|---|---|
| 1. 用户交互与 Agent | 展示工作台、收集输入、运行命令/对话、调用应用 API、展示结果 | 不做模型校验、不直接调用 Runtime、不直接读写 JSON 存储、不自己计算评价 | `frontend/src/App.jsx`、`AgentPanel.jsx`、`Inspector.jsx`、`Toolbar.jsx` | 保留并扩展；新增仿真/评价/方案/实验/报告面板 |
| 2. 论证流程与方案迭代管理 | 创建 Study、创建方案、运行实验、保存实验、记录迭代、比较多方案、规则推荐、记录最终决策、生成报告 | 不重写 Runtime、不接管 Evaluation 公式、不做模型语义校验 | 目前不存在 | 新增 `Study`、`CandidateScheme`、`Experiment`、`Iteration`、`Comparison`、`Recommendation`、`DecisionRecord`、`Report` 应用服务 |
| 3. 建模层 | 定义业务模型、可靠性参数、Study 评价目标/约束；校验、版本、绑定 | 不保存仿真结果；不做实验比较；不负责 UI 展示 | Process IR、Reliability IR、校验、版本、绑定 | 保留；Study 管理共同目标/约束，Scheme/Experiment 保存快照；不把目标和约束塞入 Process IR/Reliability IR |
| 4. 仿真层 | 基于已保存且精确绑定的模型执行真实仿真；产生事件、抽样、设备状态、故障/维修记录 | 不知道 Study/Candidate Scheme/Experiment 的概念；不负责持久化实验；不负责评价 | `app/simulation/` | 保留；未来故障生命周期只改仿真领域语义，不改 Experiment Manager |
| 5. 评价层 | 对 SimulationResult 计算指标、目标状态、警告、解释 | 不管理 Study/方案、不运行仿真、不决定推荐方案 | `app/evaluation/` | 保留并接入；新增比较/推荐服务时复用其指标，不重复实现 |
| 6. 存储与版本追溯 | 保存 Process 版本、Reliability revision、Study、Scheme、Experiment、Iteration、DecisionRecord、Report；保证原子写入和引用完整 | 不做业务判断；不把不同概念混在同一文件 | 现有 ProcessStore/ReliabilityStore；新增 Study/Scheme/Experiment/Iteration/Decision Store | 保留现有存储；新增独立存储；避免把 Experiment 结果塞进 Process/Reliability 文件 |

### 4.3 依赖规则

建议采用以下单向依赖：

```text
Frontend/Agent
  -> Application API（Study/Scheme/Experiment）
    -> Study/Scheme/Experiment/Iteration Service
      -> ProcessStore / ReliabilityStore / EvaluationPlan
      -> Simulation Runtime
      -> Evaluation
      -> StudyStore / SchemeStore / ExperimentStore / IterationStore
```

严格约束：

- Frontend/Agent 不直接调用 `ProcessStore`、`ReliabilityStore`、`SimulationRuntime` 或 `evaluate_simulation`。
- Experiment Manager 只负责编排，不包含仿真算法，不复制评价公式。
- Runtime 不引用 Scheme/Experiment，不读取 Experiment 存储。
- Evaluation 不引用 Scheme/Experiment，不读取 Scheme/Experiment 存储。
- Candidate Scheme 只引用精确版本，不引用“最新版本”。
- Experiment 保存“实际使用的输入快照 + 结果 + 评价”，不依赖未来可能变化的“最新”状态。
- Iteration 只记录方案之间的关系和变化，不保存仿真结果。

### 4.4 数据流

#### 创建 Study 与方案

```text
用户/Agent
  -> 创建/选择 Study
  -> Study 设置共同评价目标/约束（第一版仅现有两个目标）
  -> 在 Study 下选择已保存的 Process 版本
  -> 选择精确的 Reliability revision
  -> 保存创建时的目标快照/plan 版本
  -> 填写仿真默认配置和方案说明
  -> SchemeService 校验 Study 归属、绑定和完整性
  -> SchemeStore 保存不可变 CandidateScheme（新 scheme_id）
```

#### 运行实验

```text
用户/Agent
  -> 选择 Study 下的 CandidateScheme
  -> ExperimentService 读取 Scheme 绑定的精确 Process/Reliability/目标快照
  -> 校验内容哈希、revision 和 plan 版本
  -> 构造 SimulationConfig（方案默认值 + 本次覆盖）
  -> SimulationRuntime.run()
  -> evaluate_simulation()
  -> 保存 Experiment（输入快照、完整 SimulationResult、完整 EvaluationResult、解释、语义版本）
  -> 返回 ExperimentView
```

#### 比较与推荐

```text
用户选择若干 Experiment（每个方案一个或多次重复）
  -> ComparisonService 读取 EvaluationResult
  -> 生成指标矩阵、目标状态、差异、警告
  -> RecommendationService 按规则筛选/排序
  -> 用户确认推荐方案
  -> ReportService 生成报告
```

### 4.5 职责重复与边界不清的检查

| 潜在问题 | 当前判断 | 建议 |
|---|---|---|
| Process IR 与 Reliability IR 是否重复 | 不重复。Process IR 只描述业务流程，Reliability IR 只描述 task 可靠性参数 | 保持；不要把 λ、目标、实验配置写入 Process IR |
| Evaluation 是否应放进 Runtime | 不应。Runtime 产出事实，Evaluation 解释事实 | 保持分离；ExperimentService 编排两者 |
| Experiment Manager 是否应计算仿真 | 不应。它只负责加载输入、调用 Runtime、保存结果 | 禁止在 Experiment Manager 中复制事件推进或抽样逻辑 |
| Experiment Manager 是否应计算评价 | 不应。它只调用 Evaluation 并保存结果 | 禁止复制指标公式 |
| Study 是否是 Candidate Scheme | 不是。Study 是论证任务和共同目标容器 | 不要把方案内容、实验结果直接写进 Study |
| Candidate Scheme 是否是 Experiment | 不是。Scheme 是方案快照，Experiment 是一次运行 | 不要把运行时间、随机种子、结果写入 Scheme |
| Iteration 是否是 Experiment | 不是。Iteration 是方案间关系 | 不要把迭代关系混入 Experiment 列表 |
| DecisionRecord 是否是 Evaluation | 不是。DecisionRecord 是规则推荐后的用户最终确认 | 不要把最终决策写入 EvaluationResult |
| `app/analysis/` 与 `app/experiments/` 是否职责重叠 | 目前都为空目录，尚未形成实现 | 建议 `app/experiments/` 负责 Scheme/Experiment/Iteration 编排；`app/analysis/` 负责比较/推荐/报告或评价编排；最终以实际模块设计为准 |
| Agent 是否应成为唯一业务执行者 | 不应。Agent 只是交互助手 | Agent 通过应用 API/工具调用能力，不直接操作存储、Runtime 或 Evaluation |

## 5. Study、Candidate Scheme、Experiment、Iteration 的概念与职责

### 5.0 Study（论证任务）

#### 5.0.1 定位

Study 表示一次完整的论证任务。它把同一个问题下需要共同遵守的评价目标和约束组织在一起，并包含若干 Candidate Scheme。

它回答的问题是：

> “这次论证要解决什么问题？共同的评价目标是什么？有哪些候选方案参与比较？”

Study 不是 Candidate Scheme，不是 Experiment，也不是复杂的项目管理对象。第一版不引入成员、权限、审批流、任务看板等项目管理能力。

#### 5.0.2 是否引入轻量 Study

建议引入轻量 Study。

原因：

- 多个候选方案必须使用可比较的共同目标和约束；如果每个 Scheme 各自带一套目标，比较会失去统一基准；
- Study 可以作为“本次论证任务”的边界，方案、实验、比较和最终决策都归属于同一个 Study；
- 可以避免在每个 Scheme 中重复保存同一套目标；
- 后续报告需要以 Study 为单位组织“问题—目标—方案—实验—推荐结论”。

#### 5.0.3 第一版最小字段

以下为建议设计，不是当前已实现 Schema：

```json
{
  "study_id": "stu_0123456789ab",
  "name": "设备可靠性论证",
  "description": "比较不同 λ 配置下的整体可靠性与结束可用性",
  "evaluation_plan": {
    "schema_version": "evaluation-plan/1.0",
    "plan_version": 1,
    "plan_hash": "sha256:...",
    "targets": {
      "overall_reliability_min": 0.9,
      "end_availability_min": 0.95
    },
    "evaluation_config": {
      "small_sample_threshold": 30
    },
    "constraints": []
  },
  "created_at": "2026-11-20T12:00:00Z"
}
```

说明：`constraints` 是预留字段，第一版不实现具体约束计算；不得把它写成已支持能力。

第一版不包含：

- 成员、角色、权限；
- 审批流、任务分配；
- 复杂项目计划；
- 方案列表内嵌（方案通过 `study_id` 归属，查询获得）；
- 实验结果内嵌（实验通过 `scheme_id` 归属）。

#### 5.0.4 目标变化与历史兼容

- Study 定义当前共同的评价目标/约束；
- Scheme 创建时保存当时的 `evaluation_plan` 快照或精确 `plan_version/hash`；
- Experiment 保存实际使用的评价输入快照；
- Study 的目标后续变化时，不追溯修改旧 Scheme/Experiment；
- 比较不同 `plan_version` 的方案时，必须提示目标版本不一致，不能静默当作同一基准。

第一版只实现现有 Evaluation 已支持的两个目标（`overall_reliability_min`、`end_availability_min`）。约束字段可以预留，但不得写成已实现能力。

#### 5.0.5 与其他概念的关系

```text
Study 1 ──< Candidate Scheme 1..n
Candidate Scheme 1 ──< Experiment 1..n
Candidate Scheme 1 ──< Iteration（from/to，同一 Study 内）
```

- 一个 Study 包含多个 Candidate Scheme；
- 一个 Candidate Scheme 属于一个 Study；
- 一个 Candidate Scheme 可以有多个 Experiment；
- Iteration 连接同一 Study 内的两个 Scheme；
- 跨 Study 的方案比较需要显式说明目标是否兼容，第一版不建议支持。

### 5.1 Candidate Scheme（候选方案）

#### 5.1.1 定位

Candidate Scheme 是一个可参与论证和比较的完整方案快照，不是模型本身，也不是一次仿真运行。

它回答的问题是：

> “在当前论证任务中，我要比较的这个完整方案是什么？它使用哪个业务模型版本、哪组可靠性参数、什么评价目标和仿真默认配置？”

#### 5.1.2 是否应成为独立业务实体

建议成为独立业务实体。

原因：

- Process 版本和 Reliability revision 只是模型/参数历史，不是“方案”。
- 一个方案需要名称、说明、目标、约束、仿真默认配置和可比较的绑定关系。
- 后续方案比较、推荐、报告都需要稳定的 `scheme_id`。
- 不能把“方案版本管理”简单等同于 Process 版本管理或 Reliability revision 管理。

#### 5.1.3 建议最小字段

以下为建议设计，不是当前已实现 Schema：

```json
{
  "scheme_id": "sch_0123456789ab",
  "study_id": "stu_0123456789ab",
  "parent_scheme_id": null,
  "name": "基线方案",
  "description": "当前流程 + 基线 λ",
  "process_binding": {
    "process_id": "proc_...",
    "version": 3,
    "content_hash": "sha256:..."
  },
  "reliability_binding": {
    "reliability_id": "rel_...",
    "revision": 2,
    "process_version": 3,
    "process_hash": "sha256:...",
    "reliability_hash": "sha256:..."
  },
  "evaluation_plan_snapshot": {
    "source_study_id": "stu_0123456789ab",
    "schema_version": "evaluation-plan/1.0",
    "plan_version": 1,
    "plan_hash": "sha256:...",
    "targets": {
      "overall_reliability_min": 0.9,
      "end_availability_min": 0.95
    },
    "evaluation_config": {
      "small_sample_threshold": 30
    }
  },
  "simulation_defaults": {
    "entity_count": 100,
    "simulation_end": 30,
    "random_seed": 2026,
    "failure_policy": "require_failure_exit"
  },
  "metadata": {
    "tags": ["baseline"]
  },
  "created_at": "2026-11-20T12:00:00Z"
}
```

#### 5.1.4 绑定规则

Candidate Scheme 必须绑定：

- 所属 Study：`study_id`；
- 父方案（如由已有方案派生）：`parent_scheme_id`；
- 精确 Process 版本：`process_id + version + content_hash`；
- 精确 Reliability revision：`reliability_id + revision + process_version + process_hash`；
- 创建时的评价计划快照：`evaluation_plan_snapshot`，包含 `source_study_id`、`plan_version/plan_hash`、目标和评价配置；
- 仿真默认配置：设备数量、仿真结束时间、默认随机种子、故障策略。

不建议 Candidate Scheme 绑定：

- 一次具体的 SimulationResult（那属于 Experiment）；
- 一次具体的评价结果（那属于 Experiment）；
- 运行时间戳、运行状态（那属于 Experiment）；
- 可变的“最新 Process 版本”引用；
- 可变的“Study 当前目标”引用（必须保存创建时的目标快照或精确 plan 版本）。

#### 5.1.5 Scheme 不可变规则

本轮修订明确采用以下规则：

1. Candidate Scheme 是**不可变快照**；创建后不允许覆盖修改。
2. 每次调整参数（λ、duration、评价目标、仿真默认配置等）都必须创建新的 `scheme_id`。
3. 旧方案永久保留，不提供“更新旧方案内容”的写接口；只能创建新方案。
4. 新方案通过 `parent_scheme_id` 记录直接来源；如果没有来源则为 `null`。
5. 方案之间的调整关系由独立 Iteration 记录，不在 Scheme 内重复保存完整迭代历史。
6. 派生新方案时，复制源方案的精确绑定和目标快照，再应用变更；源方案不变化。
7. 不允许把“同一个 scheme_id 的不同修订”当作多个候选方案；候选方案以 `scheme_id` 为唯一身份。

这样可保证历史方案不会因后续模型修改、参数修改或 Study 目标变化而改变。

#### 5.1.6 Candidate Scheme 不应包含什么

- 不包含 SimulationResult；
- 不包含 EvaluationResult；
- 不包含 Runtime 事件；
- 不包含“推荐结论”；
- 不包含“最终决策”；
- 不包含“最新”引用；
- 不承担仿真计算；
- 不承担方案比较和推荐计算。

#### 5.1.7 EvaluationPlan 的归属

本轮修订建议采用：

- **Study** 定义共同评价目标和约束；
- **Candidate Scheme** 保存创建时所使用的目标快照或精确版本绑定；
- **Experiment** 保存实际使用的评价输入快照。

具体规则：

- Study 是共同目标的来源，但 Study 目标变化不追溯修改旧方案；
- Scheme 的 `evaluation_plan_snapshot` 必须足以独立解释该方案当时的评价基准；
- Experiment 必须保存实际传入 `evaluate_simulation` 的目标/配置快照，不能只引用当前 Study；
- 第一版只使用现有 Evaluation 已支持的两个目标；
- 约束字段可以预留，但在 Evaluation 正式实现前不得写成“已支持”；
- 不要把目标和约束写入 Process IR 或 Reliability IR。

### 5.2 Experiment（实验记录）

#### 5.2.1 定位

Experiment 是针对某个 Candidate Scheme 的一次实际仿真评估。它是一次运行事实，不是方案本身。

它回答的问题是：

> “在什么精确输入、什么随机种子、什么仿真配置下，实际运行了什么，得到了什么原始结果和评价结果？”

#### 5.2.2 建议保存的输入快照

```json
{
  "experiment_id": "exp_0123456789ab",
  "study_id": "stu_...",
  "scheme_id": "sch_...",
  "inputs": {
    "process_binding": {
      "process_id": "proc_...",
      "version": 3,
      "content_hash": "sha256:..."
    },
    "reliability_binding": {
      "reliability_id": "rel_...",
      "revision": 2,
      "process_version": 3,
      "process_hash": "sha256:...",
      "reliability_hash": "sha256:..."
    },
    "evaluation_plan_snapshot": {
      "source_study_id": "stu_...",
      "schema_version": "evaluation-plan/1.0",
      "plan_version": 1,
      "plan_hash": "sha256:...",
      "targets": {},
      "evaluation_config": {}
    },
    "simulation_config": {
      "entity_count": 100,
      "simulation_end": 30,
      "random_seed": 2026,
      "failure_policy": "require_failure_exit"
    }
  },
  "runtime_version": "0.3.0",
  "runtime_semantic_version": "immediate-failure/1.0",
  "evaluation_schema_version": "evaluation/1.0",
  "status": "completed",
  "started_at": "2026-11-20T12:00:00Z",
  "completed_at": "2026-11-20T12:00:01Z"
}
```

#### 5.2.3 必须保存的结果

Experiment 必须保存完整结果，不能只保存摘要：

- `SimulationResult`：完整设备结果、全量事件、可靠性抽样、计数、绑定信息；
- `EvaluationResult`：整体/节点/设备指标、目标结果、警告、限制；
- `explanation`：`build_explanation` 生成的解释文本，或保存生成所需的输入；
- `result_hash`：对结果规范化后的哈希，用于完整性校验；
- `runtime_semantic_version`：用于判断新旧实验是否可比；
- 失败实验的 `error`（如果决定保存失败记录）。

不能只保存整体指标摘要而丢失事件历史和可靠性抽样，否则无法重新解释、复核或迁移评价算法。

#### 5.2.4 存储形态

本轮修订明确采用 metadata + artifact：

```text
data/experiments/{experiment_id}/
  metadata.json      实验输入、绑定、状态、版本、结果哈希
  simulation.json    完整 SimulationResult
  evaluation.json    完整 EvaluationResult
  explanation.md     可选
```

规则：

- `metadata.json` 不替代完整仿真结果；
- `simulation.json` 必须包含完整事件和可靠性抽样；
- `evaluation.json` 必须保存当时的评价结果和评价 schema 版本；
- `explanation.md` 可选，但不能作为唯一结果；
- 不能只保存摘要或前端展示所需字段；
- 如结果体积过大，可以采用压缩/分片，但不得丢失事件和抽样。

#### 5.2.5 一次方案与多次实验

- 一个 Candidate Scheme 可以有多个 Experiment；
- 每个 Experiment 用 `experiment_id` 区分；
- 同一方案、同一配置、同一随机种子应产生可复现结果；
- 第一版比较时由用户显式选择代表实验；
- 同一方案的多随机种子聚合属于后续阶段，不在 Phase 6 强制实现。

#### 5.2.6 Experiment 不应包含什么

- 不应包含 Candidate Scheme 的完整定义（只保存输入快照和 `scheme_id`）；
- 不应成为方案的唯一版本记录；
- 不应承担比较和推荐职责；
- 不应包含“未来重算后”的可变评价结果；如评价公式升级，应保留旧结果并记录版本。

#### 5.2.7 快照与历史可追溯规则

本轮修订明确采用三层追溯：

1. **精确引用**：保存 `process_id/version/content_hash`、`reliability_id/revision/process_hash`；
2. **关键输入快照**：保存实际使用的评价目标/配置快照和仿真配置；
3. **完整结果持久化**：保存完整 SimulationResult 和 EvaluationResult。

目的：

- 底层模型、可靠性参数或评价算法升级后，旧 Experiment 仍能解释“当时用了什么、得到了什么”；
- 旧结果不因当前 Store 的“最新版本”或 Study 的“当前目标”而变化；
- 比较和报告可以追溯到具体版本和哈希；
- 新旧实验如果 Runtime 语义版本不同，必须显式提示不可直接比较。

### 5.3 Iteration（方案迭代关系）

#### 5.3.1 定位

Iteration 是方案之间的派生关系记录，不是一次实验，也不是方案本身。

它回答的问题是：

> “新方案是从哪个旧方案、基于哪次实验、调整了哪些参数而来的？为什么调整？”

#### 5.3.2 建议字段

```json
{
  "iteration_id": "itr_0123456789ab",
  "study_id": "stu_0123456789ab",
  "from_scheme_id": "sch_old",
  "to_scheme_id": "sch_new",
  "source_experiment_id": "exp_...",
  "change_type": "parameter_adjustment",
  "change_summary": "降低 inspection 节点 λ，观察整体可靠性变化",
  "parameter_diff": {
    "reliability.lambda.inspection": {
      "from": 0.02,
      "to": 0.01
    }
  },
  "rationale": "上一轮未达到整体可靠性目标",
  "created_at": "2026-11-20T12:00:00Z"
}
```

#### 5.3.3 迭代与实验的关系

- Iteration 连接同一 Study 内的两个 Candidate Scheme；
- 可选地指向触发调整的 Experiment；
- 新方案自己的 Experiment 记录仍属于 Experiment，不塞进 Iteration；
- 一个迭代可以有多个实验来验证新方案；
- “第几轮”可以由迭代链计算，不需要把轮次写死在一个混合对象中；
- Iteration 只追加，不修改已有方案或实验。

#### 5.3.4 推荐结论与最终决策的位置

推荐结论不建议放入 Iteration。建议：

1. 在比较/报告阶段生成推荐候选和理由；
2. Phase 7 增加独立 `DecisionRecord`，记录选中的方案、代表实验、规则版本、理由和最终用户确认；
3. 不要把“推荐方案”写成 Candidate Scheme 的字段；
4. 不要把“最终选择”混入 Experiment。

#### 5.3.5 DecisionRecord 最小结构

第一版建议最小字段：

```json
{
  "decision_id": "dec_0123456789ab",
  "study_id": "stu_...",
  "selected_scheme_id": "sch_...",
  "selected_experiment_ids": ["exp_..."],
  "compared_scheme_ids": ["sch_a", "sch_b"],
  "compared_experiment_ids": ["exp_a1", "exp_b1"],
  "evaluation_plan_snapshot": {
    "plan_version": 1,
    "plan_hash": "sha256:..."
  },
  "rule_version": "recommendation-rules/1.0",
  "recommendation": "recommended",
  "rationale": "满足两个目标，且整体可靠性最高；已提示小样本警告。",
  "warnings": ["small_sample"],
  "decided_by": "user",
  "decided_at": "2026-11-20T12:00:00Z"
}
```

要求：

- 记录用户最终确认，而不是只记录系统推荐；
- 记录依据的 Experiment ID；
- 记录评价计划版本/哈希和规则版本；
- 记录推荐理由和必须披露的警告；
- 不把 DecisionRecord 塞进 EvaluationResult 或 Candidate Scheme。

### 5.4 Evaluation、方案比较与推荐

#### 5.4.1 单次实验评价

直接复用现有：

- `evaluate_simulation(process, reliability, result, targets, evaluation_config)`；
- `EvaluationResult`；
- `build_explanation`。

不要重新实现指标公式，不要复制 `evaluator.py`。

#### 5.4.2 目标判定

当前已有：

- `EvaluationTargets.overall_reliability_min`；
- `EvaluationTargets.end_availability_min`；
- `TargetResult` 和 `target_status`。

证据：`app/evaluation/models.py:35-38,154-178`；`app/evaluation/evaluator.py:798-844`。

归属规则：

- Study 定义共同目标/约束；
- Scheme 保存创建时的目标快照或精确 plan 版本；
- Experiment 保存实际传入的评价输入快照；
- 第一版只复用现有两个目标；
- 约束（例如最大故障数、最大未修复数、成本等）目前没有实现，不应写成已支持；
- 如果不同 Scheme/Experiment 的目标版本不同，比较时必须提示不可直接比较。

#### 5.4.3 多方案比较

建议新增 ComparisonService，但只做“读取和呈现”，不重新计算评价公式：

输入：

- 同一 Study 下的一组 Experiment；
- 每个 Experiment 的 EvaluationResult；
- 对应 Candidate Scheme 的元数据；
- 评价计划/目标版本。

输出：

- 指标矩阵：整体可靠性、结束可用性、故障数、维修数、未完成数等；
- 目标达成矩阵；
- 节点级差异；
- 警告差异；
- 方案绑定信息；
- 可解释的差异摘要；
- 目标版本不一致、Runtime 语义版本不一致的警告。

比较选择规则：

- 第一版必须由用户在比较界面显式选择每个方案的代表 Experiment；
- 不允许静默选择“最新实验”作为默认代表；
- 多随机种子聚合、自动代表实验选择放到后续阶段；
- 如果选中的 Experiment 的 `runtime_semantic_version` 或评价计划版本不同，必须显式提示。

#### 5.4.4 初步规则化推荐

第一版可以做规则化推荐，不需要自动优化：

1. 过滤满足所有已配置目标的方案；
2. 若有多个，按主指标排序（例如 `overall_reliability`）；
3. 次指标排序（例如 `end_availability`）；
4. 再比较故障数/维修数/未完成数；
5. 输出“推荐/不推荐/证据不足”及理由；
6. 由用户最终确认。

推荐必须解释依据：

- 使用了哪些目标，实际值、目标值、差距；
- 比较了哪些 Experiment；
- 排序规则和规则版本；
- 有哪些警告（小样本、unknown 结束状态、Runtime 语义不一致等）；
- 如果没有任何方案满足目标，必须明确“没有满足目标的推荐方案”，不能强行推荐。

用户最终确认必须记录到 `DecisionRecord`；推荐结果本身不等于最终决策。

#### 5.4.5 比较与推荐的边界

- ComparisonService 读取 EvaluationResult，不重新计算指标；
- RecommendationService 读取比较结果，不重新运行仿真；
- 自动优化（参数扫描、搜索算法）不是第一版推荐的前置条件；
- 推荐规则必须可配置/可版本化，但第一版可以是固定规则；
- 不允许把推荐结果直接写成 Candidate Scheme 的字段。

### 5.5 概念关系与不混淆表

| 概念 | 是什么 | 不是什么 | 主要标识 | 存储 |
|---|---|---|---|---|
| Process 版本 | 某个业务流程模型的不可变版本 | 不是方案，不是实验 | `process_id + version + content_hash` | `data/processes` |
| Reliability revision | 某组可靠性参数的不可变修订 | 不是方案，不是实验 | `reliability_id + revision + process_version + process_hash` | `data/reliability` |
| Study | 一次完整论证任务，管理共同目标/约束和多个候选方案 | 不是方案，不是一次运行，不是项目管理系统 | `study_id` | 建议新增 `data/studies` |
| EvaluationPlan | Study 定义的目标/约束和评价配置；Scheme/Experiment 保存快照或精确版本 | 不是流程模型，不是仿真结果 | `plan_version/plan_hash` 或快照 | Study 内/建议新增 |
| Candidate Scheme | Study 下的完整候选方案快照：模型 + 参数 + 目标快照 + 仿真默认值 | 不是一次运行，不是结果；不可覆盖修改 | `scheme_id` | 新增 `data/schemes` |
| Experiment | 对某个方案的一次实际仿真评估 | 不是方案，不是模型版本 | `experiment_id` | 新增 `data/experiments` |
| Iteration | 同一 Study 内两个方案之间的派生/调整关系 | 不是实验，不是结果 | `iteration_id` | 新增 `data/iterations` |
| EvaluationResult | 对一次 SimulationResult 的评价结果 | 不是方案，不是实验记录本身 | 与 Experiment 绑定 | Experiment 内/评价 artifact |
| DecisionRecord | 规则推荐 + 用户最终确认的决策记录 | 不是 Evaluation 指标，不是 Candidate Scheme | `decision_id` | 新增/报告内 |

关系：

```text
Study 1 ──< Candidate Scheme 1..n
                 │
                 ├──< Experiment 1..n
                 │        └── EvaluationResult 1
                 │
                 └──< Iteration（from/to，同一 Study 内）

Process 版本 1 ──< Reliability revision 1..n
       ^                    ^
       └──── Scheme 精确绑定 ┘

Study 1 ──< DecisionRecord 1..n（用户最终确认）
```

---

## 6. 完整端到端业务流程

### 6.1 目标流程步骤

| 步骤 | 目标由谁负责 | 目标行为 | 当前状态 | 需要新增/修改 |
|---|---|---|---|---|
| 1. 用户提出建模需求 | 用户 + Agent | 用户用自然语言描述业务目标、流程、约束 | 部分实现：只能按固定命令或手工编辑 | LLM/Agent 工具层；当前 `app/nlp/` 为空 |
| 2. Agent 理解需求并协助建模 | Agent | 提取步骤、分支、循环、角色、约束；必要时澄清 | 只有设计/命令模式 | 自然语言理解、工具调用协议、对话状态 |
| 3. 用户检查、修改并确认模型 | 用户 + 前端 + Process IR | 在画布和 Inspector 中修改；校验后保存 | 已实现 | 保留现有画布/Inspector；可增加“确认”状态 |
| 4. 配置可靠性参数 | 用户 + 前端 + Reliability IR | 每个 task 设置参与和 λ；保存并绑定 | 已实现 | 保留；可能需要增加精确 revision 选择 |
| 5. 创建/选择 Study 并设置共同目标/约束 | 用户 + StudyService + EvaluationPlan | 创建论证任务，设置当前评价目标和评价配置；第一版只支持现有两个目标 | 尚未实现 | 新增 Study Schema/Store/API/UI；约束暂不实现 |
| 6. 在 Study 下创建候选方案 | 用户 + SchemeService | 绑定 Study、Process 版本、Reliability revision、目标快照、仿真默认配置，命名并保存 | 尚未实现 | 新增 CandidateScheme Schema/Store/API/UI |
| 7. 选择方案并发起仿真 | 用户 + 前端 + ExperimentService | 选择方案，确认/覆盖仿真配置和种子，发起实验 | 前端尚未实现；后端可裸调 `/simulate` | 新增 ExperimentService/API 和前端入口 |
| 8. Runtime 执行真实仿真 | Runtime | 基于精确绑定的模型执行离散事件仿真 | 已实现 | 保留；未来故障生命周期另行扩展 |
| 9. Evaluation 计算评价结果 | Evaluation | 计算整体/节点/设备指标、目标状态、警告、解释 | 库级已实现，产品未接入 | ExperimentService 调用；API/UI 展示 |
| 10. 保存 Experiment 记录 | ExperimentService/Store | 保存输入快照、SimulationResult、EvaluationResult、状态、时间、哈希 | 尚未实现 | 新增 ExperimentStore/API/数据目录 |
| 11. 查看和比较多个候选方案 | 用户 + ComparisonService | 选择实验，查看指标矩阵、目标状态、差异 | 尚未实现 | 新增比较服务/API/UI |
| 12. 用户调整参数并创建新方案 | 用户 + SchemeService + Iteration | 复制方案，修改 λ/duration/目标等，生成新方案和迭代记录 | 尚未实现 | 新增复制/派生 API、Iteration Store/UI |
| 13. 重新仿真并记录新一轮实验 | ExperimentService | 对新方案再次运行并保存实验 | 后端可裸调；无实验记录 | 复用 Phase 5 能力 |
| 14. 形成推荐方案并记录最终决策 | 用户 + RecommendationService + DecisionRecord | 规则筛选/排序，展示推荐及依据，用户确认后写入 DecisionRecord | 尚未实现 | 新增规则推荐和 DecisionRecord；不做自动优化 |
| 15. 查看和导出最终论证报告 | 用户 + ReportService | 生成报告，包含 Study、模型/参数/实验/评价/比较/推荐/最终决策和绑定信息，导出 | 尚未实现 | 新增 ReportService/API/UI |

### 6.2 人工与自动职责划分

| 角色 | 负责 |
|---|---|
| 用户 | 提出需求、确认模型、配置可靠性参数、设定目标、选择方案、决定推荐结果、导出报告 |
| Agent | 理解需求、辅助建模、解释结果、建议参数调整、调用应用 API；不替代用户最终决策 |
| 前端 | 展示、表单校验、调用 API、展示实验/比较/报告；不直接计算评价 |
| Process/Reliability 校验 | 结构、参数、绑定校验；不执行仿真 |
| Runtime | 真实仿真；不管理方案/实验 |
| Evaluation | 计算指标/目标状态/解释；不管理方案/实验 |
| ExperimentService | 编排仿真和评价，保存实验；不做仿真计算 |
| Comparison/Recommendation | 读取评价结果，生成对比和规则推荐；不重新实现评价公式 |
| ReportService | 组织报告内容和导出；不改变结果 |

### 6.3 最小人工闭环

即使没有自动优化，也应支持：

```text
创建 Study（共同目标/约束）
  -> 创建方案 A
  -> 运行实验 A1
  -> 查看评价 A1
  -> 复制 A 为 B，调整 λ（新 scheme_id，parent_scheme_id=A）
  -> 记录 Iteration A -> B
  -> 运行实验 B1
  -> 用户显式选择 A1/B1 进行比较
  -> 判断是否满足目标
  -> 不满足则继续迭代；满足则生成推荐并由用户确认
  -> 写入 DecisionRecord
  -> 导出报告
```

这条链路不依赖 LLM、不依赖自动优化，是第一阶段必须成立的闭环。

---

## 7. Evaluation 接入设计

### 7.1 当前状态

已实现：

- `evaluate_simulation` 纯函数，见 `app/evaluation/evaluator.py:320-846`；
- 整体指标、节点指标、设备指标、目标结果、警告、限制；
- `build_explanation`，见 `app/evaluation/explanations.py:126-139`；
- 目标状态逻辑，见 `app/evaluation/evaluator.py:307-317,798-844`；
- 单元测试和 Runtime 集成测试。

未实现：

- 没有 API 路由；
- 没有前端展示；
- 没有 Experiment 持久化；
- 没有目标配置的持久化入口；
- 没有方案比较。

### 7.2 接入原则

1. 不重写评价逻辑：直接调用 `evaluate_simulation`。
2. 不把评价塞进 Runtime：Runtime 只产出 SimulationResult。
3. 不把评价塞进 Process IR/Reliability IR：Study 定义共同目标/约束，Scheme 和 Experiment 保存目标快照或精确 plan 版本。
4. ExperimentService 负责编排：加载精确输入 -> 运行 -> 评价 -> 保存。
5. 保留原始仿真结果：评价结果不能替代 SimulationResult；两者都要可追溯。
6. 记录版本：保存 `evaluation_schema_version`、评价计划版本/哈希、`runtime_semantic_version`、Runtime 版本。

### 7.3 推荐调用链

```text
POST /api/schemes/{scheme_id}/experiments
  -> ExperimentService
      -> SchemeStore.get(scheme_id)
      -> StudyStore.get(scheme.study_id)（校验归属）
      -> ProcessStore.get(process_id, version)
      -> ReliabilityStore.get_exact(reliability_id, revision)
      -> 读取 Scheme.evaluation_plan_snapshot
      -> 校验 process_hash / reliability binding / plan snapshot
      -> SimulationConfig（方案默认 + 请求覆盖）
      -> run_simulation(process, reliability, config)
      -> evaluate_simulation(process, reliability, result, targets, evaluation_config)
      -> ExperimentStore.save(metadata + simulation artifact + evaluation artifact)
      -> 返回 ExperimentView
```

### 7.4 建议 API 草案

以下为建议设计，不是当前已实现接口：

| 方法 | 路径 | 作用 | 状态 |
|---|---|---|---|
| POST | `/api/studies` | 创建 Study | 建议新增，Phase 5 |
| GET | `/api/studies` | Study 列表 | 建议新增，Phase 5 |
| GET | `/api/studies/{study_id}` | Study 详情 | 建议新增，Phase 5 |
| POST | `/api/studies/{study_id}/schemes` | 在 Study 下创建 Candidate Scheme | 建议新增，Phase 5 |
| GET | `/api/studies/{study_id}/schemes` | Study 下的方案列表 | 建议新增，Phase 5 |
| GET | `/api/schemes/{scheme_id}` | 方案详情 | 建议新增，Phase 5 |
| POST | `/api/schemes/{scheme_id}/derive` | 复制方案并创建一个新方案 | 建议新增，Phase 5/6 |
| POST | `/api/schemes/{scheme_id}/experiments` | 运行一次实验并保存 | 建议新增，Phase 5 |
| GET | `/api/experiments` | 实验列表/筛选 | 建议新增，Phase 5 |
| GET | `/api/experiments/{experiment_id}` | 实验详情（含结果/评价） | 建议新增，Phase 5 |
| POST | `/api/comparisons` | 比较若干实验/方案 | 建议新增，Phase 6 |
| POST | `/api/iterations` | 记录方案迭代关系 | 建议新增，Phase 6 |
| GET | `/api/studies/{study_id}/iterations` | 查看迭代链 | 建议新增，Phase 6 |
| POST | `/api/recommendations` | 生成规则推荐 | 建议新增，Phase 7 |
| POST | `/api/decisions` | 记录用户最终决策 | 建议新增，Phase 7 |
| GET | `/api/experiments/{experiment_id}/report` | 导出报告 | 建议新增，Phase 7 |

兼容策略：

- 保留现有 `POST /api/processes/{id}/simulate` 作为低层原始仿真接口，不改变其语义；
- 新增实验编排接口，不把实验逻辑塞进旧仿真接口；
- Reliability 读取增加可选 `revision` 参数；不传时保持现有“最新 revision”行为，避免破坏兼容性。

### 7.5 目标与约束

当前已实现：

- `overall_reliability_min`；
- `end_availability_min`；
- `target_status`：`achieved / not_achieved / unevaluable / not_configured`。

目前未实现：

- 最大故障数、最大维修数、未修复数、成本、时间等约束；
- 多目标权重；
- 约束违反的解释；
- 自动优化目标函数。

建议：

- Study 定义共同评价目标和约束；
- Candidate Scheme 保存创建时的目标快照或精确 plan 版本；
- Experiment 保存实际使用的评价输入快照；
- 第一版只复用现有两个目标；
- 后续如需要更多约束，再扩展 EvaluationPlan 和 EvaluationTargets；
- 不要在 Process IR/Reliability IR 中加入这些字段；
- 不同目标版本的方案比较必须显式提示，不能静默混用。

### 7.6 评价结果持久化

Experiment 必须同时保存：

- `SimulationResult`（完整原始事实，包含事件和可靠性抽样）；
- `EvaluationResult`（评价结论）；
- `explanation` 或生成解释所需的输入；
- `evaluation_schema_version`；
- `runtime_semantic_version`；
- 实际使用的目标/评价配置快照；
- `result_hash`。

存储形式采用：

```text
data/experiments/{experiment_id}/
  metadata.json
  simulation.json
  evaluation.json
  explanation.md（可选）
```

原因：

- SimulationResult 是事实来源，不能只保存摘要；
- EvaluationResult 是当时评价逻辑的结果；
- 评价逻辑未来可能升级，旧实验必须保持原样，不能被静默重算；
- 报告需要追溯到具体版本；
- Runtime 语义版本不同时，新旧实验不能直接比较。

---

## 8. 前端信息架构

### 8.1 保留现有三栏布局

当前布局：

```text
App
  header
  workspace
    AgentPanel      左侧
    canvas-column   中间：Toolbar + ReactFlow + IssuesBar
    Inspector       右侧
```

证据：`frontend/src/App.jsx:1242-1374`。

建议保留：

- 左侧 `AgentPanel`；
- 中间画布和 `Toolbar`；
- 右侧 `Inspector`；
- React Flow 节点/边和自动布局；
- 现有流程库和版本历史。

不要为了统一流程推翻现有建模工作台。

### 8.2 四个主要工作区

建议在现有工作台上增加四个顶层工作区，而不是重写页面：

| 工作区 | 主要内容 | 主要复用 |
|---|---|---|
| 1. 指标建模 | Study 选择、画布、Agent、Inspector、流程校验、可靠性配置、Study 目标/评价配置 | 现有 `AgentPanel`、画布、`Inspector`、`Toolbar`；新增 Study 目标编辑 |
| 2. 仿真评估 | 选择 Study 下的方案、设置仿真配置、运行实验、展示评价指标/目标/警告/解释 | 新增 Scheme/Experiment 面板与评价摘要 |
| 3. 方案权衡与优化 | Study 下方案列表、实验历史、指标对比、迭代树、目标达成矩阵 | 新增 Comparison/Iteration 视图 |
| 4. 结果查看与导出 | 选择 Study/实验/方案、报告预览、导出 Markdown/JSON | 新增 Report 视图 |

建议以顶部导航或工作区切换器组织，不必立即引入前端路由；可以先用应用状态切换工作区。

建议在顶部提供全局 Study 选择器。Study 不是独立“项目管理”页面，第一版只需要创建、选择、查看名称/目标和方案数量，不引入成员、权限和审批流。

### 8.3 仿真运行入口和结果展示

建议放在“仿真评估”工作区：

- 顶部：当前 Study/方案选择器；
- 左侧：Agent + 方案列表 + 实验历史；
- 中间：
  - 方案绑定摘要（Process 版本、Reliability revision、评价目标）；
  - 仿真参数表单（entity_count、simulation_end、random_seed、failure_policy）；
  - “运行实验”按钮；
  - 运行状态；
  - 结果卡片：整体可靠性、结束可用性、故障数、维修数、目标状态；
  - 节点指标表；
  - 警告和限制；
  - 评价解释；
- 右侧 Inspector：显示当前方案/实验的详细绑定、评价详情或阶段信息。

运行后应自动保存 Experiment，并显示 `experiment_id`，而不是只显示一次性 JSON。

### 8.4 方案列表和方案对比

建议：

- 左侧增加“方案”区域，按当前 Study 分组：方案名称、绑定版本、最近实验、目标状态；
- 中间“方案权衡”工作区：
  - Study 下方案对比矩阵（行=方案，列=指标/目标状态）；
  - 选择 2-4 个方案进行详细差异；
  - 每个方案由用户显式选择代表实验（第一版不静默选最新，不做多随机种子聚合）；
  - 迭代树/链：显示方案从哪个方案派生、调整了什么；
  - 推荐候选和理由（Phase 7）。
- 右侧显示选中方案的绑定、实验、差异和警告。

当前 AgentPanel 已有“流程库”（`AgentPanel.jsx:103-138`），可扩展为“流程/方案/实验”分组，或新增独立折叠区；不应把方案列表塞进画布。

### 8.5 实验历史和迭代关系

实验历史建议：

- 按方案分组；
- 每条显示 `experiment_id`、时间、随机种子、仿真配置摘要、目标状态；
- 可打开详情查看完整结果/评价；
- 可标记“代表实验”或“推荐依据”。

迭代关系建议：

- 以方案为节点、Iteration 为边；
- 显示父方案、子方案、触发实验、变更摘要；
- 不把 Experiment 画成方案节点；
- 不把 Iteration 混入 Experiment 列表。

### 8.6 目标达成与推荐方案

建议：

- 在方案卡片和对比矩阵中显示每个目标的 `actual / target / gap / status`；
- 对 `unevaluable` 明确说明原因；
- 推荐方案单独显示，不作为 Evaluation 的字段；
- 推荐依据必须可展开：满足哪些目标、比较了哪些实验、有哪些警告、使用了什么规则版本；
- 用户最终确认，不由系统静默决定；
- 用户确认后写入 DecisionRecord，并在报告和方案历史中显示“最终决策”；
- 如果目标版本、Runtime 语义版本不一致，必须提示不可直接比较。

### 8.7 Agent 如何贯穿整个流程

建议 Agent 保持“助手”定位：

- 建模工作区：解释流程、添加/连接节点、建议结构、调用校验；
- 仿真评估：解释指标、指出小样本/未知状态、建议调整参数；
- 方案权衡：比较差异、总结权衡、建议下一个方案；
- 报告：生成报告叙述、解释推荐理由。

约束：

- Agent 只调用应用 API/工具，不直接读写存储；
- Agent 不直接调用 Runtime/Evaluation 内部函数；
- Agent 不替代用户最终选择；
- 当前阶段可以是离线命令；LLM 接入后再增强自然语言理解，不改变分层边界。

### 8.8 前端能力矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 流程建模、画布、Inspector | 已实现 | `App.jsx:1242-1374` |
| 流程校验、保存、版本 | 已实现 | `App.jsx:789-839` |
| 可靠性配置 | 已实现 | `App.jsx:841-908`；`Inspector.jsx:309-429` |
| 仿真运行 | 尚未实现 | 仅 HTTP API |
| 评价展示 | 尚未实现 | 评价库未接入 |
| 目标配置 | 尚未实现 | EvaluationTargets 仅库内/测试 |
| Candidate Scheme 管理 | 尚未实现 | 无 |
| Experiment 历史 | 尚未实现 | 无 |
| 方案比较 | 尚未实现 | 无 |
| 迭代关系 | 尚未实现 | 无 |
| 推荐方案 | 尚未实现 | 无 |
| 报告导出 | 尚未实现 | 仅 Process IR JSON 导出 |

## 9. 分阶段开发路线图

### 9.1 阶段顺序

本轮修订采用以下顺序：

1. **Phase 4B**：Evaluation 正式接入仿真流程。
2. **Phase 4C / Runtime 语义门**：Runtime 语义冻结及故障生命周期实施安排。
3. **Phase 5**：Study + Candidate Scheme + Experiment。
4. **Phase 6**：Iteration + Comparison。
5. **Phase 7**：Recommendation + DecisionRecord + Report。
6. **Phase 8（可选）**：参数扫描、敏感性分析、自动优化。
7. **独立轨道**：故障生命周期领域能力；其是否在 Phase 5 前实施，由 Phase 4C 的语义冻结决策确定。

顺序理由：

- 先让 Evaluation 在产品链路可用；
- 在正式积累实验数据前，必须冻结 Runtime 语义版本并明确故障生命周期是否改变仿真结果，否则新旧实验不可比；
- Study 是共同目标的载体，Scheme 和 Experiment 依附于 Study，应与 Experiment 持久化同期完成；
- Iteration 和 Comparison 依赖稳定的 Scheme/Experiment；
- Recommendation/DecisionRecord/Report 依赖比较结果；
- 自动优化放在最后，且不是人工闭环的前置条件。

### 9.2 Phase 4B：Evaluation 正式接入仿真流程

**开发目标**

让一次真实仿真可以立即得到评价结果，并可在前端看到；但不要求持久化实验。

**需要新增的模块**

- 评价编排服务（可以放在 `app/analysis/` 或新建 `app/application/`）。
- 评价 API 路由（例如 `app/api/analysis_routes.py`）。
- `EvaluationPlan` 的最小模型（目标 + evaluation config）；第一版可以先作为请求参数/方案快照。

**需要修改的现有模块**

- `app/main.py`：注册评价/分析路由。
- `app/api/simulation_routes.py`：保持原接口不变；新增分析入口或独立评价入口。
- `frontend/src/api.js`：增加仿真/评价调用。
- `frontend/src/App.jsx`：增加仿真评估工作区。
- `app/evaluation/__init__.py`：如需要，暴露服务调用；不改变评价公式。

**数据结构和 API 变化**

建议新增：

```text
POST /api/analysis/simulate-evaluate
或
POST /api/processes/{id}/simulate?include_evaluation=true
```

建议响应：

```json
{
  "simulation": { "...": "SimulationResult" },
  "evaluation": { "...": "EvaluationResult" },
  "explanation": "..."
}
```

建议请求包含：

- `process_version`；
- `reliability_revision`（可选，Phase 4B 可先不启用）；
- 仿真配置；
- 评价目标/评价配置。

**前端变化**

- 增加“仿真评估”工作区；
- 选择当前已保存流程/可靠性；
- 设置设备数、仿真结束时间、种子；
- 运行后展示 EvaluationResult 摘要、目标状态、警告、解释。

**依赖关系**

- 依赖 Phase 3 的真实 Runtime；
- 依赖现有 Evaluation 库；
- 不依赖 Candidate Scheme/Experiment。

**验收标准**

- API 能基于精确绑定的 Process/Reliability 运行真实仿真并返回 EvaluationResult；
- EvaluationResult 的 `process_binding` / `reliability_binding` 与实际输入一致；
- 目标状态正确显示；
- 前端能展示整体/节点指标、目标状态、警告和解释；
- 原 `/simulate` 行为不变；
- 不使用 Mock 数据；
- 有 API 测试和至少一条前端调用链验证。

**主要风险**

- 响应体过大（完整事件 + 评价）；
- 目标和评价配置没有持久化，刷新后丢失；
- 评价与仿真绑定校验必须严格，不能允许错误绑定静默通过。

### 9.3 Phase 4C：Runtime 语义冻结与故障生命周期实施安排

**开发目标**

在正式积累 Experiment 数据前，冻结 Runtime 的语义版本，并明确故障生命周期是否、何时改变仿真结果。该阶段是语义门，不是 Experiment Manager 功能开发。

**需要新增的模块**

- Runtime 语义版本标识（例如 `runtime_semantic_version`）；
- 语义冻结决策记录（可放在设计文档或配置中，但本次不修改其他设计文档）；
- 新旧实验可比性检查规则（在 Experiment/Comparison 设计中预留）。

**需要修改的现有模块**

- 本报告后续 Experiment Schema 设计：增加 `runtime_semantic_version`；
- ComparisonService 设计：当实验语义版本不同时提示不可直接比较；
- 不修改 Runtime 领域算法，除非用户另行批准实施故障生命周期。

**数据结构和 API 变化**

- Experiment metadata 必须保存 `runtime_semantic_version`；
- 不要求新增业务 API；可以只通过常量/配置/文档定义；
- 如果后续实施故障生命周期，必须升级语义版本，并禁止新旧实验静默混比。

**前端变化**

- 实验详情和比较界面显示 Runtime 语义版本；
- 语义版本不一致时显示警告。

**依赖关系**

- 依赖 Phase 4B；
- 阻塞 Phase 5 的 Experiment 持久化设计；
- 不依赖 Study/Scheme。

**验收标准**

- 明确当前 Runtime 语义版本；
- 明确故障生命周期在实验数据积累前是否实施；
- 明确新旧实验可比性策略；
- Experiment Schema 设计包含语义版本字段；
- 不把故障生命周期放进 Experiment Manager；
- 不把设计文档中的已确认领域决策重新列为待确认。

**主要风险**

- 如果先积累实验、后改变 Runtime 语义，旧实验将不可直接比较；
- 如果语义版本只写在文档中、没有进入 Experiment metadata，后续无法自动识别；
- 该阶段可能延迟 Phase 5，但比事后迁移实验数据成本低。

### 9.4 Phase 5：Study + Candidate Scheme + Experiment

**开发目标**

把“论证任务、完整方案、一次实际实验”变成可保存、可追溯、可复现的产品对象。

**需要新增的模块**

- `app/domain/study.py` 或等价模型；
- `app/domain/candidate_scheme.py` 或等价模型；
- `app/studies/store.py`；
- `app/schemes/store.py`；
- `app/experiments/store.py`；
- `app/application/study_service.py`；
- `app/application/scheme_service.py`；
- `app/application/experiment_service.py`；
- `app/api/study_routes.py`；
- `app/api/scheme_routes.py`；
- `app/api/experiment_routes.py`；
- `data/studies/`、`data/schemes/`、`data/experiments/` 数据目录。

**需要修改的现有模块**

- `app/reliability/store.py`：增加按 `reliability_id/revision` 精确读取的方法；
- `app/api/reliability_routes.py`：增加可选 `revision` 查询参数；
- `app/main.py`：注册 Study/Scheme/Experiment 路由；
- `frontend/src/api.js`：增加 Study/方案/实验接口；
- `frontend/src/App.jsx`：增加 Study 选择、方案创建、运行实验、实验历史。

**数据结构和 API 变化**

建议：

```text
POST /api/studies
GET  /api/studies
GET  /api/studies/{study_id}
POST /api/studies/{study_id}/schemes
GET  /api/studies/{study_id}/schemes
GET  /api/schemes/{scheme_id}
POST /api/schemes/{scheme_id}/derive
POST /api/schemes/{scheme_id}/experiments
GET  /api/experiments
GET  /api/experiments/{experiment_id}
```

Study 保存：

- `study_id`、名称、说明；
- 当前评价目标/配置快照或 plan 版本；
- 不内嵌方案列表、不内嵌实验结果。

Scheme 保存：

- `study_id`；
- `parent_scheme_id`；
- Process 精确绑定；
- Reliability 精确 revision；
- 创建时的目标快照或精确 plan 版本；
- 仿真默认配置；
- 名称、说明、标签。

Experiment 保存：

- `study_id`、`scheme_id`；
- 输入快照；
- 完整 SimulationResult（`simulation.json`）；
- 完整 EvaluationResult（`evaluation.json`）；
- 解释（可选 `explanation.md`）；
- 状态、时间、结果哈希；
- `runtime_version`、`runtime_semantic_version`、`evaluation_schema_version`。

**前端变化**

- 增加 Study 选择/创建；
- “指标建模”中增加“保存为候选方案”；
- “仿真评估”中选择 Study 下方案、运行实验；
- 实验历史列表；
- 显示实验 ID、绑定、目标状态、Runtime 语义版本；
- 支持用户显式选择代表实验。

**依赖关系**

- 依赖 Phase 4B 的评价接入；
- 依赖 Phase 4C 的 Runtime 语义版本；
- 依赖精确 Reliability revision 读取；
- 不依赖 Iteration/Comparison/Recommendation。

**验收标准**

- 能创建 Study，并设置当前两个评价目标；
- 能从 Study + 已保存 Process + Reliability + 目标创建 Candidate Scheme；
- Scheme 绑定精确版本/hash，不使用“最新”；
- Scheme 创建后不可覆盖修改；每次调整生成新 `scheme_id`；
- Scheme 记录 `parent_scheme_id`；
- 同一 Scheme 运行两次、相同随机种子，结果逐字段一致；
- Experiment 保存完整输入快照、完整 SimulationResult、完整 EvaluationResult；
- 重新加载 Experiment 能追溯准确输入和结果；
- 失败运行能记录错误（是否保存失败记录可按用户确认）；
- 有 Store/API/端到端测试；不使用 Mock。

**主要风险**

- Study/ Scheme/ Experiment 概念边界需要严格实现，避免混用；
- JSON 存储体积增长；
- 完整事件结果较大；
- Scheme/Experiment 不可变性需要强约束；
- 现有 Reliability “最新 revision”语义需要兼容扩展；
- 数据删除/引用完整性需要校验。

### 9.5 Phase 6：Iteration + Comparison

**开发目标**

让用户能够从旧方案派生新方案，记录调整，并在同一 Study 下比较多个方案。

**需要新增的模块**

- `app/domain/iteration.py`；
- `app/iterations/store.py`；
- `app/application/comparison_service.py`；
- `app/application/iteration_service.py`；
- `app/api/iteration_routes.py`；
- `app/api/comparison_routes.py`；
- 比较视图数据模型（可以是 API 返回的派生结构，不一定持久化）。

**需要修改的现有模块**

- Candidate Scheme：增加派生/复制 API（新 `scheme_id` + `parent_scheme_id`）；
- Experiment：增加按方案筛选、用户标记代表实验；
- 前端：增加“方案权衡与优化”工作区。

**数据结构和 API 变化**

建议：

```text
POST /api/schemes/{scheme_id}/derive
POST /api/iterations
GET  /api/studies/{study_id}/iterations
POST /api/comparisons
GET  /api/comparisons/{comparison_id}（如需要持久化对比快照）
```

ComparisonService 输入：

- study_id；
- experiment_ids 或 scheme_ids；
- 每个方案由用户显式选择的代表实验；
- 目标版本和 Runtime 语义版本。

输出：

- 指标矩阵；
- 目标矩阵；
- 差异；
- 警告；
- 解释。

第一版明确：

- 用户显式选择代表实验；
- 不静默选择最新实验；
- 不做多随机种子聚合；
- 目标版本或 Runtime 语义版本不一致时，必须提示不可直接比较。

**前端变化**

- 方案列表（按 Study 分组）；
- 方案对比表；
- 迭代树；
- 目标达成矩阵；
- 用户显式选择代表实验；
- 差异高亮和说明。

**依赖关系**

- 依赖 Phase 5 的 Study/Scheme/Experiment；
- 依赖 Phase 4B 的 Evaluation；
- 依赖 Phase 4C 的 Runtime 语义版本；
- 不依赖自动优化。

**验收标准**

- 用户可以从方案 A 派生方案 B，生成新的 `scheme_id` 和 `parent_scheme_id`；
- Iteration 记录父/子方案、源实验、变更摘要和参数差异；
- 可以比较至少两个方案/实验；
- 每个方案的代表实验由用户显式选择；
- 比较结果包含整体指标、节点指标、目标状态、警告；
- 比较不重新运行仿真；
- 用户可以判断是否满足目标；
- 旧方案和旧实验不被修改；
- 有 API/前端/存储测试。

**主要风险**

- 比较时“选择哪个实验”不明确会导致误导，必须由用户显式选择；
- 不同方案使用不同目标版本或 Runtime 语义版本时不可直接比较，需要提示；
- 当前指标维度有限，真正的权衡分析有限；
- 小样本、unknown 状态必须随比较展示。

### 9.6 Phase 7：Recommendation + DecisionRecord + Report

**开发目标**

形成最终论证输出：推荐方案、推荐理由、用户最终决策、完整报告和导出。

**需要新增的模块**

- `app/application/recommendation_service.py`；
- `app/application/decision_service.py`；
- `app/application/report_service.py`；
- `app/api/recommendation_routes.py`；
- `app/api/decision_routes.py`；
- `app/api/report_routes.py`；
- `DecisionRecord` 存储（建议独立，不要塞进 Scheme/Experiment）。

**需要修改的现有模块**

- 前端：增加“结果查看与导出”工作区；
- Study/方案/实验 API：增加报告所需聚合读取；
- 文档：报告 Schema 和导出格式。

**数据结构和 API 变化**

建议：

```text
POST /api/recommendations
POST /api/decisions
GET  /api/decisions/{decision_id}
GET  /api/experiments/{experiment_id}/report?format=md|json
GET  /api/schemes/{scheme_id}/report?format=md|json
GET  /api/studies/{study_id}/report?format=md|json
```

报告至少包含：

- Study 名称、说明、共同目标；
- 方案名称、说明、绑定；
- Process 版本/hash；
- Reliability revision/hash；
- 评价计划/目标快照；
- 仿真配置、随机种子；
- Experiment ID；
- SimulationResult 完整结果或 artifact 引用；
- EvaluationResult；
- 警告和限制；
- 多方案比较；
- 推荐方案和理由；
- 用户最终选择（DecisionRecord）。

**前端变化**

- 报告预览；
- 导出 Markdown/JSON；
- 显示推荐依据、规则版本和警告；
- 显示用户最终确认；
- 支持从 Study/方案/实验跳转到报告。

**依赖关系**

- 依赖 Phase 6 的比较；
- 依赖 Phase 5 的 Study/Scheme/Experiment；
- 不依赖自动优化。

**验收标准**

- 规则推荐只使用已保存实验和评价结果；
- 推荐明确说明“满足目标/不满足目标/证据不足”；
- 推荐理由包含目标、实验、规则版本和警告；
- 用户最终确认写入 DecisionRecord；
- 报告包含所有绑定 ID/hash，能够追溯到准确模型、参数和实验；
- 导出文件可读、结构稳定；
- 用户确认的推荐方案与报告一致；
- 不把自动优化作为前置条件；
- 有 API/报告内容测试。

**主要风险**

- 规则推荐可能过度简化；
- 小样本/unknown 状态可能被误读；
- 报告 Schema 后续变化需要版本化；
- 大结果报告导出体积；
- 推荐结果与用户最终决策不一致时必须保留差异说明。

### 9.7 Phase 8（可选）：参数扫描、敏感性和自动优化

**开发目标**

在人工闭环稳定后，增加效率工具。

**需要新增的模块**

- 参数扫描服务；
- 多随机种子批量实验；
- 敏感性分析；
- 可选优化器。

**约束**

- 不是 Phase 4B-7 的前置条件；
- 必须复用 ExperimentService；
- 优化器只能生成候选方案/实验，不能绕过 Evaluation 和 Experiment 记录；
- 不能把优化结果直接写成“已确认推荐”。

**验收标准**

- 批量实验可追溯；
- 参数扫描结果可比较；
- 优化建议有明确目标函数和约束；
- 不破坏已有实验记录。

### 9.8 独立轨道：故障生命周期

**当前状态**

- `docs/fault-lifecycle-technical-design.md:3` 明确是 design-only；
- 代码中没有 `latent`、`detection`、`fault_detected` 等实现；
- 当前 Runtime 在 task 完成时抽样，故障后立即进入 failure 出口（`app/simulation/engine.py:639-761`）。

**归属**

- 领域建模：可能在 Process IR 增加 task 检测能力；该领域设计文档已确认项不由本报告重新定义。
- 领域仿真：Runtime 增加 LATENT/DETECTED/REPAIRING 状态、检测事件、维修恢复、抽样抑制。
- 领域评价：Evaluation 增加 latent/detection/fault-free 等指标。
- 不属于 Experiment Manager；Experiment 只负责保存和追溯。

**已确认的架构边界**

- 故障生命周期属于领域 Runtime 能力，不属于 Experiment Manager；
- Experiment Manager 不应知道 LATENT/DETECTED/REPAIRING 的领域语义；
- 故障生命周期不应阻塞统一论证流程的上层闭环；
- 设计文档 `docs/fault-lifecycle-technical-design.md:24-50` 的已确认决策不再作为待确认项重复列出；
- 是否在 Phase 5 前实施故障生命周期，由 Phase 4C 的 Runtime 语义冻结决策确定。

**待确认**

- 同一个 `fault_id` 是否允许多次维修尝试；
- Runtime 语义版本号命名和新旧实验可比性策略（见 Phase 4C）。

**建议**

- 不要为了让上层流程“看起来完整”而把故障生命周期塞进 Experiment/Scheme；
- 不要让 Experiment Manager 知道 LATENT/DETECTED；
- 先完成 Phase 4B，并在 Phase 4C 明确 Runtime 语义和故障生命周期实施时点；上层 Phase 5-7 的人工论证闭环不要求故障生命周期先行；
- 实施时必须保留旧 Process/Reliability 数据的可读性，并记录 schema 版本；
- 如果实施故障生命周期，必须升级 Runtime 语义版本，并禁止新旧实验静默混比。

---

## 10. 各阶段验收标准汇总

| 阶段 | 核心验收标准 | 不允许的替代 |
|---|---|---|
| Phase 4B | 仿真 API 返回真实 EvaluationResult；目标状态正确；前端可见；绑定一致 | 用 Mock 指标或前端假数据 |
| Phase 4C | Runtime 语义版本明确；故障生命周期实施时点明确；Experiment metadata 设计包含语义版本；新旧实验不可比时有提示策略 | 未定义语义版本就开始积累实验；把故障生命周期塞进 Experiment Manager |
| Phase 5 | Study 可创建并管理共同目标；Scheme 不可变、精确绑定；Experiment 可保存完整结果；同种子可复现 | 用“最新”替代精确版本；只保存摘要丢失事件/抽样；覆盖修改旧 Scheme |
| Phase 6 | 可派生方案；Iteration 记录变更；用户显式选择代表实验；可比较多个方案；不重跑仿真 | 用“重复运行”冒充方案比较；静默选最新实验；多随机种子聚合冒充第一版能力 |
| Phase 7 | 规则推荐可解释；用户最终确认写入 DecisionRecord；报告包含完整绑定；可导出 | 自动优化冒充人工闭环；报告缺少版本/哈希；推荐结果替代用户决策 |
| Phase 8（可选） | 批量实验可追溯；优化建议不绕过评价与实验 | 直接生成“推荐”而不留实验记录 |

---

## 11. 兼容性与数据迁移风险

### 11.1 兼容性

| 项目 | 风险/策略 |
|---|---|
| Process IR | 不改现有 Schema 即可完成 Phase 4B-7；新增 Study/Scheme/Experiment 不写入 Process IR |
| Reliability IR | 需要增加按精确 revision 读取的能力；保留现有“不传 revision 取最新”的行为 |
| Process 版本 | 现有版本和 hash 继续有效；Scheme 绑定精确版本/hash |
| Reliability revision | 现有 revision 继续有效；Scheme/Experiment 绑定精确 revision |
| Study | 新增独立存储；Study 目标变化不追溯修改旧 Scheme/Experiment |
| Candidate Scheme | 不可变；每次调整创建新 `scheme_id`；保存 `parent_scheme_id` 和目标快照 |
| Experiment | 保存精确引用 + 关键输入快照 + 完整 SimulationResult/EvaluationResult artifact |
| Runtime 语义 | Experiment 必须保存 `runtime_semantic_version`；新旧语义实验不可静默比较 |
| Evaluation | 复用现有 EvaluationResult；新增 Experiment 包装，不改评价公式；未来评价 schema 升级需保存版本 |
| Simulation API | 保留 `/simulate` 原始语义；新增实验编排 API，避免破坏现有测试和调用 |
| 前端 | 保留现有三栏和建模功能；新增工作区是增量 |
| 历史实验 | 当前没有持久化实验，因此没有可迁移的历史实验；未来从 Phase 5 开始积累 |
| 故障生命周期 | 未来可能修改 Process IR/Runtime/Evaluation；必须保留旧 hash/旧数据读取，属于独立设计轨道 |

### 11.2 数据迁移风险

1. 没有历史 Experiment 可迁移：当前 `data/experiments/` 为空，不需要伪造历史数据。
2. Reliability 精确 revision：现有 API 只按 Process 版本取最新 revision；Scheme 需要精确 revision，必须新增读取方法/参数，不能依赖“最新”。
3. Scheme/Experiment 引用完整性：如果 Process/Reliability 文件被删除，Scheme 引用会失效；需要加载时校验，或保存关键输入快照。
4. 结果体积：完整 SimulationResult 可能很大；建议元数据与结果 artifact 分离，必要时压缩/归档。
5. 并发写入：现有 Store 使用进程内锁和原子替换；新增 Experiment/Scheme Store 应沿用相同策略。
6. JSON 本地存储上限：方案/实验数量增长后，单文件/目录扫描会变慢；第一版可以接受，后续可迁移 SQLite。
7. 评价 schema 升级：旧 Experiment 必须保留旧 EvaluationResult 和 schema 版本，不能静默重算覆盖。
8. 前端构建产物：修改前端后必须重新构建 `web/`；当前 `web/` 与源码状态需要重新同步。
9. 文档滞后：README/architecture 仍称评价未实现；需要在新阶段完成后更新，但本次不修改文档（除本文件）。
10. 无 Git 提交：当前仓库没有提交历史，所有文件为 untracked；开发阶段需要建立版本管理，否则实验记录之外的代码变更不可追溯。
11. Runtime 语义变化：如果故障生命周期在 Experiment 积累后实施，旧实验不能与新实验直接比较；必须在 Phase 4C 定义语义版本和比较策略。
12. Study 目标变化：Study 当前目标变化后，旧 Scheme/Experiment 仍使用旧快照；比较和报告必须显示目标版本差异，不能静默当作同一基准。

---

## 12. 决策状态

本节区分：已确认决策、建议采纳但待确认的决策、仍待确认的决策。

### 12.1 已确认决策（本轮修订）

| 编号 | 决策 | 确认内容 |
|---|---|---|
| D2 | Scheme 不可变规则 | 每次调整参数创建新的 `scheme_id`；旧方案不允许覆盖修改；新方案记录 `parent_scheme_id`；方案间通过 Iteration 记录调整关系 |
| D3 | Scheme/Experiment 快照策略 | 采用精确引用 + 关键输入快照 + 完整仿真结果和评价结果持久化 |
| D4 | SimulationResult 存储 | 采用 metadata + artifact：`metadata.json`、`simulation.json`、`evaluation.json`、可选 `explanation.md`；不能只保存摘要而丢失完整事件和可靠性抽样 |
| D6 | 比较时的代表实验 | 第一版由用户显式选择代表实验；不做静默选择；多随机种子聚合放到后续阶段 |
| D7 | 推荐与最终决策 | 规则推荐必须解释依据；用户最终确认必须写入 DecisionRecord；推荐结果不等于最终决策 |
| D8 | 开发路线图 | 按 Phase 4B、Phase 4C Runtime 语义门、Phase 5 Study+Scheme+Experiment、Phase 6 Iteration+Comparison、Phase 7 Recommendation+DecisionRecord+Report、Phase 8 可选自动优化 |
| D13 | 故障生命周期归属 | 故障生命周期属于领域 Runtime 能力，不属于 Experiment Manager；不阻塞上层论证闭环 |

### 12.2 建议采纳、仍需确认的决策

| 编号 | 决策 | 建议 | 是否阻塞 |
|---|---|---|---|
| D1 | 是否引入轻量 Study | 建议引入；Study 管理共同目标/约束和多个候选方案，不引入项目管理、成员、权限、审批流 | 阻塞 Phase 5 |
| D5 | 评价目标/约束归属 | 建议 Study 定义共同目标/约束；Scheme 保存创建时快照或精确 plan 版本；Experiment 保存实际评价输入快照 | 阻塞 Phase 5 |
| D9 | 前端是否采用四个工作区 | 建议采用四工作区，同时保留现有三栏作为“指标建模”工作区 | 不阻塞 |
| D10 | Reliability 精确 revision API | 建议新增可选 `revision` 查询参数，保留现有“不传取最新”行为 | 阻塞 Phase 5 |
| D11 | EvaluationPlan 在 Phase 4B 的形态 | 建议先作为请求参数/方案快照，Phase 5 再持久化 Study/方案快照 | 不阻塞 |
| D12 | 失败实验是否保存 | 建议保存失败记录或至少错误摘要，便于追溯 | 不阻塞 |
| D15 | 多用户/鉴权/并发 | 当前继续单用户本地；Experiment 阶段至少保持原子写入 | 不阻塞 |
| D18 | DecisionRecord 是否独立持久化 | 建议独立存储，不塞进 Scheme/Experiment/EvaluationResult | 不阻塞 |

### 12.3 仍待确认的决策

| 编号 | 决策 | 说明 | 是否阻塞 |
|---|---|---|---|
| D14 | 同一个 `fault_id` 是否允许多次维修尝试 | 这是故障生命周期中仍需确认的领域问题；不再把设计文档已确认事项重复列为待确认 | 阻塞故障生命周期领域实施 |
| D16 | Runtime 语义版本和新旧实验可比性策略 | 在开始正式积累实验数据前，必须定义 `runtime_semantic_version`、版本升级规则和不可比提示策略 | 阻塞 Phase 5 |
| D17 | Study 目标变化策略 | Study 目标变化时，是创建新 plan 版本、新 Study，还是只影响新 Scheme；旧 Scheme/Experiment 必须保留快照 | 阻塞 Phase 5/6 |

### 12.4 故障生命周期：已确认的领域决策

以下来自 `docs/fault-lifecycle-technical-design.md:24-50`，本报告不重新定义，也不把它们列为待确认：

- 只采用统一故障生命周期；
- 潜在故障不立即中断业务执行；
- 只有显式配置检测能力的节点可以发现故障；
- 检测节点仍执行完整配置时长；
- 检测节点的完成效果先于故障路由；
- 检测到故障后，failure 边优先于 normal/conditional 路由；
- 故障确认后停止后续可靠性暴露和抽样；
- 实际业务停留时间继续累计；
- 业务结束可用性与无故障结束可用性分开；
- 检测节点必须有 failure 出口；
- 潜在故障发生节点不要求 failure 出口；
- 第一版无法确定精确物理故障时刻，只能表示抽样区间；
- 检测节点可以直接检测自身完成时抽样确认的新故障。

本报告只保留一个领域待确认项：同一个 `fault_id` 是否允许多次维修尝试（D14）。

---

## 13. 结论

### 13.1 当前项目是否可以继续演进为统一论证流程产品

可以。

现有架构已经具备：

- 严格的 Process IR/Reliability IR 建模；
- 真实、可复现的离散事件仿真；
- 独立的 Evaluation 评价库；
- 版本、哈希、绑定和测试基础。

不需要推翻现有架构。需要新增的是一个上层论证与实验管理层，把已有能力组织成：

```text
Study
  -> Candidate Scheme（不可变）
    -> Experiment（完整结果持久化）
      -> EvaluationResult
  -> Iteration（方案派生关系）
  -> Comparison（用户显式选代表实验）
  -> DecisionRecord（规则推荐 + 用户最终确认）
  -> Report
```

### 13.2 最重要的架构判断

1. Process IR 只放业务流程语义，Reliability IR 只放可靠性参数；Study 定义共同评价目标/约束，Scheme/Experiment 保存目标快照。
2. Study 是论证任务，Candidate Scheme 是方案，Experiment 是运行，Iteration 是关系，DecisionRecord 是用户最终决策；不能合并。
3. Scheme 不可变：每次调整创建新 `scheme_id`，旧方案不覆盖，新方案记录 `parent_scheme_id`。
4. Experiment 必须保存精确引用、关键输入快照、完整 SimulationResult 和 EvaluationResult；不能只保存摘要。
5. Experiment Manager 只编排，不重写 Runtime，不接管 Evaluation。
6. Evaluation 必须接入产品链路，但不能把评价公式复制到 Experiment Manager。
7. 故障生命周期属于领域 Runtime/Evaluation 能力，不属于 Experiment Manager；当前仍是设计阶段，不能当作已实现。
8. 第一版允许人工迭代、用户显式选代表实验和规则推荐，不要求自动优化。

### 13.3 推荐开发顺序

```text
Phase 4B：Evaluation 接入
  -> Phase 4C：Runtime 语义冻结及故障生命周期实施安排
  -> Phase 5：Study + Candidate Scheme + Experiment
  -> Phase 6：Iteration + Comparison
  -> Phase 7：Recommendation + DecisionRecord + Report
  -> Phase 8（可选）：参数扫描/敏感性/自动优化

独立轨道：故障生命周期（领域能力，非上层实验管理）
```

该顺序的核心原则是：

- 先让评价可用；
- 在积累实验数据前冻结 Runtime 语义，明确故障生命周期是否改变结果；
- 再让 Study、方案和实验可追溯、可复现；
- 再做可比较、可迭代；
- 最后做推荐、最终决策和报告；
- 自动优化放在最后，且不是人工闭环的前置条件。



