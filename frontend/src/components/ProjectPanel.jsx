import {
  PROJECT_FIELDS,
  SIMULATION_UNITS,
  lambdaUnitLabel,
  unitLabel,
} from "../project.js";

export default function ProjectPanel({
  project,
  onChange,
  validation,
  onOpenSimulation,
  simulationOpen,
  collapsed = false,
  onToggleCollapsed,
}) {
  const unit = project.simulation_unit || "day";
  const totalTime = String(project.simulation_total_time ?? "").trim();

  if (collapsed) {
    return (
      <section className="project-panel project-panel-collapsed">
        <div className="project-collapsed-summary">
          <div>
            <span className="eyebrow">PROJECT PARAMETERS</span>
            <strong>{project.name || "未命名项目"}</strong>
            <span className="project-collapsed-meta">
              仿真单位 {unitLabel(unit)}
              <span className="dot-sep">·</span>
              仿真总时间 {totalTime || "未填写"} {unitLabel(unit)}
              <span className="dot-sep">·</span>
              导弹 {project.missile_count || "未填写"}
            </span>
          </div>
          <div className="project-head-status">
            <span
              className={`pill ${validation.valid ? "good" : "warn"}`}
              title={validation.message}
            >
              {validation.valid ? "项目参数完整" : "项目参数待补全"}
            </span>
            <button
              type="button"
              className="button compact"
              onClick={onToggleCollapsed}
            >
              展开参数
            </button>
          </div>
        </div>
      </section>
    );
  }

  const renderField = (field) => {
    const value = project[field.key] ?? "";
    const error = validation.fieldErrors[field.key];
    const common = {
      id: `project-${field.key}`,
      value,
      "aria-invalid": Boolean(error),
      onChange: (event) => onChange(field.key, event.target.value),
    };
    return (
      <div
        className={`field project-field project-${field.kind} project-key-${field.key} ${
          error ? "has-error" : ""
        }`}
        key={field.key}
      >
        <label htmlFor={`project-${field.key}`}>
          {field.label}
          {field.required && <span className="required-mark">*</span>}
          {field.key === "simulation_unit" && (
            <span className="field-unit-hint">
              故障率与仿真时间均使用该单位
            </span>
          )}
          {field.key === "simulation_total_time" && (
            <span className="field-unit-hint">
              单位：{unitLabel(unit)}
            </span>
          )}
        </label>
        {field.kind === "textarea" ? (
          <textarea rows={2} placeholder={field.placeholder} {...common} />
        ) : field.kind === "select" ? (
          <select {...common}>
            {SIMULATION_UNITS.map((unitOption) => (
              <option key={unitOption.value} value={unitOption.value}>
                {unitOption.label}（故障率 {unitOption.lambdaLabel}）
              </option>
            ))}
          </select>
        ) : (
          <input
            type={field.kind === "number" ? "number" : "text"}
            min={field.min}
            max={field.max}
            step={field.step}
            placeholder={field.placeholder}
            {...common}
          />
        )}
        {error && <span className="field-error">{error}</span>}
      </div>
    );
  };

  return (
    <section className="project-panel">
      <div className="project-head">
        <div>
          <span className="eyebrow">PROJECT PARAMETERS</span>
          <h2>项目基本信息与仿真目标</h2>
          <p>
            这七项参数会进入正式仿真配置并随实验结果保存。仿真总时间按当前仿真单位直接计时，
            月份和年份不会折算成固定天数。目标值只用于评价，不能替代阶段故障率 λ、
            测试模块检测率 Ft 或普通活动持续时间。
          </p>
        </div>
        <div className="project-head-status">
          <span
            className={`pill ${validation.valid ? "good" : "warn"}`}
            title={validation.message}
          >
            {validation.valid ? "项目参数完整" : "项目参数待补全"}
          </span>
          <button
            type="button"
            className="button compact"
            onClick={onToggleCollapsed}
          >
            收起参数
          </button>
          <button
            type="button"
            className={`button ${simulationOpen ? "primary" : ""}`}
            onClick={onOpenSimulation}
            disabled={!validation.valid}
            title={
              validation.valid
                ? "打开仿真运行面板"
                : validation.message
            }
          >
            {simulationOpen ? "仿真面板已打开" : "打开仿真运行"}
          </button>
        </div>
      </div>

      <div className="project-grid">
        {PROJECT_FIELDS.map(renderField)}
      </div>

      <div className="project-foot">
        <span>
          当前单位：<strong>{unitLabel(unit)}</strong>
          <span className="dot-sep">·</span>
          阶段故障率单位：<strong>{lambdaUnitLabel(unit)}</strong>
          <span className="dot-sep">·</span>
          仿真总时间：
          <strong>
            {totalTime || "未填写"} {unitLabel(unit)}
          </strong>
        </span>
        {!validation.valid && (
          <span className="project-missing">{validation.message}</span>
        )}
      </div>
    </section>
  );
}
