import { useEffect, useRef, useState } from "react";

const QUICK_COMMANDS = [
  "创建一个装备保障流程，包含任务准备、执行任务、任务结束，依次执行。",
  "解释当前流程的结构和风险点。",
  "检查当前流程，并告诉我需要补充哪些信息。",
];

const PLACEHOLDER =
  "直接用自然语言描述业务需求，例如：装备完成任务后进行检查，如果正常则结束，如果发现故障则进入维修，维修完成后重新执行任务。";

const FLOW_REQUIREMENT_TEMPLATE = `请按下面结构描述流程；不知道的写“未确定”，不要猜。没有判断、循环或子流程时写“无”。

1. 流程目标：
2. 开始：
3. 主要步骤（按顺序）：
   - 步骤名称：
   - 前一步：
   - 下一步：
4. 判断分支（如有）：
   - 判断名称：
   - 判断依据（正常/异常如何区分）：
   - 正常分支去向：
   - 异常/故障分支去向：
   - 默认分支去向：
   - 维修后返回哪个步骤：
5. 循环（如有）：
   - 从哪个步骤回到哪个步骤：
   - 继续循环的条件：
   - 退出循环的条件：
6. 子流程（如有）：
   - 子流程名称：
   - 属于父流程哪个步骤：
   - 子流程内部步骤：
   - 子流程内部判断与分支：
   - 正常出口及返回父流程的位置：
   - 异常/故障出口及返回父流程的位置：
7. 结束：
   - 结束节点及其业务含义：
8. 未确定信息：
   - 未确定的持续时间、判断依据、分支去向等：

不要自行填写故障率、检测率或概率；未提供的参数由系统提示补充。`;

const TOOL_LABELS = {
  get_project_capabilities: "读取项目能力",
  get_process_ir_schema: "读取 Process IR Schema",
  get_reliability_ir_schema: "读取 Reliability IR Schema",
  list_process_models: "列出已保存流程",
  get_process_model: "读取已保存流程",
  get_reliability_config: "读取可靠性配置",
  analyze_requirements: "分析长文本需求",
  validate_process_model: "校验 Process IR",
  validate_reliability_model: "校验 Reliability IR",
  simulation_result: "仿真评估结果已记录",
};

const STATUS_LABELS = {
  disconnected: "未连接",
  connecting: "正在连接后端 Agent",
  ready: "已连接 Pi Agent",
  idle: "Agent 空闲",
  sending: "正在发送",
  running: "Agent 正在处理",
  retrying: "Provider 重试中",
  reconnecting: "事件流重连中",
  error: "Agent 异常",
  cancelled: "已取消",
};

function toolLabel(name) {
  return TOOL_LABELS[name] || name || "工具";
}

function validationIssues(validation) {
  return Array.isArray(validation?.issues) ? validation.issues : [];
}

function isStructureValid(validation) {
  if (!validation) return false;
  if (typeof validation.structure_valid === "boolean") {
    return validation.structure_valid;
  }
  return validation.valid === true;
}

function ValidationLine({ validation }) {
  if (!validation) {
    return <span className="agent-proposal-muted">尚未收到后端校验结果</span>;
  }
  const issues = validationIssues(validation);
  const errors = issues.filter((issue) => issue.severity === "error");
  const warnings = issues.filter((issue) => issue.severity === "warning");
  const structureValid = isStructureValid(validation);
  const label = structureValid
    ? validation.config_pending
      ? `结构校验通过，仿真参数待配置（${warnings.length} 项提示）`
      : "后端校验通过"
    : `结构校验未通过（${errors.length} 个错误）`;
  return (
    <span className={`agent-validation ${structureValid ? "good" : "bad"}`}>
      {label}
      {validation.content_hash ? (
        <code>{String(validation.content_hash).replace(/^sha256:/, "").slice(0, 12)}</code>
      ) : null}
    </span>
  );
}

function RequirementAnalysisMessage({ message }) {
  const analysis = message.analysis || {};
  const ambiguities = Array.isArray(analysis.ambiguities)
    ? analysis.ambiguities
    : [];
  const issues = validationIssues(message.validation);
  const valid = message.valid ?? message.validation?.valid;
  return (
    <div className="agent-analysis">
      <div className="agent-proposal-head">
        <div>
          <span className="eyebrow">REQUIREMENT ANALYSIS</span>
          <strong>长文本需求结构化结果</strong>
        </div>
        <span className={`pill ${valid ? "good" : "bad"}`}>
          {valid ? "分析可用于建模" : "分析需修正"}
        </span>
      </div>
      {analysis.summary && <p>{analysis.summary}</p>}
      <p className="agent-proposal-meta">
        {message.stepCount} 步骤 · {message.branchCount} 关系 · 待澄清{" "}
        {message.ambiguityCount} 项（阻塞 {message.blockingCount} 项）
      </p>
      <ValidationLine validation={message.validation} />
      {issues.length > 0 && (
        <ul className="agent-issue-list">
          {issues.slice(0, 8).map((issue, index) => (
            <li key={`${issue.code}-${index}`} className={issue.severity}>
              <code>{issue.code}</code> {issue.message}
            </li>
          ))}
        </ul>
      )}
      {ambiguities.length > 0 && (
        <ul className="agent-issue-list">
          {ambiguities.map((item) => (
            <li
              key={item.id}
              className={item.blocks_generation ? "error" : "warning"}
            >
              <code>{item.id}</code> {item.question}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ClarificationMessage({ message }) {
  const questions = Array.isArray(message.questions) ? message.questions : [];
  return (
    <div className="agent-clarification">
      <div className="agent-proposal-head">
        <div>
          <span className="eyebrow">NEEDS CLARIFICATION</span>
          <strong>需要你确认后继续</strong>
        </div>
        <span className="pill warn">{questions.length} 个问题</span>
      </div>
      {message.text && <p>{message.text}</p>}
      <ol className="agent-question-list">
        {questions.map((item) => (
          <li key={item.id || item.question}>
            <span>{item.question}</span>
            {Array.isArray(item.options) && item.options.length > 0 && (
              <span className="agent-question-options">
                {item.options.join(" / ")}
              </span>
            )}
          </li>
        ))}
      </ol>
      <p className="agent-proposal-hint">
        直接在下方输入回答；Agent 不会在澄清前编造关系或参数。
      </p>
    </div>
  );
}

function ProcessProposal({ message, onApply }) {
  const spec = message.spec || {};
  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  const edges = Array.isArray(spec.edges) ? spec.edges : [];
  const issues = validationIssues(message.validation);
  const coverage = message.coverage || message.validation?.coverage;
  const canApply = isStructureValid(message.validation) && !message.applied;
  const structureValid = isStructureValid(message.validation);
  return (
    <div className="agent-proposal">
      <div className="agent-proposal-head">
        <div>
          <span className="eyebrow">PROCESS IR PROPOSAL</span>
          <strong>{spec.name || "未命名流程"}</strong>
        </div>
        <span className={`pill ${structureValid ? "good" : "bad"}`}>
          {structureValid
            ? message.validation?.config_pending
              ? "结构合法·待配置"
              : "可应用"
            : "需修正"}
        </span>
      </div>
      <p className="agent-proposal-meta">
        {nodes.length} 个节点 · {edges.length} 条连接
        {coverage
          ? ` · 需求覆盖 ${coverage.covered_step_count}/${coverage.step_count} 步骤、${coverage.covered_branch_count}/${coverage.branch_count} 关系`
          : ""}
      </p>
      <ValidationLine validation={message.validation} />
      {issues.length > 0 && (
        <ul className="agent-issue-list">
          {issues.slice(0, 5).map((issue, index) => (
            <li key={`${issue.code}-${index}`} className={issue.severity}>
              <code>{issue.code}</code> {issue.message}
            </li>
          ))}
        </ul>
      )}
      <div className="agent-proposal-actions">
        <button
          type="button"
          className="button primary compact"
          onClick={() => onApply(message)}
          disabled={!canApply}
        >
          {message.applied ? "已应用到画布" : "应用为画布草稿"}
        </button>
        <span className="agent-proposal-hint">
          不会自动保存；应用后请检查并手动保存。
        </span>
      </div>
    </div>
  );
}

function ReliabilityProposal({ message, onApply, onSave, busy }) {
  const spec = message.spec || {};
  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  const participants = nodes.filter((node) => node.participates);
  return (
    <div className="agent-proposal">
      <div className="agent-proposal-head">
        <div>
          <span className="eyebrow">RELIABILITY IR PROPOSAL</span>
          <strong>可靠性配置 · {participants.length} 个参与节点</strong>
        </div>
        <span className={`pill ${message.validation?.valid ? "good" : "bad"}`}>
          {message.validation?.valid ? "可应用" : "需修正"}
        </span>
      </div>
      <p className="agent-proposal-meta">
        Process v{spec.process_version ?? "?"} ·{" "}
        {String(spec.process_hash || "").replace(/^sha256:/, "").slice(0, 12) || "无哈希"}
      </p>
      <ValidationLine validation={message.validation} />
      <div className="agent-reliability-table">
        {nodes.map((node) => (
          <div key={node.node_id} className="agent-reliability-row">
            <span>{node.node_id}</span>
            <span>{node.participates ? "参与" : "不参与"}</span>
            <span>
              {node.participates ? `λ=${node.lambda ?? "缺少"}` : "—"}
            </span>
          </div>
        ))}
      </div>
      <div className="agent-proposal-actions">
        <button
          type="button"
          className="button primary compact"
          onClick={() => onApply(message)}
          disabled={!!message.applied || message.validation?.valid !== true}
        >
          {message.applied ? "已应用到可靠性面板" : "应用到可靠性面板"}
        </button>
        <button
          type="button"
          className="button compact"
          onClick={() => onSave(message)}
          disabled={busy || !!message.saved || message.validation?.valid !== true}
        >
          {message.saved ? "可靠性配置已保存" : "确认并保存全部可靠性配置"}
        </button>
      </div>
      {message.saveError && <p className="form-error">{message.saveError}</p>}
    </div>
  );
}

function ToolMessage({ message }) {
  const running = message.status === "running";
  return (
    <div className={`agent-tool ${running ? "running" : message.status}`}>
      <span className={`agent-tool-dot ${running ? "running" : message.status}`} />
      <div>
        <strong>{toolLabel(message.toolName)}</strong>
        <span>
          {running
            ? "执行中"
            : message.status === "error"
              ? "执行失败"
              : "已完成"}
          {message.summary?.process_name
            ? ` · ${message.summary.process_name}`
            : ""}
          {message.summary?.node_count != null
            ? ` · ${message.summary.node_count} 节点`
            : ""}
          {message.summary?.result_id
            ? ` · ${message.summary.result_id}`
            : ""}
          {message.summary?.process_version != null
            ? ` · v${message.summary.process_version}`
            : ""}
          {typeof message.summary?.overall_reliability === "number"
            ? ` · 整体可靠度 ${(message.summary.overall_reliability * 100).toFixed(2)}%`
            : ""}
          {typeof message.summary?.end_availability === "number"
            ? ` · 完好率 ${(message.summary.end_availability * 100).toFixed(2)}%`
            : ""}
        </span>
      </div>
    </div>
  );
}

export default function AgentPanel({
  messages,
  busy,
  onSend,
  processes,
  activeProcessId,
  onOpenProcess,
  onNewProcess,
  onImport,
  agentStatus,
  currentTool,
  onCancel,
  onApplyProcessProposal,
  onApplyReliabilityProposal,
  onSaveReliabilityProposal,
  reliabilityBusy,
}) {
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const submit = () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    onSend(text);
  };

  const insertTemplate = () => {
    if (input.trim()) {
      const replace = window.confirm(
        "输入框已有内容，是否用流程需求模板替换？",
      );
      if (!replace) return;
    }
    setInput(FLOW_REQUIREMENT_TEMPLATE);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const statusText = STATUS_LABELS[agentStatus] || agentStatus || "未连接";

  return (
    <aside className="agent-panel">
      <div className="agent-header">
        <div className="agent-identity">
          <div className="agent-avatar">AI</div>
          <div>
            <strong>流程建模 Agent</strong>
            <span>
              <i className={`live-dot ${agentStatus === "error" ? "bad" : ""}`} />
              {statusText}
              {currentTool ? ` · ${toolLabel(currentTool)}` : ""}
            </span>
          </div>
        </div>
        {busy && onCancel && (
          <button type="button" className="button compact danger" onClick={onCancel}>
            取消执行
          </button>
        )}
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((message, index) => {
          const key = message.id || `${message.role}-${index}`;
          if (message.role === "tool") {
            return (
              <div key={key} className="chat-message tool">
                <ToolMessage message={message} />
              </div>
            );
          }
          if (message.role === "error") {
            return (
              <div key={key} className="chat-message error">
                <div className="chat-role">错误</div>
                <div className="chat-bubble">{message.text}</div>
              </div>
            );
          }
          if (message.role === "analysis") {
            return (
              <div key={key} className="chat-message analysis">
                <RequirementAnalysisMessage message={message} />
              </div>
            );
          }
          if (message.role === "clarification") {
            return (
              <div key={key} className="chat-message clarification">
                <ClarificationMessage message={message} />
              </div>
            );
          }
          if (message.role === "proposal" && message.kind === "process_ir") {
            return (
              <div key={key} className="chat-message proposal">
                <ProcessProposal
                  message={message}
                  onApply={onApplyProcessProposal}
                />
              </div>
            );
          }
          if (message.role === "proposal" && message.kind === "reliability_ir") {
            return (
              <div key={key} className="chat-message proposal">
                <ReliabilityProposal
                  message={message}
                  onApply={onApplyReliabilityProposal}
                  onSave={onSaveReliabilityProposal}
                  busy={reliabilityBusy}
                />
              </div>
            );
          }
          return (
            <div key={key} className={`chat-message ${message.role}`}>
              <div className="chat-role">
                {message.role === "assistant" ? "Agent" : "你"}
              </div>
              <div className={`chat-bubble ${message.streaming ? "streaming" : ""}`}>
                {message.text}
                {message.streaming && <span className="streaming-cursor" />}
              </div>
            </div>
          );
        })}
        {busy && (
          <div className="chat-message assistant">
            <div className="chat-role">Agent</div>
            <div className="chat-bubble thinking">
              <span className="thinking-dot" />
              <span className="thinking-dot" />
              <span className="thinking-dot" />
              {currentTool ? ` 正在执行 ${toolLabel(currentTool)}` : " 正在思考"}
            </div>
          </div>
        )}
      </div>

      <div className="quick-commands">
        {QUICK_COMMANDS.map((command) => (
          <button
            key={command}
            type="button"
            className="quick-chip"
            onClick={() => onSend(command)}
            disabled={busy}
          >
            {command}
          </button>
        ))}
      </div>

      <div className="composer">
        <textarea
          ref={textareaRef}
          value={input}
          placeholder={PLACEHOLDER}
          rows={3}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="composer-footer">
          <div className="composer-hints">
            <span>Enter 发送，Shift+Enter 换行</span>
            <span>模板只会填入输入框，不会自动提交</span>
          </div>
          <div className="composer-actions">
            <button
              type="button"
              className="button compact template-trigger"
              onClick={insertTemplate}
              disabled={busy}
            >
              使用模板
            </button>
            <button
              type="button"
              className="button primary compact"
              onClick={submit}
              disabled={busy || !input.trim()}
            >
              发送
            </button>
          </div>
        </div>
      </div>

      <details className="process-library" open>
        <summary>
          <span>流程库</span>
          <span className="library-count">{processes.length}</span>
        </summary>
        <div className="library-actions">
          <button type="button" className="button compact" onClick={onNewProcess}>
            新建流程
          </button>
          <button type="button" className="button compact" onClick={onImport}>
            导入 JSON
          </button>
        </div>
        <div className="process-list">
          {processes.length === 0 && (
            <p className="empty-library">还没有已保存流程。</p>
          )}
          {processes.map((process) => (
            <button
              type="button"
              key={process.process_id}
              className={`process-item ${
                process.process_id === activeProcessId ? "active" : ""
              }`}
              onClick={() => onOpenProcess(process.process_id)}
            >
              <span className="process-name">{process.name}</span>
              <span className="process-meta">
                v{process.latest_version} · {process.node_count} 节点 ·{" "}
                {process.edge_count} 连接
              </span>
              <span className="process-id">{process.process_id}</span>
            </button>
          ))}
        </div>
      </details>
    </aside>
  );
}
