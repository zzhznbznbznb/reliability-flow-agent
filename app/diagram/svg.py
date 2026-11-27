"""Render Process IR as a self-contained SVG flowchart."""

from __future__ import annotations

from html import escape

from app.diagram.layout import (
    DiagramLayout,
    EdgeRoute,
    NodeBox,
    layout_nested_process,
    layout_process,
)
from app.domain.process_ir import ProcessSpec
from app.domain.versioning import short_hash

EDGE_COLORS = {
    "normal": "#64748b",
    "conditional": "#7c3aed",
    "default": "#0f766e",
    "failure": "#dc2626",
}


def _iter_nodes(nodes):
    for node in nodes:
        yield node
        if node.subflow is not None:
            yield from _iter_nodes(node.subflow.nodes)


def _text(value: str, x: float, y: float, css_class: str, anchor: str = "middle") -> str:
    return (
        f'<text class="{css_class}" x="{x:.1f}" y="{y:.1f}" '
        f'text-anchor="{anchor}">{escape(value)}</text>'
    )


def _node_markup(box: NodeBox) -> str:
    node = box.node
    title = escape(f"{node.type}: {node.name}")
    description = escape(node.description or node.name)
    group_open = (
        f'<g class="node node-{node.type}" data-node-id="{escape(node.id)}" '
        f'data-node-type="{node.type}">'
        f"<title>{title}</title><desc>{description}</desc>"
    )
    if node.type in {"start", "end"}:
        shape = (
            f'<ellipse cx="{box.center_x:.1f}" cy="{box.center_y:.1f}" '
            f'rx="{box.width / 2:.1f}" ry="{box.height / 2:.1f}"/>'
        )
    elif node.type == "decision":
        points = " ".join(
            [
                f"{box.center_x:.1f},{box.y:.1f}",
                f"{box.right:.1f},{box.center_y:.1f}",
                f"{box.center_x:.1f},{box.bottom:.1f}",
                f"{box.x:.1f},{box.center_y:.1f}",
            ]
        )
        shape = f'<polygon points="{points}"/>'
    else:
        shape = (
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" '
            f'width="{box.width:.1f}" height="{box.height:.1f}" rx="9"/>'
        )

    line_height = 18
    if node.type == "subprocess":
        start_y = box.y + 24
    else:
        start_y = box.center_y - (len(box.lines) - 1) * line_height / 2 + 5
    lines = "".join(
        _text(line, box.center_x, start_y + index * line_height, "node-label")
        for index, line in enumerate(box.lines)
    )
    return f"{group_open}{shape}{lines}</g>"


def _route_markup(route: EdgeRoute) -> str:
    edge = route.edge
    color = EDGE_COLORS.get(edge.kind, EDGE_COLORS["normal"])
    marker = "arrow-back" if route.is_back else f"arrow-{edge.kind}"
    classes = ["edge", f"edge-{edge.kind}"]
    if route.is_back:
        classes.append("edge-back")
    label = route.label
    if len(label) > 34:
        label = label[:33] + "…"
    label_markup = ""
    if label:
        label_markup = (
            f'<text class="edge-label" x="{route.label_x:.1f}" y="{route.label_y:.1f}" '
            f'text-anchor="middle">{escape(label)}</text>'
        )
    return (
        f'<g class="{" ".join(classes)}" data-edge-id="{escape(edge.id)}" '
        f'data-edge-kind="{edge.kind}" '
        f'data-from="{escape(edge.source)}" data-to="{escape(edge.target)}">'
        f"<title>{escape(edge.id)}: {escape(edge.source)} → {escape(edge.target)}</title>"
        f'<path d="{route.path}" fill="none" stroke="{color}" '
        f'marker-end="url(#{marker})" stroke-width="1.8"/>'
        f"{label_markup}</g>"
    )


def _defs() -> str:
    markers = []
    for name, color in [
        ("normal", EDGE_COLORS["normal"]),
        ("conditional", EDGE_COLORS["conditional"]),
        ("default", EDGE_COLORS["default"]),
        ("failure", EDGE_COLORS["failure"]),
        ("back", "#7c3aed"),
    ]:
        markers.append(
            f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
        )
    return (
        "<defs>"
        + "".join(markers)
        + "<filter id=\"soft-shadow\" x=\"-20%\" y=\"-20%\" width=\"140%\" height=\"140%\">"
        "<feDropShadow dx=\"0\" dy=\"2\" stdDeviation=\"3\" flood-color=\"#0f172a\" flood-opacity=\"0.08\"/>"
        "</filter></defs>"
    )


def _styles() -> str:
    return """
    <style>
      .canvas { fill: #f8fafc; }
      .title { font: 700 20px "Microsoft YaHei", "Segoe UI", sans-serif; fill: #0f172a; }
      .subtitle { font: 12px "Microsoft YaHei", "Segoe UI", sans-serif; fill: #64748b; }
      .node rect, .node ellipse, .node polygon {
        stroke-width: 1.8;
        filter: url(#soft-shadow);
      }
      .node-task rect { fill: #ffffff; stroke: #94a3b8; }
      .node-start ellipse { fill: #ecfdf5; stroke: #10b981; }
      .node-end ellipse { fill: #eff6ff; stroke: #3b82f6; }
      .node-decision polygon { fill: #fff7ed; stroke: #f59e0b; }
      .node-subprocess rect { fill: #f5f3ff; stroke: #8b5cf6; stroke-width: 2.4; }
      .node-subprocess .node-label { font-weight: 700; fill: #4c1d95; }
      .node-label {
        font: 13px "Microsoft YaHei", "Segoe UI", sans-serif;
        fill: #0f172a;
        pointer-events: none;
      }
      .edge path { opacity: 0.95; }
      .edge-back path { stroke-dasharray: 6 4; }
      .edge-label {
        font: 11px "Microsoft YaHei", "Segoe UI", sans-serif;
        fill: #334155;
        paint-order: stroke;
        stroke: #f8fafc;
        stroke-width: 4px;
        stroke-linejoin: round;
      }
      .legend { font: 11px "Microsoft YaHei", "Segoe UI", sans-serif; fill: #64748b; }
    </style>
    """


def render_process_svg(
    spec: ProcessSpec,
    *,
    version: int | None = None,
    content_hash: str | None = None,
) -> str:
    has_subprocess = any(
        node.type == "subprocess" for node in _iter_nodes(spec.nodes)
    )
    layout: DiagramLayout = (
        layout_nested_process(spec) if has_subprocess else layout_process(spec)
    )
    subtitle_parts = []
    if version is not None:
        subtitle_parts.append(f"版本 v{version}")
    if content_hash:
        subtitle_parts.append(f"内容哈希 {short_hash(content_hash)}")
    if not subtitle_parts:
        subtitle_parts.append("未保存草稿")
    subtitle = " · ".join(subtitle_parts)

    hash_attr = escape(content_hash) if content_hash else "draft"
    ordered_boxes = sorted(
        layout.boxes.values(),
        key=lambda box: (0 if box.node.type == "subprocess" else 1, box.layer),
    )
    node_markup = "".join(_node_markup(box) for box in ordered_boxes)
    edge_markup = "".join(_route_markup(route) for route in layout.routes)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width:.0f}" '
        f'height="{layout.height:.0f}" viewBox="0 0 {layout.width:.0f} {layout.height:.0f}" '
        f'role="img" aria-label="{escape(spec.name)} 流程图" '
        f'data-content-hash="{hash_attr}">'
        f"<title>{escape(spec.name)} 流程图</title>"
        f'<desc>{escape(spec.description or "由 Process IR 自动生成的流程图")}</desc>'
        f"{_defs()}{_styles()}"
        f'<rect class="canvas" x="0" y="0" width="{layout.width:.0f}" height="{layout.height:.0f}"/>'
        f'<text class="title" x="24" y="34">{escape(spec.name)}</text>'
        f'<text class="subtitle" x="24" y="56">{escape(subtitle)}</text>'
        f'<text class="legend" x="{layout.width - 24:.0f}" y="34" text-anchor="end">'
        "实线：普通/条件/默认/故障　虚线：循环回边</text>"
        f"{edge_markup}{node_markup}</svg>"
    )
