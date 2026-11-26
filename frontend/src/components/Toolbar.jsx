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
}) {
  const disabled = !spec || busy;
  const historical =
    processId && viewingVersion && viewingVersion !== latestVersion;

  return (
    <section className="toolbar">
      <div className="toolbar-title">
        <div className="title-line">
          <h1>{spec?.name || "流程工作台"}</h1>
          {dirty && <span className="pill warn">未保存</span>}
          {historical && (
            <span className="pill warn">查看历史 v{viewingVersion}</span>
          )}
        </div>
        <div className="subtitle">
          {processId ? (
            <>
              ID <code>{processId}</code>
              <span className="dot-sep">·</span>
              最新 v{latestVersion || 1}
              <span className="dot-sep">·</span>
              哈希 <code>{shortHash(contentHash)}</code>
            </>
          ) : (
            <>未保存草稿 · 保存后生成正式 Process IR 版本</>
          )}
          <span className="dot-sep">·</span>
          {VALIDATION_TEXT[validationState] || validationState}
        </div>
      </div>

      <div className="toolbar-actions">
        <div className="action-group">
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
          <button className="button" onClick={onReload} disabled={!processId || busy}>
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
        </div>

        <div className="action-group">
          <button className="button" onClick={onValidate} disabled={disabled}>
            校验
          </button>
          <button className="button" onClick={onAutoLayout} disabled={disabled}>
            自动布局
          </button>
          <button className="button" onClick={onFitView} disabled={disabled}>
            适应屏幕
          </button>
        </div>

        <div className="action-group">
          <button
            className={`button ${simulationOpen ? "primary" : ""}`}
            onClick={onOpenSimulation}
            disabled={!processId || busy}
            title={processId ? "打开仿真评估面板" : "请先保存流程"}
            aria-pressed={simulationOpen}
          >
            仿真评估
          </button>
        </div>

        <div className="action-group">
          <button className="button" onClick={onImport}>
            导入 JSON
          </button>
          <button className="button" onClick={onExport} disabled={!spec}>
            导出 JSON
          </button>
          <button className="button primary" onClick={onSave} disabled={disabled}>
            {busy ? "处理中…" : "保存新版本"}
          </button>
        </div>
      </div>
    </section>
  );
}
