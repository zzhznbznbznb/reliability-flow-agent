from __future__ import annotations

import json
from pathlib import Path

from app.diagram.layout import layout_process
from app.diagram.svg import render_process_svg
from app.domain.process_ir import ProcessSpec
from app.domain.validation import validate_process
from app.domain.versioning import compute_content_hash
from tests.helpers import spec_from, minimal_process_dict

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _example(name: str) -> ProcessSpec:
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return ProcessSpec.model_validate(data)


def test_example_diagram_contains_nodes_edges_and_loop() -> None:
    spec = _example("equipment_support_flow.json")
    result = validate_process(spec)
    assert result.valid is True
    svg = render_process_svg(
        spec, version=1, content_hash=compute_content_hash(spec)
    )
    assert "<svg" in svg
    assert "设备支援流程" in svg
    assert "设备检测" in svg
    assert "edge-back" in svg
    assert "marker-end" in svg
    assert "检测是否合格" in svg


def test_manual_positions_are_used_by_layout() -> None:
    spec = _example("equipment_support_flow.json")
    layout = layout_process(spec)
    assert layout.boxes["inspection"].x == 720
    assert layout.boxes["inspection"].y == 230
    back_route = next(
        route for route in layout.routes if route.edge.id == "e_repair_inspection"
    )
    assert back_route.is_back is True


def test_svg_escapes_user_content() -> None:
    data = minimal_process_dict()
    data["nodes"][1]["name"] = "<script>alert(1)</script>"
    spec = spec_from(data)
    svg = render_process_svg(spec)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_auto_layout_when_positions_are_missing() -> None:
    data = minimal_process_dict()
    for node in data["nodes"]:
        node.pop("position", None)
    spec = spec_from(data)
    layout = layout_process(spec)
    assert len(layout.boxes) == 3
    assert layout.width > 0
    assert layout.height > 0
    assert len(layout.routes) == 2
