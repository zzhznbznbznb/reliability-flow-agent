"""Real browser E2E verification for project parameters, stage λ, Ft and runtime.

This script starts the real FastAPI app with isolated temporary stores, creates
the canonical reference process, drives the real web UI with Microsoft Edge via
Playwright, configures project parameters, λ/Ft through the canvas/Inspector,
runs a real simulation, and saves screenshots + a machine-readable summary.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROCESS_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"
RUN_DATA = HERE / "run_data"
PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"


def dump(name: str, data) -> None:
    (HERE / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def wait_health(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("backend did not become healthy")


def post_json(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_toast(page, text: str, timeout: int = 15000) -> None:
    page.wait_for_selector(f".toast:has-text('{text}')", timeout=timeout)
    page.wait_for_timeout(250)


def save_reliability(page) -> None:
    page.locator("button:has-text('保存可靠性配置')").click()
    wait_toast(page, "可靠性配置已保存")


def force_click(page, selector: str, timeout: int = 5000) -> None:
    locator = page.locator(selector)
    try:
        locator.click(timeout=timeout)
    except Exception:
        locator.evaluate("el => el.click()")
        page.wait_for_timeout(200)


def open_reliability_tab(page) -> None:
    page.locator(".segmented button:has-text('可靠性')").click()
    page.wait_for_timeout(150)


def main() -> None:
    if RUN_DATA.exists():
        shutil.rmtree(RUN_DATA)
    RUN_DATA.mkdir(parents=True)

    spec = json.loads(PROCESS_PATH.read_text(encoding="utf-8"))
    server = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "serve_temp.py"),
            str(RUN_DATA),
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    summary: dict = {"assertions": [], "screenshots": []}

    def check(name: str, condition: bool, detail: str = "") -> None:
        summary["assertions"].append(
            {"name": name, "ok": bool(condition), "detail": detail}
        )
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    try:
        wait_health()
        created = post_json("/api/processes", spec)["process"]
        summary["process_id"] = created["process_id"]
        summary["process_version"] = created["version"]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge", headless=True
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1180})
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_selector(".project-panel", timeout=20000)
            check(
                "项目参数区域已渲染",
                page.locator(".project-panel").is_visible(),
            )
            for field in (
                "name",
                "description",
                "reliability_target",
                "readiness_target",
                "simulation_unit",
                "missile_count",
            ):
                check(
                    f"项目字段可见: {field}",
                    page.locator(f"#project-{field}").is_visible(),
                )
            check(
                "未填写项目参数时打开仿真按钮禁用",
                page.locator(
                    ".project-panel button:has-text('打开仿真运行')"
                ).is_disabled(),
            )

            # Save the auto-laid-out canonical process first; reliability can
            # only be bound to a saved, non-dirty Process IR version.
            save_button = page.locator("button:has-text('保存新版本')")
            if save_button.is_enabled():
                save_button.click()
                page.wait_for_selector(".toast:has-text('已保存 v')", timeout=20000)
                page.wait_for_timeout(600)

            page.fill("#project-name", "某型导弹贮存值班保障项目")
            page.fill(
                "#project-description",
                "验证贮存与值班阶段故障率、测试检测率以及项目目标值进入正式仿真配置。",
            )
            page.fill("#project-reliability_target", "0.6")
            page.fill("#project-readiness_target", "0.6")
            page.select_option("#project-simulation_unit", "day")
            page.fill("#project-missile_count", "6")
            page.wait_for_timeout(300)
            check(
                "填写完整项目参数后打开仿真按钮启用",
                page.locator(
                    ".project-panel button:has-text('打开仿真运行')"
                ).is_enabled(),
            )

            # Missing reliability parameters must block the run button.
            page.locator(
                ".project-panel button:has-text('打开仿真运行')"
            ).click()
            page.wait_for_selector(".simulation-panel", timeout=10000)
            check(
                "缺少阶段 λ/测试 Ft 时运行按钮禁用",
                page.locator(
                    ".simulation-panel button:has-text('运行仿真并评价')"
                ).is_disabled(),
            )
            readiness_text = page.locator(".readiness-issues").inner_text()
            check(
                "运行前检查明确提示可靠性参数缺失",
                (
                    "缺少阶段故障率" in readiness_text
                    or "可靠性配置尚未保存或加载" in readiness_text
                ),
                readiness_text,
            )
            page.locator(".simulation-head button:has-text('收起')").click()
            page.wait_for_timeout(200)

            # Storage stage λ through the subprocess right-side parameter button.
            page.locator("button:has-text('适应屏幕')").click()
            page.wait_for_timeout(500)
            force_click(
                page,
                ".react-flow__node[data-id='n_storage'] .subprocess-param-button",
            )
            page.wait_for_selector("#node-lambda", timeout=10000)
            lambda_label = page.locator("label[for='node-lambda']").inner_text()
            check(
                "贮存阶段 λ 单位跟随仿真单位（每天）",
                "每天" in lambda_label,
                lambda_label,
            )
            page.fill("#node-lambda", "0.002")
            page.select_option("#stage-task", "s_store")
            save_reliability(page)

            # Duty stage λ.
            force_click(
                page,
                ".react-flow__node[data-id='n_duty'] .subprocess-param-button",
            )
            page.wait_for_selector("#node-lambda", timeout=10000)
            page.fill("#node-lambda", "0.005")
            page.select_option("#stage-task", "d_duty")
            save_reliability(page)

            # Ordinary task must not expose a lambda input.
            force_click(page, ".react-flow__node[data-id='n_transport']")
            open_reliability_tab(page)
            check(
                "普通活动没有故障率 λ 输入框",
                page.locator("#node-lambda").count() == 0,
                "unexpected #node-lambda",
            )
            body_text = page.locator(".reliability-panel").inner_text()
            check(
                "普通活动提示只配置持续时间",
                "普通活动只配置持续时间" in body_text,
                body_text[:200],
            )

            # Expand subprocesses and configure the four test modules.
            force_click(
                page,
                ".react-flow__node[data-id='n_storage'] .subprocess-toggle",
            )
            page.wait_for_selector(
                ".react-flow__node[data-id='s_inspect']", timeout=10000
            )
            force_click(
                page,
                ".react-flow__node[data-id='n_duty'] .subprocess-toggle",
            )
            page.wait_for_selector(
                ".react-flow__node[data-id='d_inspect']", timeout=10000
            )

            for node_id in (
                "s_inspect",
                "n_first_test",
                "n_second_test",
                "d_inspect",
            ):
                force_click(
                    page, f".react-flow__node[data-id='{node_id}']"
                )
                open_reliability_tab(page)
                page.wait_for_selector("#node-detection", timeout=10000)
                page.fill("#node-detection", "0.8")
                page.fill("#node-test-time", "1")
                save_reliability(page)

            # Outer overview with both subprocesses collapsed.
            page.locator("button:has-text('收起全部')").click()
            page.wait_for_timeout(400)
            page.locator("button:has-text('适应屏幕')").click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(HERE / "01_project_and_outer_flow.png"))
            summary["screenshots"].append("01_project_and_outer_flow.png")

            # Expanded storage block: focus automatically on expand so the
            # internal nodes and loop edges are readable and fully visible.
            force_click(
                page,
                ".react-flow__node[data-id='n_storage'] .subprocess-toggle",
            )
            page.wait_for_selector(
                ".react-flow__node[data-id='s_inspect']", timeout=10000
            )
            page.wait_for_timeout(700)
            page.screenshot(path=str(HERE / "03_storage_expanded.png"))
            summary["screenshots"].append("03_storage_expanded.png")

            force_click(
                page,
                ".react-flow__node[data-id='n_duty'] .subprocess-toggle",
            )
            page.wait_for_selector(
                ".react-flow__node[data-id='d_inspect']", timeout=10000
            )
            page.wait_for_timeout(700)
            page.screenshot(path=str(HERE / "04_duty_expanded.png"))
            summary["screenshots"].append("04_duty_expanded.png")

            # Run a real experiment through the web UI.
            page.locator(
                ".project-panel button:has-text('打开仿真运行')"
            ).click()
            page.wait_for_selector(".simulation-panel", timeout=10000)
            page.fill("#sim-end", "120")
            page.fill("#sim-seed", "2026")
            run_button = page.locator(
                ".simulation-panel button:has-text('运行仿真并评价')"
            )
            check(
                "补齐参数后运行按钮启用",
                run_button.is_enabled(),
                "run button disabled",
            )
            run_button.click()
            page.wait_for_selector(
                "text=战备完好度（时间口径）", timeout=90000
            )
            page.wait_for_selector("text=测试模块 / 故障检测", timeout=30000)
            check(
                "网页真实运行并显示战备完好度",
                page.locator("text=战备完好度（时间口径）").count() > 0,
            )
            check(
                "网页显示测试模块检测指标",
                page.locator("text=测试模块 / 故障检测").count() > 0,
            )
            check(
                "网页显示项目名称与目标",
                page.locator(".project-result-summary").count() > 0,
            )
            page.locator(".simulation-panel").screenshot(
                path=str(HERE / "02_simulation_results.png")
            )
            summary["screenshots"].append("02_simulation_results.png")

            experiments = get_json("/api/experiments")["experiments"]
            check(
                "实验已持久化",
                len(experiments) >= 1,
                str(len(experiments)),
            )
            stored = get_json(f"/api/experiments/{experiments[0]['result_id']}")
            record = stored["experiment"]
            summary["experiment"] = {
                "result_id": record["result_id"],
                "project": record.get("project"),
                "simulation_unit": record["simulation"]["simulation_unit"],
                "entity_count": record["simulation"]["entity_count"],
                "total_failure_count": record["simulation"]["total_failure_count"],
                "readiness": record["evaluation"]["overall"]["readiness"],
                "overall_reliability": record["evaluation"]["overall"][
                    "overall_reliability"
                ],
                "tests": record["evaluation"].get("tests", []),
                "nodes": [
                    {
                        "node_id": node["node_id"],
                        "module_type": node.get("module_type"),
                        "lambda": node.get("lambda"),
                        "lambda_unit": node.get("lambda_unit"),
                    }
                    for node in record["evaluation"]["nodes"]
                ],
            }
            check(
                "实验结果追溯项目名称",
                record.get("project", {}).get("name")
                == "某型导弹贮存值班保障项目",
            )
            check(
                "实验结果记录导弹数量",
                record["simulation"]["entity_count"] == 6,
            )
            check(
                "实验结果记录测试模块",
                len(record["evaluation"].get("tests", [])) >= 4,
            )
            check(
                "实验结果记录阶段节点",
                {
                    node["node_id"]
                    for node in record["evaluation"]["nodes"]
                    if node.get("module_type") == "stage"
                }
                == {"n_storage", "n_duty"},
            )

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    summary["ok"] = all(item["ok"] for item in summary["assertions"])
    dump("web_e2e_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
