import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";

import { api, issuesFromError } from "./api";
import { nodeTypes, nodeSize } from "./flow/nodes";
import { edgeTypes } from "./flow/edges";
import * as nested from "./flow/nested";
import AgentPanel from "./components/AgentPanel";
import Toolbar from "./components/Toolbar";
import Inspector from "./components/Inspector";
import SimulationPanel from "./components/SimulationPanel";
import ProjectPanel from "./components/ProjectPanel";
import {
  buildReliabilityNodes,
  reliabilityNodeFor,
  validateReliabilityReadiness,
} from "./reliability";
import {
  emptyProject,
  lambdaUnitFor,
  buildProjectPayload,
  buildTargetsFromProject,
  validateProject,
} from "./project.js";
import { formatSimulationError } from "./simulation.js";

const EDGE_COLORS = {
  normal: "#64748b",
  conditional: "#7c3aed",
  default: "#0f766e",
  failure: "#dc2626",
};

const INITIAL_MESSAGES = [
  {
    role: "assistant",
    text: "欢迎使用流程建模助手。直接描述业务需求，我会通过真实 Pi Agent 生成 Process IR，并调用后端校验。",
  },
  {
    role: "assistant",
    text: "例如：创建一个装备保障流程，包含任务准备、执行任务、任务结束，依次执行。",
  },
];

const DEFAULT_SIMULATION_FORM = {
  simulation_start: "0",
  random_seed: "2026",
  failure_policy: "require_failure_exit",
  failure_sampling: "time_to_failure",
};

const AGENT_EVENT_TYPES = [
  "assistant_delta",
  "assistant_message",
  "tool_start",
  "tool_end",
  "requirement_analysis",
  "clarification",
  "process_ir",
  "reliability_ir",
  "validation_result",
  "simulation_result",
  "task_status",
  "error",
  "done",
];

const TYPE_LABEL = {
  start: "开始",
  task: "业务活动",
  decision: "判断",
  end: "结束",
  subprocess: "嵌套流程块",
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function shortHash(hash) {
  return hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "未保存";
}

function isStructureValid(validation) {
  if (!validation) return false;
  if (typeof validation.structure_valid === "boolean") {
    return validation.structure_valid;
  }
  return validation.valid === true;
}

function conditionText(condition) {
  if (!condition) return "";
  if (["and", "or", "not"].includes(condition.op)) {
    const joiner = { and: " 且 ", or: " 或 ", not: "非 " }[condition.op];
    const parts = (condition.conditions || []).map(conditionText);
    return condition.op === "not"
      ? `非 (${parts[0] || ""})`
      : `(${parts.join(joiner)})`;
  }
  const field = (condition.field || "?").replace("attributes.", "");
  if (condition.op === "exists") return `${field} 存在`;
  if (condition.op === "is_null") return `${field} 为空`;
  if (condition.op === "in") return `${field} ∈ ${JSON.stringify(condition.value)}`;
  if (condition.op === "not_in") {
    return `${field} ∉ ${JSON.stringify(condition.value)}`;
  }
  const symbols = {
    eq: "==",
    ne: "!=",
    gt: ">",
    gte: ">=",
    lt: "<",
    lte: "<=",
  };
  return `${field} ${symbols[condition.op] || condition.op} ${JSON.stringify(
    condition.value,
  )}`;
}

function edgeLabel(edge) {
  if (edge.label) return edge.label;
  if (edge.kind === "conditional") return conditionText(edge.condition) || "条件";
  if (edge.kind === "default") return "默认";
  if (edge.kind === "failure") return "故障";
  return "";
}

function normalizeSpec(raw) {
  return nested.normalizeSpec(raw);
}

function syncSpecialRefs(spec) {
  return nested.syncSpecialRefs(spec);
}

function autoLayoutSpec(spec) {
  return nested.autoLayoutSpec(spec);
}

function ensurePositions(spec) {
  return nested.ensurePositions(spec);
}

function toFlowNodes(
  spec,
  selectedNodeId,
  expandedBlocks = {},
  onToggle = null,
  options = {},
) {
  return nested.toFlowNodes(
    spec,
    selectedNodeId,
    expandedBlocks,
    onToggle,
    options,
  );
}

function toFlowEdges(spec, selectedEdgeId, expandedBlocks = {}) {
  return nested.toFlowEdges(
    spec,
    selectedEdgeId,
    expandedBlocks,
    edgeLabel,
  );
}

function nextNodeId(spec, type) {
  const ids = new Set(spec.nodes.map((node) => node.id));
  if (type === "start" && !ids.has("start")) return "start";
  if (type === "end" && !ids.has("end")) return "end";
  let index = 1;
  while (ids.has(`${type}_${index}`)) index += 1;
  return `${type}_${index}`;
}

function nextEdgeId(spec, source, target) {
  const ids = new Set(spec.edges.map((edge) => edge.id));
  const base = `e_${source}_${target}`;
  if (!ids.has(base)) return base;
  let index = 2;
  while (ids.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

function createDraft(name = "未命名流程") {
  const draft = {
    schema_version: "process-ir/1.0",
    name,
    description: "",
    status_catalog: [],
    start_node_id: "start",
    end_node_ids: ["end"],
    nodes: [
      { id: "start", type: "start", name: "开始", description: "" },
      {
        id: "task_1",
        type: "task",
        name: "业务流程节点",
        description: "",
        duration: null,
        on_enter: [],
        on_complete: [],
        outcomes: [],
      },
      { id: "end", type: "end", name: "结束", description: "" },
    ],
    edges: [
      {
        id: "e_start_task_1",
        from: "start",
        to: "task_1",
        kind: "normal",
        label: "",
        priority: 0,
      },
      {
        id: "e_task_1_end",
        from: "task_1",
        to: "end",
        kind: "normal",
        label: "",
        priority: 0,
      },
    ],
    guards: { max_node_visits: 10000 },
  };
  return autoLayoutSpec(draft);
}

function findNodeByName(spec, query) {
  if (!spec) return null;
  const text = query.trim();
  if (!text) return null;
  return (
    spec.nodes.find((node) => node.id === text) ||
    spec.nodes.find((node) => node.name === text) ||
    spec.nodes.find((node) => node.name.includes(text)) ||
    null
  );
}

function summarizeSpec(spec) {
  if (!spec) return "当前没有流程草稿。";
  const tasks = nested.listTasks(spec);
  const decisions = spec.nodes.filter((node) => node.type === "decision");
  const nodeMap = new Map(spec.nodes.map((node) => [node.id, node]));
  const loops = spec.edges.filter((edge) => {
    const source = nodeMap.get(edge.from);
    const target = nodeMap.get(edge.to);
    if (!source?.position || !target?.position) return false;
    return edge.from === edge.to || target.position.x < source.position.x;
  });
  const durations = tasks
    .slice(0, 8)
    .map((node) => `${node.name}: ${node.duration ?? "未设置"} 天`);
  const lines = [
    `流程「${spec.name}」共 ${spec.nodes.length} 个节点、${spec.edges.length} 条连接。`,
    `其中业务活动 ${tasks.length} 个，判断节点 ${decisions.length} 个，检测到 ${loops.length} 条回边。`,
  ];
  if (durations.length) lines.push(`主要持续时间：${durations.join("；")}。`);
  if (decisions.length) {
    lines.push(`判断节点：${decisions.map((node) => node.name).join("、")}。`);
  }
  if (loops.length) {
    lines.push(
      `循环连接：${loops
        .map((edge) => `${edge.from} → ${edge.to}`)
        .join("、")}。`,
    );
  }
  lines.push("该解释基于当前 Process IR 结构，不包含 Reliability IR 参数。");
  return lines.join("\n");
}

function IssuesBar({ issues, validationState }) {
  const errors = issues.filter((issue) => issue.severity === "error");
  const warnings = issues.filter((issue) => issue.severity === "warning");
  const label =
    validationState === "checking"
      ? "正在校验…"
      : errors.length
        ? `校验未通过：${errors.length} 个错误`
        : warnings.length
          ? `校验通过，${warnings.length} 个警告`
          : validationState === "valid"
            ? "校验通过"
            : "等待校验";

  return (
    <details className={`issues-bar ${errors.length ? "has-errors" : ""}`}>
      <summary>
        <span className="issues-summary-left">
          <span className={`status-dot ${errors.length ? "bad" : "good"}`} />
          {label}
        </span>
        <span className="issues-hint">展开查看校验问题</span>
      </summary>
      {issues.length === 0 ? (
        <p className="issues-empty">当前没有校验问题。</p>
      ) : (
        <ul className="issue-list">
          {issues.map((issue, index) => (
            <li
              key={`${issue.code}-${issue.node_id || ""}-${issue.edge_id || ""}-${index}`}
              className={`issue ${issue.severity}`}
            >
              <span className="issue-code">{issue.code}</span>
              <span>{issue.message}</span>
              {(issue.node_id || issue.edge_id) && (
                <span className="issue-target">
                  {issue.node_id || issue.edge_id}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

export default function App() {
  const { fitView } = useReactFlow();
  const [spec, setSpec] = useState(null);
  const [processId, setProcessId] = useState(null);
  const [latestVersion, setLatestVersion] = useState(0);
  const [viewingVersion, setViewingVersion] = useState(null);
  const [versions, setVersions] = useState([]);
  const [processes, setProcesses] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [issues, setIssues] = useState([]);
  const [validationState, setValidationState] = useState("idle");
  const [contentHash, setContentHash] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [inspectorTab, setInspectorTab] = useState("business");
  const [project, setProject] = useState(emptyProject);
  const [expandedBlocks, setExpandedBlocks] = useState({});
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [agentSessionId, setAgentSessionId] = useState(null);
  const [agentStatus, setAgentStatus] = useState("disconnected");
  const [agentBusy, setAgentBusy] = useState(false);
  const [currentTool, setCurrentTool] = useState(null);
  const [meta, setMeta] = useState(null);
  const [reliability, setReliability] = useState(null);
  const [reliabilityStatus, setReliabilityStatus] = useState("idle");
  const [reliabilityStale, setReliabilityStale] = useState([]);
  const [reliabilityProcess, setReliabilityProcess] = useState(null);
  const [reliabilityBusy, setReliabilityBusy] = useState(false);
  const [simulationOpen, setSimulationOpen] = useState(false);
  const [projectCollapsed, setProjectCollapsed] = useState(false);
  const [simulationForm, setSimulationForm] = useState(
    DEFAULT_SIMULATION_FORM,
  );
  const [simulationRunning, setSimulationRunning] = useState(false);
  const [simulationPhase, setSimulationPhase] = useState("idle");
  const [simulationResult, setSimulationResult] = useState(null);
  const [simulationError, setSimulationError] = useState("");
  const [experiments, setExperiments] = useState([]);
  const [experimentLoading, setExperimentLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [toast, setToast] = useState("");
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
  const validateSequence = useRef(0);
  const toastTimer = useRef(null);
  const fileInputRef = useRef(null);
  const chatBusyRef = useRef(false);
  const initializedRef = useRef(false);
  const agentEventSourceRef = useRef(null);
  const agentSessionPromiseRef = useRef(null);
  const agentTaskContextRef = useRef({});
  const agentStateRef = useRef({});
  const agentStatusRef = useRef("disconnected");
  const agentLastSeqRef = useRef(0);
  const agentReconnectRef = useRef({ attempts: 0, timer: null });

  const showToast = useCallback((message) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 3600);
  }, []);

  const fitLater = useCallback(() => {
    window.setTimeout(() => {
      fitView({ padding: 0.18, minZoom: 0.4, maxZoom: 1.15, duration: 300 });
    }, 180);
  }, [fitView]);

  const focusBlock = useCallback(
    (blockId) => {
      if (!spec) return;
      const ids = nested.collectBlockNodeIds(spec, blockId);
      window.setTimeout(() => {
        fitView({
          nodes: ids.map((id) => ({ id })),
          padding: 0.12,
          minZoom: 0.55,
          maxZoom: 1.25,
          duration: 350,
        });
      }, 220);
    },
    [fitView, spec],
  );

  const projectValidation = useMemo(
    () => validateProject(project),
    [project],
  );

  const reliabilityReadiness = useMemo(
    () => validateReliabilityReadiness(spec, reliability, project),
    [spec, reliability, project],
  );

  const storageKey = `rfa.project.${processId || "draft"}`;
  const skipProjectSaveRef = useRef(true);

  useEffect(() => {
    skipProjectSaveRef.current = true;
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored) {
        setProject({ ...emptyProject(), ...JSON.parse(stored) });
      } else {
        setProject(emptyProject());
      }
    } catch {
      // A corrupt local project cache must never block the editor.
      setProject(emptyProject());
    }
  }, [storageKey]);

  useEffect(() => {
    if (skipProjectSaveRef.current) {
      skipProjectSaveRef.current = false;
      return;
    }
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(project));
    } catch {
      // Ignore storage quota/disabled errors.
    }
  }, [project, storageKey]);

  useEffect(() => {
    if (!spec) return;
    setProject((current) =>
      current.name
        ? current
        : { ...current, name: spec.name || "" },
    );
  }, [spec]);

  const updateProject = useCallback((key, value) => {
    setProject((current) => ({ ...current, [key]: value }));
  }, []);

  const reliabilityByNode = useMemo(() => {
    const map = {};
    for (const node of reliability?.nodes || []) {
      map[node.node_id] = node;
    }
    return map;
  }, [reliability]);

  const openNodeParameters = useCallback((nodeId) => {
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    setInspectorTab("reliability");
  }, []);

  const handleToggleBlock = useCallback(
    (blockId) => {
      const next = nested.toggleBlock(expandedBlocks, blockId);
      setExpandedBlocks(next);
      if (next[blockId]) {
        focusBlock(blockId);
      } else {
        fitLater();
      }
    },
    [expandedBlocks, fitLater, focusBlock],
  );

  const expandAllBlocks = useCallback(() => {
    setExpandedBlocks((current) => {
      if (!spec) return current;
      const next = { ...current };
      nested.walkScopes(spec, (scope) => {
        for (const node of scope.nodes || []) {
          if (node.type === "subprocess") next[node.id] = true;
        }
      });
      return next;
    });
    fitLater();
  }, [fitLater, spec]);

  const collapseAllBlocks = useCallback(() => {
    setExpandedBlocks({});
    fitLater();
  }, [fitLater]);

  const refreshProcesses = useCallback(async () => {
    const data = await api.listProcesses();
    setProcesses(data.processes || []);
    return data.processes || [];
  }, []);

  const resetReliability = useCallback(() => {
    setReliability(null);
    setReliabilityStatus("idle");
    setReliabilityStale([]);
    setReliabilityProcess(null);
  }, []);

  const loadReliability = useCallback(
    async (id, version) => {
      if (!id || !version) {
        resetReliability();
        return;
      }
      setReliabilityBusy(true);
      setReliabilityStatus("loading");
      try {
        const data = await api.getReliability(id, version);
        setReliability(data.reliability || null);
        setReliabilityStatus(data.status || "missing");
        setReliabilityStale(data.stale_revisions || []);
        setReliabilityProcess(data.process || null);
      } catch (error) {
        setReliability(null);
        setReliabilityStatus("error");
        setReliabilityStale([]);
        setReliabilityProcess(null);
        showToast(error.message || "可靠性配置加载失败");
      } finally {
        setReliabilityBusy(false);
      }
    },
    [resetReliability, showToast],
  );

  useEffect(() => {
    if (processId && viewingVersion) {
      loadReliability(processId, viewingVersion);
    } else {
      resetReliability();
    }
  }, [loadReliability, processId, resetReliability, viewingVersion]);

  useEffect(() => {
    Promise.all([api.health(), api.meta()])
      .then(([, metaData]) => setMeta(metaData))
      .catch(() => setMeta(null));
  }, []);

  useEffect(() => {
    agentStateRef.current = {
      spec,
      processId,
      latestVersion,
      viewingVersion,
      dirty,
      contentHash,
      reliability,
      reliabilityProcess,
    };
  }, [
    contentHash,
    dirty,
    latestVersion,
    processId,
    reliability,
    reliabilityProcess,
    spec,
    viewingVersion,
  ]);

  useEffect(() => {
    agentStatusRef.current = agentStatus;
  }, [agentStatus]);

  useEffect(
    () => () => {
      if (agentReconnectRef.current.timer) {
        window.clearTimeout(agentReconnectRef.current.timer);
        agentReconnectRef.current.timer = null;
      }
      if (agentEventSourceRef.current) {
        agentEventSourceRef.current.close();
        agentEventSourceRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    if (spec) {
      setRfNodes(
        toFlowNodes(spec, selectedNodeId, expandedBlocks, handleToggleBlock, {
          onEditParameters: openNodeParameters,
          reliabilityByNode,
          unit: project.simulation_unit || "day",
        }),
      );
    }
  }, [
    spec,
    selectedNodeId,
    expandedBlocks,
    handleToggleBlock,
    openNodeParameters,
    reliabilityByNode,
    project.simulation_unit,
    setRfNodes,
  ]);

  useEffect(() => {
    if (spec) {
      setRfEdges(toFlowEdges(spec, selectedEdgeId, expandedBlocks));
    }
  }, [spec, selectedEdgeId, expandedBlocks, setRfEdges]);

  useEffect(() => {
    if (!spec) return undefined;
    const timer = window.setTimeout(() => {
      fitView({ padding: 0.18, minZoom: 0.4, maxZoom: 1.15, duration: 0 });
    }, 360);
    return () => window.clearTimeout(timer);
  }, [spec, fitView]);

  useEffect(() => {
    if (!spec) return undefined;
    const sequence = ++validateSequence.current;
    setValidationState("checking");
    const handle = window.setTimeout(async () => {
      try {
        const result = await api.validate(spec);
        if (sequence !== validateSequence.current) return;
        setIssues(result.issues || []);
        setValidationState(result.valid ? "valid" : "invalid");
        setContentHash(result.content_hash);
      } catch (error) {
        if (sequence !== validateSequence.current) return;
        setValidationState("error");
        setIssues([
          {
            severity: "error",
            code: "validation_request_failed",
            message: error.message || "校验请求失败",
          },
        ]);
      }
    }, 650);
    return () => window.clearTimeout(handle);
  }, [spec]);

  const createNewProcess = useCallback(
    (name = "未命名流程") => {
      const draft = createDraft(name);
      setSpec(draft);
      setProcessId(null);
      setLatestVersion(0);
      setViewingVersion(null);
      setVersions([]);
      setDirty(true);
      setIssues([]);
      setContentHash(null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      fitLater();
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: `已创建草稿「${name}」。保存后才会生成正式流程版本。`,
        },
      ]);
    },
    [fitLater],
  );

  const openProcess = useCallback(
    async (id, version = null) => {
      setBusy(true);
      try {
        const [versionData, documentData] = await Promise.all([
          api.getVersions(id),
          api.getProcess(id, version),
        ]);
        const document = documentData.process;
        const layoutGenerated = (document.nodes || []).some(
          (node) => !node.position,
        );
        setProcessId(id);
        setLatestVersion(versionData.versions?.[0]?.version ?? document.version);
        setViewingVersion(document.version);
        setVersions(versionData.versions || []);
        setSpec(ensurePositions(normalizeSpec(document)));
        setDirty(layoutGenerated);
        setContentHash(document.content_hash);
        setIssues([]);
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        fitLater();
        if (layoutGenerated) {
          showToast("该流程缺少画布坐标，已自动布局；保存后会写入 Process IR。");
        }
      } catch (error) {
        showToast(error.message || "打开流程失败");
      } finally {
        setBusy(false);
      }
    },
    [fitLater, showToast],
  );

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    (async () => {
      try {
        const list = await refreshProcesses();
        if (list.length > 0) {
          await openProcess(list[0].process_id);
        } else {
          createNewProcess();
        }
      } catch (error) {
        showToast(error.message || "无法加载流程列表");
      }
    })();
  }, [createNewProcess, openProcess, refreshProcesses, showToast]);

  const mutateSpec = useCallback((updater, syncRefs = false) => {
    setSpec((current) => {
      if (!current) return current;
      const next = updater(current);
      return syncRefs ? syncSpecialRefs(next) : next;
    });
    setDirty(true);
  }, []);

  const validateNow = useCallback(async () => {
    if (!spec) return null;
    try {
      const result = await api.validate(spec);
      setIssues(result.issues || []);
      setValidationState(result.valid ? "valid" : "invalid");
      setContentHash(result.content_hash);
      return result;
    } catch (error) {
      setValidationState("error");
      const errorIssues = issuesFromError(error);
      setIssues(
        errorIssues.length
          ? errorIssues
          : [
              {
                severity: "error",
                code: "validation_request_failed",
                message: error.message || "校验请求失败",
              },
            ],
      );
      return null;
    }
  }, [spec]);

  const autoLayout = useCallback(() => {
    setSpec((current) => (current ? autoLayoutSpec(current) : current));
    setDirty(true);
    window.setTimeout(() => fitView({ padding: 0.22, duration: 300 }), 60);
  }, [fitView]);

  const updateNode = useCallback(
    (updatedNode) => {
      mutateSpec(
        (current) => nested.updateNode(current, updatedNode.id, updatedNode),
        false,
      );
    },
    [mutateSpec],
  );

  const addNode = useCallback(
    (type, name = null) => {
      if (!spec) return null;
      const selected = selectedNodeId
        ? nested.findNode(spec, selectedNodeId)
        : null;
      const targetPath =
        selected?.node.type === "subprocess"
          ? [...selected.path, selected.node.id]
          : selected?.path || [];
      const position = selected?.node.position
        ? {
            x: selected.node.position.x + 240,
            y: selected.node.position.y + 40,
          }
        : { x: 280, y: 220 };
      const labels = {
        task: "新任务",
        decision: "新判断",
        start: "新开始",
        end: "新结束",
        subprocess: "嵌套流程块",
      };
      let node;
      if (type === "subprocess") {
        node = nested.createSubprocessNode(
          spec,
          targetPath,
          position,
          name || "嵌套流程块",
        );
      } else {
        const id = nested.nextNodeId(spec, type);
        node = {
          id,
          type,
          name: name || labels[type] || "新节点",
          description: "",
          position,
          on_enter: [],
          on_complete: [],
          outcomes: [],
        };
        if (type === "task") node.duration = null;
      }
      setSpec((current) => {
        const next = nested.addNode(current, targetPath, node);
        return type === "subprocess"
          ? { ...next, schema_version: "process-ir/1.1" }
          : next;
      });
      setDirty(true);
      setSelectedNodeId(node.id);
      setSelectedEdgeId(null);
      if (type === "subprocess") {
        setExpandedBlocks((current) => ({ ...current, [node.id]: true }));
      }
      showToast(`已添加${TYPE_LABEL[type] || labels[type]}「${node.name}」`);
      return node;
    },
    [selectedNodeId, showToast, spec],
  );

  const deleteNode = useCallback(
    (nodeId) => {
      setSpec((current) => nested.deleteNodes(current, [nodeId]));
      setDirty(true);
      if (selectedNodeId === nodeId) setSelectedNodeId(null);
      showToast("节点及其连接已删除");
    },
    [selectedNodeId, showToast],
  );

  const addEdge = useCallback(
    (source, target) => {
      if (!spec) return null;
      const sourceContext = nested.findNode(spec, source);
      const targetContext = nested.findNode(spec, target);
      if (!sourceContext || !targetContext) return null;
      const sourcePath = JSON.stringify(sourceContext.path);
      const targetPath = JSON.stringify(targetContext.path);
      if (sourcePath !== targetPath) {
        showToast("禁止跨层级连接：内部节点只能连接同一子流程内的节点。");
        return null;
      }
      const scope = sourceContext.scope;
      const sourceNode = sourceContext.node;
      const outgoing = (scope.edges || []).filter((edge) => edge.from === source);
      let kind = "normal";
      let condition = null;
      let label = "";
      let subflow_exit = null;
      if (sourceNode.type === "subprocess") {
        const ends = sourceNode.subflow?.end_node_ids || [];
        if (ends.length > 0) subflow_exit = ends[0];
        if (ends.length > 1) {
          showToast("该嵌套块有多个出口，请在右侧选择正确的子流程出口。");
        }
      } else if (sourceNode.type === "decision") {
        const hasDefault = outgoing.some((edge) => edge.kind === "default");
        kind = hasDefault ? "conditional" : "default";
        label = hasDefault ? "条件" : "默认";
        if (hasDefault) {
          condition = {
            op: "eq",
            field: "currently_failed",
            value: true,
          };
        }
      } else if (source === target) {
        kind = "conditional";
        label = "循环";
        condition = {
          op: "gte",
          field: `node_visits.${source}`,
          value: 1,
        };
      }
      const id = nested.nextEdgeId(spec, source, target);
      const edge = {
        id,
        from: source,
        to: target,
        kind,
        label,
        priority: kind === "default" ? 0 : 10,
        ...(condition ? { condition } : {}),
        ...(subflow_exit ? { subflow_exit } : {}),
      };
      setSpec((current) => nested.addEdge(current, sourceContext.path, edge));
      setDirty(true);
      setSelectedEdgeId(id);
      setSelectedNodeId(null);
      showToast(
        kind === "conditional"
          ? "已创建条件连接，请在右侧填写条件"
          : "已创建连接",
      );
      return edge;
    },
    [showToast, spec],
  );

  const updateEdge = useCallback(
    (updatedEdge) => {
      mutateSpec((current) =>
        nested.updateEdge(current, updatedEdge.id, updatedEdge),
      );
    },
    [mutateSpec],
  );

  const deleteEdge = useCallback(
    (edgeId) => {
      setSpec((current) => nested.deleteEdges(current, [edgeId]));
      setDirty(true);
      if (selectedEdgeId === edgeId) setSelectedEdgeId(null);
      showToast("连接已删除");
    },
    [selectedEdgeId, showToast],
  );

  const updateProcess = useCallback(
    (patch) => {
      mutateSpec((current) => ({ ...current, ...patch }));
    },
    [mutateSpec],
  );

  const saveProcess = useCallback(async () => {
    if (!spec || busy) return;
    setBusy(true);
    try {
      const validation = await api.validate(spec);
      setIssues(validation.issues || []);
      setValidationState(validation.valid ? "valid" : "invalid");
      setContentHash(validation.content_hash);
      if (!validation.valid) {
        showToast("存在校验错误，未保存。请展开底部校验问题查看详情。");
        return;
      }
      const result = processId
        ? await api.updateProcess(processId, latestVersion, spec)
        : await api.createProcess(spec);
      const document = result.process;
      setProcessId(document.process_id);
      setLatestVersion(document.version);
      setViewingVersion(document.version);
      setSpec(normalizeSpec(document));
      setContentHash(document.content_hash);
      setDirty(false);
      const versionData = await api.getVersions(document.process_id);
      setVersions(versionData.versions || []);
      await refreshProcesses();
      showToast(
        result.created
          ? `已保存 v${document.version} · ${shortHash(document.content_hash)}`
          : `内容未变化，仍为 v${document.version}`,
      );
    } catch (error) {
      if (error.status === 409) {
        showToast("保存冲突：服务端已有更新版本，正在重新加载最新版本。");
        if (processId) await openProcess(processId);
      } else {
        const errorIssues = issuesFromError(error);
        if (errorIssues.length) setIssues(errorIssues);
        showToast(error.message || "保存失败");
      }
    } finally {
      setBusy(false);
    }
  }, [
    busy,
    latestVersion,
    openProcess,
    processId,
    refreshProcesses,
    showToast,
    spec,
  ]);

  const saveReliabilityForNode = useCallback(
    async (nodeId, edit) => {
      if (!spec) return { ok: false, message: "当前没有流程草稿" };
      if (!processId) {
        return { ok: false, message: "请先保存 Process IR，再保存可靠性配置" };
      }
      if (viewingVersion !== latestVersion) {
        return { ok: false, message: "历史版本只能查看，不能保存可靠性配置" };
      }
      if (dirty) {
        return { ok: false, message: "流程有未保存修改，请先保存流程" };
      }
      if (!reliabilityProcess) {
        return { ok: false, message: "尚未加载当前 Process IR 绑定信息" };
      }
      const reliabilityNodes = nested.listReliabilityNodes(spec);
      const nodes = buildReliabilityNodes(
        reliabilityNodes,
        reliability?.nodes || [],
        nodeId,
        edit,
        { simulationUnit: project.simulation_unit || "day" },
      );
      setReliabilityBusy(true);
      try {
        const result = await api.saveReliability(processId, {
          process_version: reliabilityProcess.version,
          process_hash: reliabilityProcess.content_hash,
          nodes,
        });
        setReliability(result.reliability);
        setReliabilityStatus("bound");
        setReliabilityStale([]);
        setReliabilityProcess({
          process_id: processId,
          version: result.reliability.process_version,
          content_hash: result.reliability.process_hash,
        });
        showToast(
          `可靠性配置已保存，绑定 Process IR v${
            result.reliability.process_version
          } · ${shortHash(result.reliability.process_hash)}`,
        );
        return { ok: true, reliability: result.reliability };
      } catch (error) {
        const detail = error.payload?.detail;
        const issueList =
          (detail && Array.isArray(detail.issues) && detail.issues) ||
          (Array.isArray(error.payload?.issues) && error.payload.issues) ||
          [];
        const message = issueList.length
          ? issueList.map((issue) => issue.message).join("；")
          : error.message || "可靠性配置保存失败";
        return { ok: false, message };
      } finally {
        setReliabilityBusy(false);
      }
    },
    [
      dirty,
      latestVersion,
      processId,
      project,
      reliability,
      reliabilityProcess,
      showToast,
      spec,
      viewingVersion,
    ],
  );

  const refreshExperiments = useCallback(async () => {
    setExperimentLoading(true);
    try {
      const data = await api.listExperiments();
      setExperiments(data.experiments || []);
      return data.experiments || [];
    } catch (error) {
      showToast(error.message || "加载实验历史失败");
      return [];
    } finally {
      setExperimentLoading(false);
    }
  }, [showToast]);

  const loadExperiment = useCallback(
    async (resultId) => {
      const data = await api.getExperiment(resultId);
      setSimulationResult(data.experiment);
      setSimulationError("");
      setSimulationPhase("success");
      setSimulationOpen(true);
      return data.experiment;
    },
    [],
  );

  const runSimulationEvaluation = useCallback(
    async (payload) => {
      if (!processId) {
        throw new Error("请先保存 Process IR");
      }
      const result = await api.runExperiment(processId, {
        process_version: viewingVersion || undefined,
        ...payload,
      });
      await refreshExperiments();
      if (agentSessionId && result?.result_id) {
        try {
          await api.recordAgentSimulationResult(
            agentSessionId,
            result.result_id,
          );
        } catch {
          // The simulation result is already persisted; the Agent event is
          // best-effort and must never hide the real evaluation result.
        }
      }
      return result;
    },
    [agentSessionId, processId, refreshExperiments, viewingVersion],
  );

  const startSimulation = useCallback(async () => {
    if (simulationRunning) return;
    setSimulationOpen(true);
    setSimulationError("");
    setSimulationResult(null);
    setSimulationPhase("preparing");
    setSimulationRunning(true);

    const fail = (message) => {
      setSimulationError(message);
      setSimulationPhase("error");
    };

    try {
      let projectPayload;
      try {
        projectPayload = buildProjectPayload(project);
      } catch (projectError) {
        fail(projectError.message);
        return;
      }
      if (!projectPayload.simulation_total_time) {
        fail("仿真总时间必须大于 0。");
        return;
      }
      if (!processId) {
        fail("请先保存 Process IR，再运行仿真。");
        return;
      }
      if (viewingVersion && latestVersion && viewingVersion !== latestVersion) {
        fail("当前正在查看历史版本，请切换到最新版本后再运行仿真。");
        return;
      }
      if (dirty) {
        fail("当前流程有未保存修改，请先保存新版本后再运行仿真。");
        return;
      }
      if (validationState !== "valid") {
        const validation = await validateNow();
        if (!validation || !validation.valid) {
          const firstIssue = (validation?.issues || [])[0];
          fail(
            firstIssue
              ? `流程结构校验未通过：${firstIssue.message}`
              : "流程结构校验未通过，请先修正校验问题。",
          );
          return;
        }
      }
      if (!reliabilityReadiness?.ready) {
        const issues = reliabilityReadiness?.issues || [];
        fail(
          issues.length
            ? `仿真参数未就绪：${issues.join("；")}`
            : "仿真参数未就绪，请补齐阶段故障率、检测率或持续时间。",
        );
        return;
      }
      if (reliabilityStatus !== "bound") {
        fail("当前 Process IR 版本没有绑定 Reliability IR，请先保存可靠性配置。");
        return;
      }

      const simulationStart = Number(simulationForm.simulation_start);
      if (!Number.isFinite(simulationStart) || simulationStart < 0) {
        fail("仿真开始时间必须是大于等于 0 的数字。");
        return;
      }
      const randomSeed = Number(simulationForm.random_seed);
      if (!Number.isInteger(randomSeed) || randomSeed < 0) {
        fail("随机种子必须是大于等于 0 的整数。");
        return;
      }

      const targets = buildTargetsFromProject(project);
      const payload = {
        entity_count: projectPayload.missile_count,
        simulation_unit: projectPayload.simulation_unit,
        project: projectPayload,
        simulation_start: simulationStart,
        simulation_duration: projectPayload.simulation_total_time,
        random_seed: randomSeed,
        failure_policy:
          simulationForm.failure_policy || "require_failure_exit",
        failure_sampling:
          simulationForm.failure_sampling || "time_to_failure",
      };
      if (targets) payload.evaluation_targets = targets;

      setSimulationPhase("running");
      const data = await runSimulationEvaluation(payload);
      setSimulationResult(data);
      setSimulationPhase("success");
    } catch (runError) {
      fail(formatSimulationError(runError));
    } finally {
      setSimulationRunning(false);
    }
  }, [
    dirty,
    latestVersion,
    processId,
    project,
    reliabilityReadiness,
    reliabilityStatus,
    runSimulationEvaluation,
    simulationForm,
    simulationRunning,
    validateNow,
    validationState,
    viewingVersion,
  ]);

  const updateSimulationForm = useCallback((key, value) => {
    setSimulationForm((current) => ({ ...current, [key]: value }));
  }, []);

  useEffect(() => {
    setSimulationResult(null);
    setSimulationError("");
    setSimulationPhase("idle");
  }, [processId, viewingVersion]);

  const loadVersion = useCallback(
    async (version) => {
      if (!processId) return;
      setBusy(true);
      try {
        const data = await api.getProcess(processId, version);
        const document = data.process;
        setSpec(ensurePositions(normalizeSpec(document)));
        setViewingVersion(document.version);
        setDirty(false);
        setContentHash(document.content_hash);
        setIssues([]);
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        fitLater();
      } catch (error) {
        showToast(error.message || "加载历史版本失败");
      } finally {
        setBusy(false);
      }
    },
    [fitLater, processId, showToast],
  );

  const handleNodeDragStop = useCallback(
    (_event, node) => {
      const specPosition = nested.flowPositionToSpec(
        node.position,
        node.parentId || null,
      );
      mutateSpec((current) =>
        nested.updateNodePosition(current, node.id, specPosition),
      );
    },
    [mutateSpec],
  );

  const handleNodesDelete = useCallback(
    (deletedNodes) => {
      const ids = deletedNodes.map((node) => node.id);
      setSpec((current) => nested.deleteNodes(current, ids));
      setDirty(true);
      if (ids.includes(selectedNodeId)) setSelectedNodeId(null);
    },
    [selectedNodeId],
  );

  const handleEdgesDelete = useCallback((deletedEdges) => {
    const ids = deletedEdges.map((edge) => edge.id);
    setSpec((current) => nested.deleteEdges(current, ids));
    setDirty(true);
  }, []);

  const handleConnect = useCallback(
    (connection) => {
      if (connection.source && connection.target) {
        addEdge(connection.source, connection.target);
      }
    },
    [addEdge],
  );

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (event) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        const imported = ensurePositions(normalizeSpec(parsed));
        setSpec(imported);
        setProcessId(null);
        setLatestVersion(0);
        setViewingVersion(null);
        setVersions([]);
        setDirty(true);
        setSelectedNodeId(null);
        setSelectedEdgeId(null);
        setContentHash(null);
        fitLater();
        showToast(`已导入「${imported.name}」作为新的未保存草稿。`);
      } catch (error) {
        showToast(`导入失败：${error.message}`);
      }
    },
    [fitLater, showToast],
  );

  const exportJson = useCallback(() => {
    if (!spec) return;
    const blob = new Blob([JSON.stringify(spec, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${spec.name || "process"}.process.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [spec]);

  const appendMessage = useCallback((role, text, extra = {}) => {
    setMessages((current) => [
      ...current,
      {
        id: `${role}:${Date.now()}:${Math.random().toString(36).slice(2)}`,
        role,
        text,
        ...extra,
      },
    ]);
  }, []);

  const handleAgentEvent = useCallback((payload) => {
    if (!payload || typeof payload !== "object") return;
    const type = payload.type;
    const data = payload.data || {};
    const taskId = payload.task_id || null;

    if (type === "assistant_delta") {
      const messageId = data.message_id || `assistant:${taskId || "task"}`;
      const delta = data.delta || "";
      if (!delta) return;
      setMessages((current) => {
        const existing = current.find((message) => message.id === messageId);
        if (existing) {
          return current.map((message) =>
            message.id === messageId
              ? {
                  ...message,
                  text: `${message.text || ""}${delta}`,
                  streaming: true,
                }
              : message,
          );
        }
        return [
          ...current,
          {
            id: messageId,
            role: "assistant",
            text: delta,
            streaming: true,
            taskId,
          },
        ];
      });
      return;
    }

    if (type === "assistant_message") {
      const messageId = data.message_id || `assistant:${taskId || "task"}`;
      const text = data.text || "";
      if (!text) return;
      setMessages((current) => {
        const existing = current.find((message) => message.id === messageId);
        if (existing) {
          return current.map((message) =>
            message.id === messageId
              ? { ...message, text, streaming: false }
              : message,
          );
        }
        return [
          ...current,
          {
            id: messageId,
            role: "assistant",
            text,
            streaming: false,
            taskId,
          },
        ];
      });
      return;
    }

    if (type === "tool_start") {
      const id = `tool:${data.tool_call_id || `${taskId}:${data.tool_name}`}`;
      setMessages((current) => {
        const existing = current.some((message) => message.id === id);
        const next = {
          id,
          role: "tool",
          toolName: data.tool_name,
          toolCallId: data.tool_call_id,
          status: "running",
          summary: data.args_summary || {},
          taskId,
        };
        return existing
          ? current.map((message) =>
              message.id === id ? { ...message, ...next } : message,
            )
          : [...current, next];
      });
      setCurrentTool(data.tool_name || null);
      return;
    }

    if (type === "tool_end") {
      const id = `tool:${data.tool_call_id || `${taskId}:${data.tool_name}`}`;
      setMessages((current) => {
        const next = {
          status: data.is_error ? "error" : "completed",
          durationMs: data.duration_ms,
          summary: data.summary || {},
        };
        const existing = current.some((message) => message.id === id);
        if (existing) {
          return current.map((message) =>
            message.id === id ? { ...message, ...next } : message,
          );
        }
        return [
          ...current,
          {
            id,
            role: "tool",
            toolName: data.tool_name,
            toolCallId: data.tool_call_id,
            taskId,
            ...next,
          },
        ];
      });
      setCurrentTool(null);
      return;
    }

    if (type === "requirement_analysis") {
      const messageId = `analysis:${taskId || "task"}`;
      setMessages((current) => {
        const next = {
          id: messageId,
          role: "analysis",
          taskId,
          analysis: data.analysis || null,
          valid: data.valid ?? data.validation?.valid ?? null,
          validation: data.validation || null,
          stepCount: data.step_count ?? 0,
          branchCount: data.branch_count ?? 0,
          ambiguityCount: data.ambiguity_count ?? 0,
          blockingCount: data.blocking_count ?? 0,
        };
        const existing = current.some((message) => message.id === messageId);
        return existing
          ? current.map((message) =>
              message.id === messageId ? next : message,
            )
          : [...current, next];
      });
      return;
    }

    if (type === "clarification") {
      const messageId = `clarification:${taskId || "task"}`;
      setMessages((current) => {
        const next = {
          id: messageId,
          role: "clarification",
          taskId,
          text: data.message || "",
          questions: Array.isArray(data.questions) ? data.questions : [],
        };
        const existing = current.some((message) => message.id === messageId);
        return existing
          ? current.map((message) =>
              message.id === messageId ? next : message,
            )
          : [...current, next];
      });
      return;
    }

    if (type === "process_ir") {
      const messageId = `proposal:process:${taskId || "task"}`;
      const baseProcessId =
        data.base_process_id ||
        agentTaskContextRef.current[taskId]?.processId ||
        null;
      setMessages((current) => {
        const existing = current.find((message) => message.id === messageId);
        const sameSpec =
          existing &&
          JSON.stringify(existing.spec || null) ===
            JSON.stringify(data.spec || null);
        const next = {
          id: messageId,
          role: "proposal",
          kind: "process_ir",
          taskId,
          spec: data.spec || null,
          validation: data.validation || null,
          coverage:
            data.requirement_coverage || data.validation?.coverage || null,
          baseProcessId,
          applied: sameSpec ? Boolean(existing.applied) : false,
        };
        return existing
          ? current.map((message) => (message.id === messageId ? next : message))
          : [...current, next];
      });
      if (data.spec && isStructureValid(data.validation)) {
        api
          .previewSvg(data.spec)
          .then((svg) => {
            if (typeof svg === "string" && svg.trim().startsWith("<svg")) {
              setPreview({
                svg,
                spec: data.spec,
                validation: data.validation || null,
                taskId,
                visible: true,
              });
            }
          })
          .catch(() => {});
      }
      return;
    }

    if (type === "reliability_ir") {
      const messageId = `proposal:reliability:${taskId || "task"}`;
      setMessages((current) => {
        const existing = current.find((message) => message.id === messageId);
        const sameSpec =
          existing &&
          JSON.stringify(existing.spec || null) ===
            JSON.stringify(data.spec || null);
        const next = {
          id: messageId,
          role: "proposal",
          kind: "reliability_ir",
          taskId,
          processId: data.process_id || null,
          spec: data.spec || null,
          validation: data.validation || null,
          applied: sameSpec ? Boolean(existing.applied) : false,
          saved: sameSpec ? Boolean(existing.saved) : false,
          saveError: "",
        };
        return existing
          ? current.map((message) => (message.id === messageId ? next : message))
          : [...current, next];
      });
      return;
    }

    if (type === "simulation_result") {
      setMessages((current) => [
        ...current,
        {
          id: `simulation-result:${data.result_id || payload.seq || Date.now()}`,
          role: "tool",
          toolName: "simulation_result",
          toolCallId: data.result_id || null,
          status: "completed",
          taskId,
          summary: {
            result_id: data.result_id,
            process_version: data.process_version,
            overall_reliability: data.evaluation?.overall_reliability,
            end_availability: data.evaluation?.end_availability,
            target_status: data.evaluation?.target_status,
          },
        },
      ]);
      return;
    }

    if (type === "task_status") {
      if (data.tool !== undefined) setCurrentTool(data.tool || null);
      if (data.status === "running" || data.status === "retrying") {
        setAgentBusy(true);
        setAgentStatus(data.status);
      } else if (data.status === "idle") {
        setAgentBusy(false);
        setAgentStatus("idle");
      }
      return;
    }

    if (type === "error") {
      const code = data.code || "agent_error";
      const fatal = ["agent_timeout", "pi_process_exit", "prompt_failed"].includes(
        code,
      );
      setMessages((current) => [
        ...current,
        {
          id: `error:${payload.seq || Date.now()}`,
          role: "error",
          text: data.message || "Agent 执行失败。",
          taskId,
        },
      ]);
      if (fatal) {
        setAgentBusy(false);
        setAgentStatus("error");
        setCurrentTool(null);
      }
      return;
    }

    if (type === "done") {
      setAgentBusy(false);
      setCurrentTool(null);
      setAgentStatus(data.status === "completed" ? "idle" : data.status || "idle");
      setMessages((current) =>
        current.map((message) =>
          message.streaming ? { ...message, streaming: false } : message,
        ),
      );
    }
  }, []);

  const openAgentEvents = useCallback(
    (sessionId) => {
      if (agentReconnectRef.current.timer) {
        window.clearTimeout(agentReconnectRef.current.timer);
        agentReconnectRef.current.timer = null;
      }
      if (agentEventSourceRef.current) {
        agentEventSourceRef.current.close();
        agentEventSourceRef.current = null;
      }
      agentReconnectRef.current.attempts = 0;
      const suffix = agentLastSeqRef.current
        ? `?last_event_id=${agentLastSeqRef.current}`
        : "";
      const source = new EventSource(
        `${api.agentEventsUrl(sessionId)}${suffix}`,
      );
      agentEventSourceRef.current = source;
      const onEvent = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (
            payload &&
            typeof payload.seq === "number" &&
            payload.seq > agentLastSeqRef.current
          ) {
            agentLastSeqRef.current = payload.seq;
          }
          handleAgentEvent(payload);
        } catch {
          // Ignore malformed frames; the backend continues to stream.
        }
      };
      AGENT_EVENT_TYPES.forEach((type) =>
        source.addEventListener(type, onEvent),
      );
      source.onmessage = onEvent;
      source.onopen = () => {
        agentReconnectRef.current.attempts = 0;
        setAgentStatus((current) =>
          current === "connecting" || current === "reconnecting"
            ? "ready"
            : current,
        );
      };
      source.onerror = () => {
        agentReconnectRef.current.attempts += 1;
        if (source.readyState === EventSource.CONNECTING) {
          setAgentStatus("reconnecting");
          return;
        }
        if (source.readyState === EventSource.CLOSED) {
          if (agentReconnectRef.current.attempts > 5) {
            setAgentStatus("error");
            return;
          }
          setAgentStatus("reconnecting");
          agentReconnectRef.current.timer = window.setTimeout(() => {
            openAgentEvents(sessionId);
          }, 1500);
        }
      };
    },
    [handleAgentEvent],
  );

  const ensureAgentSession = useCallback(async () => {
    if (agentSessionId) return agentSessionId;
    if (agentSessionPromiseRef.current) return agentSessionPromiseRef.current;
    const promise = (async () => {
      setAgentStatus("connecting");
      const data = await api.createAgentSession();
      agentLastSeqRef.current = 0;
      setAgentSessionId(data.session_id);
      setAgentStatus("ready");
      openAgentEvents(data.session_id);
      return data.session_id;
    })();
    agentSessionPromiseRef.current = promise;
    try {
      return await promise;
    } finally {
      agentSessionPromiseRef.current = null;
    }
  }, [agentSessionId, openAgentEvents]);

  const buildAgentContext = useCallback(() => {
    return {
      current_process: {
        process_id: processId,
        version: viewingVersion || latestVersion || null,
        content_hash: contentHash,
        spec: spec || null,
      },
      dirty,
      latest_version: latestVersion,
      viewing_version: viewingVersion,
      reliability: reliability
        ? {
            process_version: reliability.process_version,
            process_hash: reliability.process_hash,
            nodes: reliability.nodes || [],
          }
        : null,
    };
  }, [
    contentHash,
    dirty,
    latestVersion,
    processId,
    reliability,
    spec,
    viewingVersion,
  ]);

  const handleAgentSend = useCallback(
    async (text) => {
      const command = text.trim();
      if (!command || agentBusy) return;
      setAgentBusy(true);
      setAgentStatus("sending");
      setCurrentTool(null);
      appendMessage("user", command);
      const context = buildAgentContext();
      const taskContext = {
        processId,
        latestVersion,
        viewingVersion,
        dirty,
      };
      try {
        const sessionId = await ensureAgentSession();
        const result = await api.sendAgentMessage(sessionId, command, context);
        if (result?.task_id) {
          agentTaskContextRef.current[result.task_id] = taskContext;
        }
        setAgentStatus("running");
      } catch (error) {
        if (error.status === 404) {
          try {
            if (agentEventSourceRef.current) {
              agentEventSourceRef.current.close();
              agentEventSourceRef.current = null;
            }
            agentLastSeqRef.current = 0;
            const data = await api.createAgentSession();
            setAgentSessionId(data.session_id);
            setAgentStatus("ready");
            openAgentEvents(data.session_id);
            const result = await api.sendAgentMessage(
              data.session_id,
              command,
              context,
            );
            if (result?.task_id) {
              agentTaskContextRef.current[result.task_id] = taskContext;
            }
            setAgentStatus("running");
            return;
          } catch (retryError) {
            setAgentBusy(false);
            setAgentStatus("error");
            appendMessage("assistant", `执行失败：${retryError.message}`);
            return;
          }
        }
        setAgentBusy(false);
        setAgentStatus("error");
        appendMessage("assistant", `执行失败：${error.message}`);
      }
    },
    [
      agentBusy,
      appendMessage,
      buildAgentContext,
      dirty,
      ensureAgentSession,
      latestVersion,
      openAgentEvents,
      processId,
      viewingVersion,
    ],
  );

  const handleCancelAgent = useCallback(async () => {
    if (!agentSessionId) return;
    try {
      await api.cancelAgentTask(agentSessionId);
    } catch (error) {
      showToast(error.message || "取消 Agent 任务失败");
    }
    setAgentBusy(false);
    setAgentStatus("cancelled");
    setCurrentTool(null);
  }, [agentSessionId, showToast]);

  const applyProcessProposal = useCallback(
    (message) => {
      if (!message?.spec) return;
      if (!isStructureValid(message.validation)) {
        showToast("该 Process IR 存在结构错误，不能应用到画布。");
        return;
      }
      const state = agentStateRef.current;
      const baseProcessId =
        message.baseProcessId ||
        agentTaskContextRef.current[message.taskId]?.processId ||
        null;
      const keepExisting =
        Boolean(baseProcessId) &&
        Boolean(state.processId) &&
        baseProcessId === state.processId;
      if (state.spec && state.dirty) {
        const ok = window.confirm(
          "当前画布有未保存修改。应用 Agent 方案会替换当前草稿，是否继续？",
        );
        if (!ok) return;
      }
      const nextSpec = ensurePositions(normalizeSpec(message.spec));
      setSpec(nextSpec);
      if (keepExisting) {
        setViewingVersion(state.latestVersion);
      } else {
        setProcessId(null);
        setLatestVersion(0);
        setViewingVersion(null);
        setVersions([]);
      }
      setDirty(true);
      setIssues(message.validation?.issues || []);
      setValidationState(message.validation?.valid ? "valid" : "invalid");
      setContentHash(message.validation?.content_hash || null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setMessages((current) =>
        current.map((item) =>
          item.id === message.id ? { ...item, applied: true } : item,
        ),
      );
      fitLater();
      showToast(
        keepExisting
          ? "已把 Agent 方案应用到当前流程草稿，请检查后手动保存。"
          : "已把 Agent 方案应用为新的流程草稿，请检查后手动保存。",
      );
    },
    [fitLater, showToast],
  );

  const applyReliabilityProposal = useCallback(
    (message) => {
      const state = agentStateRef.current;
      if (!state.processId) {
        showToast("请先保存 Process IR，再应用可靠性配置。");
        return;
      }
      if (state.dirty) {
        showToast("当前流程有未保存修改，请先保存流程再应用可靠性配置。");
        return;
      }
      if (state.viewingVersion !== state.latestVersion) {
        showToast("请切换到最新流程版本后再应用可靠性配置。");
        return;
      }
      const spec = message?.spec;
      if (
        !spec ||
        spec.process_version !== state.latestVersion ||
        spec.process_hash !== state.contentHash
      ) {
        showToast("该可靠性方案绑定的流程版本或哈希已过期，请让 Agent 重新生成。");
        return;
      }
      setReliability({
        schema_version: "reliability-ir/1.0",
        process_id: state.processId,
        process_version: spec.process_version,
        process_hash: spec.process_hash,
        reliability_id: "rel_proposed",
        revision: 0,
        nodes: spec.nodes || [],
        proposed: true,
      });
      setReliabilityStatus("proposed");
      setReliabilityStale([]);
      setReliabilityProcess({
        process_id: state.processId,
        version: spec.process_version,
        content_hash: spec.process_hash,
      });
      setMessages((current) =>
        current.map((item) =>
          item.id === message.id
            ? { ...item, applied: true, saveError: "" }
            : item,
        ),
      );
      showToast("已应用 Agent 可靠性方案到可靠性面板，请检查参数后确认保存。");
    },
    [showToast],
  );

  const saveReliabilityProposal = useCallback(
    async (message) => {
      const state = agentStateRef.current;
      const spec = message?.spec;
      if (!state.processId) {
        setMessages((current) =>
          current.map((item) =>
            item.id === message.id
              ? { ...item, saveError: "请先保存 Process IR。" }
              : item,
          ),
        );
        return;
      }
      if (state.dirty || state.viewingVersion !== state.latestVersion) {
        setMessages((current) =>
          current.map((item) =>
            item.id === message.id
              ? { ...item, saveError: "请先保存并切换到最新流程版本。" }
              : item,
          ),
        );
        return;
      }
      if (
        !spec ||
        spec.process_version !== state.latestVersion ||
        spec.process_hash !== state.contentHash
      ) {
        setMessages((current) =>
          current.map((item) =>
            item.id === message.id
              ? { ...item, saveError: "可靠性方案绑定的流程版本或哈希已过期。" }
              : item,
          ),
        );
        return;
      }
      setReliabilityBusy(true);
      try {
        const result = await api.saveReliability(state.processId, {
          process_version: spec.process_version,
          process_hash: spec.process_hash,
          nodes: spec.nodes || [],
        });
        setReliability(result.reliability);
        setReliabilityStatus("bound");
        setReliabilityStale([]);
        setReliabilityProcess({
          process_id: state.processId,
          version: result.reliability.process_version,
          content_hash: result.reliability.process_hash,
        });
        setMessages((current) =>
          current.map((item) =>
            item.id === message.id
              ? { ...item, saved: true, saveError: "" }
              : item,
          ),
        );
        showToast(`可靠性配置已保存为 revision ${result.reliability.revision}`);
      } catch (error) {
        const messageText =
          issuesFromError(error)
            .map((issue) => issue.message)
            .join("；") || error.message || "保存可靠性配置失败";
        setMessages((current) =>
          current.map((item) =>
            item.id === message.id
              ? { ...item, saveError: messageText }
              : item,
          ),
        );
      } finally {
        setReliabilityBusy(false);
      }
    },
    [showToast],
  );

  const selectedNodeContext = useMemo(
    () => (selectedNodeId ? nested.findNode(spec, selectedNodeId) : null),
    [selectedNodeId, spec],
  );
  const selectedNode = selectedNodeContext?.node || null;
  const selectedNodePath = selectedNodeContext?.path || [];
  const selectedEdge = useMemo(
    () =>
      selectedEdgeId ? nested.findEdge(spec, selectedEdgeId)?.edge || null : null,
    [selectedEdgeId, spec],
  );

  const reliabilityNode = useMemo(
    () => reliabilityNodeFor(reliability, selectedNode?.id),
    [reliability, selectedNode],
  );

  const reliabilityContext = useMemo(() => {
    const staleCount = reliabilityStale.length;
    let hint = "";
    if (!processId) {
      hint = "流程尚未保存。保存 Process IR 后才能绑定可靠性配置。";
    } else if (viewingVersion !== latestVersion) {
      hint = `正在查看历史版本 v${viewingVersion}。可靠性配置只能绑定最新版本 v${latestVersion}。`;
    } else if (dirty) {
      hint = "当前 Process IR 有未保存修改。请先保存流程，再保存可靠性配置，避免错误绑定。";
    } else if (reliabilityStatus === "loading") {
      hint = "正在加载当前版本的可靠性配置…";
    } else if (reliabilityStatus === "error") {
      hint = "可靠性配置加载失败。";
    } else if (reliabilityStatus === "stale") {
      hint = `当前 Process IR v${viewingVersion} 尚无可靠性配置。${staleCount} 个旧版本配置仅保留用于历史，不会自动绑定。`;
    } else if (reliabilityStatus === "missing") {
      hint = `当前 Process IR v${viewingVersion} 尚未配置可靠性。保存后会创建独立 Reliability IR 绑定。`;
    } else if (reliabilityStatus === "proposed") {
      hint = "当前显示 Agent 提议的可靠性配置，尚未保存。请检查每个 task 节点并确认保存。";
    } else if (reliabilityStatus === "bound") {
      const expectedUnit = lambdaUnitFor(project.simulation_unit || "day");
      const unitMismatch = (reliability?.nodes || []).some(
        (node) =>
          node.module_type === "stage" &&
          node.lambda_unit &&
          node.lambda_unit !== expectedUnit,
      );
      hint = unitMismatch
        ? "阶段故障率 λ 的单位与当前项目仿真单位不一致，请重新保存可靠性配置。"
        : `可靠性配置已绑定当前 Process IR v${viewingVersion}。`;
    }
    const canSave =
      Boolean(processId) &&
      viewingVersion === latestVersion &&
      !dirty &&
      Boolean(reliabilityProcess) &&
      reliabilityStatus !== "loading" &&
      reliabilityStatus !== "error";
    return {
      process: reliabilityProcess,
      reliability,
      status: reliabilityStatus,
      staleCount,
      hint,
      canSave,
      busy: reliabilityBusy,
      simulationUnit: project.simulation_unit || "day",
    };
  }, [
    dirty,
    latestVersion,
    processId,
    project.simulation_unit,
    reliability,
    reliabilityBusy,
    reliabilityProcess,
    reliabilityStale,
    reliabilityStatus,
    viewingVersion,
  ]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="identity">
          <div className="logo" aria-hidden="true">
            RF
          </div>
          <div>
            <strong>Reliability Flow Agent</strong>
            <span>通用流程建模与设备可靠性仿真 · Phase 4B</span>
          </div>
        </div>
        <div className="header-meta">
          <span className={`pill ${meta?.offline_capable ? "good" : ""}`}>
            离线仿真可用
          </span>
          <span className="pill">
            LLM {meta?.llm?.enabled ? "已启用" : "未启用"}
          </span>
          <span className="pill">Process IR 单源</span>
        </div>
      </header>

      <div className="workspace">
        <AgentPanel
          messages={messages}
          busy={agentBusy}
          onSend={handleAgentSend}
          processes={processes}
          activeProcessId={processId}
          onOpenProcess={openProcess}
          onNewProcess={() => createNewProcess()}
          onImport={handleImportClick}
          agentStatus={agentStatus}
          currentTool={currentTool}
          onCancel={handleCancelAgent}
          onApplyProcessProposal={applyProcessProposal}
          onApplyReliabilityProposal={applyReliabilityProposal}
          onSaveReliabilityProposal={saveReliabilityProposal}
          reliabilityBusy={reliabilityBusy}
        />

        <main className="canvas-column">
          <ProjectPanel
            project={project}
            onChange={updateProject}
            validation={projectValidation}
            onOpenSimulation={() => setSimulationOpen(true)}
            simulationOpen={simulationOpen}
            collapsed={projectCollapsed}
            onToggleCollapsed={() =>
              setProjectCollapsed((current) => !current)
            }
          />

          <Toolbar
            spec={spec}
            processId={processId}
            dirty={dirty}
            busy={busy}
            contentHash={contentHash}
            validationState={validationState}
            versions={versions}
            latestVersion={latestVersion}
            viewingVersion={viewingVersion}
            onVersionChange={loadVersion}
            onValidate={validateNow}
            onSave={saveProcess}
            onAutoLayout={autoLayout}
            onFitView={() => fitView({ padding: 0.22, duration: 300 })}
            onAddNode={addNode}
            onImport={handleImportClick}
            onExport={exportJson}
            onReload={() => processId && openProcess(processId)}
            onOpenSimulation={() => setSimulationOpen((current) => !current)}
            simulationOpen={simulationOpen}
            simulationRunning={simulationRunning}
            simulationPhase={simulationPhase}
            onRunSimulation={startSimulation}
            onExpandAll={expandAllBlocks}
            onCollapseAll={collapseAllBlocks}
          />

          <div className="canvas-card">
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_event, node) => {
                setSelectedNodeId(node.id);
                setSelectedEdgeId(null);
                setInspectorTab("business");
              }}
              onNodeDoubleClick={(_event, node) => {
                if (node.type === "subprocess") handleToggleBlock(node.id);
              }}
              onEdgeClick={(_event, edge) => {
                setSelectedEdgeId(edge.id);
                setSelectedNodeId(null);
                setInspectorTab("business");
              }}
              onPaneClick={() => {
                setSelectedNodeId(null);
                setSelectedEdgeId(null);
                setInspectorTab("business");
              }}
              onNodeDragStop={handleNodeDragStop}
              onNodesDelete={handleNodesDelete}
              onEdgesDelete={handleEdgesDelete}
              onConnect={handleConnect}
              minZoom={0.3}
              maxZoom={1.8}
              fitView
              fitViewOptions={{ padding: 0.18, minZoom: 0.4, maxZoom: 1.15 }}
              proOptions={{ hideAttribution: true }}
              deleteKeyCode={["Backspace", "Delete"]}
              connectionLineStyle={{ stroke: "#7c3aed", strokeWidth: 1.8 }}
            >
              <Background color="#dbe3ec" gap={22} size={1.2} />
              <MiniMap
                pannable
                zoomable
                nodeColor={(node) =>
                  ({
                    start: "#10b981",
                    end: "#3b82f6",
                    decision: "#f59e0b",
                    task: "#6479cb",
                    subprocess: "#7c3aed",
                  })[node.type] || "#94a3b8"
                }
              />
              <Controls showInteractive={false} />
            </ReactFlow>
            {preview?.svg && preview.visible && (
              <div className="canvas-preview-overlay">
                <div className="canvas-preview-toolbar">
                  <span>
                    SVG 预览 ·{" "}
                    {isStructureValid(preview.validation)
                      ? "结构合法"
                      : "存在结构错误"}
                    {preview.validation?.config_pending
                      ? " · 仿真参数待配置"
                      : ""}
                  </span>
                  <div className="canvas-preview-actions">
                    <button
                      type="button"
                      className="button primary compact"
                      onClick={() => {
                        applyProcessProposal({
                          id: `preview:${preview.taskId || "task"}`,
                          spec: preview.spec,
                          validation: preview.validation,
                          baseProcessId: null,
                          taskId: preview.taskId,
                        });
                        setPreview((current) =>
                          current ? { ...current, visible: false } : current,
                        );
                      }}
                      disabled={!isStructureValid(preview.validation)}
                    >
                      应用到画布
                    </button>
                    <button
                      type="button"
                      className="button compact"
                      onClick={() =>
                        setPreview((current) =>
                          current ? { ...current, visible: false } : current,
                        )
                      }
                    >
                      关闭预览
                    </button>
                  </div>
                </div>
                <div
                  className="canvas-preview-svg"
                  dangerouslySetInnerHTML={{ __html: preview.svg }}
                />
              </div>
            )}
            {preview?.svg && !preview.visible && (
              <button
                type="button"
                className="canvas-preview-reopen"
                onClick={() =>
                  setPreview((current) =>
                    current ? { ...current, visible: true } : current,
                  )
                }
              >
                重新打开 SVG 预览
              </button>
            )}
            {!spec && (
              <div className="empty-overlay">
                <h2>还没有流程</h2>
                <p>在左侧 Agent 新建流程，或从 JSON 导入。</p>
              </div>
            )}
          </div>

          <SimulationPanel
            open={simulationOpen}
            onClose={() => setSimulationOpen(false)}
            processId={processId}
            processVersion={viewingVersion}
            dirty={dirty}
            reliabilityStatus={reliabilityStatus}
            project={project}
            projectValidation={projectValidation}
            reliabilityReadiness={reliabilityReadiness}
            validationState={validationState}
            form={simulationForm}
            onFormChange={updateSimulationForm}
            onRun={startSimulation}
            running={simulationRunning}
            phase={simulationPhase}
            error={simulationError}
            result={simulationResult}
            experiments={experiments}
            experimentLoading={experimentLoading}
            onListExperiments={refreshExperiments}
            onLoadExperiment={loadExperiment}
          />

          <IssuesBar issues={issues} validationState={validationState} />
        </main>

        <Inspector
          spec={spec}
          processId={processId}
          latestVersion={latestVersion}
          viewingVersion={viewingVersion}
          versions={versions}
          selectedNode={selectedNode}
          selectedNodePath={selectedNodePath}
          selectedEdge={selectedEdge}
          reliabilityNode={reliabilityNode}
          reliabilityContext={reliabilityContext}
          onUpdateNode={updateNode}
          onDeleteNode={deleteNode}
          onUpdateEdge={updateEdge}
          onDeleteEdge={deleteEdge}
          onUpdateProcess={updateProcess}
          onLoadVersion={loadVersion}
          onSaveReliability={saveReliabilityForNode}
          project={project}
          initialTab={inspectorTab}
        />
      </div>

      {toast && <div className="toast">{toast}</div>}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={handleFileChange}
      />
    </div>
  );
}
