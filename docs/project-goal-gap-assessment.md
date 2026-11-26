# reliability-flow-agent 项目目标差距审查报告

> 文档性质：只读现状审查，不包含任何功能开发或架构决策的最终裁定。
> 审查日期：2026-11-25
> 审查对象：`C:\Users\woain\Desktop\reliability-flow-agent`
> 本次边界：未修改任何现有代码、Schema、API、前端、配置、测试或业务数据；只新增本文件。
> 目标参照：用户给出的“基于 Agent 的装备指标论证辅助软件”最终目标，以及仓库内 `docs/unified-argumentation-architecture.md` 中的阶段设计。

---

## 第一章 审查范围与方法

### 1.1 实际检查范围

本次逐项阅读并交叉核对了以下内容。

| 范围 | 实际检查对象 |
|---|---|
| 项目结构 | 根目录、`app/`、`frontend/`、`web/`、`data/`、`tests/`、`docs/`、`examples/` |
| 后端入口与路由 | `app/main.py`、`app/api/process_routes.py`、`app/api/reliability_routes.py`、`app/api/simulation_routes.py`、`app/api/evaluation_routes.py`、`app/api/deps.py` |
| 领域模型 | `app/domain/process_ir.py`、`app/domain/reliability_ir.py`、`app/domain/validation.py`、`app/domain/reliability_validation.py`、`app/domain/versioning.py` |
| 存储 | `app/processes/store.py`、`app/reliability/store.py`、`data/` 实际文件 |
| 仿真 | `app/simulation/engine.py`、`models.py`、`config.py`、`rng.py`、`errors.py` |
| 评价 | `app/evaluation/models.py`、`evaluator.py`、`explanations.py`、`app/analysis/service.py` |
| 前端 | `frontend/src/App.jsx`、`api.js`、`simulation.js`、`reliability.js`、`components/AgentPanel.jsx`、`Inspector.jsx`、`SimulationPanel.jsx`、`Toolbar.jsx`、`flow/`、`web/` 构建产物 |
| 测试 | `tests/` 全部文件、`frontend/tests/` |
| 文档 | `README.md`、`docs/architecture.md`、`docs/process-ir.md`、`docs/reliability-ir.md`、`docs/simulation-runtime.md`、`docs/phase-1/2/3-report.md`、`docs/phase-3-review.md`、`docs/fault-lifecycle-technical-design.md`、`docs/unified-argumentation-architecture.md`、`docs/requirements-analysis/` |
| 外部集成 | 全仓库检索 `Pi`、`Pi Web`、`Riffoid`、`Harness`、`plugin`、MCP、工具调用协议、LLM 客户端 |
| 工程状态 | `.git`、`.gitignore`、`pyproject.toml`、`requirements.txt`、`frontend/package.json`、`.env.example` |
| 桌面打包 | 全仓库检索 Electron、Tauri、PyInstaller、Nuitka、pywebview、installer、安装包 |

### 1.2 证据分级

本报告把结论来源分为四类，正文中尽量标明：

| 等级 | 含义 | 本报告中的例子 |
|---|---|---|
| 代码证据 | 在仓库源码中直接看到实现 | `SimulationRuntime.run` 在 `app/simulation/engine.py:125` |
| 测试证据 | 存在自动化测试覆盖，且本次实际运行通过 | 后端 176 passed、前端 16 passed |
| 运行证据 | 本次实际启动服务、调用接口或执行仿真并观察到输出 | 本次仅执行测试套件；未手工启动服务、未写入业务数据 |
| 架构推断 | 基于代码结构和接口做出的判断，不是直接观测 | “需要新增 Harness 适配层”属于推断 |

### 1.3 本次实际执行的验证

| 验证 | 命令 | 结果 | 是否写入项目业务数据 |
|---|---|---|---|
| 后端测试 | `.venv\Scripts\python.exe -m pytest -p no:cacheprovider` | **176 passed in 3.74s**（退出码 0） | 否。测试使用 `tmp_path`，`data/` 仍只有三个 `.gitkeep` |
| 前端测试 | `npm test`（工作目录 `frontend`） | **16 passed，0 failed** | 否，纯 Node 单元测试 |
| 测试缓存 | 使用 `-p no:cacheprovider` | 未写入 `.pytest_cache` | — |
| Git 检查 | `git log --oneline`、`git status --short` | 仓库无任何提交；所有文件为 untracked | — |
| 构建产物检查 | 检查 `web/assets/index-CSXR49Y1.js` | 包含 `simulate/evaluate` 和“仿真评估” | — |

未执行：未启动 uvicorn，未手工创建 Study/Scheme/Experiment，未运行任何会写入 `data/` 的接口。

### 1.4 无法从本仓库验证的部分

以下内容在本仓库中没有任何实现或接口痕迹，因此**不能判断为“已具备”**，只能列为待外部确认：

- Pi 是否可以作为独立后台 Agent 运行引擎启动。
- Pi 是否提供可被外部程序调用的 headless/session/HTTP/JSON-RPC 接口。
- Pi Web 与 Pi 的通信协议。
- Riffoid IR 插件是否可以在 Pi Web 之外被调用。
- IR 插件工具的输入/输出 Schema、版本、错误模型。
- IR 插件与本项目 Process IR / Reliability IR 的语义是否一致。

---

## 第二章 当前项目实际架构

### 2.1 实际目录与模块

```text
reliability-flow-agent/
  app/
    main.py                 FastAPI 应用装配、静态前端托管、异常处理
    config.py               Settings（phase=4B, version=0.3.0, LLM 配置占位）
    api/
      process_routes.py     流程校验、预览、CRUD、版本、SVG
      reliability_routes.py 可靠性配置读取/校验/保存/历史
      simulation_routes.py  原始仿真接口
      evaluation_routes.py  仿真 + 评价 + 解释接口
      deps.py               Store 依赖注入
    domain/
      process_ir.py         Process IR Pydantic Schema
      reliability_ir.py     Reliability IR Pydantic Schema
      validation.py         Process 结构/条件/可达性/循环校验
      reliability_validation.py 可靠性参数与绑定校验
      versioning.py         规范化内容哈希
    processes/store.py      版本化 Process JSON 存储
    reliability/store.py    revision 化 Reliability JSON 存储
    simulation/
      engine.py             真实离散事件 Runtime
      models.py             事件、抽样、实体结果、仿真结果
      config.py             仿真配置与安全上限
      rng.py                独立随机流
      errors.py             仿真错误类型
    evaluation/
      models.py             EvaluationResult / 目标 / 警告
      evaluator.py          指标、目标判定、警告
      explanations.py       确定性解释文本
    analysis/service.py     仿真 + 评价编排
    experiments/            空目录
    nlp/                    空目录
    diagram/                自动布局与 SVG
  frontend/                 React 19 + Vite + React Flow 源码
  web/                      已构建前端产物
  data/                     processes / reliability / experiments（目前只有 .gitkeep）
  tests/                    pytest
  docs/                     架构、设计、阶段报告
```

### 2.2 实际架构图（按真实代码绘制）

图例：`[已实现]` 有代码并有测试/调用链；`[部分]` 有代码但能力或链路不完整；`[缺失]` 无实现；`[外部未知]` 依赖本仓库外系统。

```text
┌─────────────────────────────────────────────────────────────┐
│ 浏览器                                                      │
│  三栏工作台：AgentPanel | React Flow 画布 | Inspector       │ [已实现]
│  仿真评估面板 SimulationPanel                               │ [已实现]
│  Agent 输入框（正则命令解析，无 LLM）                       │ [部分/仅命令]
└───────────────┬─────────────────────────────────────────────┘
                │ fetch /api/*
                ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI (app/main.py)                                       │ [已实现]
│   /api/processes/**   /api/processes/{id}/reliability/**    │
│   /api/processes/{id}/simulate                              │
│   /api/processes/{id}/simulate/evaluate                     │
└───────┬───────────────┬───────────────┬─────────────────────┘
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│ ProcessStore │ │ReliabilitySt.│ │ analysis.service         │
│ JSON 版本存储│ │JSON revision │ │  run_simulation          │
│ [已实现]     │ │[已实现]      │ │  evaluate_simulation     │
└──────────────┘ └──────────────┘ │  build_explanation       │
                                  └───────────┬──────────────┘
                                              │
                              ┌───────────────┴───────────────┐
                              ▼                               ▼
                    ┌──────────────────┐            ┌──────────────────┐
                    │ SimulationRuntime│            │ Evaluation       │
                    │ 真实离散事件     │            │ 指标/目标/警告    │
                    │ [已实现]         │            │ [已实现]         │
                    └──────────────────┘            └──────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 目标层中当前不存在的部分                                    │
│  Agent Harness / 任务规划 / 上下文 / 工具调度               │ [缺失]
│  LLM 客户端 / Prompt / 对话状态                             │ [缺失]
│  Pi 后台运行引擎                                            │ [缺失/外部未知]
│  Riffoid IR 插件调用                                        │ [缺失/外部未知]
│  Study / Scheme / Experiment / Iteration                   │ [缺失]
│  Comparison / Recommendation / DecisionRecord / Report     │ [缺失]
│  Experiment 持久化                                          │ [缺失]
│  桌面封装 / 安装包 / 进程编排                               │ [缺失]
└─────────────────────────────────────────────────────────────┘
```

### 2.3 当前真实可运行链路

当前只有两条真实链路，且都要求用户手工操作或直接调用 HTTP：

**链路 A：建模与可靠性配置**

```text
画布 / Inspector / 正则命令
  -> frontend/src/api.js
  -> POST /api/processes/validate
  -> POST /api/processes 或 PUT /api/processes/{id}
  -> validate_process
  -> ProcessStore 追加版本
  -> PUT /api/processes/{id}/reliability
  -> validate_reliability
  -> ReliabilityStore 追加 revision
```

**链路 B：单次仿真 + 评价（不持久化）**

```text
SimulationPanel
  -> POST /api/processes/{id}/simulate/evaluate
  -> ProcessStore.get(process_id, process_version)
  -> ReliabilityStore.get(process_id, version, hash)
  -> run_simulation
  -> evaluate_simulation
  -> build_explanation
  -> 返回 { simulation, evaluation, explanation }
  -> 前端展示后即丢弃
```

### 2.4 与目标架构的结构性差异

1. 当前是“手工建模 + 单次仿真 + 单次评价”的**建模工具 + 仿真内核**，不是“Agent 驱动的论证任务系统”。
2. 当前没有论证任务对象，也没有任何实验记录，因此无法追溯、比较、复现历史运行。
3. 当前 Agent 是前端正则命令解析，不是 LLM，也没有 Harness、工具协议、任务规划或上下文管理。
4. 当前仓库与 Pi、Pi Web、Riffoid IR 插件**没有任何代码、配置或文档接口**；这部分不是“部分实现”，而是“完全没有接入”。
5. 当前仿真是项目自研 Runtime，不是通过 IR 插件执行；目标中的“IR 插件提供模型生成、检查、编译、仿真”与本项目现有内核存在职责重叠，必须先做架构裁定。

---

## 第三章 目标架构对照

### 3.1 总表

状态定义：

- **已实现且已验证**：有代码，有测试或真实运行证据，且已进入产品调用链。
- **已实现但未完整验证**：有代码，但缺少端到端或充分测试。
- **部分实现**：有部分模块或单层能力，缺少完整业务链路。
- **尚未实现**：没有找到实际实现。

| 模块 | 目标能力 | 当前实现 | 状态 | 证据 | 差距 |
|---|---|---|---|---|---|
| 前端 | 自然语言需求输入、任务展示、模型编辑、参数配置、实验/比较/报告 | React Flow 建模工作台、Inspector、可靠性标签、仿真评估面板；Agent 为命令解析 | 部分实现 | `frontend/src/App.jsx:1257-1413`；`SimulationPanel.jsx:254-466`；`AgentPanel.jsx:40-43` | 无 Study/Scheme/Experiment/比较/报告界面；无自然语言对话；无任务上下文展示 |
| 业务后端 | Study、Scheme、Experiment、Iteration、Comparison、Recommendation、DecisionRecord、Report | 只有 Process/Reliability/Simulation/Evaluation 路由 | 尚未实现 | `app/main.py:46-49`；`app/api/` 仅 4 个路由文件 | 全部上层业务对象、服务和存储缺失 |
| Agent Harness | 接收任务、理解目标、计划、调度 Pi、管理工具、状态、失败处理、澄清、回传 | 无 | 尚未实现 | 全仓库无 Harness/任务/工具协议代码；`app/nlp/` 为空 | 需要从零设计并实现 |
| Pi 集成 | Pi 作为后台 Agent 引擎被独立调用 | 无 | 尚未实现 | 仓库内 0 处 Pi 引用、0 个客户端、0 个进程管理 | 需外部仓库确认 headless 能力 |
| IR 插件集成 | 通过工具接口调用 Riffoid IR 的生成/检查/编译/仿真 | 无 | 尚未实现 | 仓库内 0 处 Riffoid/plugin 引用 | 需确认插件工具 Schema、宿主依赖、IR 兼容性 |
| 仿真核心 | 流程执行、设备可靠性、故障/维修、指标计算、目标判定 | 真实离散事件 Runtime + Evaluation 库 + API + UI；当前语义已实现并验证 | 部分实现（相对最终语义） | `app/simulation/engine.py:125`；`app/evaluation/evaluator.py:320`；35 个 Runtime 测试；29 个评价测试 | 故障生命周期未按已确认设计实现；仅指数分布；无检测/维修资源；无 Runtime 语义版本 |
| 数据层 | Study/Scheme/Process/Reliability/Experiment/SimulationResult/EvaluationResult/Agent 记录/Iteration/Comparison/Recommendation/Decision/Report | Process 版本 JSON、Reliability revision JSON；实验目录为空 | 部分实现 | `app/processes/store.py:99-193`；`app/reliability/store.py:95-162`；`data/experiments/.gitkeep` | 8 类业务对象无持久化；无实验快照；无查询/索引/备份/迁移 |
| 方案比较与推荐 | 比较仿真与评价结果、解释优劣、提出调整建议、用户确认决策 | 单次评价的目标达成展示 | 部分实现（仅单次） | `SimulationPanel.jsx:56-252`；`app/evaluation/evaluator.py:798-844` | 无多方案比较、无迭代记录、无推荐、无决策记录、无报告 |
| 本地单机交付 | 前端/后端/Pi/IR/仿真/存储/配置/打包/安装/退出安全 | 可在开发环境用 uvicorn 托管已构建前端 | 部分实现（仅开发态本地运行） | `app/main.py:137-154`；`web/index.html`；README 启动说明 | 无桌面壳、无安装包、无进程编排、无数据备份、无 Pi 运行环境、无离线模型服务方案 |

### 3.2 分模块细项

#### 3.2.1 前端

已实现：

- 三栏工作台：Agent 面板、画布、Inspector（`App.jsx:1257-1413`）。
- React Flow 节点/连线编辑、拖拽、删除、缩放、MiniMap、自动布局。
- 流程版本切换与历史加载（`App.jsx:925-947`）。
- 可靠性参数按 task 节点配置与保存。
- 仿真评估面板：设备数、仿真结束、种子、故障策略、两个评价目标；展示整体/节点指标、目标状态、警告、限制、解释（`SimulationPanel.jsx:254-466`）。

缺口：

- Agent 面板明确显示“离线命令模式 · LLM 待接入”（`AgentPanel.jsx:42`）。
- 无 Study 选择、方案列表、实验历史、比较矩阵、报告导出。
- 无“当前论证任务/上下文”展示。
- 没有桌面应用形态。

#### 3.2.2 业务后端

现有 API（实测路由）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/processes/validate` | 校验 Process IR |
| POST | `/api/processes/preview.svg` | 草稿 SVG |
| GET/POST | `/api/processes` | 列表/创建 |
| GET/PUT | `/api/processes/{id}` | 读取/更新版本 |
| GET | `/api/processes/{id}/versions` | 版本历史 |
| GET | `/api/processes/{id}/diagram.svg` | 已存版本 SVG |
| POST | `/api/processes/{id}/reliability/validate` | 可靠性校验 |
| GET/PUT | `/api/processes/{id}/reliability` | 读取/保存可靠性 |
| GET | `/api/processes/{id}/reliability/history` | 可靠性 revision 历史 |
| POST | `/api/processes/{id}/simulate` | 原始仿真 |
| POST | `/api/processes/{id}/simulate/evaluate` | 仿真 + 评价 + 解释 |

没有：`/api/studies`、`/api/schemes`、`/api/experiments`、`/api/comparisons`、`/api/recommendations`、`/api/decisions`、`/api/reports`、任何 Agent/Harness 接口。

#### 3.2.3 Agent Harness

逐项回答重点问题：

| 问题 | 结论 | 证据 |
|---|---|---|
| 当前 Agent 是什么实现方式？ | 前端 `useCallback` 内的正则命令解析 | `App.jsx:1053-1173` |
| 是否只是前端离线命令解析？ | 是 | `AgentPanel.jsx:42`；`App.jsx:1058-1161` |
| 是否存在真正的 LLM 调用？ | 否 | 仓库无 openai 客户端代码；`requirements.txt` 虽含 `openai`，但 `app/` 无 import/调用 |
| 是否存在任务规划机制？ | 否 | 无 planner、task、step、state machine |
| 是否存在工具调度机制？ | 否 | 无 tool registry、function schema、调用协议 |
| 是否存在上下文管理？ | 否 | 仅 `messages` 数组用于界面展示 |
| 是否存在多步骤任务执行？ | 否 | 单条命令即时执行，无跨步骤状态 |
| 是否能调用 Pi？ | 否 | 无 Pi 客户端、URL、进程管理 |
| Pi 能否作为独立后台服务运行？ | 本仓库无法验证 | 无任何证据 |
| IR 插件能否脱离 Pi Web 被调用？ | 本仓库无法验证 | 无任何证据 |
| IR 插件工具输入/输出是什么？ | 本仓库无法验证 | 无 Schema、无示例 |
| 需要新增哪些适配层？ | Harness、LLM 客户端、工具注册表、状态机、Pi 适配器、IR 工具适配器、审计记录 | 架构推断 |

#### 3.2.4 仿真核心

已实现：

- 真实离散事件队列，`heapq` 按 `(time, order, kind, entity, node)` 排序（`engine.py:118-120`）。
- 每设备独立状态、历史、随机流（`engine.py:50-74`；`rng.py:18-24`）。
- task 完成时按指数分布抽样，故障后立即路由到 `failure` 边（`engine.py:396-425`、`700-761`）。
- 维修完成、计数、部分暴露（`engine.py:600-637`、`888-912`）。
- 结果包含完整事件、可靠性抽样、设备状态（`models.py:48-82`）。
- 35 个 Runtime 测试覆盖多设备、复现、故障、维修、循环、上限、错误。

未落地：

- `docs/fault-lifecycle-technical-design.md:3` 明确为 **design-only**，要求统一 `NORMAL → LATENT → DETECTED → REPAIRING → NORMAL`；当前 Runtime 仍在 task 完成时即时故障，没有 latent、detection 节点、检测后暂停抽样等语义。
- 只有指数分布（`reliability_ir.py:34`）。
- 没有维修资源、备件、检测策略等业务配置。
- `SimulationResult` 没有 `runtime_semantic_version`（`models.py:66-82`），无法判断新旧实验可比性。

#### 3.2.5 数据层

已实现：

- Process IR 版本追加、内容哈希、`base_version` 冲突检测、历史读取（`processes/store.py:99-166`）。
- Reliability revision 追加、绑定 `process_version + process_hash`、历史保留（`reliability/store.py:95-162`）。
- 原子写入（临时文件 + `os.replace`）。

未实现：

- Study、Scheme、Experiment、Iteration、Comparison、Recommendation、DecisionRecord、Report 的 Schema、Store、查询。
- 实验输入快照、完整结果 artifact、结果哈希、状态、时间。
- 按 `reliability_id + revision` 精确读取；当前 `ReliabilityStore.get` 返回“匹配 process 版本/hash 的最大 revision”（`reliability/store.py:132-150`）。
- 数据库、索引、备份、迁移、并发写入控制（除了单进程 RLock）。

#### 3.2.6 本地单机交付

现状：

- FastAPI 托管 `web/`，开发环境 `uvicorn app.main:app` 可用（`main.py:137-154`）。
- 前端构建产物存在，且包含仿真评估面板。
- LLM 默认关闭，仿真可离线运行（`/api/meta` 的 `offline_capable: true`，`main.py:66`）。
- 但没有任何桌面壳、安装器、进程管理、自动启动、数据目录配置、退出保护、备份恢复。
- PyInstaller/Tauri/Electron 等关键词全仓库 0 命中。

---

## 第四章 端到端调用链审查

### 4.1 目标链路逐段核对

| # | 目标环节 | 当前接口/对象 | 真实调用关系 | 数据格式 | 结果回传 | 错误处理 | 测试/运行证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 1 | 用户自然语言输入 | AgentPanel textarea | 有输入框 | 纯文本 | 仅前端消息 | 无 | 无 | 部分（只能命令） |
| 2 | 前端理解/转发 | `App.executeAgentCommand` | 正则匹配，本地执行 | 无结构 | 文本回复 | try/catch | 无 | 部分 |
| 3 | 前端 → 业务后端 | `frontend/src/api.js` | `fetch` REST | JSON | Promise | `ApiError` | 前端测试仅辅助逻辑 | 已打通（建模/仿真） |
| 4 | 业务后端 → Agent Harness | 无 | 不存在 | — | — | — | — | 中断 |
| 5 | Harness → Pi | 无 | 不存在 | — | — | — | — | 中断 |
| 6 | Pi → IR 插件 | 无 | 不存在 | — | — | — | — | 中断 |
| 7 | IR 插件生成/检查模型 | 无 | 不存在 | — | — | — | — | 中断 |
| 8 | 编译 | 无编译概念 | 不存在 | — | — | — | — | 缺失 |
| 9 | 仿真 | `POST /simulate`、`POST /simulate/evaluate` | 真实调用 `run_simulation` | Process/Reliability → SimulationResult | JSON | 400/409/422/500 | 35 个 Runtime 测试 + 8 个 API 测试 | 已打通（自研内核） |
| 10 | Evaluation | `evaluate_simulation` | 真实调用 | SimulationResult → EvaluationResult | Python 对象 → JSON | 路由捕获异常 | 29 个评价测试 | 已打通 |
| 11 | Experiment 保存 | 无 | 不存在 | — | — | — | — | 中断 |
| 12 | 方案比较 | 无 | 不存在 | — | — | — | — | 缺失 |
| 13 | 论证结论展示 | `SimulationPanel` 单次结果 | 展示单次评价 | JSON | React state | 表单校验/错误提示 | 无前端集成测试 | 部分 |

### 4.2 当前真实链路（已打通部分）

```text
用户手工建模或输入固定命令
  -> 前端画布 / Inspector / 正则命令
  -> POST /api/processes/validate
  -> POST/PUT /api/processes
  -> ProcessStore（版本 + 内容哈希）
  -> PUT /api/processes/{id}/reliability
  -> ReliabilityStore（revision + 精确绑定）
  -> 用户点击“运行仿真并评价”
  -> POST /api/processes/{id}/simulate/evaluate
  -> run_simulation（真实事件队列）
  -> evaluate_simulation（真实指标计算）
  -> build_explanation（确定性文本）
  -> 前端展示
  -> 结果丢弃，无实验记录
```

这条链路是**真实执行、非 Mock**，有代码和测试证据；但它完全绕过了目标中的 Agent、Harness、Pi、IR 插件和实验管理。

### 4.3 断点定位

1. **断点 A：自然语言 → 结构化任务**。当前没有 LLM，也没有任务对象。
2. **断点 B：业务后端 → Harness**。后端没有 Agent 任务接口，Harness 不存在。
3. **断点 C：Harness → Pi**。没有 Pi 客户端或运行环境。
4. **断点 D：Pi → IR 插件**。没有插件调用协议，且外部能力未验证。
5. **断点 E：仿真结果 → Experiment**。没有持久化，结果返回即丢弃。
6. **断点 F：Experiment → 比较/推荐/决策/报告**。全部缺失。
7. **断点 G：本地应用 → 单机交付**。没有桌面封装和安装流程。

---

## 第五章 已实现能力

以下能力可以确认有代码证据，其中大部分还有测试证据。

### 5.1 Process IR 与结构校验

- 节点类型 `start/task/decision/end`、边类型 `normal/conditional/default/failure`、条件表达式、效果、状态目录、业务 outcomes、画布坐标（`app/domain/process_ir.py:23-198`）。
- 严格 `extra="forbid"`，可靠性字段被明确拒绝（`process_ir.py:43-44`；架构文档 `architecture.md:69`）。
- 结构、端点、可达性、decision 分支、循环、条件字段、效果、状态引用等校验（`validation.py:361-793`）。
- 测试：`tests/test_process_ir.py`、`tests/test_validation.py`（24 个测试）。

### 5.2 版本化 Process 存储

- 创建/更新版本、内容哈希、内容未变不新增版本、`base_version` 冲突 409（`processes/store.py:99-149`）。
- 历史版本查询、列表摘要（`processes/store.py:151-193`）。
- 测试：`tests/test_store.py`、`tests/test_api.py`。

### 5.3 Reliability IR 与精确绑定

- 每个 task 的 `participates`、`distribution=exponential`、`lambda`、单位（`reliability_ir.py:38-105`）。
- 与 `process_id + process_version + process_hash` 精确绑定；新版本不自动继承旧配置（`reliability/store.py:95-162`）。
- 校验节点类型、λ、task 配置完整性（`reliability_validation.py:90-169`）。
- 测试：`tests/test_reliability_ir.py`（15）、`test_reliability_validation.py`（9）、`test_reliability_store.py`（5）、`test_reliability_api.py`（11）。

### 5.4 真实离散事件仿真 Runtime

- 全局事件队列、多设备独立状态、独立历史。
- 每设备两个 RNG，种子由 SHA-256 派生（`simulation/rng.py:18-24`）。
- 指数可靠性区间抽样、业务 outcomes 抽样、故障出口、维修、部分暴露。
- 相同种子逐字段复现。
- 集中安全上限与明确错误码（`simulation/config.py:15-32`、`errors.py`）。
- 测试：`tests/test_simulation_runtime.py`（35）、`tests/test_simulation_api.py`（7）。

### 5.5 Evaluation 评价与解释

- 整体可靠性、结束可用性、故障/维修/完成/停止统计、状态分布（`evaluator.py:509-541`）。
- 节点级指标：访问、抽样、故障、暴露时间、理论可靠度、联合无故障概率、经验故障频率（`evaluator.py:543-774`）。
- 设备级指标与结束状态分类（`evaluator.py:776-796`）。
- 目标判定 `overall_reliability_min`、`end_availability_min`（`models.py:35-38`；`evaluator.py:798-844`）。
- 绑定一致性、样本量、计数一致性等警告（`evaluator.py:351-541`）。
- 确定性解释文本（`explanations.py:126-139`）。
- API：`POST /api/processes/{id}/simulate/evaluate`（`evaluation_routes.py:61-120`）。
- 测试：`tests/evaluation/` 共 29 个测试；`tests/test_simulation_evaluation_api.py` 8 个测试。

### 5.6 前端建模与仿真评估工作台

- React Flow 画布、节点/连线编辑、拖拽、自动布局、MiniMap、Controls。
- Inspector 业务属性、连接条件、版本历史、可靠性配置。
- 仿真评估面板，含目标输入、整体指标、目标表、节点表、警告、限制、解释。
- 已构建产物 `web/` 与源码基本同步（构建时间 2026-11-21，晚于 SimulationPanel 源码）。

### 5.7 工程与文档

- 176 个后端测试通过，16 个前端测试通过。
- 阶段报告 `phase-1/2/3-report.md`、`phase-3-review.md` 记录了真实运行案例。
- `docs/unified-argumentation-architecture.md` 已对 Study/Scheme/Experiment/Iteration/Comparison/Recommendation/Report 做出较完整的**设计**（不是实现）。

### 5.8 已实现但尚未接入产品链路

| 能力 | 实现位置 | 当前未接入表现 |
|---|---|---|
| 原始仿真接口 `/simulate` | `simulation_routes.py:41-87` | 前端只调用 `/simulate/evaluate` |
| 可靠性校验接口 | `reliability_routes.py:64-72` | 前端 `api.js` 定义了 `validateReliability`，但 `App.jsx` 未调用 |
| 可靠性历史接口 | `reliability_routes.py:107-129` | 前端 `api.js` 定义了 `getReliabilityHistory`，但 `App.jsx` 未调用 |
| 草稿 SVG 预览 `/preview.svg` | `process_routes.py:53-64` | 前端无调用 |
| 已存版本 SVG `/diagram.svg` | `process_routes.py:125-149` | 前端无调用，导出只导出 Process IR JSON |
| `explain_node_metric` | `explanations.py:142-148` | 未被任何路由或前端调用 |
| Evaluation 目标配置持久化 | 仅请求参数（`evaluation_routes.py:29-31`） | 刷新页面后目标丢失 |
| `app/analysis/` 编排服务 | `analysis/service.py:23-42` | 已接入评价路由，但仅单次调用，无实验记录 |

---

## 第六章 未实现和不完整能力

### 6.1 缺少功能（完全没有实现）

| 编号 | 缺口 | 影响 | 依赖 |
|---|---|---|---|
| M1 | Study（论证任务） | 无法组织共同目标、多个方案和最终报告 | 无，但需要 Schema/Store/API/UI |
| M2 | Candidate Scheme（候选方案） | 无法把 Process 版本 + Reliability revision + 目标 + 仿真默认配置组织成可比较方案 | Process/Reliability 存储已具备 |
| M3 | Experiment（实验记录） | 无法保存、查询、复现历史仿真 | Runtime/Evaluation 已具备 |
| M4 | Iteration（方案迭代关系） | 无法记录“从哪个方案、基于哪次实验、改了什么、为什么” | M2/M3 |
| M5 | Comparison（方案比较） | 无法比较多方案指标、目标达成、警告 | M3 |
| M6 | Recommendation（推荐） | 无法按规则筛选/排序并解释推荐依据 | M5 |
| M7 | DecisionRecord（最终决策） | 无法记录用户最终确认 | M6 |
| M8 | Report（论证报告） | 无法生成和导出报告 | M1-M7 |
| M9 | Agent Harness | 无法接收任务、规划、调度工具、管理状态、处理失败、澄清 | 需要业务 API 和 LLM |
| M10 | LLM 客户端 / Prompt / 对话状态 | 无法自然语言理解 | `requirements.txt` 有 `openai`，但无实现 |
| M11 | Pi 后台运行集成 | 无法使用 Pi 作为 Agent 引擎 | 外部能力未验证 |
| M12 | Riffoid IR 插件工具集成 | 无法调用插件生成/检查/编译/仿真 | 外部能力未验证 |
| M13 | 桌面封装 / 安装包 / 进程编排 | 无法作为本地单机软件交付 | 需先确定技术路线 |
| M14 | 数据备份/恢复/迁移/索引 | 长期使用后数据安全和查询能力不足 | 数据层设计 |
| M15 | Runtime 语义版本 | 无法判断新旧实验可比性 | `SimulationResult` Schema |
| M16 | 故障生命周期（latent/detect/repair） | 与已确认设计不一致，领域语义未冻结 | Runtime/Reliability IR |
| M17 | 其他可靠性分布、检测策略、维修资源 | 领域建模能力不足 | Reliability IR |
| M18 | 评价约束（成本、最大故障数等） | 只能判断两个比例目标 | Evaluation 模型 |
| M19 | 统计置信区间 / 多随机种子聚合 | 单次实验结论统计强度不足 | Evaluation/Experiment |
| M20 | 精确 Reliability revision 读取 | 方案无法绑定任意历史 revision | `ReliabilityStore` |
| M21 | 多用户、鉴权、并发控制 | 当前只能单用户本地 | 非首版阻塞项 |

### 6.2 功能存在但没有集成

| 能力 | 现状 | 集成缺口 |
|---|---|---|
| 原始仿真 | 后端可用 | 前端未暴露，只有“仿真+评价”入口 |
| 可靠性校验 | 后端可用 | 前端未调用 |
| 可靠性历史 | 后端可用 | 前端未展示 |
| SVG 预览/导出 | 后端可用 | 前端无调用 |
| 评价解释 | 已生成 | 仅单次展示，未进入实验/报告 |
| 目标配置 | 请求参数可用 | 未持久化，刷新丢失 |
| Process 版本历史 | 前端可用 | 未与方案/实验关联 |

### 6.3 有接口但没有真实调用

- `frontend/src/api.js` 中的 `simulate`、`validateReliability`、`getReliabilityHistory` 只有定义，没有调用点。
- 后端 `/preview.svg`、`/diagram.svg` 只有实现，没有前端调用。
- `app/analysis/service.py` 只有单次仿真+评价编排，没有 Experiment/Comparison 调用。
- `app/experiments/`、`app/nlp/` 是空目录，不是实现。

### 6.4 有实现但缺少验证

| 能力 | 实现 | 验证缺口 |
|---|---|---|
| 前端仿真评估面板 | `SimulationPanel.jsx` | 只有纯函数辅助测试，无组件/端到端测试；未验证真实浏览器调用 |
| 前端 Agent 命令 | `App.jsx:1053-1173` | 无自动化测试 |
| 前端可靠性面板 | `Inspector.jsx` | 只有辅助逻辑测试 |
| 服务端 SVG | `diagram/svg.py`、`layout.py` | 有单元测试，但未与前端导出链路联调 |
| 完整桌面/离线 | 无 | 无法验证 |

### 6.5 外部依赖尚未确认

- Pi 的启动方式、端口/协议、会话生命周期、工具注册方式、错误模型。
- Pi Web 是否只是 UI，还是也承担 Agent 运行时；是否可 headless。
- Riffoid IR 插件的宿主依赖、工具清单、输入/输出 Schema、版本兼容性。
- IR 插件是否自带仿真内核；若自带，与本项目 Runtime/Evaluation 的关系必须裁定。
- IR 插件的模型生成结果是否就是本项目 Process IR / Reliability IR；若不是，需要转换层和语义映射。
- 许可证、分发方式、离线可用性、是否需要网络。

### 6.6 文档漂移与工程风险

| 问题 | 证据 | 影响 |
|---|---|---|
| README 说“评价指标、实验比较和完整 LLM Agent 尚未实现”“前端暂未增加仿真运行面板” | `README.md:165-169` | 与代码不符：评价 API、前端仿真评估面板已存在 |
| `architecture.md` 同样滞后 | `docs/architecture.md:220-230` | 容易误判现状 |
| README 测试数量 139/9 | `README.md:63,72` | 实际为 176/16 |
| `docs/unified-argumentation-architecture.md` 说 Evaluation 未接入 API | 该文档 2026-11-20 版 | 该判断已被后续 Phase 4B 实现超越，需更新 |
| Git 无任何提交 | `git log` 失败；`git status` 全部 untracked | 代码变更不可追溯，与“实验可追溯”目标不匹配 |
| 数据目录只有 `.gitkeep` | `data/` 实际检查 | 没有真实实验数据可用于验证历史/比较 |
| `.env.example` 编码显示异常 | PowerShell 读取出现乱码 | 需确认文件实际 UTF-8 编码与内容完整性 |

---

## 第七章 项目距离最终目标还有多少

### 7.1 分层判断

| 层 | 判断 | 说明 |
|---|---|---|
| 核心仿真能力 | **中上，约 60%** | 真实 DES、多设备、可复现、事件日志、测试充分；但故障语义未按设计冻结，分布单一，无检测/资源 |
| 建模与可靠性配置 | **中上，约 65%** | Process IR/校验/版本/UI 较完整；Reliability 只覆盖指数 λ，目标/约束未建模 |
| 单次评价 | **中上，约 70%** | 指标、目标、警告、解释、API、UI 都有；但目标只有两个，无统计置信区间 |
| 业务系统 | **很低，约 5%** | 只有对象级版本历史，没有 Study/Scheme/Experiment/Iteration/比较/推荐/决策/报告 |
| Agent Harness | **很低，约 10%** | 只有正则命令解析；无 LLM、规划、工具调度、上下文、状态机 |
| Pi + IR 插件集成 | **0%** | 仓库内零代码、零配置、零接口；外部能力未知 |
| 数据管理 | **低，约 30%** | Process/Reliability 持久化可靠；实验/方案/报告全缺；无索引/备份/迁移 |
| 本地单机交付 | **很低，约 10%** | 可在开发机启动 Web 服务，但没有桌面应用、安装器、进程编排、离线 Agent 环境 |

### 7.2 加权评分方法与结果

权重按“最终软件必须具备的能力重要性”分配，不是按当前代码量分配。分数是本审查基于细项清单的主观评级，计算过程公开如下，便于质疑和调整。

| 模块 | 权重 | 分数 | 加权贡献 | 评分依据（细项） |
|---|---:|---:|---:|---|
| 建模层（Process/Reliability/UI） | 15% | 65 | 9.75 | Process IR/校验/版本约 90；Reliability 约 55；建模 UI 约 75；缺目标/检测/资源建模 |
| 仿真核心 | 15% | 60 | 9.00 | DES/多设备/复现约 85；故障生命周期约 30；分布约 30；检测/资源约 15 |
| 评价层 | 10% | 70 | 7.00 | 单次指标约 90；两个目标约 70；比较/统计/约束约 20 |
| 业务管理 | 20% | 5 | 1.00 | 8 类业务对象均无实现；对象级版本历史不能等同 Scheme/Experiment |
| Agent Harness | 15% | 10 | 1.50 | 命令解析约 60；LLM/规划/工具/上下文/Harness 均为 0 |
| Pi + IR 插件 | 10% | 0 | 0.00 | 零实现、零接口、外部能力未验证 |
| 数据层 | 5% | 30 | 1.50 | Process/Reliability 约 85；实验/方案约 0；查询/备份/迁移约 20 |
| 前端产品 | 5% | 45 | 2.25 | 建模工作台约 85；仿真面板约 75；任务/方案/实验/比较/报告约 0 |
| 本地单机交付 | 5% | 10 | 0.50 | 本地开发启动约 70；离线仿真约 60；桌面封装/安装/进程管理约 0 |
| **合计** | **100%** | — | **32.50** | — |

计算公式：

```text
总分 = Σ(模块权重 × 模块分数)
     = 0.15×65 + 0.15×60 + 0.10×70 + 0.20×5
     + 0.15×10 + 0.10×0 + 0.05×30 + 0.05×45 + 0.05×10
     = 9.75 + 9.00 + 7.00 + 1.00 + 1.50 + 0 + 1.50 + 2.25 + 0.50
     = 32.50
```

分层折算：

| 分层 | 权重合计 | 加权得分 | 层内完成度 |
|---|---:|---:|---:|
| 核心链路（建模 + 仿真 + 评价） | 40% | 25.75 | **64.4%** |
| 上层业务与 Agent（业务管理 + Harness + Pi/IR） | 45% | 2.50 | **5.6%** |
| 工程与交付（数据 + 前端 + 单机） | 15% | 4.25 | **28.3%** |
| 总体 | 100% | 32.50 | **约 33%** |

### 7.3 解读

- 如果只看“能不能做真实仿真和单次评价”，项目已经达到可演示、可测试的水平（约 64%）。
- 如果看“能否完成一次完整的 Agent 论证任务并留下可追溯实验”，项目仍处于早期（约 6%）。
- 最大风险不是仿真内核，而是**上层业务对象、Agent Harness、Pi/IR 集成和单机交付**同时缺失。
- 当前成果应保留，不应推翻；但必须承认：现有代码只是最终产品的“仿真与评价底座”。

---

## 第八章 后续开发路线图

### 8.0 对现有阶段划分的调整建议

现有文档使用 `Phase 1/2/3/4B/4C/5/6/7/8`。建议**保留其核心顺序思想**，但增加一个前置“外部能力验证门”，并把“桌面封装技术选型”提前为并行 spike。理由：

1. Pi 和 IR 插件能否 headless 调用，是最终架构的前提；如果不先验证，后续 Harness 设计可能返工。
2. 桌面封装（Electron/Tauri/Python sidecar）会反向影响进程编排、数据目录和 Agent 启动方式，不能等到最后才评估。
3. 现有 Phase 4B 实际已完成（评价 API + 前端 + 测试），不应机械重复。
4. Study/Scheme/Experiment 应作为一个整体交付，否则无法形成可追溯闭环。

建议路线：

```text
Gate 0（外部能力验证，前置门）
  -> Stage 1（基线、语义冻结与数据完整性）
    -> Stage 2（Study + Scheme + Experiment 最小闭环）
      -> Stage 3（Agent Harness v1 + LLM）
        -> Stage 4（Pi + IR 插件适配，依赖 Gate 0）
          -> Stage 5（Iteration + Comparison + Recommendation + Decision + Report）
            -> Stage 6（桌面封装与单机交付）

并行轨道：
  - 桌面技术 spike：从 Gate 0 后开始，Stage 6 收口
  - 故障生命周期：Stage 1 决策后并行，独立升级 Runtime 语义版本
```

### 8.1 Gate 0：Pi / Pi Web / Riffoid IR 外部能力验证

**目标**：在不改本项目业务代码的前提下，确认外部系统能否被独立调用，并形成接口契约。

**需要完成**

- 定位 Pi、Pi Web、Riffoid IR 插件仓库、版本、许可证。
- 验证 Pi 是否能以 headless 方式启动；是否有 HTTP/JSON-RPC/CLI/SDK。
- 验证 IR 插件是否能脱离 Pi Web UI 调用；工具清单、输入/输出 Schema、错误模型。
- 用最小脚本跑通一次“列出工具 / 调用一个工具 / 取回结构化结果”。
- 判断 IR 插件与本项目 Process IR / Reliability IR / Runtime / Evaluation 的职责关系。

**前置依赖**：无（可立即开始）。

**验收标准**

- 有一份可执行的接口说明和最小调用脚本。
- 明确 Pi 的启动命令、健康检查、会话生命周期、超时与错误返回。
- 明确 IR 插件每个工具的 JSON Schema 和示例。
- 明确“仿真真相”归属：使用插件仿真，还是继续使用本项目 Runtime。
- 若无法 headless 调用，必须给出替代方案（如自带 MCP 适配、子进程、或放弃 Pi 改用直接 LLM + 工具协议）。

**风险**

- Pi 可能与 UI 强耦合，无法独立运行。
- 插件可能依赖 Pi Web 的扩展宿主，不能直接调用。
- 外部仓库可能无文档、无测试、版本不稳定。

**可并行**：与 Stage 1 并行。

### 8.2 Stage 1：工程基线、Runtime 语义冻结与数据完整性

**目标**：在积累实验数据前，把“可追溯”的地基打牢。

**需要实现**

- 建立 Git 基线（当前无任何提交）。
- 更新 README/architecture 与代码一致，标注 Phase 4B 已完成。
- 定义 `runtime_semantic_version`（例如 `immediate-failure/1.0`），写入 `SimulationResult`。
- 明确故障生命周期实施时点；若暂不实施，必须在文档和结果中标注当前语义。
- `ReliabilityStore.get_by_revision(process_id, reliability_id, revision)` 及 API 可选 `revision` 参数。
- 统一实验结果目录与数据目录约定（`data/studies`、`data/schemes`、`data/experiments`）。
- 明确数据备份/恢复的最小策略。

**前置依赖**：无；建议在 Gate 0 同期完成。

**验收标准**

- 新仿真结果包含 `runtime_semantic_version`。
- 能按 `reliability_id + revision` 精确读取历史配置。
- 文档不再声称评价/仿真面板未实现。
- 有测试覆盖新字段和精确读取。

**风险**

- 语义版本定义过早或过晚都会造成迁移成本；需和老板确认故障生命周期时点。

### 8.3 Stage 2：Study + Candidate Scheme + Experiment 最小闭环

**目标**：把“论证任务 → 候选方案 → 一次实验 → 完整结果”变成可保存、可查询、可复现的产品对象。

**需要实现**

- `Study` Schema/Store/Service/API/UI：名称、说明、评价目标、评价配置、创建时间。
- `CandidateScheme` Schema/Store/Service/API/UI：`study_id`、`parent_scheme_id`、精确 Process 绑定、精确 Reliability revision、目标快照、仿真默认配置；不可变，派生创建新 ID。
- `Experiment` Schema/Store/Service/API/UI：输入快照、完整 `SimulationResult`、完整 `EvaluationResult`、解释、状态、时间、结果哈希、Runtime 语义版本。
- 实验存储采用 metadata + artifact（`metadata.json`、`simulation.json`、`evaluation.json`、可选 `explanation.md`）。
- 复用 `run_simulation`、`evaluate_simulation`、`build_explanation`，不得复制公式。
- 前端增加 Study 选择、创建方案、运行实验、实验历史详情。
- 支持同一 Scheme 多次 Experiment，同种子可复现。

**前置依赖**：Stage 1。

**验收标准**

- 创建 Study → 创建 Scheme → 运行 Experiment → 重新加载可完整还原输入和结果。
- Scheme 绑定精确版本/hash，不使用“最新”。
- 同一 Scheme 同配置同种子两次运行结果逐字段一致。
- 实验保存完整事件和可靠性抽样，不只保存摘要。
- 有 Store/API/端到端测试，不使用 Mock。

**风险**

- 完整事件日志体积大；需评估压缩、分片或数据库。
- 不可变规则和引用完整性容易在实现中松动。
- 目标快照与 Study 目标变化的关系需要严格测试。

**可并行**：Stage 3 的 LLM 客户端和工具注册表可在 API 契约稳定后并行开发。

### 8.4 Stage 3：Agent Harness v1 + LLM

**目标**：让用户用自然语言发起论证任务，由 Harness 规划并调用现有业务 API。

**需要实现**

- LLM 客户端（OpenAI 兼容），支持 OpenCode Go / 本地模型可替换。
- 工具注册表：把 Process、Reliability、Study、Scheme、Experiment、Simulation、Evaluation API 包装为工具 Schema。
- Harness 状态机：接收任务 → 理解目标 → 计划 → 调用工具 → 处理错误 → 请求澄清 → 汇总结果。
- 上下文管理：任务上下文、已选 Study/Scheme、最近实验、用户确认。
- 失败处理：工具失败重试/降级/向用户报告；模型输出校验失败时纠错。
- 执行记录：保存 Agent 运行记录（输入、计划、工具调用、结果、错误）。
- 前端：Agent 对话、任务状态、澄清问题、结果摘要。
- 严格边界：Agent 不直接读写 Store，不直接调用 Runtime/Evaluation，只通过应用 API/工具。

**前置依赖**：Stage 2 的 API 契约；Stage 1 的语义版本。

**验收标准**

- 一条自然语言请求可以触发“创建 Study → 创建 Scheme → 运行 Experiment → 返回结论”的多步执行。
- 工具调用失败时有明确错误处理和用户可见反馈。
- Harness 执行记录可查询。
- 不使用前端正则命令作为最终方案。
- 有 Harness 单元测试和至少一条端到端测试（可用 Mock LLM，但工具链必须是真实 API）。

**风险**

- LLM 输出不稳定，需要严格 Schema 校验和重试。
- 任务规划与工具边界设计不当会导致 Agent 越权或死循环。
- 认证密钥管理；离线场景下模型服务不可用。

### 8.5 Stage 4：Pi + IR 插件适配

**目标**：按 Gate 0 的结论，把 Pi 作为后台 Agent 引擎、IR 插件作为专业工具接入 Harness。

**需要实现（取决于 Gate 0 结论）**

- Pi 适配器：启动/健康检查/会话/超时/退出/日志。
- Harness → Pi 的任务协议。
- IR 插件工具适配器：生成、检查、编译、仿真等工具的输入/输出映射。
- IR 转换层：插件 IR ↔ 本项目 Process IR / Reliability IR（若语义不同）。
- 错误映射：插件错误 → Harness 可处理错误 → 用户可读信息。
- 双运行模式策略：插件仿真 vs 本项目 Runtime，明确唯一真相源。
- 集成测试：真实调用插件，不允许 Mock 通过验收。

**前置依赖**：Gate 0、Stage 3。

**验收标准**

- Harness 能通过 Pi 调用 IR 插件完成至少一个真实工具任务。
- 插件输出能被本项目校验/保存/展示。
- 失败、超时、非法输出有明确处理。
- 明确并记录“仿真真相源”，不出现两套结果互相矛盾。

**风险**

- 外部系统不可控，接口可能变化。
- IR 语义不一致导致转换丢失。
- Pi/插件运行环境增加桌面打包复杂度。

### 8.6 Stage 5：Iteration + Comparison + Recommendation + Decision + Report

**目标**：完成方案迭代、比较、推荐、用户决策和报告闭环。

**需要实现**

- Iteration：方案派生关系、变更摘要、参数 diff、触发实验、理由。
- Comparison：用户显式选择代表实验，生成指标矩阵、目标达成矩阵、差异、警告；不重算评价公式。
- Recommendation：规则筛选/排序，解释依据，处理“无方案达标”“证据不足”。
- DecisionRecord：用户最终确认、选中方案/实验、规则版本、理由、警告。
- Report：Study 问题、目标、方案、实验、评价、比较、推荐、决策、绑定信息；支持导出。
- 前端：比较视图、迭代链、推荐与确认、报告预览/导出。
- 语义版本/目标版本不一致时显式提示不可直接比较。

**前置依赖**：Stage 2、Stage 3（Agent 可参与解释）、Stage 4（若插件参与）。

**验收标准**

- 能比较同一 Study 下至少两个 Scheme 的代表实验。
- 推荐有可解释依据，且不把推荐等同于最终决策。
- DecisionRecord 独立持久化。
- 报告可追溯到精确 Process/Reliability/Experiment/评价版本。
- 目标版本或 Runtime 语义版本不一致时有明确警告。

**风险**

- 比较规则和推荐规则需要业务确认。
- 报告格式和内容范围需要用户确认。
- 多随机种子聚合未实现时，结论统计强度有限。

### 8.7 Stage 6：桌面封装与本地单机交付

**目标**：把独立 Web 应用封装为可安装、可离线、数据安全的本地单机软件。

**需要实现**

- 桌面技术选型（Electron / Tauri / 其他），需评估 Python 后端、前端、Pi 运行时、IR 插件的进程模型。
- 进程编排：启动/健康检查/退出/崩溃恢复；端口选择；单实例。
- 打包：Python 运行时、前端静态资源、数据目录、配置文件、Agent 运行时。
- 安装器：Windows 优先（当前环境），后续可扩展。
- 数据安全：备份/恢复、退出时写入完成、异常退出保护、日志脱敏。
- 离线能力：LLM 关闭时仍可完成手工闭环；若需要 LLM，明确网络依赖和降级。
- 配置界面：数据目录、模型服务、认证。

**前置依赖**：Stage 2-5 的功能稳定；Gate 0 的运行时结论。

**验收标准**

- 在干净机器上安装后可启动，无需开发工具。
- 前后端/Pi/IR/仿真服务按需启动，退出后数据完整。
- 断网时手工建模、仿真、评价、实验、比较、报告可用（若 LLM 非必需）。
- 有安装、升级、卸载、备份恢复说明。

**风险**

- Pi/IR 的运行环境可能难以打包。
- 多进程生命周期和端口冲突。
- 数据目录权限和杀毒软件误报。
- 桌面壳体积和启动速度。

**可并行**：技术 spike 可在 Stage 2 前开始，最终收口在 Stage 6。

### 8.8 并行轨道：故障生命周期

**目标**：按 `docs/fault-lifecycle-technical-design.md` 已确认的领域决策实现统一生命周期。

**需要实现**

- LATENT / DETECTED / REPAIRING 状态与检测节点配置。
- 检测节点完成效果先于故障路由；failure 边优先。
- 故障确认后暂停可靠性暴露与抽样。
- 业务结束可用性与无故障结束可用性分离。
- 升级 `runtime_semantic_version`，禁止新旧实验静默混比。

**前置依赖**：Stage 1 的语义冻结决策。

**验收标准**

- 设计文档中的已确认决策逐条有测试。
- 旧 Process/Reliability 数据仍可读取。
- 新旧实验比较时有明确不可比提示。

**风险**

- 会改变仿真结果，影响已有实验可比性。
- 与 IR 插件仿真语义可能冲突，需要统一。

### 8.9 依赖关系与并行建议

```text
Gate 0 ───────────────┐
                      ├─> Stage 4 ──┐
Stage 1 ─> Stage 2 ─> Stage 3 ──────┤
   │           │                     ├─> Stage 5 ─> Stage 6
   │           └─────────────────────┘
   └─> 故障生命周期（并行，升级语义版本）

桌面技术 spike：Stage 1 后开始，Stage 6 收口
```

可并行：

- Gate 0 与 Stage 1。
- Stage 2 与 Stage 3 的 LLM 客户端/工具注册表（API 契约稳定后）。
- 故障生命周期与 Stage 2-5（但必须版本隔离）。
- 桌面技术 spike 与 Stage 2-5。

不可并行/强依赖：

- Stage 3 依赖 Stage 2 的应用 API。
- Stage 4 依赖 Gate 0。
- Stage 5 依赖 Stage 2/3。
- Stage 6 依赖功能稳定。

---

## 第九章 需要用户或老板确认的问题

以下问题无法仅从代码和现有设计文档中确定。建议在进入 Stage 2/3/4 前逐项确认，否则会造成架构返工。

| 编号 | 问题 | 为什么必须确认 | 影响阶段 |
|---|---|---|---|
| Q1 | Pi、Pi Web、Riffoid IR 插件的仓库位置、版本、许可证是什么？ | 本仓库零引用，无法验证能力 | Gate 0 |
| Q2 | Pi 能否以 headless/后台服务方式运行？提供什么协议（HTTP/JSON-RPC/CLI/SDK）？ | 决定 Harness 如何调度 | Gate 0、Stage 3/4 |
| Q3 | IR 插件能否脱离 Pi Web UI 被调用？工具 Schema 在哪里？ | 决定是否需要自建适配器或放弃插件 | Gate 0、Stage 4 |
| Q4 | IR 插件是否自带仿真内核？若自带，最终“仿真真相”是本项目 Runtime 还是插件？ | 避免两套仿真结果冲突 | Gate 0、Stage 4 |
| Q5 | 插件生成的 IR 是否就是本项目 Process IR / Reliability IR？若不同，是否接受转换层？ | 决定数据模型和迁移成本 | Gate 0、Stage 4 |
| Q6 | 最终产品是否允许联网调用 LLM？还是必须完全离线？ | 决定模型服务、认证和单机交付方案 | Stage 3、Stage 6 |
| Q7 | LLM 继续使用 OpenCode Go / deepseek-v4.1-flash，还是允许本地模型？ | 决定客户端和认证实现 | Stage 3 |
| Q8 | 故障生命周期是在 Experiment 数据积累前实施，还是之后？ | 决定 Runtime 语义版本和旧实验可比性 | Stage 1、并行轨道 |
| Q9 | 桌面封装是否接受 Electron/Tauri？目标操作系统是否只有 Windows？是否需要 Python sidecar？ | 决定打包架构 | Stage 6 |
| Q10 | Study 目标变化时，是创建新 plan 版本、新 Study，还是只影响新 Scheme？ | 影响比较基准和报告 | Stage 2、Stage 5 |
| Q11 | 失败实验是否保存错误记录？ | 影响 Experiment Schema 和追溯 | Stage 2 |
| Q12 | 论证报告需要什么格式（Markdown/PDF/Word）和内容范围？ | 影响 Report 设计与实现 | Stage 5 |
| Q13 | 是否需要多用户、鉴权、审批流？还是首版只做单用户本地？ | 影响数据层、并发和桌面交付 | Stage 2-6 |
| Q14 | 是否需要保留完整事件日志？数据量上限和保留策略是什么？ | 影响存储选型（JSON/SQLite/压缩） | Stage 2、Stage 6 |
| Q15 | 是否要求“Agent 执行记录”可审计到每次工具调用和模型输出？ | 影响 Harness 日志与隐私 | Stage 3 |

---

## 附录 A：关键证据索引

| 主题 | 文件:行号 |
|---|---|
| 应用装配与路由注册 | `app/main.py:26-49` |
| 静态前端托管 | `app/main.py:137-154` |
| LLM 配置占位 | `app/config.py:28-67` |
| Process IR Schema | `app/domain/process_ir.py:23-198` |
| 结构校验入口 | `app/domain/validation.py:361` |
| Reliability IR Schema | `app/domain/reliability_ir.py:38-105` |
| Reliability 校验 | `app/domain/reliability_validation.py:90` |
| Process 版本存储 | `app/processes/store.py:99-193` |
| Reliability revision 存储 | `app/reliability/store.py:95-162` |
| 仿真入口 | `app/simulation/engine.py:125`、`963` |
| task 完成抽样与即时故障 | `app/simulation/engine.py:396-425` |
| 故障路由 | `app/simulation/engine.py:700-761` |
| 部分暴露 | `app/simulation/engine.py:888-912` |
| 仿真结果 Schema | `app/simulation/models.py:66-82` |
| 评价主函数 | `app/evaluation/evaluator.py:320` |
| 目标判定 | `app/evaluation/evaluator.py:798-844` |
| 评价解释 | `app/evaluation/explanations.py:126-139` |
| 仿真+评价编排 | `app/analysis/service.py:23-42` |
| 评价 API | `app/api/evaluation_routes.py:61-120` |
| 前端 API 客户端 | `frontend/src/api.js:40-103` |
| 前端 Agent 正则命令 | `frontend/src/App.jsx:1053-1173` |
| 前端 Agent 面板 | `frontend/src/components/AgentPanel.jsx:40-43` |
| 前端仿真评估面板 | `frontend/src/components/SimulationPanel.jsx:254-466` |
| 故障生命周期设计状态 | `docs/fault-lifecycle-technical-design.md:3` |
| 统一论证架构设计 | `docs/unified-argumentation-architecture.md` |
| 文档滞后声明 | `README.md:160-169`；`docs/architecture.md:220-230` |

## 附录 B：本次未做的操作

- 未修改任何现有文件。
- 未新增除本文件外的任何文件。
- 未启动 uvicorn，未创建 Study/Scheme/Experiment，未写入 `data/`。
- 未执行 git commit/push/checkout/reset/rebase/merge。
- 未安装、升级或删除依赖。
- 未运行前端生产构建（仅运行已有测试；`web/` 保持原状）。

---

## 结论摘要

1. 当前项目是一个**可运行、可测试、真实执行的流程建模 + 离散事件仿真 + 单次评价工具**。
2. 现有核心链路（Process IR → Reliability IR → Runtime → Evaluation → 单次展示）已经打通，代码和 176 个后端测试、16 个前端测试可以证明。
3. 目标中的**业务管理层、Agent Harness、LLM、Pi、Riffoid IR 插件、实验持久化、比较推荐报告、桌面交付**基本全部缺失。
4. 本仓库对 Pi / Riffoid 的引用为 0，无法证明任何相关能力；必须先做外部仓库能力验证。
5. 按公开权重的定性评估，总体完成度约 **33%**；核心仿真链路约 **64%**，上层论证与 Agent 约 **6%**，工程交付约 **28%**。
6. 建议下一步不是继续加仿真细节，而是：**先做 Gate 0 外部能力验证 + Stage 1 基线/语义冻结，再进入 Study/Scheme/Experiment 闭环。**
