import { useEffect, useState } from "react";

import { findNode } from "../flow/nested";
import {
  firstTaskId,
  validateDetectionRateInput,
  validateLambdaInput,
  validateTestTimeInput,
} from "../reliability";
import { lambdaUnitFor, lambdaUnitLabel, unitLabel } from "../project.js";

function collectSubflowTasks(node, result = []) {
  for (const child of node?.subflow?.nodes || []) {
    if (child.type === "task") result.push(child);
    if (child.subflow) collectSubflowTasks(child, result);
  }
  return result;
}

function looksLikeTestNode(node) {
  if (node?.type !== "task") return false;
  const text = String(node.name || "").trim();
  if (text.includes("场")) return false;
  return text.includes("检测") || text.endsWith("测试");
}

const TYPE_LABEL = {
  start: "开始",
  task: "业务活动",
  decision: "判断",
  end: "结束",
  subprocess: "嵌套流程块",
};

const EDGE_KIND_LABEL = {
  normal: "普通出口",
  conditional: "条件出口",
  default: "默认兜底",
  failure: "故障出口",
};

function parseJsonArray(text, fieldName) {
  const parsed = JSON.parse(text || "[]");
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} 必须是 JSON 数组`);
  }
  return parsed;
}

function StatusOptions({ statuses, value, onChange, id }) {
  return (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">未指定</option>
      {statuses.map((status) => (
        <option key={status.id} value={status.id}>
          {status.name} ({status.id})
          {status.counts_as_available ? " · 计入完好" : " · 不计入完好"}
        </option>
      ))}
    </select>
  );
}

function shortHash(hash) {
  return hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "未保存";
}

function NodeEditor({
  node,
  spec,
  onUpdate,
  onDelete,
  reliabilityNode,
  reliabilityContext,
  onSaveReliability,
  selectedNodePath = [],
  project,
  initialTab = "business",
}) {
  const [tab, setTab] = useState(initialTab);
  const [name, setName] = useState(node.name);
  const [type, setType] = useState(node.type);
  const [description, setDescription] = useState(node.description || "");
  const [duration, setDuration] = useState(
    node.duration === null || node.duration === undefined
      ? ""
      : String(node.duration),
  );
  const [statusOnEnter, setStatusOnEnter] = useState(node.status_on_enter || "");
  const [statusOnComplete, setStatusOnComplete] = useState(
    node.status_on_complete || "",
  );
  const [effectsEnter, setEffectsEnter] = useState(
    JSON.stringify(node.on_enter || [], null, 2),
  );
  const [effectsComplete, setEffectsComplete] = useState(
    JSON.stringify(node.on_complete || [], null, 2),
  );
  const [outcomes, setOutcomes] = useState(
    JSON.stringify(node.outcomes || [], null, 2),
  );
  const [error, setError] = useState("");
  const [moduleType, setModuleType] = useState(
    node.type === "subprocess"
      ? "stage"
      : reliabilityNode?.module_type === "test" || looksLikeTestNode(node)
        ? "test"
        : "activity",
  );
  const [lambdaInput, setLambdaInput] = useState(
    reliabilityNode?.lambda === null || reliabilityNode?.lambda === undefined
      ? ""
      : String(reliabilityNode.lambda),
  );
  const [detectionInput, setDetectionInput] = useState(
    reliabilityNode?.detection_rate === null ||
      reliabilityNode?.detection_rate === undefined
      ? ""
      : String(reliabilityNode.detection_rate),
  );
  const [testTimeInput, setTestTimeInput] = useState(
    reliabilityNode?.test_time === null ||
      reliabilityNode?.test_time === undefined
      ? ""
      : String(reliabilityNode.test_time),
  );
  const [stageTaskInput, setStageTaskInput] = useState(
    reliabilityNode?.stage_task_id ||
      firstTaskId(node) ||
      "",
  );
  const [reliabilityError, setReliabilityError] = useState("");
  const [reliabilitySaving, setReliabilitySaving] = useState(false);

  useEffect(() => {
    setModuleType(
      node.type === "subprocess"
        ? "stage"
        : reliabilityNode?.module_type === "test" || looksLikeTestNode(node)
          ? "test"
          : "activity",
    );
    setLambdaInput(
      reliabilityNode?.lambda === null || reliabilityNode?.lambda === undefined
        ? ""
        : String(reliabilityNode.lambda),
    );
    setDetectionInput(
      reliabilityNode?.detection_rate === null ||
        reliabilityNode?.detection_rate === undefined
        ? ""
        : String(reliabilityNode.detection_rate),
    );
    setTestTimeInput(
      reliabilityNode?.test_time === null ||
        reliabilityNode?.test_time === undefined
        ? ""
        : String(reliabilityNode.test_time),
    );
    setStageTaskInput(
      reliabilityNode?.stage_task_id || firstTaskId(node) || "",
    );
    setReliabilityError("");
  }, [
    node,
    reliabilityNode?.node_id,
    reliabilityNode?.module_type,
    reliabilityNode?.lambda,
    reliabilityNode?.detection_rate,
    reliabilityNode?.test_time,
    reliabilityNode?.stage_task_id,
  ]);

  const apply = () => {
    setError("");
    try {
      if (!name.trim()) throw new Error("节点名称不能为空");
      const parsedEnter = parseJsonArray(effectsEnter, "进入效果");
      const parsedComplete = parseJsonArray(effectsComplete, "完成效果");
      const parsedOutcomes =
        type === "task" ? parseJsonArray(outcomes, "业务结果") : [];
      let parsedDuration = null;
      if (type === "task") {
        const text = String(duration ?? "").trim();
        if (text) {
          parsedDuration = Number(text);
          if (!Number.isFinite(parsedDuration) || parsedDuration < 0) {
            throw new Error("持续时间必须是非负数字");
          }
        }
      }
      const updated = {
        id: node.id,
        type,
        name: name.trim(),
        description,
        position: node.position,
        duration: parsedDuration,
        status_on_enter: statusOnEnter || null,
        status_on_complete: statusOnComplete || null,
        on_enter: parsedEnter,
        on_complete: parsedComplete,
        outcomes: parsedOutcomes,
        ...(type === "subprocess" ? { subflow: node.subflow } : {}),
      };
      onUpdate(updated);
    } catch (err) {
      setError(err.message);
    }
  };

  const saveReliability = async () => {
    setReliabilityError("");
    if (!reliabilityContext?.canSave) {
      setReliabilityError(
        reliabilityContext?.hint || "当前流程状态不允许保存可靠性配置",
      );
      return;
    }
    const unit = project?.simulation_unit || "day";
    let edit;
    if (node.type === "subprocess") {
      const parsed = validateLambdaInput(true, lambdaInput);
      if (parsed.error) {
        setReliabilityError(parsed.error);
        return;
      }
      if (!stageTaskInput) {
        setReliabilityError("阶段模块必须选择一个内部主任务");
        return;
      }
      edit = {
        module_type: "stage",
        participates: true,
        lambda: parsed.lambda,
        lambda_unit: lambdaUnitFor(unit),
        stage_task_id: stageTaskInput,
      };
    } else if (moduleType === "test") {
      const detection = validateDetectionRateInput(detectionInput);
      if (detection.error) {
        setReliabilityError(detection.error);
        return;
      }
      const testTime = validateTestTimeInput(testTimeInput);
      if (testTime.error) {
        setReliabilityError(testTime.error);
        return;
      }
      edit = {
        module_type: "test",
        participates: false,
        lambda: null,
        detection_rate: detection.detectionRate,
        test_time: testTime.testTime,
      };
    } else {
      edit = {
        module_type: "activity",
        participates: false,
        lambda: null,
      };
    }
    setReliabilitySaving(true);
    try {
      const result = await onSaveReliability(node.id, edit);
      if (result && !result.ok) {
        setReliabilityError(result.message || "可靠性配置保存失败");
      }
    } finally {
      setReliabilitySaving(false);
    }
  };

  return (
    <div className="inspector-body">
      <div className="inspector-heading">
        <span className="eyebrow">NODE INSPECTOR</span>
        <h2>{node.name}</h2>
        <p>
          {TYPE_LABEL[node.type]} · <code>{node.id}</code>
        </p>
        {selectedNodePath.length > 0 && (
          <p className="inspector-breadcrumb">
            层级：root / {selectedNodePath.join(" / ")}
          </p>
        )}
      </div>

      <div className="segmented">
        <button
          type="button"
          className={tab === "business" ? "active" : ""}
          onClick={() => setTab("business")}
        >
          业务属性
        </button>
        <button
          type="button"
          className={tab === "reliability" ? "active" : ""}
          onClick={() => setTab("reliability")}
        >
          可靠性
        </button>
      </div>

      {tab === "business" ? (
        <>
          <div className="field">
            <label htmlFor="node-name">名称</label>
            <input
              id="node-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="node-type">节点类型</label>
              <select
                id="node-type"
                value={type}
                onChange={(event) => setType(event.target.value)}
                disabled={node.type === "subprocess"}
              >
                {Object.entries(TYPE_LABEL)
                  .filter(
                    ([value]) =>
                      value !== "subprocess" || node.type === "subprocess",
                  )
                  .map(([value, label]) => (
                    <option key={value} value={value}>
                      {label} ({value})
                    </option>
                  ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="node-duration">
                持续时间（{unitLabel(project?.simulation_unit || "day")}）
              </label>
              <input
                id="node-duration"
                type="number"
                min="0"
                step="0.1"
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                disabled={type !== "task"}
                placeholder="必填，留空会阻止仿真"
              />
              <p className="help">
                与项目仿真单位一致，直接写入 Process IR；留空表示尚未配置，
                运行仿真前会提示补充。
              </p>
            </div>
          </div>
          <div className="field">
            <label htmlFor="node-description">业务说明</label>
            <textarea
              id="node-description"
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="status-enter">进入时状态</label>
              <StatusOptions
                id="status-enter"
                statuses={spec.status_catalog || []}
                value={statusOnEnter}
                onChange={setStatusOnEnter}
              />
            </div>
            <div className="field">
              <label htmlFor="status-complete">完成时状态</label>
              <StatusOptions
                id="status-complete"
                statuses={spec.status_catalog || []}
                value={statusOnComplete}
                onChange={setStatusOnComplete}
              />
            </div>
          </div>

          <details className="advanced">
            <summary>业务结果 outcomes</summary>
            <p className="help">
              用于检测合格/不合格等通用业务分支。此处不含 λ 或可靠性参数。
            </p>
            <textarea
              rows={7}
              value={outcomes}
              onChange={(event) => setOutcomes(event.target.value)}
              disabled={type !== "task"}
            />
          </details>

          <details className="advanced">
            <summary>进入节点效果 on_enter</summary>
            <textarea
              rows={6}
              value={effectsEnter}
              onChange={(event) => setEffectsEnter(event.target.value)}
            />
          </details>

          <details className="advanced">
            <summary>完成节点效果 on_complete</summary>
            <p className="help">
              可通过 set_state、increment_counter 等效果表达维修完成后的状态恢复。
            </p>
            <textarea
              rows={7}
              value={effectsComplete}
              onChange={(event) => setEffectsComplete(event.target.value)}
            />
          </details>

          {error && <div className="form-error">{error}</div>}

          <div className="inspector-actions">
            <button type="button" className="button primary" onClick={apply}>
              应用节点修改
            </button>
            <button
              type="button"
              className="button danger"
              onClick={() => {
                if (window.confirm(`删除节点「${node.name}」及其连接？`)) {
                  onDelete(node.id);
                }
              }}
            >
              删除节点
            </button>
          </div>
        </>
      ) : node.type === "start" ||
        node.type === "end" ||
        node.type === "decision" ? (
        <div className="reliability-placeholder">
          <span className="badge phase">不参与抽样</span>
          <h3>该节点不参与可靠性计算</h3>
          <p>
            start、decision、end 节点正常执行业务流程，不进行随机故障抽样，
            因此不需要 λ 或 Ft。
          </p>
        </div>
      ) : (
        <div className="reliability-panel">
          <div className="reliability-binding">
            <div>
              <span className="eyebrow">BOUND PROCESS IR</span>
              <strong>
                {reliabilityContext?.process
                  ? `v${reliabilityContext.process.version}`
                  : "尚未保存"}
              </strong>
            </div>
            <code>
              {reliabilityContext?.process
                ? shortHash(reliabilityContext.process.content_hash)
                : "无绑定"}
            </code>
          </div>
          <p className="help">
            可靠性配置独立存储，只绑定指定的 Process IR 版本和内容哈希；流程产生新版本后不会自动继承。
          </p>

          {reliabilityContext?.hint && (
            <p className="help reliability-hint">{reliabilityContext.hint}</p>
          )}

          {node.type === "subprocess" ? (
            <>
              <div className="reliability-formula">
                阶段故障率只作用于该嵌套子流程的主任务；t 为该阶段本次进入后的累计时间。
                维修后重新进入主任务时，t 从 0 重新开始。
              </div>
              <div className="field">
                <label htmlFor="node-lambda">
                  阶段故障率 λ（次/{lambdaUnitLabel(project?.simulation_unit || "day")}）
                </label>
                <input
                  id="node-lambda"
                  type="number"
                  min="0"
                  step="any"
                  value={lambdaInput}
                  onChange={(event) => setLambdaInput(event.target.value)}
                  placeholder="例如 0.001"
                />
                <p className="help">
                  单位跟随项目仿真单位（{unitLabel(project?.simulation_unit || "day")}）。
                  允许 λ = 0，表示该阶段不抽样故障。测试节点不配置 λ。
                </p>
              </div>
              <div className="field">
                <label htmlFor="stage-task">阶段主任务（累计计时对象）</label>
                <select
                  id="stage-task"
                  value={stageTaskInput}
                  onChange={(event) => setStageTaskInput(event.target.value)}
                >
                  <option value="">请选择</option>
                  {collectSubflowTasks(node).map((task) => (
                    <option key={task.id} value={task.id}>
                      {task.name}（{task.id}，持续 {task.duration ?? "未设置"}）
                    </option>
                  ))}
                </select>
                <p className="help">
                  例如贮存阶段的“贮存”任务、值班阶段的“值班”任务。普通活动只配置持续时间。
                </p>
              </div>
            </>
          ) : moduleType === "test" ? (
            <>
              <div className="reliability-formula">
                测试模块：每次测试只抽取一次 pt，并与故障检测率 Ft 比较；
                不配置故障率 λ，也不参与独立的指数故障抽样。
              </div>
              <div className="field">
                <label htmlFor="node-detection">
                  故障检测率 Ft（0 ~ 1）
                </label>
                <input
                  id="node-detection"
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={detectionInput}
                  onChange={(event) => setDetectionInput(event.target.value)}
                  placeholder="例如 0.8"
                />
              </div>
              <div className="field">
                <label htmlFor="node-test-time">
                  测试时间（{unitLabel(project?.simulation_unit || "day")}，可选）
                </label>
                <input
                  id="node-test-time"
                  type="number"
                  min="0"
                  step="0.1"
                  value={testTimeInput}
                  onChange={(event) => setTestTimeInput(event.target.value)}
                  placeholder="留空时使用节点持续时间"
                />
              </div>
              <button
                type="button"
                className="button compact"
                onClick={() => setModuleType("activity")}
              >
                改为普通活动
              </button>
            </>
          ) : (
            <>
              <div className="reliability-formula">
                普通活动只配置持续时间，不配置故障率 λ，也不进行独立的指数分布故障抽样。
              </div>
              <p className="help">
                当前节点持续时间：{node.duration ?? "未设置"}{" "}
                {unitLabel(project?.simulation_unit || "day")}。请在“业务属性”页修改持续时间。
              </p>
              {(reliabilityNode?.participates ||
                (reliabilityNode?.lambda !== null &&
                  reliabilityNode?.lambda !== undefined)) && (
                <p className="help reliability-hint">
                  该节点存在旧版活动级 λ 配置。新模型不再在普通活动上使用 λ；
                  保存后将按普通活动处理。
                </p>
              )}
              <button
                type="button"
                className="button compact"
                onClick={() => {
                  setModuleType("test");
                  if (!detectionInput) setDetectionInput("1");
                }}
              >
                设为测试模块
              </button>
            </>
          )}

          {reliabilityError && (
            <div className="form-error">{reliabilityError}</div>
          )}

          <div className="inspector-actions">
            <button
              type="button"
              className="button primary"
              onClick={saveReliability}
              disabled={
                reliabilitySaving ||
                reliabilityContext?.busy ||
                !reliabilityContext?.canSave
              }
            >
              {reliabilitySaving ? "正在保存可靠性配置…" : "保存可靠性配置"}
            </button>
          </div>
          {reliabilityContext?.reliability && (
            <p className="help">
              当前绑定：Process IR v
              {reliabilityContext.reliability.process_version} ·{" "}
              {shortHash(reliabilityContext.reliability.process_hash)} ·
              可靠性修订 r{reliabilityContext.reliability.revision}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function EdgeEditor({ edge, sourceNode, onUpdate, onDelete }) {
  const [kind, setKind] = useState(edge.kind);
  const [label, setLabel] = useState(edge.label || "");
  const [priority, setPriority] = useState(edge.priority ?? 0);
  const [subflowExit, setSubflowExit] = useState(edge.subflow_exit || "");
  const [condition, setCondition] = useState(
    edge.condition ? JSON.stringify(edge.condition, null, 2) : "",
  );
  const [error, setError] = useState("");

  const apply = () => {
    setError("");
    try {
      let parsedCondition = null;
      if (kind === "conditional") {
        if (!condition.trim()) throw new Error("条件出口必须填写 condition JSON");
        parsedCondition = JSON.parse(condition);
        if (typeof parsedCondition !== "object" || Array.isArray(parsedCondition)) {
          throw new Error("condition 必须是 JSON 对象");
        }
      }
      const numericPriority = Number(priority);
      if (!Number.isInteger(numericPriority)) {
        throw new Error("优先级必须是整数");
      }
      onUpdate({
        ...edge,
        kind,
        label,
        priority: numericPriority,
        condition: parsedCondition,
        subflow_exit: subflowExit || null,
      });
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="inspector-body">
      <div className="inspector-heading">
        <span className="eyebrow">EDGE INSPECTOR</span>
        <h2>{edge.from} → {edge.to}</h2>
        <p>
          连接 <code>{edge.id}</code>
        </p>
      </div>

      <div className="field">
        <label>起点 / 终点</label>
        <div className="readonly-pair">
          <code>{edge.from}</code>
          <span>→</span>
          <code>{edge.to}</code>
        </div>
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="edge-kind">连接类型</label>
          <select
            id="edge-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            {Object.entries(EDGE_KIND_LABEL).map(([value, text]) => (
              <option key={value} value={value}>
                {text} ({value})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="edge-priority">优先级</label>
          <input
            id="edge-priority"
            type="number"
            step="1"
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="edge-label">显示标签</label>
        <input
          id="edge-label"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="例如：合格 / 不合格 / 默认"
        />
      </div>
      {sourceNode?.type === "subprocess" && (
        <div className="field">
          <label htmlFor="edge-subflow-exit">子流程出口映射</label>
          <select
            id="edge-subflow-exit"
            value={subflowExit}
            onChange={(event) => setSubflowExit(event.target.value)}
          >
            <option value="">未指定</option>
            {(sourceNode.subflow?.end_node_ids || []).map((endId) => (
              <option key={endId} value={endId}>
                {endId}
              </option>
            ))}
          </select>
          <p className="help">
            父连接通过该字段指定从哪个子流程 end 出口返回。
          </p>
        </div>
      )}
      {kind === "conditional" && (
        <div className="field">
          <label htmlFor="edge-condition">条件表达式 JSON</label>
          <textarea
            id="edge-condition"
            rows={9}
            value={condition}
            onChange={(event) => setCondition(event.target.value)}
            placeholder='{"op":"eq","field":"attributes.inspection_passed","value":true}'
          />
          <p className="help">
            字段可使用 currently_failed、failure_count、repair_count、
            current_status、attributes.* 或 node_visits.*。
          </p>
        </div>
      )}
      {error && <div className="form-error">{error}</div>}
      <div className="inspector-actions">
        <button type="button" className="button primary" onClick={apply}>
          应用连接修改
        </button>
        <button
          type="button"
          className="button danger"
          onClick={() => {
            if (window.confirm("删除这条连接？")) onDelete(edge.id);
          }}
        >
          删除连接
        </button>
      </div>
    </div>
  );
}

function ProcessEditor({
  spec,
  processId,
  latestVersion,
  viewingVersion,
  versions,
  onUpdateProcess,
  onLoadVersion,
}) {
  const [name, setName] = useState(spec.name);
  const [description, setDescription] = useState(spec.description || "");
  const [maxVisits, setMaxVisits] = useState(
    spec.guards?.max_node_visits ?? 10000,
  );
  const [statusCatalog, setStatusCatalog] = useState(
    JSON.stringify(spec.status_catalog || [], null, 2),
  );
  const [error, setError] = useState("");

  const apply = () => {
    setError("");
    try {
      if (!name.trim()) throw new Error("流程名称不能为空");
      const visits = Number(maxVisits);
      if (!Number.isInteger(visits) || visits < 1) {
        throw new Error("最大节点访问次数必须是正整数");
      }
      const catalog = JSON.parse(statusCatalog || "[]");
      if (!Array.isArray(catalog)) {
        throw new Error("状态目录必须是 JSON 数组");
      }
      onUpdateProcess({
        name: name.trim(),
        description,
        guards: { max_node_visits: visits },
        status_catalog: catalog,
      });
    } catch (err) {
      setError(err.message);
    }
  };

  const starts = spec.nodes.filter((node) => node.type === "start");
  const ends = spec.nodes.filter((node) => node.type === "end");

  return (
    <div className="inspector-body">
      <div className="inspector-heading">
        <span className="eyebrow">PROCESS INSPECTOR</span>
        <h2>{spec.name}</h2>
        <p>{processId ? `流程 ${processId}` : "未保存草稿"}</p>
      </div>

      <div className="field">
        <label htmlFor="process-name">流程名称</label>
        <input
          id="process-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="process-description">流程说明</label>
        <textarea
          id="process-description"
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="max-visits">单设备最大节点访问次数</label>
        <input
          id="max-visits"
          type="number"
          min="1"
          step="1"
          value={maxVisits}
          onChange={(event) => setMaxVisits(event.target.value)}
        />
        <p className="help">用于运行时防止循环无限执行。</p>
      </div>
      <div className="field">
        <label>开始 / 结束节点</label>
        <div className="ref-pills">
          {starts.map((node) => (
            <span key={node.id} className="pill good">
              开始：{node.name}
            </span>
          ))}
          {ends.map((node) => (
            <span key={node.id} className="pill">
              结束：{node.name}
            </span>
          ))}
          {starts.length === 0 && <span className="pill bad">缺少开始节点</span>}
          {ends.length === 0 && <span className="pill bad">缺少结束节点</span>}
        </div>
      </div>
      <details className="advanced">
        <summary>状态目录 status_catalog</summary>
        <p className="help">
          Phase 1 只保存通用状态定义；设备完好状态语义将在评价阶段使用。
        </p>
        <textarea
          rows={8}
          value={statusCatalog}
          onChange={(event) => setStatusCatalog(event.target.value)}
        />
      </details>

      {error && <div className="form-error">{error}</div>}
      <div className="inspector-actions">
        <button type="button" className="button primary" onClick={apply}>
          应用流程信息
        </button>
      </div>

      <div className="version-section">
        <div className="section-heading">
          <h3>版本历史</h3>
          <span>{versions.length} 个版本</span>
        </div>
        {viewingVersion !== latestVersion && processId && (
          <p className="help warn-text">
            当前查看历史版本。保存时会基于最新 v{latestVersion} 创建新版本，不会覆盖历史。
          </p>
        )}
        <div className="version-list">
          {versions.length === 0 && (
            <p className="empty-library">尚未保存任何版本。</p>
          )}
          {versions.map((version) => (
            <button
              type="button"
              key={version.version}
              className={`version-item ${
                version.version === viewingVersion ? "active" : ""
              }`}
              onClick={() => onLoadVersion(version.version)}
            >
              <span className="version-number">v{version.version}</span>
              <span className="version-meta">
                {version.node_count} 节点 · {version.edge_count} 连接
              </span>
              <span className="version-hash">
                {version.content_hash.replace(/^sha256:/, "").slice(0, 10)}
              </span>
              {version.version === latestVersion && (
                <span className="pill good">最新</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Inspector({
  spec,
  processId,
  latestVersion,
  viewingVersion,
  versions,
  selectedNode,
  selectedNodePath = [],
  selectedEdge,
  reliabilityNode,
  reliabilityContext,
  onUpdateNode,
  onDeleteNode,
  onUpdateEdge,
  onDeleteEdge,
  onUpdateProcess,
  onLoadVersion,
  onSaveReliability,
  project,
  initialTab = "business",
}) {
  const selectedEdgeSourceNode = selectedEdge
    ? findNode(spec, selectedEdge.from)?.node || null
    : null;
  return (
    <aside className="inspector">
      {!spec ? (
        <div className="inspector-body">
          <div className="inspector-heading">
            <span className="eyebrow">INSPECTOR</span>
            <h2>等待流程</h2>
            <p>选择节点或连接后在此编辑属性。</p>
          </div>
        </div>
      ) : selectedNode ? (
        <NodeEditor
          key={`${selectedNode.id}-${selectedNode.name}-${selectedNode.type}-${selectedNode.duration ?? "none"}-${initialTab}`}
          node={selectedNode}
          spec={spec}
          onUpdate={onUpdateNode}
          onDelete={onDeleteNode}
          reliabilityNode={reliabilityNode}
          reliabilityContext={reliabilityContext}
          onSaveReliability={onSaveReliability}
          selectedNodePath={selectedNodePath}
          project={project}
          initialTab={initialTab}
        />
      ) : selectedEdge ? (
        <EdgeEditor
          key={selectedEdge.id}
          edge={selectedEdge}
          sourceNode={selectedEdgeSourceNode}
          onUpdate={onUpdateEdge}
          onDelete={onDeleteEdge}
        />
      ) : (
        <ProcessEditor
          key={`${processId || "draft"}-${viewingVersion || 0}`}
          spec={spec}
          processId={processId}
          latestVersion={latestVersion}
          viewingVersion={viewingVersion}
          versions={versions}
          onUpdateProcess={onUpdateProcess}
          onLoadVersion={onLoadVersion}
        />
      )}
    </aside>
  );
}
