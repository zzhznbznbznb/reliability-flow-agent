import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEvaluationTargets,
  formatNumber,
  formatPercent,
  parseOptionalTarget,
  targetMetricLabel,
  targetStatusLabel,
  targetStatusTone,
} from "../src/simulation.js";

test("formatPercent preserves actual and N/A semantics", () => {
  assert.equal(formatPercent(0.987654, 4), "98.7654%");
  assert.equal(formatPercent(0), "0.0000%");
  assert.equal(formatPercent(null), "N/A");
  assert.equal(formatPercent(undefined), "N/A");
});

test("formatNumber preserves N/A instead of inventing zero", () => {
  assert.equal(formatNumber(0.1234567, 4), "0.1235");
  assert.equal(formatNumber(null), "N/A");
  assert.equal(formatNumber(undefined), "N/A");
});

test("target status labels and tones are stable", () => {
  assert.equal(targetStatusLabel("achieved"), "已达成");
  assert.equal(targetStatusLabel("not_achieved"), "未达成");
  assert.equal(targetStatusTone("achieved"), "good");
  assert.equal(targetStatusTone("not_achieved"), "bad");
  assert.equal(targetStatusTone("unevaluable"), "warn");
  assert.equal(targetMetricLabel("overall_reliability"), "整体可靠性");
});

test("optional target parsing accepts blank, zero and one", () => {
  assert.deepEqual(parseOptionalTarget("", "整体可靠性目标"), {
    value: null,
    error: "",
  });
  assert.deepEqual(parseOptionalTarget("0", "整体可靠性目标"), {
    value: 0,
    error: "",
  });
  assert.deepEqual(parseOptionalTarget("1", "整体可靠性目标"), {
    value: 1,
    error: "",
  });
});

test("optional target parsing rejects invalid values", () => {
  assert.match(parseOptionalTarget("-0.1", "目标").error, /0 到 1/);
  assert.match(parseOptionalTarget("1.1", "目标").error, /0 到 1/);
  assert.match(parseOptionalTarget("abc", "目标").error, /必须是数字/);
});

test("buildEvaluationTargets omits targets when both are blank", () => {
  assert.deepEqual(buildEvaluationTargets("", ""), {
    targets: null,
    error: "",
  });
});

test("buildEvaluationTargets builds the supported target payload", () => {
  assert.deepEqual(buildEvaluationTargets("0.9", "0.95"), {
    targets: {
      overall_reliability_min: 0.9,
      end_availability_min: 0.95,
    },
    error: "",
  });
});
