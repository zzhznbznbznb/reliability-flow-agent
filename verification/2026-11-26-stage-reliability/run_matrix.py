"""Run the requested multi-group reliability and detection-rate simulations."""

from __future__ import annotations

import json
import math
from pathlib import Path

from app.domain.process_ir import ProcessSpec
from app.evaluation.evaluator import evaluate_simulation
from app.evaluation.models import EvaluationTargets
from app.simulation.config import ProjectParameters, SimulationConfig
from app.simulation.engine import run_simulation
from tests.helpers import (
    document_from_spec,
    equipment_reliability_nodes,
    reliability_document_from_process,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASE_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"

GROUPS = {
    "A": (0.0, 0.0),
    "B": (0.001, 0.001),
    "C": (0.01, 0.01),
    "D": (0.05, 0.05),
    "E": (0.01, 0.05),
    "F": (0.05, 0.001),
}
ENTITIES = 200
HORIZON = 120.0
SEED = 2026


def _load_process():
    spec = ProcessSpec.model_validate(
        json.loads(CASE_PATH.read_text(encoding="utf-8"))
    )
    return document_from_spec(spec)


def _run(process, *, lambda1, lambda2, ft, entities, horizon, seed):
    reliability = reliability_document_from_process(
        process,
        equipment_reliability_nodes(
            process,
            lambda1=lambda1,
            lambda2=lambda2,
            detection_rate=ft,
            simulation_unit="day",
        ),
    )
    project = ProjectParameters(
        name="多组故障率测试",
        description="固定种子下的多组阶段故障率与检测率仿真测试",
        reliability_target=0.5,
        readiness_target=0.5,
        simulation_unit="day",
        missile_count=entities,
    )
    result = run_simulation(
        process,
        reliability,
        SimulationConfig(
            entity_count=entities,
            simulation_end=horizon,
            random_seed=seed,
            simulation_unit="day",
            project=project,
        ),
    )
    evaluation = evaluate_simulation(
        process,
        reliability,
        result,
        targets=EvaluationTargets(
            overall_reliability_min=0.5,
            readiness_min=0.5,
        ),
    )
    return reliability, result, evaluation


def _summary(result, evaluation) -> dict:
    failure_records = [
        record for entity in result.entities for record in entity.failure_records
    ]
    test_records = [
        record for entity in result.entities for record in entity.test_records
    ]
    by_test: dict[str, dict[str, int | float | None]] = {}
    for record in test_records:
        bucket = by_test.setdefault(
            record.node_id,
            {
                "test_count": 0,
                "had_fault_count": 0,
                "detected_count": 0,
                "undetected_count": 0,
            },
        )
        bucket["test_count"] += 1
        if record.had_fault:
            bucket["had_fault_count"] += 1
        if record.detected:
            bucket["detected_count"] += 1
        if record.had_fault and not record.detected:
            bucket["undetected_count"] += 1
    for bucket in by_test.values():
        had = bucket["had_fault_count"]
        bucket["detection_frequency"] = (
            bucket["detected_count"] / had if had else None
        )
    overall = evaluation.overall
    return {
        "total_failure_count": result.total_failure_count,
        "storage_failure_count": sum(
            1 for record in failure_records if record.node_id == "n_storage"
        ),
        "duty_failure_count": sum(
            1 for record in failure_records if record.node_id == "n_duty"
        ),
        "detected_failure_count": sum(
            1 for record in failure_records if record.detected
        ),
        "repaired_failure_count": sum(
            1 for record in failure_records if record.repaired
        ),
        "ever_failed_entity_count": overall.ever_failed_entity_count,
        "overall_reliability": overall.overall_reliability,
        "readiness": overall.readiness,
        "end_availability": overall.end_availability,
        "total_available_time": overall.total_available_time,
        "total_unavailable_time": overall.total_unavailable_time,
        "mean_failure_count_per_entity": overall.mean_failure_count_per_entity,
        "mean_repair_count_per_entity": overall.mean_repair_count_per_entity,
        "completed_entity_count": overall.completed_entity_count,
        "stopped_entity_count": overall.stopped_entity_count,
        "unfinished_entity_count": overall.unfinished_entity_count,
        "currently_failed_entity_count": overall.currently_failed_entity_count,
        "reliability_sample_count": result.reliability_sample_count,
        "event_count": result.event_count,
        "runtime_semantic_version": result.runtime_semantic_version,
        "reliability_sampling_mode": result.reliability_sampling_mode,
        "tests": by_test,
    }


def main() -> None:
    process = _load_process()
    rows = {}
    for name, (lambda1, lambda2) in GROUPS.items():
        reliability, result, evaluation = _run(
            process,
            lambda1=lambda1,
            lambda2=lambda2,
            ft=0.5,
            entities=ENTITIES,
            horizon=HORIZON,
            seed=SEED,
        )
        rows[name] = {
            "lambda1": lambda1,
            "lambda2": lambda2,
            "detection_rate": 0.5,
            "summary": _summary(result, evaluation),
        }

    multi_seed = {}
    for seed in (1, 7, 2026):
        seed_row = {}
        for name in ("A", "B", "C", "D"):
            lambda1, lambda2 = GROUPS[name]
            _, result, _ = _run(
                process,
                lambda1=lambda1,
                lambda2=lambda2,
                ft=0.5,
                entities=80,
                horizon=120.0,
                seed=seed,
            )
            seed_row[name] = result.total_failure_count
        multi_seed[str(seed)] = seed_row
    for seed_row in multi_seed.values():
        assert seed_row["A"] <= seed_row["B"] <= seed_row["C"] <= seed_row["D"], seed_row

    detection_rows = {}
    for ft in (0.0, 0.5, 1.0):
        reliability, result, evaluation = _run(
            process,
            lambda1=0.002,
            lambda2=0.0,
            ft=ft,
            entities=ENTITIES,
            horizon=240.0,
            seed=77,
        )
        summary = _summary(result, evaluation)
        detection_rows[str(ft)] = summary

    # Theoretical comparison for the image's per-step rule.
    theory_process = process
    theory_rel, theory_result, theory_eval = _run(
        theory_process,
        lambda1=0.001,
        lambda2=0.0,
        ft=0.0,
        entities=400,
        horizon=40.0,
        seed=99,
    )
    storage_failed = sum(
        1
        for entity in theory_result.entities
        if any(record.node_id == "n_storage" for record in entity.failure_records)
    )
    lam = 0.001
    days = 30
    theory = {
        "entities": 400,
        "lambda": lam,
        "storage_days": days,
        "empirical_storage_failure_fraction": storage_failed / 400,
        "stepwise_product_theory": 1 - math.exp(-lam * days * (days + 1) / 2),
        "standard_exponential_theory": 1 - math.exp(-lam * days),
        "note": (
            "图片算法在每个时间步比较 p(t) 与 R(t)=exp(-lambda*t)，"
            "因此 n 步后的无故障概率是各步 R(t) 的乘积，"
            "对应 1-exp(-lambda*n(n+1)/2)，而不是单次 exp(-lambda*n)。"
        ),
    }

    payload = {
        "config": {
            "entities": ENTITIES,
            "horizon": HORIZON,
            "seed": SEED,
            "groups": {name: {"lambda1": a, "lambda2": b} for name, (a, b) in GROUPS.items()},
        },
        "groups": rows,
        "multi_seed_trends": multi_seed,
        "detection": detection_rows,
        "theory_comparison": theory,
    }
    (HERE / "matrix_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 多组故障率与检测率仿真结果",
        "",
        f"- 每组实体数：{ENTITIES}",
        f"- 仿真窗口：{HORIZON} 天",
        f"- 随机种子：{SEED}",
        "- 仿真单位：天；λ 单位：每天",
        "",
        "## 六组故障率",
        "",
        "| 组 | λ1(贮存) | λ2(值班) | 总故障 | 贮存故障 | 值班故障 | 已检测 | 已维修 | 曾故障实体 | 使用可靠度 | 战备完好度 | 不可用时间 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in rows.items():
        s = row["summary"]
        lines.append(
            "| {name} | {l1} | {l2} | {tf} | {sf} | {df} | {det} | {rep} | "
            "{ever} | {rel:.3f} | {rdy:.3f} | {unav:.1f} |".format(
                name=name,
                l1=row["lambda1"],
                l2=row["lambda2"],
                tf=s["total_failure_count"],
                sf=s["storage_failure_count"],
                df=s["duty_failure_count"],
                det=s["detected_failure_count"],
                rep=s["repaired_failure_count"],
                ever=s["ever_failed_entity_count"],
                rel=s["overall_reliability"],
                rdy=s["readiness"] or 0.0,
                unav=s["total_unavailable_time"],
            )
        )
    lines += [
        "",
        "## 检测率 Ft",
        "",
        "λ1=0.002，λ2=0，240 天，种子 77。检测频率按“测试时有故障”的测试次数统计。",
        "",
        "| Ft | 总故障 | 已检测 | 已维修 | 当前故障实体 | 测试有故障次数 | 检出次数 | 检出频率 | 战备完好度 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ft, s in detection_rows.items():
        had = sum(item["had_fault_count"] for item in s["tests"].values())
        det = sum(item["detected_count"] for item in s["tests"].values())
        freq = det / had if had else None
        lines.append(
            f"| {ft} | {s['total_failure_count']} | {s['detected_failure_count']} | "
            f"{s['repaired_failure_count']} | {s['currently_failed_entity_count']} | "
            f"{had} | {det} | {freq if freq is None else round(freq, 4)} | "
            f"{s['readiness'] or 0.0:.3f} |"
        )
    lines += [
        "",
        "## 多随机种子趋势复核",
        "",
        "每组 80 实体、120 天，验证 A≤B≤C≤D 的总故障数趋势。",
        "",
        "| 种子 | A | B | C | D |",
        "|---:|---:|---:|---:|---:|",
    ]
    for seed, row in multi_seed.items():
        lines.append(
            f"| {seed} | {row['A']} | {row['B']} | {row['C']} | {row['D']} |"
        )
    lines += [
        "",
        "## 图片逐时间步算法与标准指数口径对比",
        "",
        f"- 实体数：{theory['entities']}",
        f"- λ：{theory['lambda']} / 天，贮存 30 天",
        f"- 经验贮存故障比例：{theory['empirical_storage_failure_fraction']:.4f}",
        f"- 逐时间步乘积理论：{theory['stepwise_product_theory']:.4f}",
        f"- 单次 exp(-λt) 理论：{theory['standard_exponential_theory']:.4f}",
        f"- 说明：{theory['note']}",
        "",
    ]
    (HERE / "matrix_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
