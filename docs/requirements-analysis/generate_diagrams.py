from pathlib import Path
from html import escape
import math
import re
import subprocess
import tempfile

OUT = Path(__file__).resolve().parent
FONT = "'Microsoft YaHei','Noto Sans SC','PingFang SC',sans-serif"
INK = "#132A45"
MUTED = "#52667A"
LINE = "#CBD7E4"


def num(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def char_width(ch, size):
    if ch == " ":
        return size * 0.32
    if ord(ch) < 128:
        return size * 0.56
    return size


def text_width(text, size):
    return sum(char_width(ch, size) for ch in text)


def wrap_text(text, max_width, size):
    lines = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + ch
        if current and text_width(candidate, size) > max_width:
            if ch in "，。；：、）》】”’！？":
                current = candidate
                lines.append(current)
                current = ""
                continue
            lines.append(current)
            current = ch
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


class Canvas:
    def __init__(self, width, height, background="#F6F8FC"):
        self.w = width
        self.h = height
        self.items = [f'<rect x="0" y="0" width="{width}" height="{height}" fill="{background}"/>']

    def add(self, value):
        self.items.append(value)

    def rect(self, x, y, w, h, fill="none", stroke="none", sw=1, rx=0, opacity=1, dash=None, extra=""):
        attrs = [
            f'x="{num(x)}"', f'y="{num(y)}"', f'width="{num(w)}"', f'height="{num(h)}"',
            f'fill="{fill}"', f'stroke="{stroke}"', f'stroke-width="{num(sw)}"',
            f'opacity="{num(opacity)}"',
        ]
        if rx:
            attrs.append(f'rx="{num(rx)}"')
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        if extra:
            attrs.append(extra)
        self.add(f'<rect {" ".join(attrs)}/>')

    def ellipse(self, cx, cy, rx, ry, fill="none", stroke="none", sw=1, opacity=1):
        self.add(
            f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="{num(rx)}" ry="{num(ry)}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{num(sw)}" opacity="{num(opacity)}"/>'
        )

    def path(self, d, stroke, sw=1.4, dash=None, marker=None, opacity=1, fill="none"):
        attrs = [
            f'd="{d}"', f'fill="{fill}"', f'stroke="{stroke}"', f'stroke-width="{num(sw)}"',
            f'opacity="{num(opacity)}"', 'stroke-linecap="round"', 'stroke-linejoin="round"',
        ]
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        if marker:
            attrs.append(f'marker-end="url(#{marker})"')
        self.add(f'<path {" ".join(attrs)}/>')

    def text(self, x, y, content, size=16, fill=INK, weight=400, anchor="start", opacity=1,
             halo=False, letter_spacing=None):
        attrs = [
            f'x="{num(x)}"', f'y="{num(y)}"', f'font-family="{FONT}"',
            f'font-size="{num(size)}"', f'fill="{fill}"', f'font-weight="{weight}"',
            f'text-anchor="{anchor}"', f'opacity="{num(opacity)}"',
        ]
        if halo:
            attrs.append('style="paint-order:stroke;stroke:#FFFFFF;stroke-width:4px;stroke-linejoin:round"')
        if letter_spacing is not None:
            attrs.append(f'letter-spacing="{num(letter_spacing)}"')
        self.add(f'<text {" ".join(attrs)}>{escape(str(content))}</text>')

    def multiline(self, x, y, lines, size=16, fill=INK, weight=400, anchor="start",
                  line_height=1.35, opacity=1, halo=False):
        if not lines:
            return
        self.add(
            f'<text x="{num(x)}" y="{num(y)}" font-family="{FONT}" font-size="{num(size)}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}" opacity="{num(opacity)}"'
            + (' style="paint-order:stroke;stroke:#FFFFFF;stroke-width:4px;stroke-linejoin:round"' if halo else "")
            + ">"
        )
        for idx, line in enumerate(lines):
            dy = 0 if idx == 0 else size * line_height
            self.add(
                f'<tspan x="{num(x)}" dy="{num(dy)}">{escape(line)}</tspan>'
            )
        self.add("</text>")

    def svg(self, title):
        defs = """
<defs>
  <filter id="storyShadow" x="-8%" y="-8%" width="116%" height="124%">
    <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#102A43" flood-opacity="0.09"/>
  </filter>
  <filter id="softShadow" x="-8%" y="-8%" width="116%" height="124%">
    <feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#0B2545" flood-opacity="0.06"/>
  </filter>
  <marker id="openArrow" viewBox="0 0 12 12" refX="10.5" refY="6" markerWidth="10" markerHeight="10" orient="auto-start-reverse">
    <path d="M 2 2 L 10.5 6 L 2 10" fill="none" stroke="#5E7184" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs>
"""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(title)}">\n'
            + defs
            + "\n"
            + "\n".join(self.items)
            + "\n</svg>\n"
        )


def edge_point(cx, cy, rx, ry, tx, ty):
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    denom = math.hypot(dx / rx, dy / ry)
    return cx + dx / denom, cy + dy / denom


USE_CASES = {
    "A1": ("描述业务需求", "A", "base", (650, 440)),
    "A2": ("理解业务目标与流程", "A", "include", (1130, 400)),
    "A3": ("提取流程步骤", "A", "include", (1580, 350)),
    "A4": ("识别分支、循环与约束", "A", "include", (2020, 350)),
    "A5": ("生成流程模型与流程图", "A", "include", (1580, 520)),
    "A6": ("澄清并完善需求", "A", "extend", (1130, 620)),

    "B1": ("查看流程图", "B", "base", (650, 890)),
    "B2": ("编辑流程模型", "B", "base", (650, 1020)),
    "B3": ("编辑节点与连接", "B", "include", (1130, 960)),
    "B4": ("修改节点执行时间", "B", "include", (1580, 900)),
    "B5": ("配置分支与循环", "B", "include", (1130, 1110)),
    "B6": ("保存流程模型", "B", "base", (650, 1240)),
    "B7": ("校验流程模型", "B", "include", (1130, 1220)),

    "C1": ("配置设备可靠性", "C", "base", (650, 1480)),
    "C2": ("选择可靠性计算节点", "C", "include", (1130, 1420)),
    "C3": ("设置节点故障率", "C", "include", (1130, 1560)),
    "C4": ("查看并校验可靠性配置", "C", "extend", (1600, 1560)),

    "D1": ("配置故障检测与维修", "D", "base", (650, 1870)),
    "D2": ("指定故障检测节点", "D", "include", (1130, 1810)),
    "D3": ("配置处理、维修与恢复", "D", "include", (1130, 1950)),
    "D4": ("校验故障维修配置", "D", "extend", (1600, 1950)),

    "E1": ("创建仿真任务", "E", "base", (650, 2220)),
    "E2": ("设置仿真参数", "E", "include", (1130, 2160)),
    "E3": ("校验仿真配置", "E", "include", (1580, 2160)),
    "E4": ("执行多设备仿真", "E", "base", (650, 2470)),
    "E5": ("管理设备独立运行", "E", "include", (1130, 2410)),
    "E6": ("模拟设备故障生命周期", "E", "include", (1130, 2570)),
    "E7": ("检测潜在故障", "E", "include", (1580, 2520)),
    "E8": ("维修并恢复运行", "E", "include", (1580, 2640)),
    "E9": ("查看仿真进度", "E", "extend", (650, 2670)),

    "F1": ("查看仿真结果", "F", "base", (650, 3010)),
    "F2": ("查看设备状态与轨迹", "F", "include", (1130, 2910)),
    "F3": ("查看故障与维修记录", "F", "include", (1130, 2990)),
    "F4": ("查看节点执行统计", "F", "include", (1130, 3070)),
    "F5": ("查看可靠性指标", "F", "include", (1130, 3150)),
    "F6": ("对比理论可靠度与实际统计", "F", "include", (1580, 3150)),
    "F7": ("获取结果解释", "F", "extend", (650, 3210)),

    "G1": ("管理仿真实验", "G", "base", (650, 3420)),
    "G2": ("保存实验", "G", "include", (1130, 3380)),
    "G3": ("查看历史实验", "G", "include", (1130, 3470)),
    "G4": ("复现实验", "G", "include", (1130, 3560)),
    "G5": ("修改实验参数", "G", "extend", (1600, 3560)),
    "G6": ("比较实验结果", "G", "include", (1130, 3710)),
    "G7": ("分析参数影响", "G", "base", (650, 3650)),
}

ZONES = {
    "A": ("需求理解与流程生成", 300, 480, "#2563EB", "#F3F8FE"),
    "B": ("流程查看与编辑", 820, 500, "#0F766E", "#F4FAF8"),
    "C": ("设备可靠性配置", 1360, 340, "#B45309", "#FFF9F1"),
    "D": ("故障检测与维修", 1740, 330, "#BE123C", "#FFF6F6"),
    "E": ("仿真任务与执行", 2110, 700, "#1D4ED8", "#F4F7FE"),
    "F": ("仿真结果分析", 2850, 430, "#6D28D9", "#F9F5FF"),
    "G": ("实验管理与比较", 3320, 470, "#15803D", "#F5FBF6"),
}

PRIMARY = ["A1", "B1", "B2", "B6", "C1", "D1", "E1", "E4", "F1", "G1", "G7"]

INCLUDES = [
    ("A1", "A2", 0.50, 0, -9),
    ("A2", "A3", 0.50, 0, -9),
    ("A3", "A4", 0.50, 0, -9),
    ("A2", "A5", 0.50, 0, 11),
    ("B2", "B3", 0.50, 0, -9),
    ("B3", "B4", 0.50, 0, -9),
    ("B2", "B5", 0.50, 0, 11),
    ("B6", "B7", 0.50, 0, -9),
    ("C1", "C2", 0.50, 0, -9),
    ("C1", "C3", 0.50, 0, 11),
    ("D1", "D2", 0.50, 0, -9),
    ("D1", "D3", 0.50, 0, 11),
    ("E1", "E2", 0.50, 0, -9),
    ("E2", "E3", 0.50, 0, -9),
    ("E4", "E5", 0.50, 0, -9),
    ("E4", "E6", 0.50, 0, 11),
    ("E6", "E7", 0.50, 0, -9),
    ("E6", "E8", 0.50, 0, 11),
    ("F1", "F2", 0.47, 0, -6),
    ("F1", "F3", 0.49, 0, -3),
    ("F1", "F4", 0.51, 0, 3),
    ("F1", "F5", 0.53, 0, 6),
    ("F5", "F6", 0.50, 0, -9),
    ("G1", "G2", 0.50, 0, -8),
    ("G1", "G3", 0.50, 0, -4),
    ("G1", "G4", 0.50, 0, 8),
    ("G7", "G6", 0.50, 0, -9),
]

EXTENDS = [
    ("A6", "A2", "信息不完整或存在歧义", None, (1110, 512), "end"),
    ("C4", "C3", "配置完成后查看或检查", 0.50, None, "middle"),
    ("D4", "D3", "保存或运行前校验", 0.50, None, "middle"),
    ("E9", "E4", "仿真运行期间", None, (610, 2580), "end"),
    ("F7", "F1", "需要自然语言解读", None, (610, 3135), "end"),
    ("G5", "G4", "需要调整参数", 0.50, None, "middle"),
]

NOTES = {
    "A": (
        2360, 340, 1000, "自然语言理解要点",
        "Agent 从自然语言中识别业务目标、流程步骤、顺序、条件、循环与业务约束。信息缺失或存在歧义时，主动提出澄清问题，并根据用户反馈修订模型。",
        "A4",
    ),
    "B": (
        2360, 870, 1000, "流程模型约束",
        "流程模型由节点、连接和属性组成，节点记录执行时间等业务属性。保存前校验连通性、条件分支完整性与循环退出条件，避免生成不可执行模型。",
        "B4",
    ),
    "C": (
        2360, 1400, 1000, "模型分离原则",
        "可靠性模型与流程模型分离，仅通过节点标识关联。只有“参与可靠性计算”的节点应用故障率 λ，普通业务节点不进入可靠性统计。",
        "C4",
    ),
    "D": (
        2360, 1800, 1000, "故障生命周期机制",
        "潜在故障可先发生，设备仍继续执行；只有进入故障检测节点时才被发现，随后进入处理与维修。维修完成后恢复运行，历史故障记录永久保留。",
        "D4",
    ),
    "E": (
        2360, 2190, 1000, "多设备运行规则",
        "多台设备共享同一流程定义，但独立维护运行状态、故障状态和运行历史。单台设备故障不会自动中断其他设备；参数包括设备数量、结束时间、随机种子和运行参数。",
        "E3",
    ),
    "F": (
        2360, 2920, 1000, "两类可靠性结论",
        "理论可靠度由可靠性参数解析计算；实际故障统计来自多设备仿真事件。二者并列展示，并由 Agent 解释差异来源，避免把理论值与仿真频率混为一谈。",
        "F6",
    ),
    "G": (
        2360, 3390, 1000, "实验比较原则",
        "固定流程模型与随机种子可复现实验。比较实验时应只改变目标参数，分析其对系统可靠性、故障次数和维修负担的影响。",
        "G5",
    ),
}


def draw_actor(c, x, y, label="用户"):
    c.ellipse(x, y - 43, 15, 15, "#FFFFFF", "#1F2D3D", 2.2)
    c.path(f"M {x} {y - 28} L {x} {y + 16}", "#1F2D3D", 2.2)
    c.path(f"M {x - 27} {y - 11} L {x + 27} {y - 11}", "#1F2D3D", 2.2)
    c.path(f"M {x} {y + 16} L {x - 22} {y + 58}", "#1F2D3D", 2.2)
    c.path(f"M {x} {y + 16} L {x + 22} {y + 58}", "#1F2D3D", 2.2)
    c.text(x, y + 93, label, 24, "#102A43", 700, "middle")


def draw_uc(c, key):
    name, zone, kind, (cx, cy) = USE_CASES[key]
    accent = ZONES[zone][3]
    if kind == "base":
        fill, stroke, sw = "#EAF3FE", "#2D5F8A", 2.2
    elif kind == "extend":
        fill, stroke, sw = "#FFF8E8", "#B07A16", 1.7
    else:
        fill, stroke, sw = "#FFFFFF", "#5F7F98", 1.55
    c.ellipse(cx, cy, 170, 45, fill, stroke, sw)
    c.text(cx, cy + 7.5, name, 21, "#15324E", 600 if kind == "base" else 500, "middle")


def draw_relation(c, a, b, kind, t=0.5, dx=0, dy=-9, cond=None, label_xy=None, anchor="middle"):
    _, _, _, (ax, ay) = USE_CASES[a]
    _, _, _, (bx, by) = USE_CASES[b]
    p1 = edge_point(ax, ay, 170, 45, bx, by)
    p2 = edge_point(bx, by, 170, 45, ax, ay)
    c.path(f"M {num(p1[0])} {num(p1[1])} L {num(p2[0])} {num(p2[1])}", "#5E7184", 1.45, "7 5", "openArrow")
    lx = p1[0] + (p2[0] - p1[0]) * t
    ly = p1[1] + (p2[1] - p1[1]) * t
    if label_xy:
        lx, ly = label_xy
    text1 = "«include»" if kind == "include" else "«extend»"
    if cond:
        c.text(lx + dx, ly + dy - 6, text1, 10.8, "#52667A", 500, anchor, halo=True)
        c.text(lx + dx, ly + dy + 9, f"[{cond}]", 10.4, "#8A5A00", 500, anchor, halo=True)
    else:
        c.text(lx + dx, ly + dy, text1, 10.8, "#52667A", 500, anchor, halo=True)


def draw_note(c, zone):
    x, y, w, title, body, target = NOTES[zone]
    lines = wrap_text(body, w - 44, 15.2)
    h = 60 + len(lines) * 24 + 16
    c.rect(x, y, w, h, "#FFFDF4", "#D6A62C", 1.3, 12, dash="6 5")
    c.rect(x + 14, y + 14, 30, 24, "#D6A62C", "#D6A62C", 1, 5)
    c.text(x + 29, y + 31, "注", 12, "#FFFFFF", 700, "middle")
    c.text(x + 54, y + 32, title, 16, "#7A5200", 700)
    c.multiline(x + 22, y + 58, lines, 15.2, "#5B4A2F", 400, line_height=1.58)
    _, _, _, (tx, ty) = USE_CASES[target]
    c.path(f"M {num(x)} {num(y + 42)} L {num(tx + 170)} {num(ty)}", "#C79A25", 1.1, "3 5", opacity=0.8)
    return h


def build_use_case_svg():
    c = Canvas(3600, 3960, "#F5F8FC")
    c.rect(0, 0, 3600, 13, "#132A45", rx=0)
    c.text(80, 91, "图 1  UML 用例图：基于自然语言的流程建模与设备可靠性仿真 Agent", 38, "#102A43", 700)
    c.text(80, 132, "业务闭环：自然语言需求 → 流程模型 → 可靠性配置 → 多设备仿真 → 结果解释 → 实验比较", 17, MUTED)
    c.path("M 80 160 L 2160 160", "#2D5F8A", 2.2)

    c.rect(2190, 35, 1330, 176, "#FFFFFF", "#D9E3EE", 1.2, 14, extra='filter="url(#softShadow)"')
    c.text(2216, 65, "图例", 16, "#102A43", 700)
    c.path("M 2216 104 L 2280 104", "#7B8A9A", 1.6)
    c.text(2296, 109, "关联关系", 13.6, MUTED)
    c.path("M 2216 132 L 2280 132", "#5E7184", 1.4, "7 5", "openArrow")
    c.text(2296, 137, "«include»  必需的子行为", 13.6, MUTED)
    c.path("M 2216 160 L 2280 160", "#5E7184", 1.4, "7 5", "openArrow")
    c.text(2296, 165, "«extend» [条件]  可选增强行为", 13.6, MUTED)
    c.rect(2216, 181, 28, 18, "#FFFDF4", "#D6A62C", 1, 4, dash="4 3")
    c.text(2258, 195, "业务规则 / 机制说明", 13.6, MUTED)

    c.rect(300, 250, 3180, 3580, "#FFFFFF", "#274C77", 2.2, 24)
    c.rect(330, 250, 290, 36, "#274C77", "#274C77", 1, 8)
    c.text(352, 275, "系统边界", 16, "#FFFFFF", 700)
    c.text(640, 275, "基于自然语言的流程建模与设备可靠性仿真 Agent", 16, "#274C77", 600)

    for key, (title, top, height, accent, fill) in ZONES.items():
        c.rect(330, top, 3120, height, fill, "#DFE8F1", 1.2, 18)

    actor_x, actor_y = 170, 1970
    for key in PRIMARY:
        _, _, _, (cx, cy) = USE_CASES[key]
        ex, ey = edge_point(cx, cy, 170, 45, actor_x, actor_y)
        c.path(f"M {actor_x + 25} {actor_y - 12} L {num(ex)} {num(ey)}", "#7B8A9A", 1.25, opacity=0.42)

    for key, (title, top, height, accent, fill) in ZONES.items():
        c.rect(330, top, 7, height, accent, accent, 1, 0)
        c.ellipse(362, top + 31, 17, 17, accent, accent, 1)
        c.text(362, top + 37, key, 16, "#FFFFFF", 700, "middle")
        c.text(390, top + 39, title, 23, "#102A43", 700)

    for key in NOTES:
        draw_note(c, key)

    for key in USE_CASES:
        draw_uc(c, key)

    for a, b, t, dx, dy in INCLUDES:
        draw_relation(c, a, b, "include", t, dx, dy)

    for a, b, cond, t, xy, anchor in EXTENDS:
        draw_relation(c, a, b, "extend", t if t is not None else 0.5, 0, 0, cond, xy, anchor)

    draw_actor(c, actor_x, actor_y)

    c.text(80, 3895, "需求分析基线 v1.0 · 2026-11 · 仅描述产品需求与用户目标，不以现有技术实现为设计依据", 14, "#6B7C8F")
    c.text(3520, 3895, "UML 2.x 用例图规范", 14, "#6B7C8F", 400, "end")
    return c.svg("UML 用例图")


ACTIVITIES = [
    {
        "no": "01", "name": "提出业务需求", "outcome": "明确目标、流程与约束",
        "MVP": [
            ("输入业务目标与流程", "业务建模人员", "用自然语言说明业务目标、流程步骤和参与角色", "快速获得可编辑的初始流程模型"),
            ("说明设备与规模", "业务建模人员", "说明设备类型、数量及运行方式", "系统确定可靠性建模范围和仿真规模"),
            ("补充业务约束", "业务建模人员", "补充时间、顺序、资源和异常等约束", "生成的模型符合真实业务规则"),
            ("回答澄清问题", "业务建模人员", "回答 Agent 对缺失信息和歧义的澄清问题", "完善需求并减少建模偏差"),
        ],
        "V1.1": [
            ("维护领域术语", "业务建模人员", "维护业务术语和同义词", "Agent 更准确地理解行业表达"),
            ("导入需求文档", "业务建模人员", "导入需求文档并让 Agent 提取要点", "复用已有材料开展建模"),
        ],
        "V1.2": [
            ("多轮对话式建模", "业务建模人员", "通过连续对话逐步补充复杂需求", "Agent 在上下文中持续完善模型"),
            ("语音与文档混合输入", "业务建模人员", "用语音、文档和表单混合表达需求", "适配不同工作习惯和输入场景"),
        ],
    },
    {
        "no": "02", "name": "理解和构建流程", "outcome": "得到结构化流程模型",
        "MVP": [
            ("理解业务目标", "业务建模人员", "Agent 识别业务目标、边界与成功标准", "确认系统真正理解了问题"),
            ("提取流程逻辑", "业务建模人员", "自动提取步骤、顺序、条件和循环", "获得结构化的业务流程"),
            ("生成流程模型", "业务建模人员", "得到包含节点、连接和属性的可编辑模型", "继续完善而不是从零搭建"),
            ("生成可视化流程图", "业务建模人员", "自动获得业务流程图", "与业务人员核对并定位理解偏差"),
        ],
        "V1.1": [
            ("查看建模依据", "业务建模人员", "查看每个节点和连接的提取依据", "核验 Agent 的建模判断"),
            ("识别异常与补偿路径", "业务建模人员", "让 Agent 识别异常路径和补偿措施", "流程覆盖更多真实业务情况"),
            ("复用流程模板", "业务建模人员", "从历史模型或模板开始建模", "加速相似业务的流程设计"),
        ],
        "V1.2": [
            ("自动补全流程", "业务建模人员", "Agent 主动建议缺失步骤、分支和约束", "发现未被描述的业务环节"),
            ("模型质量评估", "业务建模人员", "获得完整性、可执行性和可理解性评分", "判断模型成熟度和可仿真程度"),
        ],
    },
    {
        "no": "03", "name": "编辑和确认流程", "outcome": "形成可执行流程图",
        "MVP": [
            ("查看流程图", "业务建模人员", "缩放、平移并查看节点详情", "检查流程结构和关键路径"),
            ("新增或删除节点", "业务建模人员", "增加遗漏步骤或删除多余节点", "让流程与实际业务一致"),
            ("修改节点属性与执行时间", "业务建模人员", "修改节点名称、资源和执行时间", "模型反映真实作业耗时"),
            ("编辑连接与分支循环", "业务建模人员", "调整连接、条件分支和循环", "准确表达业务规则与异常路径"),
            ("保存并校验流程", "业务建模人员", "保存前自动校验连通性和循环退出条件", "保证模型可以进入仿真"),
        ],
        "V1.1": [
            ("批量编辑节点", "业务建模人员", "批量修改节点属性和执行时间", "高效维护大型流程"),
            ("撤销、重做与版本对比", "业务建模人员", "安全撤销修改并比较模型版本", "控制编辑风险并保留演进依据"),
        ],
        "V1.2": [
            ("AI 辅助优化流程", "业务建模人员", "Agent 给出简化、并行化和瓶颈优化建议", "提升流程效率"),
            ("协同编辑与评审", "业务建模人员", "邀请团队成员评论和审批模型", "形成共同确认的流程版本"),
        ],
    },
    {
        "no": "04", "name": "配置设备可靠性", "outcome": "量化节点失效风险",
        "MVP": [
            ("选择可靠性节点", "可靠性工程师", "选择需要参与可靠性计算的流程节点", "把分析聚焦在真实设备环节"),
            ("设置参与状态", "可靠性工程师", "设置节点是否参与可靠性计算", "区分普通业务步骤与设备失效风险"),
            ("配置故障率 λ", "可靠性工程师", "为每个设备节点配置故障率 λ", "量化设备在流程中的失效可能性"),
            ("查看并校验可靠性配置", "可靠性工程师", "查看节点与流程的理论可靠度，并校验可靠性参数的关联", "避免遗漏、错配或无效参数"),
        ],
        "V1.1": [
            ("按设备类型批量配置", "可靠性工程师", "按设备类型批量应用故障率", "减少重复配置并保持参数一致"),
            ("选择故障分布", "可靠性工程师", "配置指数、威布尔等故障分布", "更贴近真实设备失效规律"),
            ("建立可靠性参数库", "可靠性工程师", "沉淀可复用的设备可靠性参数", "在不同实验间保持一致"),
        ],
        "V1.2": [
            ("可靠性敏感性分析", "可靠性工程师", "识别对系统可靠度影响最大的参数", "优先改进关键设备"),
            ("参数取值建议", "可靠性工程师", "由 Agent 根据历史数据推荐故障率取值", "减少主观估计误差"),
        ],
    },
    {
        "no": "05", "name": "配置故障检测与维修", "outcome": "建立检测与维修规则",
        "MVP": [
            ("指定故障检测节点", "可靠性工程师", "指定具备故障检测能力的节点", "潜在故障在正确的业务环节被发现"),
            ("配置检测耗时", "可靠性工程师", "设置检测节点执行时间", "把检测开销纳入流程与可靠性分析"),
            ("配置处理、维修与恢复", "可靠性工程师", "设计故障发现后的处理路径、维修流程和恢复位置", "设备能够继续运行并形成闭环"),
            ("预览故障生命周期", "可靠性工程师", "预览潜在故障、检测、维修和恢复过程", "确认机制完整且业务路径闭环"),
        ],
        "V1.1": [
            ("配置维修资源约束", "可靠性工程师", "配置备件、维修人员和维修能力约束", "分析维修等待对可靠性的影响"),
            ("比较检测策略", "可靠性工程师", "配置不同检测节点方案并比较", "选择更有效的故障检测策略"),
        ],
        "V1.2": [
            ("预防性维修策略", "可靠性工程师", "配置计划性维护和更换策略", "比较预防维修与故障后维修的收益"),
            ("检测与维修联合优化", "可靠性工程师", "让 Agent 联合优化检测节点和维修资源", "在成本与可靠性之间取得平衡"),
        ],
    },
    {
        "no": "06", "name": "创建仿真任务", "outcome": "确定实验边界",
        "MVP": [
            ("设置设备数量", "仿真分析人员", "设置参与仿真的设备数量", "分析设备规模对系统可靠性的影响"),
            ("设置时间、种子与运行参数", "仿真分析人员", "设置仿真结束时间、随机种子和运行参数", "控制实验范围并保证结果可复现"),
            ("检查模型与参数", "仿真分析人员", "运行前自动检查流程、可靠性、检测和维修配置", "避免无效仿真和参数遗漏"),
            ("创建仿真任务", "仿真分析人员", "保存本次仿真配置并创建任务", "开始执行并支持后续复用"),
        ],
        "V1.1": [
            ("生成参数扫描任务", "仿真分析人员", "设置参数范围并批量生成任务", "系统开展多组对比实验"),
            ("克隆历史任务", "仿真分析人员", "从历史任务克隆配置", "快速创建相似仿真"),
        ],
        "V1.2": [
            ("目标驱动的实验设计", "仿真分析人员", "说明分析目标并由 Agent 设计实验方案", "减少人工试错"),
            ("仿真资源调度", "仿真分析人员", "设置计算资源和任务优先级", "高效运行大规模实验"),
        ],
    },
    {
        "no": "07", "name": "执行多设备仿真", "outcome": "获得多设备运行事实",
        "MVP": [
            ("启动并查看进度", "仿真分析人员", "启动多设备仿真并查看运行进度", "掌握实验状态"),
            ("查看设备独立状态", "仿真分析人员", "查看每台设备当前节点、状态和运行轨迹", "观察设备之间的行为差异"),
            ("查看故障与维修事件", "仿真分析人员", "实时查看故障发生、检测、维修和恢复事件", "理解设备可靠性变化过程"),
            ("验证设备独立运行", "仿真分析人员", "确认单台设备故障不会中断其他设备", "正确评估多设备系统的整体行为"),
        ],
        "V1.1": [
            ("暂停、继续与终止", "仿真分析人员", "暂停、继续或终止仿真", "控制长时间运行任务"),
            ("查看日志与告警", "仿真分析人员", "查看运行日志和异常告警", "诊断仿真问题并定位异常"),
        ],
        "V1.2": [
            ("实时动画追踪", "仿真分析人员", "用时间轴和动画观察设备运行过程", "直观理解故障传播与恢复"),
            ("异常过程智能标注", "仿真分析人员", "Agent 自动标注关键故障和长等待事件", "快速聚焦异常环节"),
        ],
    },
    {
        "no": "08", "name": "分析仿真结果", "outcome": "形成可靠性结论",
        "MVP": [
            ("查看整体可靠性指标", "仿真分析人员", "查看系统可靠度、节点可靠度、故障次数和平均修复时间", "量化评估系统可靠性"),
            ("查看设备最终状态与轨迹", "仿真分析人员", "查看每台设备的最终状态和运行轨迹", "定位不同设备的结果差异"),
            ("查看节点执行统计", "仿真分析人员", "查看节点执行次数、忙闲时间和等待情况", "发现流程瓶颈"),
            ("查看故障发现与维修统计", "仿真分析人员", "查看潜在故障、已发现故障和维修记录", "评估检测与维修机制"),
            ("对比理论与实际", "仿真分析人员", "对比理论可靠度与实际仿真故障统计", "判断模型假设与仿真结果是否一致"),
            ("获取 Agent 解释", "仿真分析人员", "Agent 用自然语言解释关键指标和异常结果", "形成可汇报的分析结论"),
        ],
        "V1.1": [
            ("筛选与导出报告", "仿真分析人员", "按设备、节点和故障类型筛选并导出报告", "用于项目汇报和评审"),
            ("图表联动与下钻", "仿真分析人员", "从总体指标下钻到设备和节点明细", "快速定位问题"),
        ],
        "V1.2": [
            ("根因分析建议", "仿真分析人员", "由 Agent 分析可靠性瓶颈的主要原因", "制定有针对性的改进措施"),
            ("优化建议与方案对比", "仿真分析人员", "获得流程和维修策略的优化方案对比", "选择最优改进路径"),
        ],
    },
    {
        "no": "09", "name": "管理和比较实验", "outcome": "沉淀实验与决策依据",
        "MVP": [
            ("保存实验", "仿真分析人员", "保存本次实验的模型、参数和结果", "后续追溯与复现"),
        ],
        "V1.1": [
            ("查看历史实验", "仿真分析人员", "浏览并检索历史实验", "找回和复用过去的分析"),
            ("复现实验", "仿真分析人员", "用相同模型和随机种子重跑实验", "验证结果一致性"),
            ("修改参数并派生", "仿真分析人员", "复制实验并修改关键参数", "快速开展对照实验"),
            ("比较实验结果", "仿真分析人员", "并排比较多个实验的指标和配置", "识别实验差异"),
            ("分析参数影响", "仿真分析人员", "分析设备数量、故障率、检测策略等参数的影响", "支撑可靠性改进决策"),
        ],
        "V1.2": [
            ("实验看板与知识沉淀", "仿真分析人员", "用看板沉淀实验结论和最佳实践", "团队复用分析成果"),
            ("决策报告自动生成", "仿真分析人员", "由 Agent 自动生成可靠性与参数影响报告", "支撑管理决策"),
        ],
    },
]

RELEASES = {
    "MVP": ("MVP", "最小可行版本", "#2563EB", "#F2F7FF",
            ["完成一次完整的", "自然语言建模 →", "可靠性配置 →", "多设备仿真 →", "结果分析闭环"]),
    "V1.1": ("V1.1", "增强版本", "#B45309", "#FFFBF2",
             ["增强自然语言理解、", "复杂流程编辑、", "实验管理与比较"]),
    "V1.2": ("V1.2", "智能版本", "#15803D", "#F3FBF6",
             ["智能解释、优化", "与协同决策"]),
}


def card_metrics(card, width=422):
    task, role, action, value = card
    inner = width - 40
    task_lines = wrap_text(task, width - 115, 14.6)
    role_lines = wrap_text(f"作为一名{role}，", inner, 13.6)
    wish_lines = wrap_text(f"我希望{action}，", inner, 14.0)
    purpose_lines = wrap_text(f"以便{value}。", inner, 14.0)
    body_top = 50 + max(0, len(task_lines) - 1) * 19
    height = body_top + len(role_lines) * 20 + len(wish_lines) * 21 + len(purpose_lines) * 21 + 15
    return {
        "task": task, "role": role, "action": action, "value": value,
        "task_lines": task_lines, "role_lines": role_lines,
        "wish_lines": wish_lines, "purpose_lines": purpose_lines,
        "height": max(140, height), "body_top": body_top,
    }


def build_story_layout():
    metrics = {}
    for activity in ACTIVITIES:
        for release in RELEASES:
            metrics[(activity["no"], release)] = [card_metrics(card) for card in activity[release]]
    lane_heights = {}
    for release in RELEASES:
        max_height = 0
        for activity in ACTIVITIES:
            cards = metrics[(activity["no"], release)]
            total = sum(card["height"] for card in cards) + 12 * (len(cards) - 1)
            max_height = max(max_height, total)
        lane_heights[release] = max_height + 40
    return metrics, lane_heights


def build_story_map_svg():
    metrics, lane_heights = build_story_layout()
    width = 4540
    start_y = 330
    footer_space = 90
    total_lane_height = sum(lane_heights.values())
    height = start_y + total_lane_height + footer_space
    c = Canvas(width, height, "#F7F9FC")
    c.rect(0, 0, width, 12, "#132A45")
    c.text(60, 74, "图 2  用户故事地图：基于自然语言的流程建模与设备可靠性仿真 Agent", 37, "#102A43", 700)
    c.text(60, 114, "从需求输入到实验比较的完整用户旅程 · 九项用户活动 · 三个版本切片", 16.5, MUTED)
    c.path("M 60 145 L 2760 145", "#2D5F8A", 2.2)

    c.rect(3020, 44, 1460, 92, "#FFFFFF", "#D9E3EE", 1.1, 13)
    c.text(3044, 70, "版本切片", 14, "#102A43", 700)
    for idx, key in enumerate(["MVP", "V1.1", "V1.2"]):
        label, _, color, _, _ = RELEASES[key]
        x = 3125 + idx * 200
        c.rect(x, 58, 13, 13, color, color, 1, 3)
        c.text(x + 22, 69, label, 13, "#34495E", 700)
    c.text(3044, 101, "横向为用户旅程（Backbone），纵向为版本切片；卡片标题为用户任务，正文为用户故事。", 12.8, MUTED)
    c.text(3044, 123, "MVP 完成闭环 · V1.1 增强建模与实验管理 · V1.2 引入智能解释与优化", 12.2, "#6B7C8F")

    c.text(62, 226, "用户活动", 18, "#102A43", 700)
    c.text(62, 250, "BACKBONE", 10.8, "#7B8A9A", 600, letter_spacing=1.2)
    c.text(62, 274, "按使用顺序 →", 12, "#7B8A9A")

    x0 = 330
    col_w = 440
    gap = 18
    step = col_w + gap
    header_y = 200
    header_h = 108
    activity_colors = ["#2D5F8A", "#0F766E", "#B45309", "#BE123C", "#1D4ED8", "#6D28D9", "#15803D", "#B45309", "#0F766E"]
    for idx, activity in enumerate(ACTIVITIES):
        x = x0 + idx * step
        c.rect(x, header_y, col_w, header_h, "#132A45", "#132A45", 1, 14, extra='filter="url(#softShadow)"')
        c.rect(x + 18, header_y + 12, 38, 4, activity_colors[idx], activity_colors[idx], 1, 2)
        c.text(x + 18, header_y + 34, activity["no"], 11.5, activity_colors[idx], 700)
        c.text(x + 18, header_y + 64, activity["name"], 20.5, "#FFFFFF", 700)
        c.text(x + 18, header_y + 89, activity["outcome"], 12.2, "#B8C8DA")

    lane_y = start_y
    for release_key in ["MVP", "V1.1", "V1.2"]:
        label, subtitle, accent, lane_fill, description = RELEASES[release_key]
        lane_h = lane_heights[release_key]
        c.rect(50, lane_y, 4440, lane_h, lane_fill, "#E0E8F1", 1.1, 16)
        c.rect(50, lane_y, 6, lane_h, accent, accent, 1, 0)
        c.text(76, lane_y + 43, label, 25, accent, 700)
        c.text(76, lane_y + 66, subtitle, 13, "#34495E", 700)
        for line_idx, line in enumerate(description):
            c.text(76, lane_y + 94 + line_idx * 18, line, 12.2, "#52667A")
        count = sum(len(activity[release_key]) for activity in ACTIVITIES)
        c.text(76, lane_y + lane_h - 24, f"{count} 个用户故事", 12.5, accent, 700)

        for idx, activity in enumerate(ACTIVITIES):
            col_x = x0 + idx * step
            cards = metrics[(activity["no"], release_key)]
            y = lane_y + 20
            for card in cards:
                card_x = col_x + 9
                card_w = 422
                card_h = card["height"]
                c.rect(card_x, y, card_w, card_h, "#FFFFFF", "#D7E2EE", 1.0, 12,
                       extra='filter="url(#storyShadow)"')
                c.rect(card_x + 14, y + 13, 4, 20, accent, accent, 1, 2)
                c.text(card_x + 27, y + 30, card["task_lines"][0], 14.7, "#17324D", 700)
                badge_w = 45 if release_key != "V1.1" else 52
                c.rect(card_x + card_w - badge_w - 14, y + 13, badge_w, 20, accent, accent, 1, 6)
                c.text(card_x + card_w - badge_w / 2 - 14, y + 27, label, 10.5, "#FFFFFF", 700, "middle")
                by = y + card["body_top"]
                for line in card["role_lines"]:
                    c.text(card_x + 20, by, line, 13.6, accent, 700)
                    by += 20
                for line in card["wish_lines"]:
                    c.text(card_x + 20, by, line, 14.0, "#243449")
                    by += 21
                for line in card["purpose_lines"]:
                    c.text(card_x + 20, by, line, 14.0, "#243449")
                    by += 21
                y += card_h + 12
        lane_y += lane_h

    y = height - 52
    c.text(60, y, "阅读方式：横向沿 Backbone 完成用户旅程；纵向按版本切片交付；每张卡片由用户任务与用户故事组成。", 13.2, "#52667A")
    c.text(4480, y, "MVP 以完整闭环为边界 · 后续版本按用户价值递进", 13.2, "#6B7C8F", 400, "end")
    c.text(60, y + 25, "说明：本图用于产品需求分析与版本规划，不依赖现有代码实现。", 12.2, "#7B8A9A")
    return c.svg("用户故事地图")


def write_plantuml():
    lines = [
        "@startuml",
        "left to right direction",
        "skinparam packageStyle rectangle",
        "skinparam usecase {",
        "  BackgroundColor #F8FBFE",
        "  BorderColor #2D5F8A",
        "}",
        "actor \"用户\" as User",
        "",
        "rectangle \"基于自然语言的流程建模与设备可靠性仿真 Agent\" {",
    ]
    for zone, (title, _, _, _, _) in ZONES.items():
        lines.append(f"  package \"{title}\" {{")
        for key, (name, z, kind, _) in USE_CASES.items():
            if z == zone:
                lines.append(f"    usecase \"{name}\" as {key}")
        lines.append("  }")
    lines.append("}")
    lines.append("")
    for key in PRIMARY:
        lines.append(f"User -- {key}")
    for a, b, *_ in INCLUDES:
        lines.append(f"{a} ..> {b} : <<include>>")
    for a, b, cond, *_ in EXTENDS:
        lines.append(f"{a} ..> {b} : <<extend>>\\n[{cond}]")
    lines.extend([
        "",
        "note right of A2",
        "  Agent 识别业务目标、流程步骤、顺序、条件、循环与约束；",
        "  信息缺失或存在歧义时发起澄清，并根据反馈修订模型。",
        "end note",
        "note right of C1",
        "  可靠性模型与流程模型分离，仅通过节点标识关联。",
        "  只有参与可靠性计算的节点应用故障率 λ。",
        "end note",
        "note right of D1",
        "  潜在故障可先发生；进入故障检测节点时才被发现，",
        "  随后处理与维修；维修后恢复运行，历史记录保留。",
        "end note",
        "note right of E4",
        "  多台设备共享流程定义，但独立维护状态、故障与历史。",
        "  单台设备故障不会自动中断其他设备。",
        "end note",
        "note right of F5",
        "  理论可靠度由解析计算得到，实际故障统计来自仿真事件；",
        "  两者并列展示并由 Agent 解释差异。",
        "end note",
        "@enduml",
        "",
    ])
    (OUT / "use-case-diagram.puml").write_text("\n".join(lines), encoding="utf-8")


def write_drawio():
    width = 4540
    metrics, lane_heights = build_story_layout()
    height = 330 + sum(lane_heights.values()) + 90
    cells = [
        f'<mxCell id="0"/>',
        f'<mxCell id="1" parent="0"/>',
    ]
    cell_id = 2

    def add_rect(x, y, w, h, style, value=""):
        nonlocal cell_id
        idx = cell_id
        cells.append(
            f'<mxCell id="{idx}" value="{escape(value, quote=True)}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        cell_id += 1

    add_rect(0, 0, width, height, "rounded=0;fillColor=#F7F9FC;strokeColor=none;", "")
    add_rect(330, 200, 440 * 9 + 18 * 8, 108, "rounded=1;arcSize=14;fillColor=none;strokeColor=none;", "")
    for idx, activity in enumerate(ACTIVITIES):
        x = 330 + idx * 458
        add_rect(x, 200, 440, 108, "rounded=1;arcSize=14;fillColor=#132A45;strokeColor=none;fontColor=#FFFFFF;align=left;spacingLeft=18;verticalAlign=middle;fontStyle=1;fontSize=18;",
                 f"{activity['no']}  {activity['name']}\n{activity['outcome']}")
    lane_y = 330
    for release_key in ["MVP", "V1.1", "V1.2"]:
        label, subtitle, accent, lane_fill, description = RELEASES[release_key]
        lane_h = lane_heights[release_key]
        add_rect(50, lane_y, 4440, lane_h, f"rounded=1;arcSize=3;fillColor={lane_fill};strokeColor=#E0E8F1;", "")
        add_rect(76, lane_y + 18, 200, 90, f"rounded=0;fillColor=none;strokeColor=none;fontColor={accent};align=left;verticalAlign=top;fontStyle=1;fontSize=22;",
                 f"{label}  {subtitle}\n" + "\n".join(description))
        for idx, activity in enumerate(ACTIVITIES):
            col_x = 330 + idx * 458
            cards = metrics[(activity["no"], release_key)]
            y = lane_y + 20
            for card in cards:
                value = f"{card['task']}\n\n作为一名{card['role']}，我希望{card['action']}，以便{card['value']}。"
                add_rect(col_x + 9, y, 422, card["height"],
                         f"rounded=1;arcSize=10;fillColor=#FFFFFF;strokeColor=#D7E2EE;fontColor=#243449;align=left;verticalAlign=top;spacing=14;fontSize=12;",
                         value)
                y += card["height"] + 12
        lane_y += lane_h
    model = (
        '<mxfile host="app.diagrams.net" modified="2026-11-20T00:00:00.000Z" agent="opencode" version="24.0.0">'
        f'<diagram id="user-story-map" name="用户故事地图"><mxGraphModel dx="1600" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{width}" pageHeight="{height}" math="0" shadow="0">'
        "<root>" + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>"
    )
    (OUT / "user-story-map.drawio").write_text(model, encoding="utf-8")


def render_png(name):
    edge_candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    browser = next((path for path in edge_candidates if path.exists()), None)
    if browser is None:
        print(f"skip {name}.png: Edge/Chrome not found")
        return
    svg = (OUT / f"{name}.svg").read_text(encoding="utf-8")
    match = re.search(r'width="(\d+)" height="(\d+)"', svg)
    if not match:
        print(f"skip {name}.png: SVG size not found")
        return
    width, height = match.group(1), match.group(2)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;background:#fff;overflow:hidden}svg{display:block}</style>"
        f"</head><body>{svg}</body></html>"
    )
    temp_html = Path(tempfile.gettempdir()) / f"{name}.html"
    temp_html.write_text(html, encoding="utf-8")
    subprocess.run([
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        "--virtual-time-budget=1500",
        f"--screenshot={OUT / f'{name}.png'}",
        temp_html.as_uri(),
    ], check=False, capture_output=True)
    print(f"{name}.png")


def main():
    use_case_svg = build_use_case_svg()
    story_svg = build_story_map_svg()
    (OUT / "use-case-diagram.svg").write_text(use_case_svg, encoding="utf-8")
    (OUT / "user-story-map.svg").write_text(story_svg, encoding="utf-8")
    write_plantuml()
    write_drawio()
    print("use-case-diagram.svg")
    print("user-story-map.svg")
    print("use-case-diagram.puml")
    print("user-story-map.drawio")
    render_png("use-case-diagram")
    render_png("user-story-map")


if __name__ == "__main__":
    main()
