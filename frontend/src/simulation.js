export const TARGET_STATUS_LABELS = {
  achieved: "已达成",
  not_achieved: "未达成",
  unevaluable: "无法评价",
  not_configured: "未设置",
};

export const TARGET_METRIC_LABELS = {
  overall_reliability: "装备使用可靠度",
  end_availability: "结束可用性",
  readiness: "战备完好度",
};

export function formatPercent(value, digits = 4) {
  if (value === null || value === undefined || value === "") return "N/A";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "N/A";
  return `${(numeric * 100).toFixed(digits)}%`;
}

export function formatNumber(value, digits = 6) {
  if (value === null || value === undefined || value === "") return "N/A";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "N/A";
  return numeric.toFixed(digits);
}

export function targetStatusLabel(status) {
  return TARGET_STATUS_LABELS[status] || status || "未知";
}

export function targetMetricLabel(metric) {
  return TARGET_METRIC_LABELS[metric] || metric;
}

export function targetStatusTone(status) {
  if (status === "achieved") return "good";
  if (status === "not_achieved") return "bad";
  if (status === "unevaluable") return "warn";
  return "";
}

export function formatSimulationError(error) {
  const payload = error?.payload;
  if (Array.isArray(payload?.issues) && payload.issues.length) {
    return payload.issues.map((issue) => issue.message).join("；");
  }
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    if (Array.isArray(detail.issues) && detail.issues.length) {
      return detail.issues.map((issue) => issue.message).join("；");
    }
    if (typeof detail.message === "string") {
      return detail.error
        ? `${detail.message}：${detail.error}`
        : detail.message;
    }
  }
  return error?.message || "仿真运行失败";
}

export function parseOptionalTarget(rawValue, label) {
  const text = String(rawValue ?? "").trim();
  if (!text) return { value: null, error: "" };
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { value: null, error: `${label}必须是数字` };
  }
  if (value < 0 || value > 1) {
    return { value: null, error: `${label}必须在 0 到 1 之间` };
  }
  return { value, error: "" };
}

export function buildTargetsFromProject(project) {
  if (!project) return null;
  const reliability = parseOptionalTarget(
    project.reliability_target,
    "装备使用可靠度目标",
  );
  const readiness = parseOptionalTarget(
    project.readiness_target,
    "战备完好度目标",
  );
  if (reliability.error || readiness.error) return null;
  return {
    overall_reliability_min: reliability.value,
    readiness_min: readiness.value,
  };
}

export function buildEvaluationTargets(overallRaw, endRaw) {
  const overall = parseOptionalTarget(overallRaw, "整体可靠性目标");
  if (overall.error) return { targets: null, error: overall.error };
  const end = parseOptionalTarget(endRaw, "结束可用性目标");
  if (end.error) return { targets: null, error: end.error };
  if (overall.value === null && end.value === null) {
    return { targets: null, error: "" };
  }
  return {
    targets: {
      overall_reliability_min: overall.value,
      end_availability_min: end.value,
    },
    error: "",
  };
}
