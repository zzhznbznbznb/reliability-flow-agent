"""Deterministic layered layout for Process IR diagrams."""

from __future__ import annotations

import heapq
import textwrap
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.domain.process_ir import ProcessEdge, ProcessNode, ProcessSpec
from app.domain.validation import condition_to_text

NODE_WIDTHS = {"start": 150, "end": 150, "task": 190, "decision": 210}
NODE_HEIGHTS = {"start": 56, "end": 56, "task": 72, "decision": 110}
H_GAP = 100
V_GAP = 42
LEFT_MARGIN = 50
RIGHT_MARGIN = 50
TOP_MARGIN = 95
BOTTOM_MARGIN = 50


@dataclass
class NodeBox:
    node: ProcessNode
    x: float
    y: float
    width: float
    height: float
    layer: int
    lines: list[str] = field(default_factory=list)

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass
class EdgeRoute:
    edge: ProcessEdge
    source: NodeBox
    target: NodeBox
    path: str
    label: str
    label_x: float
    label_y: float
    is_back: bool
    is_self_loop: bool


@dataclass
class DiagramLayout:
    boxes: dict[str, NodeBox]
    routes: list[EdgeRoute]
    width: float
    height: float
    layer_count: int
    back_edge_ids: set[str]


def _node_size(node: ProcessNode) -> tuple[float, float]:
    return NODE_WIDTHS.get(node.type, 190), NODE_HEIGHTS.get(node.type, 72)


def wrap_node_name(name: str, max_chars: int = 12) -> list[str]:
    normalized = " ".join(name.split())
    if not normalized:
        return [""]
    lines = textwrap.wrap(
        normalized,
        width=max_chars,
        break_long_words=True,
        break_on_hyphens=False,
    )
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][: max(1, max_chars - 1)] + "…"
    return lines or [""]


def _find_back_edges(spec: ProcessSpec) -> set[str]:
    node_ids = {node.id for node in spec.nodes}
    adjacency: dict[str, list[ProcessEdge]] = {node_id: [] for node_id in node_ids}
    for edge in spec.edges:
        if edge.source in node_ids and edge.target in node_ids:
            adjacency[edge.source].append(edge)
    for edges in adjacency.values():
        edges.sort(key=lambda item: item.id)

    state: dict[str, int] = {}
    back_edges: set[str] = set()

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for edge in adjacency.get(node_id, []):
            target_state = state.get(edge.target, 0)
            if target_state == 1:
                back_edges.add(edge.id)
            elif target_state == 0:
                visit(edge.target)
        state[node_id] = 2

    for node_id in sorted(node_ids):
        if state.get(node_id, 0) == 0:
            visit(node_id)
    return back_edges


def _compute_layers(
    spec: ProcessSpec, back_edges: set[str]
) -> tuple[dict[str, int], dict[str, list[str]]]:
    node_ids = [node.id for node in spec.nodes]
    node_set = set(node_ids)
    forward_adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}
    for edge in spec.edges:
        if edge.id in back_edges:
            continue
        if edge.source in node_set and edge.target in node_set:
            forward_adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

    layers: dict[str, int] = {node_id: 0 for node_id in node_ids}
    heap: list[tuple[int, str]] = []
    for node_id in node_ids:
        if indegree[node_id] == 0:
            heapq.heappush(heap, (0 if _is_start(spec, node_id) else 1, node_id))

    visited: set[str] = set()
    while heap:
        _, current = heapq.heappop(heap)
        if current in visited:
            continue
        visited.add(current)
        for target in sorted(forward_adjacency.get(current, [])):
            layers[target] = max(layers[target], layers[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(heap, (0, target))

    for node_id in node_ids:
        if node_id not in visited:
            layers[node_id] = 0
    return layers, forward_adjacency


def _is_start(spec: ProcessSpec, node_id: str) -> bool:
    return any(node.id == node_id and node.type == "start" for node in spec.nodes)


def _order_layers(
    spec: ProcessSpec,
    layers: dict[str, int],
    forward_adjacency: dict[str, list[str]],
) -> list[list[ProcessNode]]:
    node_map = {node.id: node for node in spec.nodes}
    parents: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    for source, targets in forward_adjacency.items():
        for target in targets:
            parents[target].append(source)

    grouped: dict[int, list[ProcessNode]] = {}
    for node in spec.nodes:
        grouped.setdefault(layers.get(node.id, 0), []).append(node)

    order_index: dict[str, int] = {}
    ordered_layers: list[list[ProcessNode]] = []
    for layer_number in sorted(grouped):
        nodes = grouped[layer_number]

        def sort_key(node: ProcessNode) -> tuple[float, int, str]:
            if layer_number == 0:
                return (0.0 if node.type == "start" else 1.0, 0, node.id)
            parent_positions = [
                order_index[parent]
                for parent in parents.get(node.id, [])
                if parent in order_index
            ]
            barycenter = (
                sum(parent_positions) / len(parent_positions)
                if parent_positions
                else float("inf")
            )
            return (barycenter, 0, node.id)

        nodes.sort(key=sort_key)
        for index, node in enumerate(nodes):
            order_index[node.id] = index
        ordered_layers.append(nodes)
    return ordered_layers


def _layout_from_positions(
    spec: ProcessSpec, back_edges: set[str]
) -> DiagramLayout | None:
    if not spec.nodes or any(node.position is None for node in spec.nodes):
        return None
    layers, _ = _compute_layers(spec, back_edges)
    boxes: dict[str, NodeBox] = {}
    for node in spec.nodes:
        assert node.position is not None
        width, height = _node_size(node)
        boxes[node.id] = NodeBox(
            node=node,
            x=node.position.x,
            y=node.position.y,
            width=width,
            height=height,
            layer=layers.get(node.id, 0),
            lines=wrap_node_name(node.name, 12 if node.type != "decision" else 13),
        )

    width = max(320.0, max(box.right for box in boxes.values()) + RIGHT_MARGIN)
    base_bottom = max(box.bottom for box in boxes.values())
    back_edges_ordered = sorted(back_edges)
    height = max(
        260.0,
        base_bottom + 70 + 30 * len(back_edges_ordered) + BOTTOM_MARGIN,
    )
    routes = _build_routes(spec, boxes, back_edges, base_bottom)
    return DiagramLayout(
        boxes=boxes,
        routes=routes,
        width=width,
        height=height,
        layer_count=max(layers.values(), default=0) + 1,
        back_edge_ids=back_edges,
    )


def layout_process(spec: ProcessSpec) -> DiagramLayout:
    back_edges = _find_back_edges(spec)
    manual = _layout_from_positions(spec, back_edges)
    if manual is not None:
        return manual

    layers, forward_adjacency = _compute_layers(spec, back_edges)
    ordered_layers = _order_layers(spec, layers, forward_adjacency)

    if not ordered_layers:
        return DiagramLayout({}, [], 320, 220, 0, back_edges)

    layer_widths: list[float] = []
    layer_heights: list[float] = []
    for nodes in ordered_layers:
        layer_widths.append(max(_node_size(node)[0] for node in nodes))
        layer_heights.append(
            sum(_node_size(node)[1] for node in nodes)
            + V_GAP * max(0, len(nodes) - 1)
        )

    max_layer_height = max(layer_heights) if layer_heights else 0
    boxes: dict[str, NodeBox] = {}
    x_cursor = LEFT_MARGIN
    for layer_index, nodes in enumerate(ordered_layers):
        column_width = layer_widths[layer_index]
        layer_height = layer_heights[layer_index]
        y_cursor = TOP_MARGIN + (max_layer_height - layer_height) / 2
        for node in nodes:
            width, height = _node_size(node)
            x = x_cursor + (column_width - width) / 2
            lines = wrap_node_name(
                node.name, 12 if node.type != "decision" else 13
            )
            boxes[node.id] = NodeBox(
                node=node,
                x=x,
                y=y_cursor,
                width=width,
                height=height,
                layer=layer_index,
                lines=lines,
            )
            y_cursor += height + V_GAP
        x_cursor += column_width + H_GAP

    width = max(320.0, x_cursor - H_GAP + RIGHT_MARGIN)
    base_bottom = max((box.bottom for box in boxes.values()), default=TOP_MARGIN)
    back_edges_ordered = sorted(back_edges)
    bottom_span = 70 + 30 * len(back_edges_ordered)
    height = max(260.0, base_bottom + bottom_span + BOTTOM_MARGIN)
    routes = _build_routes(spec, boxes, back_edges, base_bottom)

    return DiagramLayout(
        boxes=boxes,
        routes=routes,
        width=width,
        height=height,
        layer_count=len(ordered_layers),
        back_edge_ids=back_edges,
    )


SUB_HEADER = 54
SUB_PADDING = 18


def layout_nested_process(spec: ProcessSpec) -> DiagramLayout:
    """Simple hierarchical layout: each scope flows left-to-right in a row.

    Nested blocks are containers; their child nodes are real boxes placed inside
    the container. This is deliberately separate from the flat layered layout so
    existing single-level diagrams keep their current output.
    """

    boxes: dict[str, NodeBox] = {}
    routes: list[EdgeRoute] = []

    def scope_spec(scope, name: str) -> ProcessSpec:
        return ProcessSpec(
            schema_version=spec.schema_version,
            name=name,
            status_catalog=spec.status_catalog,
            start_node_id=getattr(scope, "start_node_id", ""),
            end_node_ids=getattr(scope, "end_node_ids", []),
            nodes=scope.nodes,
            edges=scope.edges,
            guards=getattr(scope, "guards", spec.guards),
        )

    def place_scope(scope, x0: float, y0: float, depth: int) -> tuple[float, float]:
        cursor_x = x0
        scope_boxes: list[NodeBox] = []
        for node in scope.nodes:
            if node.type == "subprocess" and node.subflow is not None:
                child_width, child_height = place_scope(
                    node.subflow,
                    x0 + SUB_PADDING,
                    y0 + SUB_HEADER + SUB_PADDING,
                    depth + 1,
                )
                width = max(260.0, child_width + SUB_PADDING * 2)
                height = max(
                    120.0, SUB_HEADER + child_height + SUB_PADDING * 2
                )
            else:
                width, height = _node_size(node)
            lines = wrap_node_name(node.name, 12 if node.type != "decision" else 13)
            box = NodeBox(
                node=node,
                x=cursor_x,
                y=y0,
                width=width,
                height=height,
                layer=depth,
                lines=lines,
            )
            boxes[node.id] = box
            scope_boxes.append(box)
            cursor_x += width + H_GAP

        edges_spec = scope_spec(scope, f"{spec.name}/{depth}")
        back_edges = _find_back_edges(edges_spec)
        base_bottom = max(
            (box.bottom for box in scope_boxes), default=y0 + 120
        )
        routes.extend(
            _build_routes(
                SimpleNamespace(edges=scope.edges),
                boxes,
                back_edges,
                base_bottom,
            )
        )
        width = max(260.0, cursor_x - H_GAP - x0)
        height = max(120.0, base_bottom - y0)
        return width, height

    place_scope(spec, LEFT_MARGIN, TOP_MARGIN, 0)
    width = max(
        320.0,
        max((box.right for box in boxes.values()), default=LEFT_MARGIN)
        + RIGHT_MARGIN,
    )
    height = max(
        260.0,
        max((box.bottom for box in boxes.values()), default=TOP_MARGIN)
        + BOTTOM_MARGIN,
    )
    return DiagramLayout(
        boxes=boxes,
        routes=routes,
        width=width,
        height=height,
        layer_count=max((box.layer for box in boxes.values()), default=0) + 1,
        back_edge_ids={route.edge.id for route in routes if route.is_back},
    )


def _build_routes(
    spec: ProcessSpec,
    boxes: dict[str, NodeBox],
    back_edges: set[str],
    base_bottom: float,
) -> list[EdgeRoute]:
    routes: list[EdgeRoute] = []
    back_offset = 0
    for edge in spec.edges:
        source = boxes.get(edge.source)
        target = boxes.get(edge.target)
        if source is None or target is None:
            continue
        is_self_loop = edge.source == edge.target
        is_back = (
            edge.id in back_edges or target.center_x <= source.center_x
        )
        label = _edge_label(edge)

        if is_self_loop:
            bulge = 64 + back_offset * 18
            path = (
                f"M {source.right:.1f} {source.y + source.height * 0.35:.1f} "
                f"C {source.right + bulge:.1f} {source.y:.1f}, "
                f"{source.right + bulge:.1f} {source.bottom:.1f}, "
                f"{source.right:.1f} {source.y + source.height * 0.68:.1f}"
            )
            label_x = source.right + bulge * 0.78
            label_y = source.center_y - 8
            back_offset += 1
        elif is_back:
            base_y = base_bottom + 48 + back_offset * 30
            source_x = source.center_x
            target_x = target.center_x
            path = (
                f"M {source_x:.1f} {source.bottom:.1f} "
                f"C {source_x:.1f} {base_y:.1f}, "
                f"{target_x:.1f} {base_y:.1f}, "
                f"{target_x:.1f} {target.bottom:.1f}"
            )
            label_x = (source_x + target_x) / 2
            label_y = base_y - 8
            back_offset += 1
        else:
            source_x = source.right
            source_y = source.center_y
            target_x = target.x
            target_y = target.center_y
            control = max(40.0, (target_x - source_x) / 2)
            path = (
                f"M {source_x:.1f} {source_y:.1f} "
                f"C {source_x + control:.1f} {source_y:.1f}, "
                f"{target_x - control:.1f} {target_y:.1f}, "
                f"{target_x:.1f} {target_y:.1f}"
            )
            label_x = (source_x + target_x) / 2
            label_y = (source_y + target_y) / 2 - 10

        routes.append(
            EdgeRoute(
                edge=edge,
                source=source,
                target=target,
                path=path,
                label=label,
                label_x=label_x,
                label_y=label_y,
                is_back=is_back,
                is_self_loop=is_self_loop,
            )
        )
    return routes


def _edge_label(edge: ProcessEdge) -> str:
    if edge.label:
        return edge.label
    if edge.kind == "conditional" and edge.condition is not None:
        return condition_to_text(edge.condition)
    if edge.kind == "default":
        return "默认"
    if edge.kind == "failure":
        return "故障"
    return ""
