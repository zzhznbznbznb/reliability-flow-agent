import assert from "node:assert/strict";
import test from "node:test";

import {
  buildReliabilityNodes,
  reliabilityNodeFor,
  validateLambdaInput,
} from "../src/reliability.js";

const tasks = [
  { id: "inspection", type: "task" },
  { id: "repair", type: "task" },
  { id: "start", type: "start" },
];

test("non-participating nodes do not require lambda", () => {
  assert.deepEqual(validateLambdaInput(false, ""), { lambda: null, error: "" });
});

test("participating nodes require lambda", () => {
  const result = validateLambdaInput(true, "  ");
  assert.equal(result.lambda, null);
  assert.match(result.error, /必须填写/);
});

test("lambda accepts zero and positive finite values", () => {
  assert.deepEqual(validateLambdaInput(true, "0"), { lambda: 0, error: "" });
  assert.deepEqual(validateLambdaInput(true, "0.02"), {
    lambda: 0.02,
    error: "",
  });
});

test("lambda rejects negative and non-finite values", () => {
  assert.match(validateLambdaInput(true, "-1").error, /大于或等于 0/);
  assert.match(validateLambdaInput(true, "abc").error, /有限数字/);
});

test("buildReliabilityNodes includes every task exactly once", () => {
  const nodes = buildReliabilityNodes(tasks, [], "inspection", {
    participates: true,
    lambda: 0.03,
  });
  assert.equal(nodes.length, 2);
  assert.deepEqual(
    nodes.map((node) => node.node_id),
    ["inspection", "repair"],
  );
  assert.equal(nodes[0].participates, true);
  assert.equal(nodes[0].lambda, 0.03);
  assert.equal(nodes[1].participates, false);
  assert.equal(nodes[1].lambda, null);
});

test("turning participation off preserves an existing lambda", () => {
  const existing = [
    {
      node_id: "inspection",
      participates: true,
      distribution: "exponential",
      lambda: 0.05,
      lambda_unit: "per_day",
    },
  ];
  const nodes = buildReliabilityNodes(tasks, existing, "inspection", {
    participates: false,
    lambda: null,
  });
  assert.equal(nodes[0].participates, false);
  assert.equal(nodes[0].lambda, 0.05);
});

test("editing one node does not change other node configuration", () => {
  const existing = [
    {
      node_id: "inspection",
      participates: true,
      distribution: "exponential",
      lambda: 0.05,
      lambda_unit: "per_day",
    },
    {
      node_id: "repair",
      participates: true,
      distribution: "exponential",
      lambda: 0.2,
      lambda_unit: "per_day",
    },
  ];
  const nodes = buildReliabilityNodes(tasks, existing, "inspection", {
    participates: true,
    lambda: 0,
  });
  assert.equal(nodes[0].lambda, 0);
  assert.equal(nodes[1].participates, true);
  assert.equal(nodes[1].lambda, 0.2);
});

test("deleted tasks are excluded and stale nodes are not resurrected", () => {
  const existing = [
    { node_id: "removed_task", participates: true, lambda: 3 },
  ];
  const nodes = buildReliabilityNodes(tasks, existing, "repair", {
    participates: false,
    lambda: null,
  });
  assert.deepEqual(
    nodes.map((node) => node.node_id),
    ["inspection", "repair"],
  );
});

test("reliabilityNodeFor reads a revision bound to the node", () => {
  const document = {
    nodes: [{ node_id: "inspection", participates: true, lambda: 0.01 }],
  };
  assert.equal(reliabilityNodeFor(document, "inspection").lambda, 0.01);
  assert.equal(reliabilityNodeFor(document, "repair"), null);
  assert.equal(reliabilityNodeFor(null, "inspection"), null);
});
