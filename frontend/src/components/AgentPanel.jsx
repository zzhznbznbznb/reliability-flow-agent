import { useEffect, useRef, useState } from "react";

const QUICK_COMMANDS = [
  "创建一个装备保障流程，包含任务准备、执行任务、任务结束，依次执行。",
  "解释当前流程的结构和风险点。",
  "检查当前流程，并告诉我需要补充哪些信息。",
];

const PLACEHOLDER =
  "直接用自然语言描述业务需求，例如：装备完成任务后进行检查，如果正常则结束，如果发现故障则进入维修，维修完成后重新执行任务。";

const TOOL_LABELS = {
  get_project_capabilities: "读取项目能力",
  get_process_ir_schema: "读取 Process IR Schema",
  get_reliability_ir_schema: "读取 Reliability IR Schema",
  list_process_models: "列出已保存流程",
  get_process_model: "读取已保存流程",
  get_reliability_config: "读取可靠性配置",
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

function ValidationLine({ validation }) {
  if (!validation) {
    return <span className="agent-proposal-muted">尚未收到后端校验结果</span>;
  }
  const issues = validationIssues(validation);
  const errors = issues.filter((issue) => issue.severity === "error");
  return (
    <span className={`agent-validation ${validation.valid ? "good" : "bad"}`}>
      {validation.valid ? "后端校验通过" : `后端校验未通过（${errors.length} 个错误）`}
      {validation.content_hash ? (
        <code>{String(validation.content_hash).replace(/^sha256:/, "").slice(0, 12)}</code>
      ) : null}
    </span>
  );
}

function ProcessProposal({ message, onApply }) {
  const spec = message.spec || {};
  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  const edges = Array.isArray(spec.edges) ? spec.edges : [];
  const issues = validationIssues(message.validation);
  const canApply = message.validation?.valid === true && !message.applied;
  return (
    <div className="agent-proposal">
      <div className="agent-proposal-head">
        <div>
          <span className="eyebrow">PROCESS IR PROPOSAL</span>
          <strong>{spec.name || "未命名流程"}</strong>
        </div>
        <span className={`pill ${message.validation?.valid ? "good" : "bad"}`}>
          {message.validation?.valid ? "可应用" : "需修正"}
        </span>
      </div>
      <p className="agent-proposal-meta">
        {nodes.length} 个节点 · {edges.length} 条连接
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
          <span>Enter 发送，Shift+Enter 换行</span>
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
