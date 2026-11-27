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

import { validateReliabilityReadiness } from "../src/reliability.js";

const readinessSpec = {
  nodes: [
    { id: "start", type: "start", name: "开始" },
    {
      id: "storage",
      type: "subprocess",
      name: "贮存",
      subflow: {
        nodes: [
          { id: "store", type: "task", name: "贮存", duration: 30 },
          { id: "inspect", type: "task", name: "贮存检测", duration: 1 },
        ],
      },
    },
    { id: "test", type: "task", name: "第一次测试", duration: 1 },
    { id: "transport", type: "task", name: "运输", duration: 2 },
    { id: "end", type: "end", name: "结束" },
  ],
};

test("readiness reports missing stage lambda and test detection rate", () => {
  const result = validateReliabilityReadiness(
    readinessSpec,
    { nodes: [] },
    { simulation_unit: "day" },
  );
  assert.equal(result.ready, false);
  assert.match(result.issues.join("；"), /缺少阶段故障率/);
  assert.match(result.issues.join("；"), /尚未配置为测试模块/);
});

test("readiness accepts stage lambda and test Ft with matching unit", () => {
  const result = validateReliabilityReadiness(
    readinessSpec,
    {
      nodes: [
        {
          node_id: "storage",
          module_type: "stage",
          lambda: 0.01,
          lambda_unit: "per_day",
          stage_task_id: "store",
        },
        {
          node_id: "inspect",
          module_type: "test",
          detection_rate: 0.8,
          test_time: 1,
        },
        {
          node_id: "test",
          module_type: "test",
          detection_rate: 0.8,
          test_time: 1,
        },
        {
          node_id: "store",
          module_type: "activity",
          lambda: null,
        },
        {
          node_id: "transport",
          module_type: "activity",
          lambda: null,
        },
      ],
    },
    { simulation_unit: "day" },
  );
  assert.deepEqual(result, { ready: true, issues: [] });
});

test("readiness reports lambda unit mismatch", () => {
  const result = validateReliabilityReadiness(
    readinessSpec,
    {
      nodes: [
        {
          node_id: "storage",
          module_type: "stage",
          lambda: 0.01,
          lambda_unit: "per_hour",
          stage_task_id: "store",
        },
      ],
    },
    { simulation_unit: "day" },
  );
  assert.equal(result.ready, false);
  assert.match(result.issues.join("；"), /单位与仿真单位不一致/);
});
