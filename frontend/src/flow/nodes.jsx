import { Handle, Position } from "@xyflow/react";

const TYPE_META = {
  start: { badge: "START", meta: "流程起点", className: "start" },
  task: { badge: "TASK", meta: "业务活动", className: "task" },
  decision: { badge: "DECIDE", meta: "条件判断", className: "decision" },
  end: { badge: "END", meta: "流程终点", className: "end" },
};

export function nodeSize(type) {
  if (type === "start" || type === "end") return { width: 176, height: 68 };
  if (type === "decision") return { width: 224, height: 124 };
  return { width: 214, height: 94 };
}

export function BusinessNode({ data, selected }) {
  const node = data.node;
  const meta = TYPE_META[node.type] ?? TYPE_META.task;
  let detail = meta.meta;
  if (node.type === "task") {
    detail = `持续 ${node.duration ?? "未设置"} 天`;
  } else if (node.type === "decision") {
    detail = "多个条件出口";
  }

  return (
    <div
      className={`biz-node biz-${meta.className} ${
        selected ? "is-selected" : ""
      }`}
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
          {meta.badge}
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

export const nodeTypes = {
  start: BusinessNode,
  task: BusinessNode,
  decision: BusinessNode,
  end: BusinessNode,
};
