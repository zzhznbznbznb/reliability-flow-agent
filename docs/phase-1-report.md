# Phase 1 开发报告

## 1. 已完成

### Process IR

- Pydantic v2 Schema，`extra="forbid"`。
- start、task、decision、end 节点。
- normal、conditional、default、failure 连接。
- 条件表达式、业务 outcomes、节点效果、状态目录。
- 节点画布坐标 `position`。
- 内容哈希和版本快照。
- Process IR 与 Reliability IR 字段严格隔离。

### 验证器

- 节点和边 ID 唯一性。
- 连接端点、start、end、可达性和结束路径。
- task 持续时间。
- decision 多出口、条件出口和 default。
- 条件字段、操作符、嵌套深度和属性引用。
- 自循环和多出口歧义。
- 循环出口、循环 decision 和退出状态更新。
- 状态、效果和计数器引用。
- 结构化错误码、节点、连接和字段定位。

### 版本存储

- JSON 原子写入。
- 每次修改生成新版本。
- 内容未变化不重复生成版本。
- `base_version` 冲突检测。
- 保留全部历史版本。
- 列表、指定版本、版本摘要。

### 流程图

- 服务端自动布局和 SVG 导出。
- 手动坐标渲染。
- 分支、条件和循环回边。
- React Flow 交互画布。
- 节点自由拖动、连接创建/删除、画布缩放/平移、MiniMap、Controls、fitView。
- Dagre 从左到右自动布局。

### 前端

- 左侧常驻 Agent 面板：
  - 离线命令：添加/删除/重命名节点、连接节点、解释流程、校验、自动布局。
  - 流程库和导入 JSON。
- 中间 React Flow 画布：
  - 业务卡片节点。
  - decision 可视化。
  - 条件边标签。
  - 虚线循环回边。
  - 选中节点/连接后同步右侧检查器。
- 右侧属性检查器：
  - 节点名称、类型、说明、持续时间、状态、outcomes、effects。
  - 连接类型、标签、优先级、条件 JSON。
  - 流程名称、说明、guards、状态目录。
  - 版本历史。
  - Reliability 标签页占位，明确标注 Phase 2，不写入 Process IR。
- 自动校验、保存前强制校验、错误详情、版本冲突提示。

### API

- 流程校验。
- 草稿 SVG 预览。
- 流程 CRUD。
- 版本历史。
- 已保存流程 SVG。
- 统一 Schema 错误格式。

## 2. 测试

自动化测试：

```text
53 passed
```

覆盖：

- Schema 和可靠性字段隔离。
- 内容哈希稳定性。
- 节点/边/start/end/duration 错误。
- decision 规则。
- 条件规则。
- 可达性和结束路径。
- 循环出口、循环 decision、退出状态更新。
- 状态和属性引用。
- 存储创建、更新、历史、冲突。
- SVG 生成、转义、手动布局。
- API CRUD、版本、冲突、预览、404、422。
- 构建后的前端由 FastAPI 托管。
- 两个通用示例流程。

真实浏览器交互测试：

- React Flow 节点渲染。
- Agent 添加节点。
- 右侧改名。
- Agent 删除节点。
- 自动布局。
- 保存 v2 并出现成功提示。
- 节点拖动。
- 从 handle 创建连接。
- 连接检查器识别。
- 删除连接。
- 浏览器控制台无错误。

## 3. 尚未完成

- Reliability IR 和可靠性参数保存。
- 右侧可靠性开关和 λ 的持久化。
- 仿真 Runtime。
- 评价指标。
- 实验管理。
- OpenCode LLM 真实自然语言接入。
- 更复杂的条件可视化编辑器（当前为 JSON 条件编辑）。
- 多用户、鉴权和并发锁文件。

## 4. 已知限制

- Agent 当前是规则命令，不是完整自然语言理解。
- 添加的新节点不会自动插入到已有路径中；用户或 Agent 需要显式连接。
- 保存前校验会阻止未连接节点、无效分支和无效循环。
- 服务端 SVG 与 React Flow 在视觉细节上存在差异，但数据源一致。
- 前端生产包约 556 KB，主要来自 React Flow。

## 5. 下一阶段

Phase 2 将新增独立的 Reliability IR：

- 节点级参与开关。
- 指数分布。
- λ 合法性。
- 与 Process IR 版本的绑定。
- 右侧可靠性面板实际保存。
