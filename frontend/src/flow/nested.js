import dagre from "@dagrejs/dagre";

export const BLOCK_HEADER = 58;
export const BLOCK_PADDING = 18;
export const COLLAPSED_WIDTH = 330;
export const COLLAPSED_HEIGHT = 158;

const BASE_SIZE = {
  start: { width: 176, height: 68 },
  end: { width: 176, height: 68 },
  decision: { width: 224, height: 126 },
  task: { width: 214, height: 94 },
};

export const EDGE_COLORS = {
  normal: "#64748b",
  conditional: "#7c3aed",
  default: "#0f766e",
  failure: "#dc2626",
};

export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeNode(node) {
  const normalized = {
    ...node,
    position: node.position ? { ...node.position } : null,
    on_enter: node.on_enter || [],
    on_complete: node.on_complete || [],
    outcomes: node.outcomes || [],
  };
  if (node.subflow) {
    normalized.subflow = normalizeSubflow(node.subflow);
  }
  return normalized;
}

function normalizeSubflow(subflow) {
  return {
    start_node_id: subflow.start_node_id || "",
    end_node_ids: Array.isArray(subflow.end_node_ids)
      ? [...subflow.end_node_ids]
      : [],
    nodes: (subflow.nodes || []).map(normalizeNode),
    edges: (subflow.edges || []).map((edge) => ({
      ...edge,
      from: edge.from ?? edge.source,
      to: edge.to ?? edge.target,
    })),
    guards: {
      max_node_visits: subflow.guards?.max_node_visits ?? 10000,
    },
  };
}

export function normalizeSpec(raw) {
  const source = raw && raw.process ? raw.process : raw;
  return {
    schema_version: source.schema_version || "process-ir/1.0",
    name: source.name || "未命名流程",
    description: source.description || "",
    status_catalog: Array.isArray(source.status_catalog)
      ? clone(source.status_catalog)
      : [],
    start_node_id: source.start_node_id || "",
    end_node_ids: Array.isArray(source.end_node_ids)
      ? [...source.end_node_ids]
      : [],
    nodes: (source.nodes || []).map(normalizeNode),
    edges: (source.edges || []).map((edge) => ({
      ...edge,
      from: edge.from ?? edge.source,
      to: edge.to ?? edge.target,
    })),
    guards: {
      max_node_visits: source.guards?.max_node_visits ?? 10000,
    },
  };
}

function syncScope(scope) {
  scope.nodes = (scope.nodes || []).map((node) => {
    if (node.subflow) {
      return { ...node, subflow: syncScope(node.subflow) };
    }
    return node;
  });
  const starts = scope.nodes.filter((node) => node.type === "start");
  const ends = scope.nodes.filter((node) => node.type === "end");
  scope.start_node_id = starts[0]?.id || "";
  scope.end_node_ids = ends.map((node) => node.id);
  return scope;
}

export function syncSpecialRefs(spec) {
  return syncScope(clone(spec));
}

export function getScope(spec, path = []) {
  let scope = spec;
  for (const blockId of path) {
    const node = scope?.nodes?.find((item) => item.id === blockId);
    if (!node?.subflow) return null;
    scope = node.subflow;
  }
  return scope;
}

export function walkScopes(spec, visitor, path = []) {
  visitor(spec, path);
  for (const node of spec.nodes || []) {
    if (node.subflow) {
      walkScopes(node.subflow, visitor, [...path, node.id]);
    }
  }
}

export function findNode(spec, nodeId, path = []) {
  for (const node of spec.nodes || []) {
    if (node.id === nodeId) {
      return { node, scope: spec, path, parentId: path.at(-1) || null };
    }
    if (node.subflow) {
      const found = findNode(node.subflow, nodeId, [...path, node.id]);
      if (found) return found;
    }
  }
  return null;
}

export function findEdge(spec, edgeId, path = []) {
  for (const edge of spec.edges || []) {
    if (edge.id === edgeId) return { edge, scope: spec, path };
  }
  for (const node of spec.nodes || []) {
    if (node.subflow) {
      const found = findEdge(node.subflow, edgeId, [...path, node.id]);
      if (found) return found;
    }
  }
  return null;
}

export function listTasks(spec) {
  const tasks = [];
  walkScopes(spec, (scope) => {
    for (const node of scope.nodes || []) {
      if (node.type === "task") tasks.push(node);
    }
  });
  return tasks;
}

export function listReliabilityNodes(spec) {
  const nodes = [];
  walkScopes(spec, (scope) => {
    for (const node of scope.nodes || []) {
      if (node.type === "task" || node.type === "subprocess") {
        nodes.push(node);
      }
    }
  });
  return nodes;
}

const LAMBDA_UNIT_LABELS = {
  hour: "每小时",
  day: "每天",
  month: "每月",
  year: "每年",
};

function lambdaLabel(config, unit) {
  if (!config || config.lambda === null || config.lambda === undefined) {
    return "未配置 λ";
  }
  return `${config.lambda} 次/${LAMBDA_UNIT_LABELS[unit] || "每天"}`;
}

export function countInternalNodes(node) {
  let count = 0;
  for (const child of node.subflow?.nodes || []) {
    count += 1;
    if (child.subflow) count += countInternalNodes(child);
  }
  return count;
}

export function scopeHasCycle(scope) {
  const adjacency = {};
  for (const node of scope.nodes || []) adjacency[node.id] = [];
  for (const edge of scope.edges || []) {
    if (adjacency[edge.from] && adjacency[edge.to]) {
      adjacency[edge.from].push(edge.to);
    }
  }
  const visiting = new Set();
  const visited = new Set();
  const visit = (nodeId) => {
    if (visiting.has(nodeId)) return true;
    if (visited.has(nodeId)) return false;
    visiting.add(nodeId);
    for (const target of adjacency[nodeId] || []) {
      if (visit(target)) return true;
    }
    visiting.delete(nodeId);
    visited.add(nodeId);
    return false;
  };
  return (scope.nodes || []).some((node) => visit(node.id));
}

export function baseNodeSize(node) {
  if (node.type === "subprocess") return blockFullSize(node);
  return BASE_SIZE[node.type] || BASE_SIZE.task;
}

export function subflowBounds(subflow) {
  const children = subflow?.nodes || [];
  if (children.length === 0) {
    return { minX: 0, minY: 0, maxX: 0, maxY: 0, empty: true };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of children) {
    const size = baseNodeSize(node);
    const x = node.position?.x ?? 0;
    const y = node.position?.y ?? 0;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + size.width);
    maxY = Math.max(maxY, y + size.height);
  }
  return { minX, minY, maxX, maxY, empty: false };
}

export function blockFullSize(node) {
  const bounds = subflowBounds(node.subflow);
  if (bounds.empty) {
    return { width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT };
  }
  return {
    width: Math.max(
      COLLAPSED_WIDTH,
      bounds.maxX - bounds.minX + BLOCK_PADDING * 2,
    ),
    height: Math.max(
      COLLAPSED_HEIGHT,
      BLOCK_HEADER + bounds.maxY - bounds.minY + BLOCK_PADDING * 2,
    ),
  };
}

export function blockSize(node, expanded) {
  return expanded ? blockFullSize(node) : {
    width: COLLAPSED_WIDTH,
    height: COLLAPSED_HEIGHT,
  };
}

function layoutScope(scope, isRoot = false) {
  for (const node of scope.nodes || []) {
    if (node.subflow) layoutScope(node.subflow, false);
  }
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: "LR",
    nodesep: isRoot ? 86 : 56,
    ranksep: isRoot ? 150 : 104,
    edgesep: isRoot ? 34 : 24,
    marginx: isRoot ? 60 : 0,
    marginy: isRoot ? 60 : 0,
  });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of scope.nodes || []) {
    const size = baseNodeSize(node);
    graph.setNode(node.id, { width: size.width, height: size.height });
  }
  const ids = new Set((scope.nodes || []).map((node) => node.id));
  for (const edge of scope.edges || []) {
    if (ids.has(edge.from) && ids.has(edge.to)) {
      graph.setEdge(edge.from, edge.to);
    }
  }
  dagre.layout(graph);
  for (const node of scope.nodes || []) {
    const laidOut = graph.node(node.id);
    const size = baseNodeSize(node);
    node.position = {
      x: Math.round((laidOut?.x || 0) - size.width / 2),
      y: Math.round((laidOut?.y || 0) - size.height / 2),
    };
  }
  if (!isRoot) {
    const bounds = subflowBounds(scope);
    if (!bounds.empty && (bounds.minX !== 0 || bounds.minY !== 0)) {
      for (const node of scope.nodes || []) {
        node.position = {
          x: Math.round((node.position?.x || 0) - bounds.minX),
          y: Math.round((node.position?.y || 0) - bounds.minY),
        };
      }
    }
  }
}

export function autoLayoutSpec(spec) {
  const next = clone(spec);
  layoutScope(next, true);
  return syncSpecialRefs(next);
}

export function scopeNeedsPositions(scope) {
  let missing = (scope.nodes || []).some((node) => !node.position);
  for (const node of scope.nodes || []) {
    if (node.subflow && scopeNeedsPositions(node.subflow)) missing = true;
  }
  return missing;
}

export function ensurePositions(spec) {
  return scopeNeedsPositions(spec) ? autoLayoutSpec(spec) : spec;
}

export function updateNode(spec, nodeId, updatedNode) {
  const next = clone(spec);
  const found = findNode(next, nodeId);
  if (!found) return spec;
  const index = found.scope.nodes.findIndex((node) => node.id === nodeId);
  const previous = found.scope.nodes[index];
  found.scope.nodes[index] = {
    ...previous,
    ...updatedNode,
    subflow: updatedNode.subflow ?? previous.subflow,
  };
  return syncSpecialRefs(next);
}

export function updateNodePosition(spec, nodeId, position) {
  const next = clone(spec);
  const found = findNode(next, nodeId);
  if (!found) return spec;
  found.node.position = {
    x: Math.round(position.x),
    y: Math.round(position.y),
  };
  return next;
}

export function updateEdge(spec, edgeId, updatedEdge) {
  const next = clone(spec);
  const found = findEdge(next, edgeId);
  if (!found) return spec;
  const index = found.scope.edges.findIndex((edge) => edge.id === edgeId);
  found.scope.edges[index] = updatedEdge;
  return next;
}

export function deleteNodes(spec, nodeIds) {
  const ids = new Set(nodeIds);
  const next = clone(spec);
  const prune = (scope) => {
    scope.nodes = (scope.nodes || []).filter((node) => !ids.has(node.id));
    scope.edges = (scope.edges || []).filter(
      (edge) => !ids.has(edge.from) && !ids.has(edge.to),
    );
    for (const node of scope.nodes) {
      if (node.subflow) prune(node.subflow);
    }
    return scope;
  };
  prune(next);
  return syncSpecialRefs(next);
}

export function deleteEdges(spec, edgeIds) {
  const ids = new Set(edgeIds);
  const next = clone(spec);
  const prune = (scope) => {
    scope.edges = (scope.edges || []).filter((edge) => !ids.has(edge.id));
    for (const node of scope.nodes || []) {
      if (node.subflow) prune(node.subflow);
    }
  };
  prune(next);
  return next;
}

export function nextNodeId(spec, type) {
  const ids = new Set();
  walkScopes(spec, (scope) => {
    for (const node of scope.nodes || []) ids.add(node.id);
  });
  if (type === "start" && !ids.has("start")) return "start";
  if (type === "end" && !ids.has("end")) return "end";
  let index = 1;
  while (ids.has(`${type}_${index}`)) index += 1;
  return `${type}_${index}`;
}

export function nextEdgeId(spec, source, target) {
  const ids = new Set();
  walkScopes(spec, (scope) => {
    for (const edge of scope.edges || []) ids.add(edge.id);
  });
  const base = `e_${source}_${target}`;
  if (!ids.has(base)) return base;
  let index = 2;
  while (ids.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

export function addNode(spec, path, node) {
  const next = clone(spec);
  const scope = getScope(next, path);
  if (!scope) return spec;
  scope.nodes.push(node);
  return syncSpecialRefs(next);
}

export function addEdge(spec, path, edge) {
  const next = clone(spec);
  const scope = getScope(next, path);
  if (!scope) return spec;
  scope.edges.push(edge);
  return next;
}

export function createSubprocessNode(spec, path, position, name = "嵌套流程块") {
  const id = nextNodeId(spec, "subprocess");
  const startId = `${id}_start`;
  const endId = `${id}_end`;
  return {
    id,
    type: "subprocess",
    name,
    description: "",
    position,
    status_on_enter: null,
    status_on_complete: null,
    on_enter: [],
    on_complete: [],
    outcomes: [],
    subflow: {
      start_node_id: startId,
      end_node_ids: [endId],
      nodes: [
        { id: startId, type: "start", name: "子流程开始", position: { x: 40, y: 80 } },
        { id: endId, type: "end", name: "子流程结束", position: { x: 300, y: 80 } },
      ],
      edges: [
        {
          id: `${id}_e_start_end`,
          from: startId,
          to: endId,
          kind: "normal",
          label: "",
          priority: 0,
        },
      ],
      guards: { max_node_visits: 10000 },
    },
  };
}

export function toggleBlock(expanded, blockId) {
  return { ...expanded, [blockId]: !expanded[blockId] };
}

export function flowPositionToSpec(position, parentId) {
  if (!parentId) return { x: position.x, y: position.y };
  return {
    x: position.x - BLOCK_PADDING,
    y: position.y - BLOCK_HEADER - BLOCK_PADDING,
  };
}

function displayPosition(node, parentId) {
  if (!parentId) return node.position || { x: 0, y: 0 };
  return {
    x: (node.position?.x || 0) + BLOCK_PADDING,
    y: (node.position?.y || 0) + BLOCK_HEADER + BLOCK_PADDING,
  };
}

function previewForNode(node) {
  const subflow = node.subflow || { nodes: [], edges: [] };
  const nodes = subflow.nodes || [];
  const previewNodes = nodes
    .filter((child) => child.type !== "start" && child.type !== "end")
    .slice(0, 3)
    .map((child) => ({ id: child.id, name: child.name, type: child.type }));
  const hasLoop = scopeHasCycle(subflow);
  const hasFailureExit = (subflow.edges || []).some(
    (edge) => edge.kind === "failure",
  );
  return {
    previewNodes,
    internalCount: countInternalNodes(node),
    directCount: nodes.length,
    hasLoop,
    hasFailureExit,
  };
}

export function toFlowNodes(
  spec,
  selectedNodeId,
  expandedBlocks = {},
  onToggle,
  options = {},
) {
  const {
    onEditParameters = null,
    reliabilityByNode = {},
    unit = "day",
  } = options;
  const result = [];
  const addScope = (scope, path) => {
    const parentId = path.at(-1) || null;
    for (const node of scope.nodes || []) {
      if (node.type === "subprocess") {
        const expanded = Boolean(expandedBlocks[node.id]);
        const size = blockSize(node, expanded);
        const preview = previewForNode(node);
        const config = reliabilityByNode[node.id];
        const isStage = config?.module_type === "stage";
        result.push({
          id: node.id,
          type: "subprocess",
          position: displayPosition(node, parentId),
          data: {
            node,
            path,
            parentId,
            expanded,
            preview,
            lambdaLabel: isStage ? lambdaLabel(config, unit) : null,
            hasLambda: Boolean(isStage),
            onToggle: onToggle ? () => onToggle(node.id) : undefined,
            onEditParameters: onEditParameters
              ? () => onEditParameters(node.id)
              : undefined,
          },
          selected: node.id === selectedNodeId,
          draggable: true,
          deletable: true,
          connectable: true,
          zIndex: 0,
          style: { width: size.width, height: size.height },
          ...(parentId ? { parentId, extent: "parent", expandParent: true } : {}),
        });
        if (expanded) {
          addScope(node.subflow, [...path, node.id]);
        }
      } else {
        const size = baseNodeSize(node);
        const config = reliabilityByNode[node.id];
        const isTestModule = config?.module_type === "test";
        result.push({
          id: node.id,
          type: node.type,
          position: displayPosition(node, parentId),
          data: {
            node,
            path,
            parentId,
            inner: path.length > 0,
            isTestModule,
            detectionRate: isTestModule ? config?.detection_rate : null,
            unit,
            onEditParameters: onEditParameters
              ? () => onEditParameters(node.id)
              : undefined,
          },
          selected: node.id === selectedNodeId,
          draggable: true,
          deletable: true,
          connectable: true,
          zIndex: 1,
          style: { width: size.width },
          ...(parentId ? { parentId, extent: "parent", expandParent: true } : {}),
        });
      }
    }
  };
  addScope(spec, []);
  return result;
}

export function toFlowEdges(
  spec,
  selectedEdgeId,
  expandedBlocks = {},
  edgeLabel = () => "",
) {
  const result = [];
  const addScope = (scope, path) => {
    const nodeMap = new Map((scope.nodes || []).map((node) => [node.id, node]));
    for (const edge of scope.edges || []) {
      const source = nodeMap.get(edge.from);
      const target = nodeMap.get(edge.to);
      const isSelf = edge.from === edge.to;
      const isBack =
        isSelf ||
        (source?.position &&
          target?.position &&
          target.position.x < source.position.x);
      const color = EDGE_COLORS[edge.kind] || EDGE_COLORS.normal;
      const inner = path.length > 0;
      result.push({
        id: edge.id,
        source: edge.from,
        target: edge.to,
        sourceHandle: "out",
        targetHandle: "in",
        type: "business",
        label: edgeLabel(edge),
        selected: edge.id === selectedEdgeId,
        deletable: true,
        data: {
          kind: edge.kind,
          color,
          isBack: Boolean(isBack),
          inner,
          depth: path.length,
          scopePath: path,
          subflowExit: edge.subflow_exit || null,
        },
        markerEnd: {
          type: "arrowclosed",
          color,
          width: inner ? 14 : 18,
          height: inner ? 14 : 18,
        },
        style: {
          stroke: color,
          strokeWidth: inner ? 1.3 : 1.8,
          ...(inner ? { strokeDasharray: "4 3" } : {}),
        },
      });
    }
    for (const node of scope.nodes || []) {
      if (node.subflow && expandedBlocks[node.id]) {
        addScope(node.subflow, [...path, node.id]);
      }
    }
  };
  addScope(spec, []);
  return result;
}

export function collectBlockNodeIds(spec, blockId) {
  const found = findNode(spec, blockId);
  if (!found) return [];
  const ids = [blockId];
  const walk = (node) => {
    for (const child of node.subflow?.nodes || []) {
      ids.push(child.id);
      if (child.subflow) walk(child);
    }
  };
  walk(found.node);
  return ids;
}
