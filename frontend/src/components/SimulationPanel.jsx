import { useEffect, useState } from "react";

import {
  formatNumber,
  formatPercent,
  formatSimulationError,
  targetMetricLabel,
  targetStatusLabel,
  targetStatusTone,
} from "../simulation";
import { lambdaUnitLabel, unitLabel } from "../project.js";

const FAILURE_POLICIES = [
  { value: "require_failure_exit", label: "必须有故障出口（require_failure_exit）" },
  { value: "stop_entity", label: "无故障出口时停止设备（stop_entity）" },
];

const FAILURE_SAMPLING_MODES = [
  {
    value: "time_to_failure",
    label: "任务内故障时刻抽样（time_to_failure，推荐）",
  },
  {
    value: "interval_end",
    label: "任务完成时区间抽样（interval_end，Phase 3 兼容）",
  },
];

const PHASE_LABELS = {
  idle: "未运行",
  preparing: "准备中",
  running: "运行中",
  success: "运行成功",
  error: "运行失败",
};

function MetricCard({ label, value, note, tone }) {
  return (
    <div className={`metric-card ${tone || ""}`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {note && <span className="metric-note">{note}</span>}
    </div>
  );
}

function TargetTable({ evaluation }) {
  return (
    <div className="result-section">
      <div className="section-heading">
        <h3>目标达成</h3>
        <span className={`pill ${targetStatusTone(evaluation.target_status)}`}>
          {targetStatusLabel(evaluation.target_status)}
        </span>
      </div>
      <div className="table-scroll">
        <table className="result-table">
          <thead>
            <tr>
              <th>指标</th>
              <th>实际值</th>
              <th>目标值</th>
              <th>差距</th>
              <th>状态</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            {evaluation.targets.map((target) => (
              <tr key={target.metric}>
                <td>{targetMetricLabel(target.metric)}</td>
                <td>{formatPercent(target.actual, 4)}</td>
                <td>
                  {target.target === null
                    ? "未设置"
                    : formatPercent(target.target, 4)}
                </td>
                <td>{formatPercent(target.gap, 4)}</td>
                <td>
                  <span className={`pill ${targetStatusTone(target.status)}`}>
                    {targetStatusLabel(target.status)}
                  </span>
                </td>
                <td>{target.reason || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function NodeTable({ nodes, unit }) {
  const lambdaLabels = {
    per_hour: `次/${unitLabel("hour")}`,
    per_day: `次/${unitLabel("day")}`,
    per_month: `次/${unitLabel("month")}`,
    per_year: `次/${unitLabel("year")}`,
  };
  return (
    <div className="result-section">
      <div className="section-heading">
        <h3>可靠性节点 / 阶段指标</h3>
        <span className="section-note">实际统计与理论指标分列</span>
      </div>
      <p className="help">
        只有阶段节点配置故障率 λ。逐时间步抽样的理论存活概率是各步 R(t) 的乘积，
        与单次 exp(-λT) 的口径不同；实际故障频率来自本次仿真。
      </p>
      {nodes.length === 0 ? (
        <p className="issues-empty">没有参与可靠性计算的节点。</p>
      ) : (
        <div className="table-scroll">
          <table className="result-table">
            <thead>
              <tr>
                <th>节点</th>
                <th>类型</th>
                <th>阶段主任务</th>
                <th>λ</th>
                <th>访问</th>
                <th>抽样</th>
                <th>故障</th>
                <th>实际故障频率</th>
                <th>设备平均理论可靠度</th>
                <th>联合理论无故障概率</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((node) => (
                <tr key={node.node_id}>
                  <td>
                    <strong>{node.node_name}</strong>
                    <div className="table-subtext">{node.node_id}</div>
                  </td>
                  <td>
                    {node.module_type === "stage" ? "阶段" : "活动"}
                    {Array.isArray(node.scope_path) && node.scope_path.length > 0
                      ? ` · ${node.scope_path.join(" / ")}`
                      : ""}
                  </td>
                  <td>{node.stage_task_id || "—"}</td>
                  <td>
                    {node.lambda}
                    <div className="table-subtext">
                      {lambdaLabels[node.lambda_unit] || node.lambda_unit}
                    </div>
                  </td>
                  <td>{node.visit_count}</td>
                  <td>{node.sample_count}</td>
                  <td>{node.failure_count}</td>
                  <td>{formatPercent(node.empirical_failure_frequency, 4)}</td>
                  <td>{formatNumber(node.mean_entity_theoretical_reliability, 6)}</td>
                  <td>
                    {formatNumber(node.joint_theoretical_no_failure_probability, 6)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="help">
        仿真单位：{unit}。阶段故障率单位必须与仿真单位一致。
      </p>
    </div>
  );
}

function TestTable({ tests }) {
  if (!tests || tests.length === 0) {
    return null;
  }
  return (
    <div className="result-section">
      <div className="section-heading">
        <h3>测试模块 / 故障检测</h3>
        <span className="section-note">每个测试阶段只随机抽取一次 pt</span>
      </div>
      <div className="table-scroll">
        <table className="result-table">
          <thead>
            <tr>
              <th>测试节点</th>
              <th>Ft</th>
              <th>测试次数</th>
              <th>有故障次数</th>
              <th>发现故障</th>
              <th>未发现故障</th>
              <th>发现频率</th>
              <th>测试时间</th>
            </tr>
          </thead>
          <tbody>
            {tests.map((test) => (
              <tr key={test.node_id}>
                <td>
                  <strong>{test.node_name}</strong>
                  <div className="table-subtext">{test.node_id}</div>
                </td>
                <td>{test.detection_rate}</td>
                <td>{test.test_count}</td>
                <td>{test.had_fault_count}</td>
                <td>{test.detected_count}</td>
                <td>{test.undetected_count}</td>
                <td>{formatPercent(test.detection_frequency, 4)}</td>
                <td>{test.test_time ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const END_STATE_LABELS = {
  good: "正常结束",
  bad: "异常结束",
  unknown: "未知",
};

function EntityTable({ entities }) {
  return (
    <details className="result-section entity-section">
      <summary className="section-heading entity-summary">
        <h3>设备级指标</h3>
        <span className="section-note">{entities.length} 台设备（点击展开）</span>
      </summary>
      {entities.length === 0 ? (
        <p className="issues-empty">没有设备级结果。</p>
      ) : (
        <div className="table-scroll">
          <table className="result-table">
            <thead>
              <tr>
                <th>设备</th>
                <th>最终节点</th>
                <th>结束分类</th>
                <th>结束状态</th>
                <th>故障</th>
                <th>维修</th>
                <th>可用时间</th>
                <th>不可用时间</th>
                <th>当前故障</th>
                <th>完成</th>
                <th>停止原因</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => (
                <tr key={entity.entity_id}>
                  <td>{entity.entity_id}</td>
                  <td>{entity.final_node_id}</td>
                  <td>
                    {END_STATE_LABELS[entity.end_state_classification] ||
                      entity.end_state_classification}
                  </td>
                  <td>{entity.final_status || "—"}</td>
                  <td>{entity.failure_count}</td>
                  <td>{entity.repair_count}</td>
                  <td>{formatNumber(entity.available_time, 2)}</td>
                  <td>{formatNumber(entity.unavailable_time, 2)}</td>
                  <td>{entity.currently_failed ? "是" : "否"}</td>
                  <td>{entity.completed ? "是" : "否"}</td>
                  <td>{entity.stopped_reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function ResultView({ result }) {
  const { simulation, evaluation, explanation } = result;
  const overall = evaluation.overall;
  const unit = unitLabel(simulation.simulation_unit || "day");
  const availabilityNote = overall.availability_evaluable
    ? "按结束时明确状态计算"
    : "存在未知结束状态，不可评价";
  const totalTime =
    simulation.simulation_duration ??
    simulation.project?.simulation_total_time ??
    "N/A";
  const eventCounts = {};
  for (const event of simulation.events || []) {
    const key = event.event_type || "unknown";
    eventCounts[key] = (eventCounts[key] || 0) + 1;
  }
  const eventRows = Object.entries(eventCounts).sort(
    (left, right) => right[1] - left[1],
  );

  return (
    <div className="simulation-results">
      <div className="simulation-meta">
        {result.result_id && (
          <span className="pill good">结果 {result.result_id}</span>
        )}
        {simulation.project?.name && (
          <span className="pill good">{simulation.project.name}</span>
        )}
        <span className="pill">Process v{simulation.process_version}</span>
        <span className="pill">Reliability r{simulation.reliability_revision}</span>
        <span className="pill">导弹/设备 {simulation.entity_count}</span>
        <span className="pill">仿真单位 {unit}</span>
        <span className="pill">
          仿真开始 {simulation.simulation_start} {unit}
        </span>
        <span className="pill">
          仿真结束 {simulation.simulation_end} {unit}
        </span>
        <span className="pill">
          仿真总时间 {totalTime} {unit}
        </span>
        <span className="pill">种子 {simulation.random_seed}</span>
        {simulation.runtime_semantic_version && (
          <span className="pill">Runtime {simulation.runtime_semantic_version}</span>
        )}
        <span className="pill">可靠性抽样 {simulation.reliability_sample_count}</span>
        <span className="pill">事件 {simulation.event_count}</span>
      </div>

      {simulation.project && (
        <div className="project-result-summary">
          <div>
            <span className="eyebrow">PROJECT</span>
            <strong>{simulation.project.name}</strong>
            <p>{simulation.project.description}</p>
          </div>
          <div className="project-result-goals">
            <span>
              可靠度目标 {formatPercent(simulation.project.reliability_target, 2)}
            </span>
            <span>
              战备完好度目标 {formatPercent(simulation.project.readiness_target, 2)}
            </span>
            <span>导弹总数量 {simulation.project.missile_count}</span>
            <span>
              仿真单位 {unitLabel(simulation.project.simulation_unit)}
            </span>
            <span>
              仿真总时间 {simulation.project.simulation_total_time ?? "N/A"}{" "}
              {unitLabel(simulation.project.simulation_unit)}
            </span>
          </div>
        </div>
      )}

      <div className="metric-grid">
        <MetricCard
          label="装备使用可靠度（实际）"
          value={formatPercent(overall.overall_reliability, 4)}
          note={`${overall.ever_failed_entity_count}/${overall.entity_count} 台设备曾经故障`}
        />
        <MetricCard
          label="战备完好度（时间口径）"
          value={formatPercent(overall.readiness, 4)}
          note={`可用 ${formatNumber(overall.total_available_time, 2)} / 不可用 ${formatNumber(
            overall.total_unavailable_time,
            2,
          )} ${unit}`}
          tone={overall.readiness !== null && overall.readiness >= 0 ? "good" : ""}
        />
        <MetricCard
          label="结束可用性 / 完好率（实际）"
          value={formatPercent(overall.end_availability, 4)}
          note={availabilityNote}
        />
        <MetricCard
          label="故障总数（实际）"
          value={overall.total_failure_count}
          note="来自本次仿真可靠性抽样"
        />
        <MetricCard
          label="维修总数（实际）"
          value={overall.total_repair_count}
          note={`维修完成 ${overall.repair_completed_count}`}
        />
        <MetricCard
          label="完成设备（实际）"
          value={overall.completed_entity_count}
          note={`设备总数 ${overall.entity_count}`}
        />
        <MetricCard
          label="未完成设备（实际）"
          value={overall.unfinished_entity_count}
          note={`停止 ${overall.stopped_entity_count}`}
        />
        <MetricCard
          label="平均故障次数 / 台"
          value={formatNumber(overall.mean_failure_count_per_entity, 4)}
          note="实际仿真统计"
        />
        <MetricCard
          label="平均维修次数 / 台"
          value={formatNumber(overall.mean_repair_count_per_entity, 4)}
          note="实际仿真统计"
        />
      </div>

      <TargetTable evaluation={evaluation} />
      <NodeTable nodes={evaluation.nodes} unit={unit} />
      <TestTable tests={evaluation.tests || []} />
      <EntityTable entities={evaluation.entities || []} />

      {eventRows.length > 0 && (
        <details className="result-section">
          <summary className="section-heading entity-summary">
            <h3>运行事件摘要</h3>
            <span className="section-note">
              {simulation.events.length} 条事件（点击展开）
            </span>
          </summary>
          <div className="event-summary-grid">
            {eventRows.map(([eventType, count]) => (
              <div className="event-summary-item" key={eventType}>
                <span>{eventType}</span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </details>
      )}

      {evaluation.warnings.length > 0 && (
        <div className="result-section">
          <div className="section-heading">
            <h3>评价警告</h3>
            <span className="section-note">{evaluation.warnings.length} 条</span>
          </div>
          <ul className="warning-list">
            {evaluation.warnings.map((warning, index) => (
              <li key={`${warning.code}-${index}`}>
                <span className={`pill ${warning.severity === "warning" ? "warn" : ""}`}>
                  {warning.code}
                </span>
                <span>{warning.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {evaluation.limitations.length > 0 && (
        <div className="result-section">
          <div className="section-heading">
            <h3>评价限制</h3>
          </div>
          <ul className="limitation-list">
            {evaluation.limitations.map((item, index) => (
              <li key={`${item}-${index}`}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="result-section">
        <div className="section-heading">
          <h3>评价解释</h3>
        </div>
        <pre className="explanation-text">{explanation}</pre>
      </div>
    </div>
  );
}

function ExperimentHistory({
  experiments,
  loading,
  onRefresh,
  onLoad,
  loadingResultId,
}) {
  return (
    <div className="result-section experiment-history">
      <div className="section-heading">
        <h3>实验历史</h3>
        <button type="button" className="button compact" onClick={onRefresh} disabled={loading}>
          {loading ? "加载中…" : "刷新"}
        </button>
      </div>
      {experiments.length === 0 ? (
        <p className="issues-empty">还没有已保存的实验结果。</p>
      ) : (
        <div className="experiment-list">
          {experiments.map((item) => (
            <button
              type="button"
              key={item.result_id}
              className="experiment-item"
              onClick={() => onLoad(item.result_id)}
              disabled={loadingResultId === item.result_id}
            >
              <span className="experiment-id">{item.result_id}</span>
              <span className="experiment-meta">
                {item.process_name || item.process_id} · v{item.process_version} ·
                Reliability r{item.reliability_revision}
              </span>
              <span className="experiment-meta">
                {new Date(item.created_at).toLocaleString()} · 目标{" "}
                {targetStatusLabel(item.target_status)} · 整体可靠度{" "}
                {formatPercent(item.overall_reliability, 2)}
                {item.simulation_total_time != null ||
                item.simulation_duration != null
                  ? ` · 总时间 ${
                      item.simulation_total_time ?? item.simulation_duration
                    } ${unitLabel(item.simulation_unit || "day")}`
                  : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SimulationPanel({
  open,
  onClose,
  processId,
  processVersion,
  dirty,
  reliabilityStatus,
  project,
  projectValidation,
  reliabilityReadiness,
  validationState,
  form,
  onFormChange,
  onRun,
  running = false,
  phase = "idle",
  error = "",
  result = null,
  experiments = [],
  experimentLoading = false,
  onListExperiments,
  onLoadExperiment,
}) {
  const unit = unitLabel(project?.simulation_unit || "day");
  const [loadingResultId, setLoadingResultId] = useState(null);
  const [loadError, setLoadError] = useState("");
  const totalTime = project?.simulation_total_time ?? "";
  const totalTimeNumber = Number(totalTime);
  const totalTimeValid =
    String(totalTime).trim() !== "" &&
    Number.isFinite(totalTimeNumber) &&
    totalTimeNumber > 0;

  useEffect(() => {
    if (open && onListExperiments) {
      onListExperiments();
    }
  }, [open, onListExperiments]);

  useEffect(() => {
    setLoadError("");
  }, [processId, processVersion]);

  if (!open) return null;

  const updateField = (key, value) => {
    onFormChange?.(key, value);
  };

  const loadResult = async (resultId) => {
    if (!onLoadExperiment) return;
    setLoadError("");
    setLoadingResultId(resultId);
    try {
      await onLoadExperiment(resultId);
    } catch (loadErrorValue) {
      setLoadError(formatSimulationError(loadErrorValue));
    } finally {
      setLoadingResultId(null);
    }
  };

  const projectReady = Boolean(projectValidation?.valid);
  const parametersReady = Boolean(reliabilityReadiness?.ready);
  const canRun =
    Boolean(processId) &&
    !dirty &&
    reliabilityStatus === "bound" &&
    projectReady &&
    totalTimeValid &&
    parametersReady &&
    validationState === "valid" &&
    !running;

  const readinessHint = !projectReady
    ? projectValidation?.message ||
      "请先补全项目名称、描述、目标值、仿真单位、仿真总时间和导弹总数量。"
    : !totalTimeValid
      ? `请填写大于 0 的仿真总时间（单位：${unit}）。`
      : validationState !== "valid"
        ? "流程结构校验未通过，请先修正底部校验问题。"
        : !parametersReady
          ? "仿真参数未就绪，请根据下方提示补齐阶段故障率、检测率或持续时间。"
          : !processId
            ? "请先保存 Process IR 并配置 Reliability IR。"
            : dirty
              ? "流程有未保存修改。请先保存流程，再运行仿真评估。"
              : reliabilityStatus === "loading"
                ? "正在加载当前版本的可靠性配置…"
                : reliabilityStatus !== "bound"
                  ? "当前 Process IR 版本没有绑定的 Reliability IR，请先保存可靠性配置。"
                  : "使用完整项目参数、当前 Process IR 和 Reliability IR 执行真实仿真，并自动调用 Evaluation。";

  return (
    <section className="simulation-panel" aria-label="仿真运行与结果">
      <div className="simulation-head">
        <div>
          <span className="eyebrow">SIMULATION + EVALUATION</span>
          <h2>仿真运行与结果</h2>
          <p>
            真实 Runtime 执行后自动调用现有 Evaluation，并展示量化评价结果。
          </p>
        </div>
        <div className="simulation-head-actions">
          <span className={`pill simulation-phase ${phase}`}>
            {PHASE_LABELS[phase] || phase}
          </span>
          <button type="button" className="button compact" onClick={onClose}>
            收起
          </button>
        </div>
      </div>

      <div className="simulation-controls">
        <div className="simulation-time-readout">
          <div>
            <span className="eyebrow">SIMULATION TIME</span>
            <strong>
              仿真总时间 {totalTimeValid ? totalTime : "未填写"} {unit}
            </strong>
            <p>
              来自“项目基本信息与仿真目标”。按当前仿真单位直接计时，
              不做固定天数换算。
            </p>
          </div>
          <span className={`pill ${totalTimeValid ? "good" : "warn"}`}>
            {totalTimeValid ? "总时间已配置" : "总时间待填写"}
          </span>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="sim-start">仿真开始时间（{unit}）</label>
            <input
              id="sim-start"
              type="number"
              min="0"
              step="0.1"
              value={form?.simulation_start ?? "0"}
              onChange={(event) =>
                updateField("simulation_start", event.target.value)
              }
            />
          </div>
          <div className="field">
            <label>导弹总数量（来自项目参数）</label>
            <input
              value={project?.missile_count ?? ""}
              readOnly
              placeholder="请在项目参数区填写"
            />
          </div>
          <div className="field">
            <label htmlFor="sim-seed">随机种子</label>
            <input
              id="sim-seed"
              type="number"
              min="0"
              step="1"
              value={form?.random_seed ?? "2026"}
              onChange={(event) =>
                updateField("random_seed", event.target.value)
              }
            />
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="sim-policy">故障处理策略</label>
            <select
              id="sim-policy"
              value={form?.failure_policy ?? "require_failure_exit"}
              onChange={(event) =>
                updateField("failure_policy", event.target.value)
              }
            >
              {FAILURE_POLICIES.map((policy) => (
                <option key={policy.value} value={policy.value}>
                  {policy.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="sim-sampling">故障抽样方式</label>
            <select
              id="sim-sampling"
              value={form?.failure_sampling ?? "time_to_failure"}
              onChange={(event) =>
                updateField("failure_sampling", event.target.value)
              }
            >
              {FAILURE_SAMPLING_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="project-target-readout">
          <div>
            <span className="eyebrow">EVALUATION TARGETS</span>
            <strong>目标值来自项目参数区</strong>
          </div>
          <span>
            装备使用可靠度目标{" "}
            {formatPercent(project?.reliability_target, 2)}
          </span>
          <span>
            战备完好度目标 {formatPercent(project?.readiness_target, 2)}
          </span>
          <span>
            故障率单位 次/{lambdaUnitLabel(project?.simulation_unit || "day")}
          </span>
        </div>

        <p className={`help simulation-hint ${canRun ? "" : "warn-text"}`}>
          {readinessHint}
        </p>
        {!parametersReady && reliabilityReadiness?.issues?.length > 0 && (
          <ul className="readiness-issues">
            {reliabilityReadiness.issues.map((issue, index) => (
              <li key={`${issue}-${index}`}>{issue}</li>
            ))}
          </ul>
        )}
        {(error || loadError) && (
          <div className="form-error simulation-error">
            {error || loadError}
          </div>
        )}

        <div className="inspector-actions">
          <button
            type="button"
            className="button primary simulation-run-button"
            onClick={onRun}
            disabled={!canRun || running}
          >
            {running
              ? phase === "preparing"
                ? "准备中…"
                : "仿真运行中…"
              : "运行仿真"}
          </button>
        </div>
      </div>

      <ExperimentHistory
        experiments={experiments}
        loading={experimentLoading}
        onRefresh={onListExperiments}
        onLoad={loadResult}
        loadingResultId={loadingResultId}
      />

      {!result ? (
        <div className="simulation-empty">
          <p>
            运行后，这里会显示整体指标、目标达成、节点指标、警告和评价解释。
          </p>
        </div>
      ) : (
        <ResultView result={result} />
      )}
    </section>
  );
}
