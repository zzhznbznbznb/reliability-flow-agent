import { lambdaUnitFor, lambdaUnitLabel, unitLabel } from "./project.js";

export const LAMBDA_UNIT = "per_day";
export const DISTRIBUTION = "exponential";
export const MODULE_TYPE = {
  activity: "activity",
  stage: "stage",
  test: "test",
};

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

export function validateDetectionRateInput(rawValue) {
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return { detectionRate: null, error: "测试模块必须填写故障检测率 Ft" };
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { detectionRate: null, error: "Ft 必须是有限数字" };
  }
  if (value < 0 || value > 1) {
    return { detectionRate: null, error: "Ft 必须在 0 到 1 之间" };
  }
  return { detectionRate: value, error: "" };
}

export function validateTestTimeInput(rawValue) {
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return { testTime: null, error: "" };
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) {
    return { testTime: null, error: "测试时间必须是大于 0 的数字" };
  }
  return { testTime: value, error: "" };
}

export function firstTaskId(node) {
  const nodes = node?.subflow?.nodes || [];
  for (const child of nodes) {
    if (child.type === "task") return child.id;
    if (child.subflow) {
      const nested = firstTaskId(child);
      if (nested) return nested;
    }
  }
  return null;
}

function taskDefault(node, unit) {
  return {
    node_id: node.id,
    module_type: MODULE_TYPE.activity,
    participates: false,
    distribution: DISTRIBUTION,
    lambda: null,
    lambda_unit: lambdaUnitFor(unit),
    detection_rate: null,
    test_time: null,
    stage_task_id: null,
  };
}

function normalizeExisting(node) {
  return {
    node_id: node.node_id,
    module_type: node.module_type || MODULE_TYPE.activity,
    participates: Boolean(node.participates),
    distribution: node.distribution || DISTRIBUTION,
    lambda: node.lambda ?? null,
    lambda_unit: node.lambda_unit || LAMBDA_UNIT,
    detection_rate: node.detection_rate ?? null,
    test_time: node.test_time ?? null,
    stage_task_id: node.stage_task_id ?? null,
  };
}

export function buildReliabilityNodes(
  nodes,
  existingNodes,
  editNodeId,
  edit,
  options = {},
) {
  const unit = options.simulationUnit || "day";
  const existing = new Map(
    (existingNodes || []).map((node) => [node.node_id, node]),
  );
  const result = [];
  for (const node of nodes || []) {
    if (node.type && node.type !== "task" && node.type !== "subprocess") {
      continue;
    }
    const current = existing.get(node.id);
    const isEdited = node.id === editNodeId;
    if (node.type === "subprocess") {
      if (!isEdited && !current) continue;
      const base = current ? normalizeExisting(current) : {
        node_id: node.id,
        module_type: MODULE_TYPE.stage,
        participates: true,
        distribution: DISTRIBUTION,
        lambda: 0,
        lambda_unit: lambdaUnitFor(unit),
        detection_rate: null,
        test_time: null,
        stage_task_id: firstTaskId(node),
      };
      if (!isEdited) {
        result.push(base);
        continue;
      }
      const parsed = validateLambdaInput(
        edit.participates !== false,
        edit.lambda,
      );
      result.push({
        ...base,
        module_type: MODULE_TYPE.stage,
        participates: true,
        lambda: parsed.lambda,
        lambda_unit: edit.lambda_unit || lambdaUnitFor(unit),
        detection_rate: null,
        test_time: null,
        stage_task_id:
          edit.stage_task_id || base.stage_task_id || firstTaskId(node),
      });
      continue;
    }

    if (!isEdited && !current) {
      result.push(taskDefault(node, unit));
      continue;
    }
    if (!isEdited && current) {
      result.push(normalizeExisting(current));
      continue;
    }

    const moduleType = edit.module_type || MODULE_TYPE.activity;
    if (moduleType === MODULE_TYPE.test) {
      result.push({
        ...(current ? normalizeExisting(current) : taskDefault(node, unit)),
        node_id: node.id,
        module_type: MODULE_TYPE.test,
        participates: false,
        lambda: null,
        detection_rate: edit.detection_rate ?? null,
        test_time: edit.test_time ?? null,
        stage_task_id: null,
      });
      continue;
    }
    if (moduleType === MODULE_TYPE.stage) {
      // A task must never become a stage; the Inspector only offers stage on
      // subprocess blocks. Keep this branch defensive.
      result.push({
        ...(current ? normalizeExisting(current) : taskDefault(node, unit)),
        module_type: MODULE_TYPE.activity,
        participates: false,
      });
      continue;
    }
    const participates = Boolean(edit.participates);
    const lambda = participates
      ? (edit.lambda ?? null)
      : (edit.lambda ?? current?.lambda ?? null);
    result.push({
      ...(current ? normalizeExisting(current) : taskDefault(node, unit)),
      node_id: node.id,
      module_type: MODULE_TYPE.activity,
      participates,
      lambda: lambda ?? null,
      lambda_unit: edit.lambda_unit || current?.lambda_unit || lambdaUnitFor(unit),
      detection_rate: null,
      test_time: null,
      stage_task_id: null,
    });
  }
  return result;
}

export function reliabilityNodeFor(reliability, nodeId) {
  if (!reliability || !Array.isArray(reliability.nodes)) return null;
  return reliability.nodes.find((node) => node.node_id === nodeId) || null;
}

export function formatLambda(value, unit = "day") {
  if (value === null || value === undefined || value === "") return "未配置";
  return `${value} 次/${lambdaUnitLabel(unit)}`;
}

export function formatUnit(unit) {
  return unitLabel(unit);
}

function walkScope(scope, visitor) {
  for (const node of scope.nodes || []) {
    visitor(node);
    if (node.subflow) walkScope(node.subflow, visitor);
  }
}

export function validateReliabilityReadiness(spec, reliability, project) {
  const issues = [];
  const nodes = [];
  if (spec) {
    walkScope(spec, (node) => nodes.push(node));
  }
  const configs = new Map(
    (reliability?.nodes || []).map((node) => [node.node_id, node]),
  );
  const unit = project?.simulation_unit || "day";
  const expectedUnit = lambdaUnitFor(unit);
  if (!reliability) {
    issues.push("可靠性配置尚未保存或加载。");
    return { ready: false, issues };
  }
  const subprocesses = nodes.filter((node) => node.type === "subprocess");
  for (const node of subprocesses) {
    const config = configs.get(node.id);
    if (!config || config.module_type !== "stage") {
      issues.push(`嵌套流程块「${node.name}」缺少阶段故障率 λ。`);
      continue;
    }
    if (config.lambda === null || config.lambda === undefined) {
      issues.push(`嵌套流程块「${node.name}」缺少阶段故障率 λ。`);
    }
    if (config.lambda_unit && config.lambda_unit !== expectedUnit) {
      issues.push(
        `嵌套流程块「${node.name}」的 λ 单位与仿真单位不一致，请重新保存可靠性配置。`,
      );
    }
    const stageTask = nodes.find((item) => item.id === config.stage_task_id);
    if (stageTask && stageTask.duration == null) {
      issues.push(`阶段主任务「${stageTask.name}」缺少持续时间。`);
    }
  }
  for (const node of nodes) {
    if (node.type !== "task") continue;
    const config = configs.get(node.id);
    const nameText = String(node.name || "").trim();
    const nameLooksLikeTest =
      !nameText.includes("场") &&
      (nameText.includes("检测") || nameText.endsWith("测试"));
    const isTest =
      config?.module_type === "test" || nameLooksLikeTest;
    if (isTest) {
      if (!config || config.module_type !== "test") {
        issues.push(`测试节点「${node.name}」尚未配置为测试模块。`);
      } else if (
        config.detection_rate === null ||
        config.detection_rate === undefined
      ) {
        issues.push(`测试模块「${node.name}」缺少故障检测率 Ft。`);
      }
      if (
        (config?.test_time === null || config?.test_time === undefined) &&
        node.duration == null
      ) {
        issues.push(`测试模块「${node.name}」缺少测试时间。`);
      }
    } else if (node.duration == null) {
      issues.push(`普通活动「${node.name}」缺少持续时间。`);
    }
  }
  return { ready: issues.length === 0, issues };
}

