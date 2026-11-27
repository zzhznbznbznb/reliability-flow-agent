import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  BLOCK_HEADER,
  BLOCK_PADDING,
  autoLayoutSpec,
  ensurePositions,
  flowPositionToSpec,
  normalizeSpec,
  toFlowEdges,
  toFlowNodes,
} from "../src/flow/nested.js";

const caseSpec = normalizeSpec(
  JSON.parse(
    readFileSync(
      new URL(
        "../../examples/equipment_support_nested_flow.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ),
);

const allNodes = (spec) => {
  const result = [];
  const walk = (scope, path) => {
    for (const node of scope.nodes) {
      result.push({ node, path });
      if (node.subflow) walk(node.subflow, [...path, node.id]);
    }
  };
  walk(spec, []);
  return result;
};

const allEdges = (spec) => {
  const result = [];
  const walk = (scope, path) => {
    for (const edge of scope.edges) result.push({ edge, path });
    for (const node of scope.nodes) {
      if (node.subflow) walk(node.subflow, [...path, node.id]);
    }
  };
  walk(spec, []);
  return result;
};

test("nested spec normalizes and preserves hierarchy", () => {
  const nodeMap = new Map(allNodes(caseSpec).map(({ node }) => [node.id, node]));
  assert.equal(nodeMap.get("n_storage").type, "subprocess");
  assert.equal(nodeMap.get("n_duty").type, "subprocess");
  assert.equal(nodeMap.get("n_storage").subflow.nodes.length, 6);
  assert.equal(nodeMap.get("n_duty").subflow.nodes.length, 6);
  assert.equal(allNodes(caseSpec).length, 28);
  assert.equal(allEdges(caseSpec).length, 29);
});

test("collapsed block exposes internal preview nodes but not child flow nodes", () => {
  const flowNodes = toFlowNodes(caseSpec, null, {}, null);
  const ids = flowNodes.map((node) => node.id);
  assert.ok(ids.includes("n_storage"));
  assert.ok(ids.includes("n_duty"));
  assert.ok(!ids.includes("s_store"));
  assert.ok(!ids.includes("d_duty"));
  const block = flowNodes.find((node) => node.id === "n_storage");
  assert.equal(block.type, "subprocess");
  assert.equal(block.data.expanded, false);
  assert.ok(block.data.preview.previewNodes.length >= 2);
  assert.equal(block.data.preview.internalCount, 6);
});

test("expanded block renders real child nodes with parentId and relative positions", () => {
  const laidOut = autoLayoutSpec(caseSpec);
  const expanded = { n_storage: true, n_duty: false };
  const flowNodes = toFlowNodes(laidOut, null, expanded, null);
  const byId = new Map(flowNodes.map((node) => [node.id, node]));
  const child = byId.get("s_inspect");
  assert.ok(child);
  assert.equal(child.parentId, "n_storage");
  assert.equal(child.data.inner, true);
  assert.equal(child.position.x, byId.get("s_inspect").data.node.position.x + BLOCK_PADDING);
  assert.equal(
    child.position.y,
    byId.get("s_inspect").data.node.position.y + BLOCK_HEADER + BLOCK_PADDING,
  );
  assert.ok(!byId.has("d_duty"));
});

test("internal edges only appear when their block is expanded", () => {
  const collapsed = toFlowEdges(caseSpec, null, {}, () => "").map((e) => e.id);
  assert.ok(collapsed.includes("e_storage_transport"));
  assert.ok(!collapsed.includes("e_s_store_inspect"));

  const expanded = toFlowEdges(
    caseSpec,
    null,
    { n_storage: true },
    () => "",
  ).map((edge) => edge.id);
  assert.ok(expanded.includes("e_s_store_inspect"));
  const internalEdge = toFlowEdges(
    caseSpec,
    null,
    { n_storage: true },
    () => "",
  ).find((edge) => edge.id === "e_s_store_inspect");
  assert.equal(internalEdge.data.inner, true);
  assert.equal(internalEdge.data.depth, 1);
});

test("expand and collapse do not mutate the Process IR", () => {
  const before = JSON.stringify(caseSpec);
  toFlowNodes(caseSpec, null, { n_storage: true, n_duty: true }, null);
  toFlowEdges(caseSpec, null, { n_storage: true, n_duty: true }, () => "");
  assert.equal(JSON.stringify(caseSpec), before);
});

test("recursive auto layout positions all nested nodes", () => {
  const laidOut = autoLayoutSpec(caseSpec);
  for (const { node } of allNodes(laidOut)) {
    assert.ok(node.position);
    assert.equal(Number.isFinite(node.position.x), true);
    assert.equal(Number.isFinite(node.position.y), true);
  }
  const storage = laidOut.nodes.find((node) => node.id === "n_storage");
  const store = storage.subflow.nodes.find((node) => node.id === "s_store");
  assert.ok(store.position.x >= 0);
  assert.ok(store.position.y >= 0);
});

test("ensurePositions lays out a nested spec missing positions", () => {
  const stripped = JSON.parse(JSON.stringify(caseSpec));
  const clear = (scope) => {
    for (const node of scope.nodes) {
      node.position = null;
      if (node.subflow) clear(node.subflow);
    }
  };
  clear(stripped);
  const laidOut = ensurePositions(stripped);
  assert.ok(laidOut.nodes.every((node) => node.position));
});

test("flow position conversion removes block header and padding", () => {
  const specPos = flowPositionToSpec(
    { x: 100 + BLOCK_PADDING, y: 200 + BLOCK_HEADER + BLOCK_PADDING },
    "n_storage",
  );
  assert.deepEqual(specPos, { x: 100, y: 200 });
  assert.deepEqual(flowPositionToSpec({ x: 10, y: 20 }, null), { x: 10, y: 20 });
});

const parentRepairSpec = normalizeSpec(
  JSON.parse(
    readFileSync(
      new URL(
        "../../tests/fixtures/equipment_support_parent_repair_flow.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ),
);

test("parent-repair flow renders two expandable subprocesses with real children", () => {
  const laidOut = autoLayoutSpec(parentRepairSpec);
  const collapsed = toFlowNodes(laidOut, null, {}, null);
  const collapsedIds = collapsed.map((node) => node.id);
  assert.ok(collapsedIds.includes("n_storage_phase"));
  assert.ok(collapsedIds.includes("n_duty_phase"));
  assert.ok(!collapsedIds.includes("st_store"));
  assert.ok(!collapsedIds.includes("du_duty"));
  assert.equal(
    collapsed.find((node) => node.id === "n_storage_phase").type,
    "subprocess",
  );
  assert.equal(
    collapsed.find((node) => node.id === "n_duty_phase").type,
    "subprocess",
  );

  const expanded = toFlowNodes(
    laidOut,
    null,
    { n_storage_phase: true, n_duty_phase: true },
    null,
  );
  const byId = new Map(expanded.map((node) => [node.id, node]));
  for (const childId of [
    "st_store",
    "st_check",
    "st_fault_judge",
    "st_normal_end",
    "st_fault_end",
    "du_duty",
    "du_check",
    "du_fault_judge",
    "du_fault_end",
  ]) {
    assert.ok(byId.has(childId), `missing expanded child ${childId}`);
    assert.equal(byId.get(childId).data.inner, true);
  }

  const edgeIds = toFlowEdges(
    laidOut,
    null,
    { n_storage_phase: true, n_duty_phase: true },
    () => "",
  ).map((edge) => edge.id);
  for (const edgeId of [
    "b_st_judge_fault",
    "b_st_judge_normal",
    "b_du_judge_normal_loop",
    "b_du_judge_fault",
    "b_storage_fault_repair",
    "b_storage_repair_loop",
    "b_duty_fault_repair",
    "b_duty_repair_loop",
  ]) {
    assert.ok(edgeIds.includes(edgeId), `missing edge ${edgeId}`);
  }
});
