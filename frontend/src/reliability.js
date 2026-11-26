export const LAMBDA_UNIT = "per_day";
export const DISTRIBUTION = "exponential";

export function validateLambdaInput(participates, rawValue) {
  if (!participates) {
    return { lambda: null, error: "" };
  }
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return { lambda: null, error: "参与可靠性计算时必须填写 λ" };
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { lambda: null, error: "λ 必须是有限数字" };
  }
  if (value < 0) {
    return { lambda: null, error: "λ 必须大于或等于 0" };
  }
  return { lambda: value, error: "" };
}

export function buildReliabilityNodes(
  tasks,
  existingNodes,
  editNodeId,
  edit,
) {
  const existing = new Map(
    (existingNodes || []).map((node) => [node.node_id, node]),
  );
  return (tasks || [])
    .filter((task) => !task.type || task.type === "task")
    .map((task) => {
    const current = existing.get(task.id);
    if (task.id === editNodeId) {
      const lambda = edit.participates
        ? (edit.lambda ?? null)
        : (edit.lambda ?? current?.lambda ?? null);
      return {
        node_id: task.id,
        participates: Boolean(edit.participates),
        distribution: DISTRIBUTION,
        lambda: lambda ?? null,
        lambda_unit: LAMBDA_UNIT,
      };
    }
    return {
      node_id: task.id,
      participates: Boolean(current?.participates),
      distribution: current?.distribution || DISTRIBUTION,
      lambda: current?.lambda ?? null,
      lambda_unit: current?.lambda_unit || LAMBDA_UNIT,
    };
  });
}

export function reliabilityNodeFor(reliability, nodeId) {
  if (!reliability || !Array.isArray(reliability.nodes)) return null;
  return reliability.nodes.find((node) => node.node_id === nodeId) || null;
}

export function formatLambda(value) {
  if (value === null || value === undefined || value === "") return "未配置";
  return `${value} 次/自然日`;
}
