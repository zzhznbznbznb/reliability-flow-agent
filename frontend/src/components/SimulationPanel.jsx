import { useEffect, useState } from "react";

import {
  buildEvaluationTargets,
  formatNumber,
  formatPercent,
  targetMetricLabel,
  targetStatusLabel,
  targetStatusTone,
} from "../simulation";

const INITIAL_FORM = {
  entity_count: "10",
  simulation_end: "30",
  random_seed: "2026",
  failure_policy: "require_failure_exit",
  overall_reliability_min: "",
  end_availability_min: "",
};

const FAILURE_POLICIES = [
  { value: "require_failure_exit", label: "必须有故障出口（require_failure_exit）" },
  { value: "stop_entity", label: "无故障出口时停止设备（stop_entity）" },
];

function formatError(error) {
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
  return error?.message || "仿真评价失败";
}

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

function NodeTable({ nodes }) {
  return (
    <div className="result-section">
      <div className="section-heading">
        <h3>节点级指标</h3>
        <span className="section-note">实际统计与理论指标分列</span>
      </div>
      <p className="help">
        实际故障频率来自本次仿真抽样；设备平均理论可靠度和联合无故障概率是理论指标，
        不能替代实际仿真统计。
      </p>
      {nodes.length === 0 ? (
        <p className="issues-empty">没有参与可靠性计算的节点。</p>
      ) : (
        <div className="table-scroll">
          <table className="result-table">
            <thead>
              <tr>
                <th>节点</th>
                <th>λ（次/日）</th>
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
                  <td>{node.lambda}</td>
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
  const availabilityNote = overall.availability_evaluable
    ? "按结束时明确状态计算"
    : "存在未知结束状态，不可评价";

  return (
    <div className="simulation-results">
      <div className="simulation-meta">
        {result.result_id && (
          <span className="pill good">结果 {result.result_id}</span>
        )}
        <span className="pill">Process v{simulation.process_version}</span>
        <span className="pill">Reliability r{simulation.reliability_revision}</span>
        <span className="pill">设备 {simulation.entity_count}</span>
        <span className="pill">仿真结束 {simulation.simulation_end} 天</span>
        <span className="pill">种子 {simulation.random_seed}</span>
        <span className="pill">可靠性抽样 {simulation.reliability_sample_count}</span>
        <span className="pill">事件 {simulation.event_count}</span>
      </div>

      <div className="metric-grid">
        <MetricCard
          label="整体可靠性（实际）"
          value={formatPercent(overall.overall_reliability, 4)}
          note={`${overall.ever_failed_entity_count}/${overall.entity_count} 台设备曾经故障`}
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
      <NodeTable nodes={evaluation.nodes} />
      <EntityTable entities={evaluation.entities || []} />

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
  onRun,
  experiments = [],
  experimentLoading = false,
  onListExperiments,
  onLoadExperiment,
}) {
  const [form, setForm] = useState(INITIAL_FORM);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [loadingResultId, setLoadingResultId] = useState(null);

  useEffect(() => {
    setResult(null);
    setError("");
  }, [processId, processVersion]);

  useEffect(() => {
    if (open && onListExperiments) {
      onListExperiments();
    }
  }, [open, onListExperiments]);

  if (!open) return null;

  const updateField = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const loadResult = async (resultId) => {
    if (!onLoadExperiment) return;
    setError("");
    setLoadingResultId(resultId);
    try {
      const record = await onLoadExperiment(resultId);
      setResult(record);
    } catch (loadError) {
      setError(formatError(loadError));
    } finally {
      setLoadingResultId(null);
    }
  };

  const canRun =
    Boolean(processId) &&
    !dirty &&
    reliabilityStatus === "bound" &&
    !running;

  const readinessHint = !processId
    ? "请先保存 Process IR 并配置 Reliability IR。"
    : dirty
      ? "流程有未保存修改。请先保存流程，再运行仿真评估。"
      : reliabilityStatus === "loading"
        ? "正在加载当前版本的可靠性配置…"
        : reliabilityStatus !== "bound"
          ? "当前 Process IR 版本没有绑定的 Reliability IR，请先保存可靠性配置。"
          : "使用当前保存的 Process IR 和 Reliability IR 执行真实仿真，并自动调用 Evaluation。";

  const run = async () => {
    setError("");
    setResult(null);

    const entityCount = Number(form.entity_count);
    if (!Number.isInteger(entityCount) || entityCount < 1) {
      setError("设备数量必须是大于等于 1 的整数。");
      return;
    }
    const simulationEnd = Number(form.simulation_end);
    if (!Number.isFinite(simulationEnd) || simulationEnd <= 0) {
      setError("仿真结束时间必须是大于 0 的数字。");
      return;
    }
    const randomSeed = Number(form.random_seed);
    if (!Number.isInteger(randomSeed) || randomSeed < 0) {
      setError("随机种子必须是大于等于 0 的整数。");
      return;
    }
    const { targets, error: targetError } = buildEvaluationTargets(
      form.overall_reliability_min,
      form.end_availability_min,
    );
    if (targetError) {
      setError(targetError);
      return;
    }

    const payload = {
      entity_count: entityCount,
      simulation_end: simulationEnd,
      random_seed: randomSeed,
      failure_policy: form.failure_policy,
    };
    if (targets) payload.evaluation_targets = targets;

    setRunning(true);
    try {
      const data = await onRun(payload);
      setResult(data);
    } catch (runError) {
      setError(formatError(runError));
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="simulation-panel">
      <div className="simulation-head">
        <div>
          <span className="eyebrow">SIMULATION + EVALUATION</span>
          <h2>仿真评估</h2>
          <p>真实 Runtime 执行后自动调用现有 Evaluation，并展示量化评价结果。</p>
        </div>
        <button type="button" className="button compact" onClick={onClose}>
          收起
        </button>
      </div>

      <div className="simulation-controls">
        <div className="field-row">
          <div className="field">
            <label htmlFor="sim-entity-count">设备数量</label>
            <input
              id="sim-entity-count"
              type="number"
              min="1"
              step="1"
              value={form.entity_count}
              onChange={(event) => updateField("entity_count", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="sim-end">仿真结束时间（天）</label>
            <input
              id="sim-end"
              type="number"
              min="0.1"
              step="0.1"
              value={form.simulation_end}
              onChange={(event) => updateField("simulation_end", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="sim-seed">随机种子</label>
            <input
              id="sim-seed"
              type="number"
              min="0"
              step="1"
              value={form.random_seed}
              onChange={(event) => updateField("random_seed", event.target.value)}
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="sim-policy">故障处理策略</label>
          <select
            id="sim-policy"
            value={form.failure_policy}
            onChange={(event) => updateField("failure_policy", event.target.value)}
          >
            {FAILURE_POLICIES.map((policy) => (
              <option key={policy.value} value={policy.value}>
                {policy.label}
              </option>
            ))}
          </select>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="sim-overall-target">整体可靠性目标（0-1）</label>
            <input
              id="sim-overall-target"
              type="number"
              min="0"
              max="1"
              step="0.01"
              placeholder="留空表示不设置"
              value={form.overall_reliability_min}
              onChange={(event) =>
                updateField("overall_reliability_min", event.target.value)
              }
            />
          </div>
          <div className="field">
            <label htmlFor="sim-availability-target">结束可用性目标（0-1）</label>
            <input
              id="sim-availability-target"
              type="number"
              min="0"
              max="1"
              step="0.01"
              placeholder="留空表示不设置"
              value={form.end_availability_min}
              onChange={(event) =>
                updateField("end_availability_min", event.target.value)
              }
            />
          </div>
        </div>

        <p className={`help simulation-hint ${canRun ? "" : "warn-text"}`}>
          {readinessHint}
        </p>
        {error && <div className="form-error">{error}</div>}

        <div className="inspector-actions">
          <button
            type="button"
            className="button primary"
            onClick={run}
            disabled={!canRun}
          >
            {running ? "正在运行仿真并评价…" : "运行仿真并评价"}
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
          <p>运行后，这里会显示整体指标、目标达成、节点指标、警告和评价解释。</p>
        </div>
      ) : (
        <ResultView result={result} />
      )}
    </section>
  );
}
