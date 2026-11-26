import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
} from "@xyflow/react";

export function BusinessEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  label,
  data,
  selected,
}) {
  const isBack = Boolean(data?.isBack);
  let path;
  let labelX;
  let labelY;

  if (isBack) {
    const baseY = Math.max(sourceY, targetY) + 118;
    path = `M ${sourceX},${sourceY} C ${sourceX},${baseY} ${targetX},${baseY} ${targetX},${targetY}`;
    labelX = (sourceX + targetX) / 2;
    labelY = baseY - 8;
  } else {
    [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
    });
  }

  const mergedStyle = {
    stroke: data?.color || "#64748b",
    strokeWidth: selected ? 2.8 : 1.8,
    ...(isBack ? { strokeDasharray: "6 4" } : {}),
    ...style,
  };

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={mergedStyle} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className={`edge-label ${isBack ? "is-back" : ""} ${
              selected ? "is-selected" : ""
            }`}
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes = {
  business: BusinessEdge,
};
