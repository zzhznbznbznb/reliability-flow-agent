function shortHash(hash) {
  return hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "未保存";
}

const VALIDATION_TEXT = {
  idle: "未校验",
  checking: "校验中",
  valid: "校验通过",
  invalid: "校验失败",
  error: "校验异常",
};

const PHASE_TEXT = {
  idle: "未运行",
  preparing: "准备中",
  running: "运行中",
  success: "运行成功",
  error: "运行失败",
};

export default function Toolbar({
  spec,
  processId,
  dirty,
  busy,
  contentHash,
  validationState,
  versions,
  latestVersion,
  viewingVersion,
  onVersionChange,
  onValidate,
  onSave,
  onAutoLayout,
  onFitView,
  onAddNode,
  onImport,
  onExport,
  onReload,
  onOpenSimulation,
  simulationOpen,
  simulationRunning,
  simulationPhase = "idle",
  onRunSimulation,
  onExpandAll,
  onCollapseAll,
}) {
  const disabled = !spec || busy;
  const historical =
    processId && viewingVersion && viewingVersion !== latestVersion;

  return (
    <section className="toolbar canvas-toolbar" aria-label="流程操作栏">
      <div className="toolbar-meta">
        <select
          className="version-select"
          value={viewingVersion || ""}
          onChange={(event) => {
            const value = Number(event.target.value);
            if (value && value !== viewingVersion) onVersionChange(value);
          }}
          disabled={disabled || versions.length === 0}
          title="查看历史版本"
        >
          {versions.length === 0 && <option value="">无版本</option>}
          {versions.map((version) => (
            <option key={version.version} value={version.version}>
              v{version.version}
              {version.version === latestVersion ? "（最新）" : ""}
            </option>
          ))}
        </select>
        {dirty && <span className="pill warn">未保存</span>}
        {historical && (
          <span className="pill warn">查看历史 v{viewingVersion}</span>
        )}
        <span className={`pill ${validationState === "valid" ? "good" : "warn"}`}>
          {VALIDATION_TEXT[validationState] || validationState}
        </span>
        {processId && (
          <>
            <span className="pill toolbar-process-id" title={processId}>
              {processId}
            </span>
            <span className="pill">哈希 {shortHash(contentHash)}</span>
          </>
        )}
        <span className={`pill simulation-phase ${simulationPhase}`}>
          {PHASE_TEXT[simulationPhase] || simulationPhase}
        </span>
      </div>

      <div className="toolbar-actions">
        <div className="action-group">
          <button className="button compact" onClick={onReload} disabled={!processId || busy}>
            刷新
          </button>
        </div>

        <div className="action-group">
          <span className="group-label">添加</span>
          <button className="button compact" onClick={() => onAddNode("task")} disabled={disabled}>
            + 任务
          </button>
          <button
            className="button compact"
            onClick={() => onAddNode("decision")}
            disabled={disabled}
          >
            + 判断
          </button>
          <button
            className="button compact"
            onClick={() => onAddNode("start")}
            disabled={disabled}
          >
            + 开始
          </button>
          <button
            className="button compact"
            onClick={() => onAddNode("end")}
            disabled={disabled}
          >
            + 结束
          </button>
          <button
            className="button compact"
            onClick={() => onAddNode("subprocess")}
            disabled={disabled}
          >
            + 嵌套块
          </button>
        </div>

        <div className="action-group">
          <button className="button compact" onClick={onValidate} disabled={disabled}>
            校验
          </button>
          <button className="button compact" onClick={onAutoLayout} disabled={disabled}>
            自动布局
          </button>
          <button className="button compact" onClick={onFitView} disabled={disabled}>
            适应屏幕
          </button>
          <button className="button compact" onClick={onExpandAll} disabled={disabled}>
            展开全部
          </button>
          <button className="button compact" onClick={onCollapseAll} disabled={disabled}>
            收起全部
          </button>
        </div>

        <div className="action-group">
          <button className="button compact" onClick={onImport}>
            导入
          </button>
          <button className="button compact" onClick={onExport} disabled={!spec}>
            导出
          </button>
          <button className="button primary compact" onClick={onSave} disabled={disabled}>
            {busy ? "处理中…" : "保存新版本"}
          </button>
        </div>

        <div className="action-group toolbar-run-group">
          <button
            className="button compact"
            onClick={onOpenSimulation}
            disabled={!processId || busy}
            title={processId ? "打开仿真运行与结果面板" : "请先保存流程"}
            aria-pressed={simulationOpen}
          >
            仿真面板
          </button>
          <button
            type="button"
            className="button primary simulation-toolbar-run"
            onClick={onRunSimulation}
            disabled={simulationRunning || busy}
            title="校验项目参数、流程与可靠性配置后调用真实 Runtime"
          >
            {simulationRunning ? "仿真运行中…" : "运行仿真"}
          </button>
        </div>
      </div>
    </section>
  );
}
