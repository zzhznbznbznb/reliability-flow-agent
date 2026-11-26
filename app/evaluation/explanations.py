"""Deterministic, non-causal explanations for evaluation results."""

from __future__ import annotations

from app.evaluation.models import EvaluationResult, NodeMetrics

_WARNING_EXPLANATIONS = {
    "small_sample": "设备样本量较小，经验指标存在统计不确定性，但指标本身未被修改。",
    "unknown_end_state": "部分设备结束状态无法依据状态目录判定，不能算作完好。",
    "availability_unevaluable": "由于存在未知结束状态，正式结束时完好率不可评价。",
    "no_valid_exposure": "节点没有有效的正可靠性暴露时间，理论指标显示为 N/A。",
    "actual_elapsed_incomplete": "部分节点实际停留时间无法从事件历史完整还原，相关字段显示为 N/A。",
    "event_sequence_invalid": "事件顺序存在异常，部分实际停留时间无法可靠重建。",
    "node_visit_history_mismatch": "节点访问计数与事件历史不一致，实际停留时间被视为不完整。",
    "failure_counter_mismatch": "可靠性样本故障数与 Runtime 计数器不一致，评价保留双方数值。",
    "repair_counter_mismatch": "Runtime 维修计数与维修完成事件数不一致。",
    "repair_cycle_overlap": "同一设备在维修活动未结束时再次开始维修，维修周期存在歧义。",
    "process_binding_mismatch": "SimulationResult 与给定 Process IR 绑定不一致。",
    "reliability_binding_mismatch": "SimulationResult 与给定 Reliability IR 绑定不一致。",
    "entity_count_mismatch": "仿真结果声明的设备数与设备列表长度不一致。",
    "sample_unknown_entity": "可靠性抽样引用了结果设备列表中不存在的设备。",
    "reliability_lambda_mismatch": "抽样记录的 lambda 与当前 Reliability IR 配置不一致。",
    "reliability_unknown_node": "Reliability IR 引用了 Process IR 中不存在的节点。",
    "reliability_invalid_node_type": "非 task 节点被配置为可靠性节点。",
}


def _percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.4f}%"


def _number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def explain_overall(result: EvaluationResult) -> str:
    overall = result.overall
    lines = [
        (
            f"整体可靠性 R_e = {_percent(overall.overall_reliability)}，"
            f"表示整个仿真期间从未发生故障的初始设备比例；"
            f"共 {overall.ever_failed_entity_count}/{overall.entity_count} 台设备曾经故障。"
        ),
    ]
    if overall.end_availability is None:
        lines.append(
            "正式结束时完好率 A_e = N/A，因为存在无法判定的结束状态；"
            f"描述性 observed_good_end_fraction = {_percent(overall.observed_good_end_fraction)}，"
            "它不能替代正式 A_e。"
        )
    else:
        lines.append(
            f"结束时完好率 A_e = {_percent(overall.end_availability)}，"
            f"按结束时明确处于完好状态的设备数计算；"
            f"good/bad/unknown = {overall.good_end_count}/"
            f"{overall.bad_end_count}/{overall.unknown_end_count}。"
        )
    lines.append(
        f"仿真结束时当前故障设备 {overall.currently_failed_entity_count} 台，"
        f"维修中设备 {overall.repair_in_progress_count} 台，"
        f"完成 {overall.completed_entity_count} 台，"
        f"停止 {overall.stopped_entity_count} 台。"
    )
    return "\n".join(lines)


def explain_node(result: EvaluationResult, node_id: str) -> str:
    node = next((item for item in result.nodes if item.node_id == node_id), None)
    if node is None:
        return f"节点 {node_id} 没有参与可靠性计算的统计记录。"
    lines = [
        (
            f"节点 {node.node_name}（{node.node_id}）：lambda = "
            f"{node.lambda_per_day} 次/自然日，访问 {node.visit_count} 次，"
            f"可靠性抽样 {node.sample_count} 次，实际故障 {node.failure_count} 次。"
        ),
        (
            f"累计可靠性暴露时间 = {node.total_reliability_exposure_time} 设备·天；"
            f"唯一暴露设备数 = {node.unique_exposed_entity_count}。"
        ),
        (
            "设备平均节点理论可靠度 = "
            f"{_number(node.mean_entity_theoretical_reliability)}；"
            "这是按每台设备累计暴露时间计算后对设备求平均。"
        ),
        (
            "所有设备在该节点的联合理论无故障概率 = "
            f"{_number(node.joint_theoretical_no_failure_probability)}；"
            "这是联合概率，不是单台设备可靠度，也不是系统整体可靠度。"
        ),
        (
            "节点实际故障频率 = "
            f"{_percent(node.empirical_failure_frequency)}；"
            "它来自实际抽样结果，不能替代理论可靠度。"
        ),
    ]
    if node.mean_entity_theoretical_reliability is None:
        lines.append("理论指标显示 N/A：该节点没有有效的正可靠性暴露时间。")
    if not node.actual_elapsed_complete:
        lines.append(
            "节点实际停留时间不完整，total_actual_elapsed_time 显示为 N/A。"
        )
    return "\n".join(lines)


def explain_warnings(result: EvaluationResult) -> list[str]:
    explanations = []
    for warning in result.warnings:
        prefix = f"[{warning.code}]"
        base = _WARNING_EXPLANATIONS.get(warning.code, "评价过程中发现数据或统计限制。")
        target = ""
        if warning.node_id:
            target += f" 节点={warning.node_id}"
        if warning.entity_id:
            target += f" 设备={warning.entity_id}"
        explanations.append(
            f"{prefix}{target} {warning.message} {base}"
        )
    return explanations


def build_explanation(result: EvaluationResult) -> str:
    sections = [explain_overall(result)]
    if result.nodes:
        sections.append(
            "\n".join(
                explain_node(result, node.node_id) for node in result.nodes
            )
        )
    if result.warnings:
        sections.append("评价提示：\n" + "\n".join(explain_warnings(result)))
    sections.append(
        "以上内容描述确定性统计事实；不把相关性或单次随机差异解释为因果关系。"
    )
    return "\n\n".join(sections)


def explain_node_metric(node: NodeMetrics) -> str:
    return (
        f"{node.node_name}：设备平均节点理论可靠度 "
        f"{_number(node.mean_entity_theoretical_reliability)}，"
        f"联合无故障概率 {_number(node.joint_theoretical_no_failure_probability)}，"
        f"实际故障频率 {_percent(node.empirical_failure_frequency)}。"
    )


__all__ = [
    "build_explanation",
    "explain_node",
    "explain_node_metric",
    "explain_overall",
    "explain_warnings",
]
