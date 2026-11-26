# reliability-flow-agent

基于自然语言的通用流程建模与设备可靠性仿真 Agent。

当前完成 **Phase 3：真实 Python 离散事件仿真 Runtime、多设备独立运行、指数可靠性区间抽样、故障维修和可复现随机流**。评价指标、实验比较和完整 LLM Agent 尚未进入本阶段。

## 技术栈

- Python 3.10
- FastAPI + Pydantic v2
- React 19 + Vite + React Flow（XYFlow）+ Dagre
- 原生 CSS
- pytest
- JSON 本地持久化
- LLM 可插拔，Phase 5 接入 OpenCode Go

## 快速启动

### 1. 启动后端和已构建前端

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000/>。

前端构建产物位于 `web/`，FastAPI 会直接托管。

### 2. 重新构建前端

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent\frontend
npm install
npm run build
```

### 3. 前端开发模式

终端 1：

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

终端 2：

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent\frontend
npm run dev
```

打开 <http://127.0.0.1:5173/>。Vite 会把 `/api` 和 `/health` 代理到 FastAPI。

## 测试

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent
.\.venv\Scripts\python.exe -m pytest
```

当前结果：**139 passed**。

前端辅助逻辑测试：

```powershell
cd C:\Users\woain\Desktop\reliability-flow-agent\frontend
npm test
```

当前结果：**9 passed**。

## 主要功能

- 通用 Process IR：start、task、decision、end。
- 条件分支、默认分支、故障出口和循环回边。
- 节点持续时间、业务 outcomes、状态和通用效果。
- 严格的结构、条件、可达性和循环验证。
- 版本化保存、内容哈希、历史版本和冲突检测。
- 从左到右的自动布局。
- React Flow 自由画布：
  - 节点拖动。
  - 创建和删除连接。
  - 缩放、平移、MiniMap、适应屏幕。
- 左侧 Agent 面板（当前为离线命令模式）。
- 右侧业务属性、连接条件和版本历史检查器。
- 独立 Reliability IR：
  - task 节点参与开关。
  - 指数分布 λ（每自然日，允许 0）。
  - 参数验证和清晰错误码。
  - 与 Process IR 的 process_id / version / content_hash 精确绑定。
  - 旧版本可靠性配置保留，但不会自动绑定到新流程版本。
- 离散事件仿真 Runtime：
  - 多设备独立状态、历史和随机流。
  - task 持续时间推进和 decision/loop 执行。
  - 指数分布可靠性区间抽样，λ=0 合法。
  - failure 出口、维修流程、状态恢复和故障计数。
  - 仿真结束时的部分暴露时间抽样。
  - 相同随机种子逐字段可复现。
  - 集中安全上限和明确错误码。
- 服务端 SVG 流程图导出和测试。

## 示例流程

- `examples/equipment_support_flow.json`
- `examples/manufacturing_flow.json`
- `examples/reliability_maintenance_flow.json`

示例只包含 Process IR，不包含 λ 或可靠性参与标记。可通过前端“导入 JSON”加载。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/processes/validate` | 校验 Process IR |
| POST | `/api/processes/preview.svg` | 从草稿生成 SVG |
| GET | `/api/processes` | 流程列表 |
| POST | `/api/processes` | 创建流程 |
| GET | `/api/processes/{id}` | 获取最新或指定版本 |
| PUT | `/api/processes/{id}` | 基于 base_version 保存新版本 |
| GET | `/api/processes/{id}/versions` | 版本历史 |
| GET | `/api/processes/{id}/diagram.svg` | 已保存版本 SVG |
| GET | `/api/processes/{id}/reliability` | 可靠性配置（指定或最新版本） |
| PUT | `/api/processes/{id}/reliability` | 保存绑定到最新 Process IR 的可靠性配置 |
| POST | `/api/processes/{id}/reliability/validate` | 验证可靠性配置和版本绑定 |
| GET | `/api/processes/{id}/reliability/history` | 可靠性 revision 历史 |
| POST | `/api/processes/{id}/simulate` | 运行离散事件仿真 |

## 目录

```text
app/
  api/              FastAPI 路由
  domain/           Process IR、Reliability IR、验证、内容哈希
  processes/        版本化 Process IR JSON 存储
  reliability/      独立 Reliability IR revision 存储
  simulation/       离散事件仿真 Runtime 与随机流
  diagram/          自动布局与 SVG
frontend/
  src/
    components/     Agent、工具栏、属性检查器
    flow/           React Flow 自定义节点和连接
web/                前端构建产物
examples/           通用示例流程
tests/              pytest
docs/               架构、Schema、Phase 1 报告
data/               本地流程与实验数据
```

## LLM 认证

- 默认关闭，不影响流程建模、校验、画布编辑和保存。
- 目标 Provider：`opencode-go`。
- 目标模型：`deepseek-v4.1-flash`。
- Base URL：`https://opencode.ai/inference/go/openai/v1`。
- 认证：运行时可读取 OpenCode 本地认证，密钥不写入源码、前端或日志。
- 没有 LLM 时使用离线命令模式。

## 已知限制

- Reliability IR 只支持指数分布；不支持 Weibull 等其他分布。
- 可靠性配置只能保存到最新 Process IR 版本。
- 仿真只支持指数分布可靠性模型。
- 仿真结果当前直接返回，尚未持久化为实验记录。
- 前端暂未增加仿真运行面板，仿真通过 HTTP API 使用。
- Agent 当前只支持有限的离线命令，不是完整 LLM 自然语言理解。
- 新节点需要显式连接到流程路径。
- 评价指标、实验比较和完整 LLM Agent 尚未实现。

参见：

- `docs/architecture.md`
- `docs/process-ir.md`
- `docs/reliability-ir.md`
- `docs/simulation-runtime.md`
- `docs/phase-1-report.md`
- `docs/phase-2-report.md`
- `docs/phase-3-report.md`
- `docs/phase-3-review.md`




