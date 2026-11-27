import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProjectPayload,
  buildTargetsFromProject,
  emptyProject,
  lambdaUnitFor,
  validateProject,
} from "../src/project.js";

const validProject = {
  name: "装备保障项目",
  description: "验证项目参数进入正式仿真配置",
  reliability_target: "0.9",
  readiness_target: "0.85",
  simulation_unit: "day",
  simulation_total_time: "120",
  missile_count: "10",
};

test("empty project reports every missing field", () => {
  const result = validateProject(emptyProject());
  assert.equal(result.valid, false);
  assert.deepEqual(result.missing, [
    "项目名称",
    "项目描述",
    "装备使用可靠度目标值",
    "战备完好度目标值",
    "仿真总时间",
    "导弹总数量",
  ]);
});

test("complete project converts numeric fields", () => {
  const result = validateProject(validProject);
  assert.equal(result.valid, true);
  assert.deepEqual(result.values, {
    name: "装备保障项目",
    description: "验证项目参数进入正式仿真配置",
    reliability_target: 0.9,
    readiness_target: 0.85,
    simulation_unit: "day",
    simulation_total_time: 120,
    missile_count: 10,
  });
});

test("targets must be inside [0,1]", () => {
  for (const value of ["-0.1", "1.1", "abc"]) {
    const result = validateProject({
      ...validProject,
      reliability_target: value,
    });
    assert.equal(result.valid, false);
    assert.match(result.fieldErrors.reliability_target, /0 到 1|数值/);
  }
});

test("missile count must be a positive integer", () => {
  for (const value of ["", "0", "1.5", "-2", "abc"]) {
    const result = validateProject({ ...validProject, missile_count: value });
    assert.equal(result.valid, false);
    assert.match(result.fieldErrors.missile_count, /正整数/);
  }
});

test("simulation total time must be a positive number", () => {
  for (const value of ["", "0", "-1", "abc", "Infinity"]) {
    const result = validateProject({
      ...validProject,
      simulation_total_time: value,
    });
    assert.equal(result.valid, false);
    assert.match(result.fieldErrors.simulation_total_time, /大于 0/);
  }
});

test("simulation unit must be one of the supported values", () => {
  const result = validateProject({
    ...validProject,
    simulation_unit: "week",
  });
  assert.equal(result.valid, false);
  assert.match(result.fieldErrors.simulation_unit, /小时/);
});

test("project payload and targets are derived from the same values", () => {
  const payload = buildProjectPayload(validProject);
  assert.equal(payload.missile_count, 10);
  assert.equal(payload.simulation_unit, "day");
  assert.equal(payload.simulation_total_time, 120);
  assert.deepEqual(buildTargetsFromProject(validProject), {
    overall_reliability_min: 0.9,
    readiness_min: 0.85,
  });
});

test("lambda units follow the simulation unit", () => {
  assert.equal(lambdaUnitFor("hour"), "per_hour");
  assert.equal(lambdaUnitFor("day"), "per_day");
  assert.equal(lambdaUnitFor("month"), "per_month");
  assert.equal(lambdaUnitFor("year"), "per_year");
});
