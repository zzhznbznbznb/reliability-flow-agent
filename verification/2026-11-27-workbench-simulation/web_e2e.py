"""Real browser E2E for the flow workbench, total-time parameter and runtime UI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROCESS_PATH = ROOT / "examples" / "equipment_support_reliability_flow.json"
RUN_DATA = HERE / "run_data"
PORT = 8013
BASE = f"http://127.0.0.1:{PORT}"

sys.path.insert(0, str(ROOT))

from app.domain.process_ir import ProcessDocument  # noqa: E402
from tests.helpers import equipment_reliability_nodes  # noqa: E402


def dump(name: str, data) -> None:
    (HERE / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def request_json(path: str, *, method: str = "GET", payload=None) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


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


def bind_reliability(process: dict) -> dict:
    nodes = equipment_reliability_nodes(
        ProcessDocument.model_validate(process),
        lambda1=0.002,
        lambda2=0.005,
        detection_rate=0.8,
        test_time=1.0,
    )
    return request_json(
        f"/api/processes/{process['process_id']}/reliability",
        method="PUT",
        payload={
            "process_version": process["version"],
            "process_hash": process["content_hash"],
            "nodes": nodes,
        },
    )["reliability"]


def wait_toast(page, text: str, timeout: int = 30000) -> None:
    page.wait_for_selector(f".toast:has-text('{text}')", timeout=timeout)
    page.wait_for_timeout(300)


def force_click(page, selector: str, timeout: int = 8000) -> None:
    locator = page.locator(selector)
    try:
        locator.click(timeout=timeout)
    except Exception:
        locator.evaluate("el => el.click()")
        page.wait_for_timeout(250)


def main() -> None:
    if RUN_DATA.exists():
        shutil.rmtree(RUN_DATA)
    RUN_DATA.mkdir(parents=True)

    spec = json.loads(PROCESS_PATH.read_text(encoding="utf-8"))
    server = subprocess.Popen(
        [sys.executable, str(HERE / "serve_temp.py"), str(RUN_DATA), str(PORT)],
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
        process = request_json("/api/processes", method="POST", payload=spec)[
            "process"
        ]
        bind_reliability(process)
        summary["process_id"] = process["process_id"]
        summary["initial_version"] = process["version"]

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1180})
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_selector(".project-panel", timeout=30000)
            page.wait_for_timeout(1200)

            check(
                "页面不再出现“流程工作台”文字",
                page.locator("text=流程工作台").count() == 0,
            )
            check(
                "原工作台标题块已移除",
                page.locator(".toolbar h1").count() == 0,
            )
            check(
                "项目参数区存在仿真总时间",
                page.locator("#project-simulation_total_time").is_visible(),
            )

            before = page.locator(".canvas-card").bounding_box()
            page.locator(".project-panel button:has-text('收起参数')").click()
            page.wait_for_timeout(500)
            after = page.locator(".canvas-card").bounding_box()
            check(
                "收起参数后画布明显扩大",
                after["height"] > before["height"] + 100,
                f"{before['height']} -> {after['height']}",
            )
            check(
                "画布宽度保持可用",
                after["width"] > 1100,
                str(after["width"]),
            )

            # Invalid total time must be blocked with a specific reason.
            page.locator(".project-panel button:has-text('展开参数')").click()
            page.wait_for_timeout(300)
            page.fill("#project-name", "验收项目：贮存值班保障")
            page.fill("#project-description", "验证仿真总时间和流程时间编辑真实进入 Runtime")
            page.fill("#project-reliability_target", "0.6")
            page.fill("#project-readiness_target", "0.6")
            page.select_option("#project-simulation_unit", "day")
            page.fill("#project-simulation_total_time", "0")
            page.fill("#project-missile_count", "6")
            page.wait_for_timeout(300)
            check(
                "非法仿真总时间显示字段错误",
                "大于 0" in page.locator(".field-error").all_inner_texts().__str__(),
            )
            page.locator(".simulation-toolbar-run").click()
            page.wait_for_selector(".simulation-panel", timeout=10000)
            page.wait_for_timeout(500)
            check(
                "非法仿真总时间阻止运行并提示原因",
                "仿真总时间" in page.locator(".simulation-error").inner_text(),
                page.locator(".simulation-error").inner_text(),
            )
            page.locator(".simulation-head button:has-text('收起')").click()

            page.fill("#project-simulation_total_time", "120")
            page.wait_for_timeout(300)
            check(
                "合法仿真总时间消除字段错误",
                page.locator("#project-simulation_total_time").get_attribute(
                    "aria-invalid"
                )
                != "true",
            )

            # Edit an outer task duration through the real Inspector.
            force_click(page, ".react-flow__node[data-id='n_transport']")
            page.wait_for_selector("#node-duration", timeout=10000)
            page.fill("#node-duration", "2.5")
            page.locator("button:has-text('应用节点修改')").click()
            page.wait_for_timeout(500)
            check(
                "外层任务持续时间在画布中更新",
                "持续 2.5 天"
                in page.locator(".react-flow__node[data-id='n_transport']").inner_text(),
            )

            # Edit a nested storage task duration.
            force_click(
                page,
                ".react-flow__node[data-id='n_storage'] .subprocess-toggle",
            )
            page.wait_for_selector(".react-flow__node[data-id='s_store']", timeout=10000)
            force_click(page, ".react-flow__node[data-id='s_store']")
            page.wait_for_selector("#node-duration", timeout=10000)
            page.fill("#node-duration", "31.5")
            page.locator("button:has-text('应用节点修改')").click()
            page.wait_for_timeout(500)
            check(
                "嵌套子流程内部任务持续时间可编辑",
                "持续 31.5 天"
                in page.locator(".react-flow__node[data-id='s_store']").inner_text(),
            )

            page.locator(".canvas-toolbar button:has-text('保存新版本')").click()
            wait_toast(page, "已保存 v")
            page.wait_for_timeout(800)
            saved = request_json(f"/api/processes/{process['process_id']}")
            saved_process = saved["process"]
            summary["saved_version"] = saved_process["version"]
            nodes = {node["id"]: node for node in saved_process["nodes"]}

            def find_task(nodes_list, node_id):
                for node in nodes_list:
                    if node["id"] == node_id:
                        return node
                    if node.get("subflow"):
                        found = find_task(node["subflow"]["nodes"], node_id)
                        if found:
                            return found
                return None

            check(
                "保存后的 Process IR 保留外层任务时间",
                find_task(saved_process["nodes"], "n_transport")["duration"] == 2.5,
            )
            check(
                "保存后的 Process IR 保留嵌套任务时间",
                find_task(saved_process["nodes"], "s_store")["duration"] == 31.5,
            )

            bind_reliability(saved_process)
            page.reload(wait_until="networkidle")
            page.wait_for_selector(".project-panel", timeout=20000)
            page.wait_for_timeout(1500)
            force_click(page, ".react-flow__node[data-id='n_transport']")
            page.wait_for_selector("#node-duration", timeout=10000)
            check(
                "重新加载后外层时间仍为 2.5",
                page.locator("#node-duration").input_value() == "2.5",
            )
            force_click(
                page,
                ".react-flow__node[data-id='n_storage'] .subprocess-toggle",
            )
            page.wait_for_selector(".react-flow__node[data-id='s_store']", timeout=10000)
            force_click(page, ".react-flow__node[data-id='s_store']")
            page.wait_for_selector("#node-duration", timeout=10000)
            check(
                "重新加载后嵌套任务时间仍为 31.5",
                page.locator("#node-duration").input_value() == "31.5",
            )

            page.locator(".project-panel button:has-text('收起参数')").click()
            page.wait_for_timeout(400)
            page.locator(".simulation-toolbar-run").click()
            page.wait_for_selector(".simulation-panel", timeout=15000)
            page.wait_for_selector(".simulation-results", timeout=120000)
            page.wait_for_selector("text=战备完好度（时间口径）", timeout=30000)
            check(
                "界面显示本次真实仿真结果",
                page.locator(".simulation-results").count() == 1,
            )
            check(
                "结果显示仿真总时间 120 天",
                "仿真总时间 120 天"
                in page.locator(".simulation-meta").inner_text(),
            )
            check(
                "结果显示项目名称与可用/不可用统计",
                "验收项目：贮存值班保障" in page.locator(".simulation-results").inner_text()
                and "可用" in page.locator(".metric-grid").inner_text(),
            )
            check(
                "结果显示真实运行事件摘要",
                page.locator("text=运行事件摘要").count() == 1,
            )
            page.screenshot(path=str(HERE / "01_layout_and_results.png"))
            summary["screenshots"].append("01_layout_and_results.png")

            experiments = request_json("/api/experiments")["experiments"]
            check("实验记录已持久化", len(experiments) >= 1, str(len(experiments)))
            latest = request_json(f"/api/experiments/{experiments[0]['result_id']}")[
                "experiment"
            ]
            summary["experiment"] = {
                "result_id": latest["result_id"],
                "process_version": latest["process_version"],
                "project": latest.get("project"),
                "simulation_duration": latest["simulation"]["simulation_duration"],
                "simulation_unit": latest["simulation"]["simulation_unit"],
                "simulation_end": latest["simulation"]["simulation_end"],
                "overall_reliability": latest["evaluation"]["overall"][
                    "overall_reliability"
                ],
                "readiness": latest["evaluation"]["overall"]["readiness"],
            }
            check(
                "实验结果保留仿真总时间",
                latest["project"]["simulation_total_time"] == 120
                and latest["simulation"]["simulation_duration"] == 120,
            )
            check(
                "Runtime 使用仿真总时间作为终止时间",
                latest["simulation"]["simulation_end"] == 120,
            )
            check(
                "实验结果绑定最新 Process 版本",
                latest["process_version"] == saved_process["version"],
            )

            # Failure path: invalid total must not create another experiment.
            count_before = len(experiments)
            page.locator(".simulation-head button:has-text('收起')").click()
            page.locator(".project-panel button:has-text('展开参数')").click()
            page.fill("#project-simulation_total_time", "0")
            page.wait_for_timeout(300)
            page.locator(".simulation-toolbar-run").click()
            page.wait_for_selector(".simulation-panel", timeout=10000)
            page.wait_for_timeout(500)
            check(
                "运行失败时显示可理解错误",
                "仿真总时间" in page.locator(".simulation-error").inner_text(),
            )
            check(
                "运行前校验失败不会新增实验记录",
                len(request_json("/api/experiments")["experiments"]) == count_before,
            )

            page.locator(".simulation-head button:has-text('收起')").click()
            page.locator(".project-panel button:has-text('收起参数')").click()
            page.set_viewport_size({"width": 1366, "height": 768})
            page.wait_for_timeout(700)
            compact_canvas = page.locator(".canvas-card").bounding_box()
            check(
                "1366x768 窗口下画布仍可用",
                compact_canvas["width"] > 650 and compact_canvas["height"] > 300,
                f"{compact_canvas['width']} x {compact_canvas['height']}",
            )
            check(
                "1366x768 窗口下无页面横向溢出",
                page.evaluate(
                    "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                ),
            )
            page.screenshot(path=str(HERE / "02_compact_1366x768.png"))
            summary["screenshots"].append("02_compact_1366x768.png")

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
