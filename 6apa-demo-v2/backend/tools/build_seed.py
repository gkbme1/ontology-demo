"""生成现象 / 根因影响关系 / 计算组态的种子数据（data/seed/*.json）。

两部分：
1. 6A_水解（S11）标杆：按 6APA_规则.xlsx 的 R-S11-* 与 6APA_处置规程.xlsx 的 ARP-S11-* 手工整理，
   判定规则写成条件树（与 / 或嵌套 + 持续时长），阈值优先引用工艺限值；
2. 其余工段：由处置卡自动生成。报警现象（有限值的给出判定规则）+ 卡片「可能原因」→ 原因现象（判定规则待定义）
   + 导致关系。

全部标「草案·待工艺确认」。没有限值、只能先给占位阈值的，在 note 里写明「占位阈值，待现场提供」。
已存在时不覆盖，--force 才覆盖。运行时编辑在 data/store/，与种子分开。

    python3 -m backend.tools.build_seed [--force]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from backend.ontology.indexes import OntologyStore
from backend.services import process_limits

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"
DRAFT = "草案·待工艺确认"
PLACEHOLDER = "占位阈值，待现场提供"


# ------------------------------------------------------------------ 规则构造小工具
def P(name: str) -> dict[str, Any]:
    return {"kind": "parameter", "name": name}


def T(tag: str) -> dict[str, Any]:
    return {"kind": "tag", "tag": tag}


def C(calc_id: str) -> dict[str, Any]:
    return {"kind": "calc", "calcId": calc_id}


def cond(subject, op, threshold=None, dur=0, agg="any", **extra) -> dict[str, Any]:
    c = {"type": "condition", "subject": subject, "operator": op, "aggregate": agg, "durationSec": dur}
    if threshold is not None:
        c["threshold"] = threshold
    c.update(extra)
    return c


def lim(limit_id: str, field: str) -> dict[str, Any]:
    return {"kind": "limit", "limitId": limit_id, "field": field}


def val(v: float) -> dict[str, Any]:
    return {"kind": "value", "value": v}


def AND(*children) -> dict[str, Any]:
    return {"type": "group", "op": "AND", "children": list(children)}


def OR(*children) -> dict[str, Any]:
    return {"type": "group", "op": "OR", "children": list(children)}


def change(subject, a, b, dur=0) -> dict[str, Any]:
    return {"type": "condition", "subject": subject, "operator": "change", "from": a, "to": b,
            "aggregate": "any", "durationSec": dur}


# ------------------------------------------------------------------ 锚点解析
class Anchors:
    def __init__(self, store: OntologyStore) -> None:
        dcs = store.dcs
        self.groups = {g["name"]: g for g in dcs.equipment_groups.values()}
        self.equipment: dict[str, list[dict[str, Any]]] = {}
        for e in dcs.equipment.values():
            self.equipment.setdefault(e["name"], []).append(e)
        self.tags = {t["name"]: t for t in dcs.tags.values()}
        self.dcs = dcs

    def group(self, name: str) -> dict[str, Any]:
        g = self.groups[name]
        return {"kind": "group", "id": g["id"], "name": g["name"], "areaCode": g.get("areaCode")}

    def equip(self, name: str, area: str | None = None) -> dict[str, Any]:
        cands = self.equipment[name]
        if area:
            cands = [e for e in cands if e.get("areaCode") == area] or cands
        e = cands[0]
        return {"kind": "equipment", "id": e["id"], "name": e["name"], "areaCode": e.get("areaCode")}

    def by_tags(self, tag_names: list[str], fallback_area: str, only_area: bool = False) -> dict[str, Any] | None:
        groups, equips = Counter(), Counter()
        for n in tag_names:
            t = self.tags.get(n)
            if not t or (only_area and t.get("areaCode") != fallback_area):
                continue
            if t.get("equipmentGroupId"):
                groups[t["equipmentGroupId"]] += 1
            elif t.get("equipmentId"):
                equips[t["equipmentId"]] += 1
        if groups and (not equips or groups.most_common(1)[0][1] >= equips.most_common(1)[0][1]):
            g = self.dcs.equipment_groups[groups.most_common(1)[0][0]]
            return {"kind": "group", "id": g["id"], "name": g["name"], "areaCode": g.get("areaCode")}
        if equips:
            e = self.dcs.equipment[equips.most_common(1)[0][0]]
            return {"kind": "equipment", "id": e["id"], "name": e["name"], "areaCode": e.get("areaCode")}
        return None


# ------------------------------------------------------------------ 6A_水解 标杆
def hydrolysis_seed(a: Anchors) -> tuple[list[dict], list[dict], list[dict]]:
    TANK = a.group("水解反应釜组(水解罐A–K)")
    NH3 = a.group("水解氨水计量罐组")
    RB = a.group("RB储罐A/B（水解进料）")
    BUF = a.equip("水解缓冲罐", "S11")
    PUMP = a.equip("水解液泵", "S11")
    PIPE = a.equip("公用测量管线", "S11")

    def ph(pid, name, anchor, category, rule, desc="", basis="", note="", severity="警告"):
        return {"id": pid, "name": name, "anchor": anchor, "category": category, "severity": severity,
                "description": desc, "rule": rule, "note": note, "status": DRAFT,
                "source": {"kind": "规则 / 处置卡", "ref": basis}}

    phen = [
        ph("PH-S11-01", "水解罐温度偏高", TANK, "工艺",
           OR(cond(P("釜内反应温度"), ">", lim("PL001", "normalHigh"), 600),
              cond(P("釜内反应温度"), ">", lim("PL001", "high"))),
           "罐温高于正常上限持续 10 分钟，或超过高限即时成立", "R-S11-01；ARP-S11-01", severity="严重"),
        ph("PH-S11-02", "水解罐温度偏低", TANK, "工艺",
           OR(cond(P("釜内反应温度"), "<", lim("PL001", "normalLow"), 600),
              cond(P("釜内反应温度"), "<", lim("PL001", "low"))),
           "罐温低于正常下限持续 10 分钟，或低于低限即时成立", "ARP-S11-02"),
        ph("PH-S11-03", "水解罐pH偏高", TANK, "工艺",
           OR(cond(P("反应体系pH"), ">", lim("PL002", "normalHigh"), 60, agg="mean"),
              cond(P("反应体系pH"), ">", lim("PL002", "high"))),
           "两支 pH 计均值高于正常上限持续 1 分钟；或任一支超过高限", "R-S11-02；ARP-S11-03"),
        ph("PH-S11-04", "水解罐pH偏低", TANK, "工艺",
           OR(cond(P("反应体系pH"), "<", lim("PL002", "normalLow"), 60, agg="mean"),
              cond(P("反应体系pH"), "<", lim("PL002", "low"))),
           "两支 pH 计均值低于正常下限持续 1 分钟；或任一支低于低限", "R-S11-02；ARP-S11-04"),
        ph("PH-S11-05", "pH双支偏差大", TANK, "仪表",
           cond(C("CALC-S11-01"), ">", val(0.2), 300),
           "同一罐两支 pH 计读数差 > 0.2 持续 5 分钟，提示电极漂移 / 污染", "R-S11-03",
           note="0.2 pH 为规则表推断值，待确认"),
        ph("PH-S11-06", "反应期搅拌停止", TANK, "设备",
           AND(cond(P("搅拌运行状态"), "=", val(0), 120),
               OR(cond(P("氨水进料阀"), "=", val(1)),
                  cond(P("釜内反应液位"), ">", val(2)))),
           "搅拌运行反馈为 0 持续 2 分钟，且罐处于反应期（氨水进料阀开，或罐内有料）",
           "R-S11-07；ARP-S11-07", note="「反应期」暂以氨水进料阀开或液位 > 2 m3 近似；液位阈值为" + PLACEHOLDER,
           severity="严重"),
        ph("PH-S11-07", "搅拌非指令停机", TANK, "设备",
           AND(cond(P("搅拌启停指令"), "=", val(1)), change(P("搅拌运行"), 1, 0)),
           "有启动指令时运行反馈由 1 变 0，多为跳闸或保护动作", "R-G-02"),
        ph("PH-S11-08", "搅拌电机故障", TANK, "设备",
           cond(P("搅拌故障"), "=", val(1)), "搅拌故障信号为 1", "ARP-S11-07 可能原因 1"),
        ph("PH-S11-09", "搅拌处于就地状态", TANK, "操作",
           cond(P("搅拌远程"), "=", val(0), 60), "远程信号为 0 持续 1 分钟，DCS 指令无效", "ARP-S11-07 可能原因 2"),
        ph("PH-S11-10", "加氨速率偏高", NH3, "工艺",
           cond(C("CALC-S11-02"), ">", val(10), 600),
           "氨水计量罐液位下降速率（液位差法）> 10 L/min 持续 10 分钟", "ARP-S11-03 可能原因 2",
           note="10 L/min 为" + PLACEHOLDER),
        ph("PH-S11-11", "加氨无响应", TANK, "工艺",
           AND(cond(P("氨水进料阀"), "=", val(1), 300),
               cond(P("反应体系pH"), "<", lim("PL002", "normalLow"), 300, agg="mean")),
           "氨水进料阀开着 5 分钟，pH 仍低于正常下限", "R-S11-04；ARP-S11-04",
           note="规则原文还要求「计量罐液位 5 min 内无下降」，计量罐是另一台设备，此处暂未纳入"),
        ph("PH-S11-12", "氨水进料阀指令与反馈不一致", TANK, "设备",
           OR(AND(cond(P("氨水进料阀指令"), "=", val(1)), cond(P("氨水进料阀"), "=", val(0), 30)),
              AND(cond(P("氨水进料阀指令"), "=", val(0)), cond(P("氨水进料阀"), "=", val(1), 30))),
           "指令开而反馈关、或指令关而反馈开，持续 30 秒", "ARP-S11-03 / 04 可能原因 3"),
        ph("PH-S11-13", "热水阀关不小", TANK, "设备",
           AND(cond(P("热水阀"), "=", val(1), 300), cond(P("釜内反应温度"), ">", lim("PL001", "normalHigh"))),
           "罐温已高于正常上限，热水阀仍全开 5 分钟", "ARP-S11-01 可能原因 4"),
        ph("PH-S11-14", "RB进料温度偏高", PIPE, "物料",
           AND(cond(T("TI_1303"), ">", lim("PL042", "normalHigh"), 120), cond(T("FT_1302A"), ">", val(0))),
           "RB 进料温度高于 35 ℃ 持续 2 分钟，且正在进料", "R-S11-10；ARP-S11-05"),
        ph("PH-S11-15", "RB储罐液位低", RB, "物料",
           cond(P("RB储罐液位"), "<", val(5), 120), "RB 储罐液位低于 5 m3 持续 2 分钟", "ARP-S11-06 可能原因 1",
           note="5 m3 为" + PLACEHOLDER),
        ph("PH-S11-16", "RB进料量异常", TANK, "工艺", None,
           "进料流量与设定不符；PL011 尚无数值，判定规则待定义", "ARP-S11-06"),
        ph("PH-S11-17", "水解液缓冲罐高位", BUF, "工艺",
           cond(P("水解液缓冲罐液位"), ">", val(25), 60),
           "水解液缓冲罐液位 > 25 m3 持续 1 分钟", "R-S11-08；ARP-S11-10", note="PL043 无数值，25 m3 为" + PLACEHOLDER),
        ph("PH-S11-18", "下游萃取不接收", BUF, "工艺",
           AND(cond(C("CALC-S11-03"), ">", val(0.02), 1200), cond(P("水解液缓冲罐液位"), ">", val(15))),
           "缓冲罐液位持续上涨 20 分钟（上升速率 > 0.02 m3/min），且液位已 > 15 m3", "ARP-S11-10 可能原因 1",
           note="速率与液位阈值为" + PLACEHOLDER),
        ph("PH-S11-19", "泵/电机非指令停机（水解液泵）", PUMP, "设备",
           OR(AND(cond(P("a启停指令"), "=", val(1)), change(P("a运行"), 1, 0)),
              AND(cond(P("b启停指令"), "=", val(1)), change(P("b运行"), 1, 0))),
           "a 泵或 b 泵：有启动指令时运行反馈由 1 变 0", "R-G-02"),
        ph("PH-S11-20", "压缩空气压力不足", PIPE, "公用工程",
           cond(T("PT_1301"), "<", val(0.45), 60), "压缩空气总管压力 < 0.45 MPa 持续 1 分钟", "R-S11-09；ARP-S11-09",
           note="取自 ARP-S06-01 仪表气 0.45 MPa 报警值；PL044 尚无数值"),
        ph("PH-S11-21", "水解罐出料缓慢", TANK, "工艺", None, "出料时间超过常规；判定规则待定义", "ARP-S11-09"),
        ph("PH-S11-22", "固定化酶活力下降", TANK, "物料", None,
           "酶活无法在线检测：一般 1000 批次以上需换酶；调 pH 后检测计算值仍 > 5000 也需换酶。判定规则待定义",
           "ARP-S11-08 可能原因 1；调研 BF-09"),
        ph("PH-S11-23", "水解终点异常 / 氨耗偏低", TANK, "工艺", None,
           "批次结束时氨水累计加量 < 理论氨耗 × 下限系数；需 RB 投料量，判定规则待定义", "R-S11-06；ARP-S11-08",
           severity="严重"),
    ]

    def link(lid, cause, effect, mech, basis, conf="中"):
        return {"id": lid, "cause": cause, "effect": effect, "mechanism": mech, "basis": basis,
                "confidence": conf, "status": DRAFT, "source": {"kind": "规则 / 处置卡", "ref": basis}}

    links = [
        link("CL-S11-01", "PH-S11-07", "PH-S11-06", "运行中跳闸或保护动作导致搅拌停止", "R-G-02；ARP-S11-07", "高"),
        link("CL-S11-02", "PH-S11-08", "PH-S11-06", "电机故障或过载保护动作", "ARP-S11-07 可能原因 1", "高"),
        link("CL-S11-03", "PH-S11-09", "PH-S11-06", "处于就地状态，DCS 启动指令无效", "ARP-S11-07 可能原因 2"),
        link("CL-S11-04", "PH-S11-06", "PH-S11-01", "搅拌停止导致罐内温度分布不均，局部超温", "ARP-S11-01 可能原因 6"),
        link("CL-S11-05", "PH-S11-06", "PH-S11-23", "反应期搅拌停机，固液传质变差，转化不足", "ARP-S11-08 可能原因 4"),
        link("CL-S11-06", "PH-S11-13", "PH-S11-01", "热水持续进入夹套", "ARP-S11-01 可能原因 4", "高"),
        link("CL-S11-07", "PH-S11-14", "PH-S11-01", "高温 RB 进料带入热量，早于罐温上升", "R-S11-10；ARP-S11-01 可能原因 5"),
        link("CL-S11-08", "PH-S11-01", "PH-S11-22", "反应超温（>35 ℃）导致酰化酶蛋白热变性失活", "工业关系表；PL001 依据", "高"),
        link("CL-S11-09", "PH-S11-10", "PH-S11-03", "加氨过量使体系 pH 升高", "ARP-S11-03 可能原因 2"),
        link("CL-S11-10", "PH-S11-05", "PH-S11-03", "电极漂移造成 pH 读数偏高（测量偏差而非工艺偏离）", "R-S11-03；ARP-S11-03 可能原因 1"),
        link("CL-S11-11", "PH-S11-05", "PH-S11-04", "电极漂移造成 pH 读数偏低（测量偏差而非工艺偏离）", "R-S11-03；ARP-S11-04 可能原因 1"),
        link("CL-S11-12", "PH-S11-12", "PH-S11-11", "阀门未按指令动作，氨水实际未加入", "ARP-S11-04 可能原因 3", "高"),
        link("CL-S11-13", "PH-S11-11", "PH-S11-04", "加氨不足无法中和反应产生的苯乙酸", "R-S11-04；ARP-S11-04 可能原因 2", "高"),
        link("CL-S11-14", "PH-S11-03", "PH-S11-23", "pH 偏离最适区间，酶活降低、6-APA 降解加剧", "ARP-S11-08 可能原因 2"),
        link("CL-S11-15", "PH-S11-04", "PH-S11-23", "偏酸降低酶活", "ARP-S11-08 可能原因 2"),
        link("CL-S11-16", "PH-S11-01", "PH-S11-23", "超温加速 6-APA 母环开环水解", "ARP-S11-08 可能原因 2"),
        link("CL-S11-17", "PH-S11-02", "PH-S11-23", "温度低反应速率慢，转化不足", "ARP-S11-08 可能原因 2"),
        link("CL-S11-18", "PH-S11-22", "PH-S11-23", "酶活下降导致氨耗偏低、终点异常", "ARP-S11-08 可能原因 1", "高"),
        link("CL-S11-19", "PH-S11-15", "PH-S11-16", "RB 储罐供料不足", "ARP-S11-06 可能原因 1"),
        link("CL-S11-20", "PH-S11-16", "PH-S11-23", "RB 实际投料量与设定不符，终点判定偏差", "ARP-S11-08 可能原因 3", "低"),
        link("CL-S11-21", "PH-S11-20", "PH-S11-21", "压料气源压力不足，多罐出料同时偏慢", "ARP-S11-09 可能原因 1", "高"),
        link("CL-S11-22", "PH-S11-18", "PH-S11-17", "萃取不接收，缓冲罐液位持续上升", "ARP-S11-10 可能原因 1", "高"),
        link("CL-S11-23", "PH-S11-19", "PH-S11-17", "水解液泵停机，缓冲罐无法外送", "R-G-02；水解液缓冲罐拓扑"),
        link("CL-S11-24", "PH-S11-17", "PH-S11-21", "缓冲罐高位时水解罐无法正常出料", "水解液缓冲罐拓扑", "低"),
    ]

    calcs = [
        {"id": "CALC-S11-01", "name": "pH双支偏差", "anchor": TANK, "method": "formula",
         "expression": "abs(a - b)",
         "inputs": [{"var": "a", "subject": {"kind": "parameter", "name": "反应体系pH", "index": 0}},
                    {"var": "b", "subject": {"kind": "parameter", "name": "反应体系pH", "index": 1}}],
         "unit": "pH", "description": "同一罐两支 pH 计（AT_1301x1 / x2）读数差的绝对值", "basis": "R-S11-03", "status": DRAFT},
        {"id": "CALC-S11-02", "name": "加氨速率（液位差法）", "anchor": NH3, "method": "level_consumption",
         "inputs": [{"var": "level", "subject": {"kind": "parameter", "name": "氨水计量罐液位"}}],
         "params": {"windowMin": 10, "deadbandRatio": 0.01}, "unit": "L/min",
         "description": "计量罐液位只累计下降量（上升视为补液），按滑动时间窗折算速率；方法复制自 Agent Demo 的液位差消耗量",
         "basis": "R-S11-04 / R-S11-05；关系「计量罐液位下降量即加氨量」", "status": DRAFT},
        {"id": "CALC-S11-03", "name": "缓冲罐液位上升速率", "anchor": BUF, "method": "rate",
         "inputs": [{"var": "level", "subject": {"kind": "parameter", "name": "水解液缓冲罐液位"}}],
         "params": {"windowMin": 10}, "unit": "m3/min",
         "description": "水解液缓冲罐液位在滑动时间窗内的平均变化速率（正为上涨）", "basis": "ARP-S11-10", "status": DRAFT},
        {"id": "CALC-S11-04", "name": "水解罐平均温度", "anchor": TANK, "method": "formula",
         "expression": "mean(t)",
         "inputs": [{"var": "t", "subject": {"kind": "parameter", "name": "釜内反应温度"}}],
         "unit": "℃", "description": "本台全部温度测点的均值（指标示例）", "basis": "PL001", "status": DRAFT},
    ]
    return phen, links, calcs


# ------------------------------------------------------------------ 其余工段：处置卡自动生成
LEVEL_FIELDS = {"H": "high", "HH": "highHigh", "L": "low", "LL": "lowLow"}
# 导航树里有的工段（与 data/config/6APA_空间层级.xlsx 一致）
INCLUDED_AREAS = {f"S{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16)}
_CODE_RE = re.compile(r"（R-[A-Z0-9-]+）")


def cards_seed(a: Anchors, limits: dict[str, dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    wb = load_workbook(ROOT / "data" / "source" / "6APA_处置规程.xlsx", read_only=True, data_only=True)
    head, *rows = list(wb["处置卡"].iter_rows(values_only=True))
    cards = [dict(zip(head, r)) for r in rows if r[0]]
    head, *rows = list(wb["可能原因"].iter_rows(values_only=True))
    causes = [dict(zip(head, r)) for r in rows if r[0]]

    phen: list[dict] = []
    links: list[dict] = []
    by_key: dict[tuple[str, str], str] = {}
    n_ph = n_link = 0
    for card in cards:
        cid = card["卡片编号"]
        area = card.get("所属工段") or ""
        if area == "S11":  # 标杆工段已手工整理
            continue
        tags = [t.strip() for t in re.split(r"[、,，]", card.get("触发位号") or "") if t.strip()]
        anchor = a.by_tags(tags, area)
        if not anchor or anchor.get("areaCode") not in INCLUDED_AREAS:
            continue
        name = card["卡片名称"]
        level = (card.get("报警级别") or "").upper()
        lid = card.get("关联限值")
        limit = limits.get(lid or "")
        rule = None
        note = ""
        trigger = card.get("触发对象") or ""
        if limit and level:
            first = level.split("/")[0]
            field = LEVEL_FIELDS.get(first)
            op = ">" if first.startswith("H") else "<"
            if field and limit.get(field) is not None:
                # 触发对象是工艺属性名且锚点是设备组时按属性写（组内每台各自判定），否则按位号写
                if anchor["kind"] == "group" and trigger and trigger not in a.groups:
                    rule = cond(P(trigger), op, lim(lid, field))
                else:
                    subs = [cond(T(t), op, lim(lid, field)) for t in tags[:8]]
                    rule = subs[0] if len(subs) == 1 else OR(*subs)
        if rule is None:
            note = "处置卡未给出可用的限值，判定规则待定义"
        n_ph += 1
        effect_id = f"PH-A{n_ph:03d}"
        phen.append({"id": effect_id, "name": name, "anchor": anchor, "category": "工艺", "severity": "警告",
                     "description": card.get("报警现象·DCS") or "", "rule": rule, "note": note, "status": DRAFT,
                     "source": {"kind": "处置卡", "ref": cid}})
        by_key[(anchor["id"], name)] = effect_id
        for cause in [c for c in causes if c["卡片编号"] == cid]:
            raw = _CODE_RE.sub("", cause.get("原因描述") or "").strip()
            # 括号里的解释放进描述，名称只留短语
            m = re.match(r"^(.+?)（(.+)）$", raw)
            cname, explain = (m.group(1).strip(), m.group(2).strip()) if m else (raw, "")
            if explain in ("-", "+"):
                explain = ""
            if not cname:
                continue
            key = (anchor["id"], cname)
            if key not in by_key:
                n_ph += 1
                by_key[key] = f"PH-A{n_ph:03d}"
                desc = "；".join(x for x in [explain, cause.get("验证方法"), cause.get("判据") and f"判据：{cause['判据']}"] if x)
                phen.append({"id": by_key[key], "name": cname, "anchor": anchor,
                             "category": cause.get("原因类别") if cause.get("原因类别") in
                             ("工艺", "设备", "仪表", "操作", "物料", "公用工程") else "工艺",
                             "severity": "提示", "description": desc, "rule": None,
                             "note": "由处置卡「可能原因」生成，判定规则待定义", "status": DRAFT,
                             "source": {"kind": "处置卡·可能原因", "ref": f"{cid} #{cause.get('序号')}"}})
            n_link += 1
            links.append({"id": f"CL-A{n_link:03d}", "cause": by_key[key], "effect": effect_id,
                          "mechanism": cause.get("判据") or "", "basis": cause.get("依据") or "",
                          "confidence": "中" if cause.get("原因类别") == "工艺" else "低", "status": DRAFT,
                          "source": {"kind": "处置卡·可能原因", "ref": f"{cid} #{cause.get('序号')}"}})
    return phen, links


# ------------------------------------------------------------------ 工况现象（被参数约束引用）
S11_TANK_MODES = ("进料过程", "水解反应期", "出料过程", "中和过程")


def limit_area_code(dcs: Any, limit: dict[str, Any]) -> str | None:
    """限值表的工段名与点表写法不一致（全角括号、大小写），按点表的归一化方式查。"""
    name = (limit.get("area") or "").strip().lower().replace("（", "(").replace("）", ")")
    aid = dcs.area_by_name.get(name)
    return aid[5:] if aid else None


def ctx_(name: str) -> dict[str, Any]:
    return {"kind": "context", "name": name}


def _range_text(lo: Any, hi: Any) -> str:
    lo_t = int(lo) if lo is not None else 0
    hi_t = "∞" if hi is None else int(hi)
    return f"换酶后第 {lo_t}～{hi_t} 批"


def condition_seed(a: Anchors, store: OntologyStore, limits: dict[str, dict[str, Any]]) -> list[dict]:
    """限值的「适用工况」与限值版本的「换酶后批次区间」都定义成类别为「工况」的现象。

    - conditionKey：mode:<工段>:<工况> / batch:<工段>:<下限>-<上限>，参数约束据此引用；
    - S11 的 进料过程 / 水解反应期 / 出料过程 按 6APA_工序与阶段.xlsx 的 DCS 识别条件写判定规则，
      换酶后批次区间按 EBR 运行上下文写规则；其余工况先只登记，判定规则待定义。
    """
    from backend.services import limit_versions

    dcs = store.dcs
    tank = a.group("水解反应釜组(水解罐A–K)")
    s11_rules = {
        "进料过程": (cond(P("RB进料阀"), "=", val(1)), "阶段「进料」：RB 进料阀开（XV_1302x_VAL2 = 1）"),
        "水解反应期": (OR(AND(cond(P("搅拌运行"), "=", val(1)), cond(P("氨水进料阀"), "=", val(1))),
                         AND(cond(P("搅拌运行"), "=", val(1)), cond(P("氨水进料阀"), "=", val(0)))),
                      "阶段「反应」或「终点判定」：搅拌运行，氨水进料阀开（滴加氨水）或已关（氨耗趋零）"),
        "出料过程": (cond(P("出料流量检测"), "=", val(1)), "阶段「出料」：出料流量检测有信号（XV_1308x_FT = 1）"),
    }
    out: list[dict] = []
    seen: dict[str, dict] = {}
    n = 0

    def area_code(limit: dict[str, Any]) -> str | None:
        return limit_area_code(dcs, limit)

    def anchor_for(limit: dict[str, Any], code: str) -> dict[str, Any] | None:
        if code == "S11" and (limit.get("operatingMode") in S11_TANK_MODES or limit.get("appliesTo") in (
                "釜内反应温度", "反应体系pH", "釜内反应液位", "搅拌运行状态", "RB进料流量", "硼酸进料流量")):
            return tank
        try:
            tags, _ = __import__("backend.services.process_limits", fromlist=["x"]).resolve_targets(store, limit)
        except Exception:  # noqa: BLE001
            return None
        return a.by_tags([t["name"] for t in tags], code, only_area=True)

    for lid, limit in sorted(limits.items()):
        code = area_code(limit)
        if code not in INCLUDED_AREAS:
            continue
        mode = (limit.get("operatingMode") or "").strip()
        if mode:
            key = f"mode:{code}:{mode}"
            if key in seen:
                seen[key]["source"]["ref"] += f"、{lid}"
            else:
                anchor = anchor_for(limit, code)
                if anchor:
                    n += 1
                    rule, desc = s11_rules.get(mode, (None, "")) if code == "S11" else (None, "")
                    seen[key] = {
                        "id": f"PH-W{n:03d}", "name": f"工况·{mode}", "anchor": anchor, "category": "工况", "severity": "提示",
                        "conditionKey": key,
                        "description": desc or f"{limit.get('area')} 处于「{mode}」工况",
                        "rule": rule, "status": DRAFT,
                        "note": "按 6APA_工序与阶段.xlsx 的 DCS 识别条件" if rule else "工况识别条件待定义",
                        "source": {"kind": "工艺限值·适用工况", "ref": lid},
                    }
                    out.append(seen[key])
        for v in limit_versions.versions(store, lid)["items"]:
            lo, hi = v.get("enzymeMin"), v.get("enzymeMax")
            if lo is None and hi is None:
                continue
            key = f"batch:{code}:{int(lo) if lo is not None else 0}-{'' if hi is None else int(hi)}"
            if key in seen:
                if lid not in seen[key]["source"]["ref"]:
                    seen[key]["source"]["ref"] += f"、{lid}"
                continue
            anchor = anchor_for(limit, code)
            if not anchor:
                continue
            n += 1
            parts = [cond(ctx_("换酶后批次数"), ">=", val(lo if lo is not None else 0))]
            if hi is not None:
                parts.append(cond(ctx_("换酶后批次数"), "<=", val(hi)))
            seen[key] = {
                "id": f"PH-W{n:03d}", "name": _range_text(lo, hi), "anchor": anchor, "category": "工况", "severity": "提示",
                "conditionKey": key, "description": "本罐自上次换酶以来的批次数在此区间（来自 EBR 换酶记录）",
                "rule": parts[0] if len(parts) == 1 else AND(*parts), "status": DRAFT,
                "note": "运行上下文取自 EBR，本 Demo 未接入，试算显示无法判定",
                "source": {"kind": "限值版本·适用条件", "ref": lid},
            }
            out.append(seen[key])
    return out


def build(force: bool = False) -> None:
    targets = {k: SEED_DIR / f"{k}.json" for k in ("phenomena", "causal_links", "calculations")}
    if all(p.exists() for p in targets.values()) and not force:
        print(f"已存在，未覆盖：{SEED_DIR}（--force 覆盖）")
        return
    store = OntologyStore()
    anchors = Anchors(store)
    limits = {l["id"]: l for l in process_limits._load()}
    p1, l1, calcs = hydrolysis_seed(anchors)
    p2, l2 = cards_seed(anchors, limits)
    p2 += condition_seed(anchors, store, limits)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    note = "种子数据：由 backend/tools/build_seed.py 生成，全部为草案·待工艺确认"
    for key, items in (("phenomena", p1 + p2), ("causal_links", l1 + l2), ("calculations", calcs)):
        targets[key].write_text(json.dumps({"note": note, "items": items}, ensure_ascii=False, indent=1), "utf-8")
    print(f"现象 {len(p1)}+{len(p2)}，根因关系 {len(l1)}+{len(l2)}，计算组态 {len(calcs)} → {SEED_DIR}")


if __name__ == "__main__":
    build(force="--force" in sys.argv)
