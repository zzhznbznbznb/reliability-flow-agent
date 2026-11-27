export const SIMULATION_UNITS = [
  { value: "hour", label: "小时", lambdaUnit: "per_hour", lambdaLabel: "每小时" },
  { value: "day", label: "天", lambdaUnit: "per_day", lambdaLabel: "每天" },
  { value: "month", label: "月", lambdaUnit: "per_month", lambdaLabel: "每月" },
  { value: "year", label: "年", lambdaUnit: "per_year", lambdaLabel: "每年" },
];

export const SIMULATION_UNIT_VALUES = SIMULATION_UNITS.map(
  (unit) => unit.value,
);

export const PROJECT_FIELDS = [
  {
    key: "name",
    label: "项目名称",
    kind: "text",
    required: true,
    placeholder: "例如：某型导弹贮存值班保障项目",
  },
  {
    key: "description",
    label: "项目描述",
    kind: "textarea",
    required: true,
    placeholder: "说明项目背景、装备对象和仿真目的",
  },
  {
    key: "reliability_target",
    label: "装备使用可靠度目标值",
    kind: "number",
    required: true,
    min: 0,
    max: 1,
    step: 0.01,
    placeholder: "0 ~ 1",
  },
  {
    key: "readiness_target",
    label: "战备完好度目标值",
    kind: "number",
    required: true,
    min: 0,
    max: 1,
    step: 0.01,
    placeholder: "0 ~ 1",
  },
  {
    key: "simulation_unit",
    label: "仿真单位",
    kind: "select",
    required: true,
  },
  {
    key: "simulation_total_time",
    label: "仿真总时间",
    kind: "number",
    required: true,
    min: 0.000001,
    step: 0.1,
    placeholder: "必须大于 0",
  },
  {
    key: "missile_count",
    label: "导弹总数量",
    kind: "number",
    required: true,
    min: 1,
    step: 1,
    placeholder: "正整数",
  },
];

export function emptyProject() {
  return {
    name: "",
    description: "",
    reliability_target: "",
    readiness_target: "",
    simulation_unit: "day",
    simulation_total_time: "",
    missile_count: "",
  };
}

export function unitMeta(unit) {
  return (
    SIMULATION_UNITS.find((item) => item.value === unit) ||
    SIMULATION_UNITS[1]
  );
}

export function unitLabel(unit) {
  return unitMeta(unit).label;
}

export function lambdaUnitFor(unit) {
  return unitMeta(unit).lambdaUnit;
}

export function lambdaUnitLabel(unit) {
  return unitMeta(unit).lambdaLabel;
}

function parseTarget(raw) {
  const text = String(raw ?? "").trim();
  if (!text) {
    return { value: null, error: "必填，请输入 0 到 1 之间的数值" };
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    return { value: null, error: "必须是数值" };
  }
  if (value < 0 || value > 1) {
    return { value: null, error: "必须在 0 到 1 之间" };
  }
  return { value, error: "" };
}

export function validateProject(project) {
  const source = project || {};
  const fieldErrors = {};
  const missing = [];
  const name = String(source.name ?? "").trim();
  if (!name) {
    fieldErrors.name = "项目名称必填";
    missing.push("项目名称");
  }
  const description = String(source.description ?? "").trim();
  if (!description) {
    fieldErrors.description = "项目描述必填";
    missing.push("项目描述");
  }
  const reliability = parseTarget(source.reliability_target);
  if (reliability.error) {
    fieldErrors.reliability_target = `装备使用可靠度目标值：${reliability.error}`;
    missing.push("装备使用可靠度目标值");
  }
  const readiness = parseTarget(source.readiness_target);
  if (readiness.error) {
    fieldErrors.readiness_target = `战备完好度目标值：${readiness.error}`;
    missing.push("战备完好度目标值");
  }
  const unit = String(source.simulation_unit ?? "").trim();
  if (!SIMULATION_UNIT_VALUES.includes(unit)) {
    fieldErrors.simulation_unit = "请选择仿真单位（小时/天/月/年）";
    missing.push("仿真单位");
  }
  const totalText = String(source.simulation_total_time ?? "").trim();
  const totalTime = Number(totalText);
  if (!totalText || !Number.isFinite(totalTime) || totalTime <= 0) {
    fieldErrors.simulation_total_time =
      "仿真总时间必须是大于 0 的合法数值";
    missing.push("仿真总时间");
  }
  const missileText = String(source.missile_count ?? "").trim();
  const missileCount = Number(missileText);
  if (
    !missileText ||
    !Number.isInteger(missileCount) ||
    missileCount < 1
  ) {
    fieldErrors.missile_count = "导弹总数量必须是大于等于 1 的正整数";
    missing.push("导弹总数量");
  }

  const valid = Object.keys(fieldErrors).length === 0;
  return {
    valid,
    missing,
    fieldErrors,
    values: valid
      ? {
          name,
          description,
          reliability_target: reliability.value,
          readiness_target: readiness.value,
          simulation_unit: unit,
          simulation_total_time: totalTime,
          missile_count: missileCount,
        }
      : null,
    message: valid
      ? "项目参数完整，可以运行仿真"
      : `还不能运行仿真：${missing.join("、")}`,
  };
}

export function buildProjectPayload(project) {
  const validation = validateProject(project);
  if (!validation.valid) {
    throw new Error(validation.message);
  }
  return validation.values;
}

export function buildTargetsFromProject(project) {
  const validation = validateProject(project);
  if (!validation.valid) return null;
  return {
    overall_reliability_min: validation.values.reliability_target,
    readiness_min: validation.values.readiness_target,
  };
}
