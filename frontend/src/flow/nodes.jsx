import { Handle, Position } from "@xyflow/react";

const TYPE_META = {
  start: { badge: "START", meta: "流程起点", className: "start" },
  task: { badge: "TASK", meta: "业务活动", className: "task" },
  decision: { badge: "DECIDE", meta: "条件判断", className: "decision" },
  end: { badge: "END", meta: "流程终点", className: "end" },
  subprocess: { badge: "SUBPROCESS", meta: "嵌套流程块", className: "subprocess" },
};

export function nodeSize(type) {
  if (type === "start" || type === "end") return { width: 176, height: 68 };
  if (type === "decision") return { width: 224, height: 126 };
  if (type === "subprocess") return { width: 330, height: 158 };
  return { width: 214, height: 94 };
}

const UNIT_LABELS = {
  hour: "小时",
  day: "天",
  month: "月",
  year: "年",
};

export function BusinessNode({ data, selected }) {
  const node = data.node;
  const meta = TYPE_META[node.type] ?? TYPE_META.task;
  const inner = Boolean(data.inner);
  let detail = meta.meta;
  if (node.type === "task") {
    const unit = UNIT_LABELS[data.unit] || "天";
    detail = data.isTestModule
      ? `测试模块 · Ft=${data.detectionRate ?? "未配置"}`
      : `持续 ${node.duration ?? "未设置"} ${unit} · 仅持续时间`;
  } else if (node.type === "decision") {
    detail = "多个条件出口";
  } else if (node.type === "subprocess") {
    detail = "嵌套流程块";
  }

  return (
    <div
      className={`biz-node biz-${meta.className} ${
        selected ? "is-selected" : ""
      } ${inner ? "is-inner" : ""}`}
      title={node.description || node.name}
    >
      {node.type !== "start" && (
        <Handle
          id="in"
          type="target"
          position={Position.Left}
          className="biz-handle"
        />
      )}
      <div className="biz-node-strip" />
      <div className="biz-node-head">
        <span className="biz-node-badge">
          {node.type === "decision" && <i className="decision-mark" />}
          {data.isTestModule ? "TEST" : meta.badge}
        </span>
        <span className="biz-node-id">{node.id}</span>
      </div>
      <div className="biz-node-title">{node.name}</div>
      <div className="biz-node-meta">{detail}</div>
      {node.type !== "end" && (
        <Handle
          id="out"
          type="source"
          position={Position.Right}
          className="biz-handle"
        />
      )}
    </div>
  );
}

export function SubprocessNode({ data, selected }) {
  const node = data.node;
  const preview = data.preview || {};
  const previewNodes = preview.previewNodes || [];
  return (
    <div
      className={`subprocess-node ${selected ? "is-selected" : ""} ${
        data.expanded ? "is-expanded" : "is-collapsed"
      }`}
    >
      <Handle
        id="in"
        type="target"
        position={Position.Left}
        className="biz-handle subprocess-handle"
      />
      <div className="subprocess-header">
        <div>
          <span className="subprocess-badge">SUBPROCESS</span>
          <strong>{node.name}</strong>
          <span className="subprocess-id">{node.id}</span>
        </div>
        <div className="subprocess-header-actions">
          <button
            type="button"
            className={`subprocess-param-button ${
              data.hasLambda ? "configured" : "missing"
            }`}
            title="设置阶段故障率 λ"
            onClick={(event) => {
              event.stopPropagation();
              data.onEditParameters?.();
            }}
          >
            λ 参数
          </button>
          <button
            type="button"
            className="subprocess-toggle"
            onClick={(event) => {
              event.stopPropagation();
              data.onToggle?.();
            }}
          >
            {data.expanded ? "收起" : "展开"}
          </button>
        </div>
      </div>
      <div className="subprocess-meta">
        <span>{preview.internalCount ?? 0} 个内部节点</span>
        <span
          className={`subprocess-lambda ${
            data.hasLambda ? "configured" : "missing"
          }`}
        >
          {data.hasLambda ? data.lambdaLabel : "未配置阶段故障率 λ"}
        </span>
        {preview.hasLoop && <span className="subprocess-flag loop">含循环</span>}
        {preview.hasFailureExit && (
          <span className="subprocess-flag failure">含异常出口</span>
        )}
      </div>
      {!data.expanded && (
        <div className="subprocess-preview">
          {previewNodes.length === 0 && (
            <span className="subprocess-empty">暂无内部节点</span>
          )}
          {previewNodes.map((child) => (
            <span key={child.id} className={`preview-chip preview-${child.type}`}>
              <i>{child.type.toUpperCase()}</i>
              {child.name}
            </span>
          ))}
          {(preview.directCount || 0) > previewNodes.length && (
            <span className="preview-more">
              +{(preview.directCount || 0) - previewNodes.length}
            </span>
          )}
        </div>
      )}
      {data.expanded && (
        <div className="subprocess-expanded-hint">内部节点在主画布中直接编辑</div>
      )}
      <Handle
        id="out"
        type="source"
        position={Position.Right}
        className="biz-handle subprocess-handle"
      />
    </div>
  );
}

export const nodeTypes = {
  start: BusinessNode,
  task: BusinessNode,
  decision: BusinessNode,
  end: BusinessNode,
  subprocess: SubprocessNode,
};
