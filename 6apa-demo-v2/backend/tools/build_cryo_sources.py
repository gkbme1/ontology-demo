"""由北I-2 深冷本体梳理结果生成 Demo 的数据源（与原 6APA 数据源同结构，加载代码不用改）。

    python3 -m backend.tools.build_cryo_sources            # 写 data/source/*.xlsx、data/config/*.xlsx

口径：画面与点表为准；操作规程是旧版，只在画面 / 点表没有的内容上作参考（限值数值、处置步骤），
这些条目一律标「草案·待工艺确认」，依据写「规程（旧版）」。
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

from . import cryo_knowledge as K
from .build_cryo_ontology import (UNIT_OF_CODE, Matcher, bind_points, build_limits, build_valves, doc_tables,
                                  load_points, parse_procedures)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "source"
CFG = ROOT / "data" / "config"
DRAFT = K.DRAFT
OLD_SOP = "北I-2装置操作规程（旧版）"

# 工段（= 一张或一组流程画面）：编号, 名称, 英文, 单元, 画面编号
AREAS = [
    ("S01", "集配气单元", "Gathering", "U01", ["SC-01"]),
    ("S02", "压缩单元", "Compression", "U02", ["SC-02"]),
    ("S03", "脱水单元", "Dehydration", "U03", ["SC-03"]),
    ("S04", "三甘醇", "TEG", "U03", ["SC-04"]),
    ("S05", "三甘醇尾气回收撬", "TEGVent", "U03", ["SC-05"]),
    ("S06", "导热油炉", "HotOil", "U03", ["SC-06"]),
    ("S07", "冷冻单元", "Cryogenic", "U04", ["SC-07"]),
    ("S08", "膨胀机", "Expander", "U04", ["SC-08", "SC-09"]),
    ("S10", "丙烷机", "Propane", "U04", ["SC-10"]),
    ("S11", "储运单元", "Storage", "U05", ["SC-11"]),
    ("S12", "火炬单元", "Flare", "U06", ["SC-12"]),
    ("S13", "空氮站", "AirNitrogen", "U06", ["SC-13"]),
    ("S14", "锅炉单元", "Boiler", "U06", ["SC-14"]),
    ("S15", "循环水厂", "CoolingWater", "U06", ["SC-15"]),
    ("S16", "ESD", "ESD", "U06", []),
    ("S17", "可燃气体报警器", "GDS", "U06", []),
    ("S18", "APC控制", "APC", "U04", []),
    ("S99", "系统与未归属点", "System", None, []),
]
AREA_NAME = {a[0]: a[1] for a in AREAS}
SCREEN_AREA = {sc: a[0] for a in AREAS for sc in a[4]}
UNIT_DEFAULT_AREA = {"101": "S01", "102": "S02", "103": "S03", "104": "S07", "105": "S11", "106": "S12",
                     "108": "S13", "110": "S15", "112": "S15", "TEG": "S04", "SGC": "S05", "DRY": "S06",
                     "BLR": "S14", "FLR": "S12", "ENV": "S99", "SYS": "S99", "ESD": "S16", "APC": "S18"}
SPECIAL_AREA = {"SYS-ESD": "S16", "SYS-GDS": "S17", "SYS-APC": "S18", "SYS-RTO": "S18", "SYS-DCS": "S99", "ENV": "S99",
                "F10305": "S03"}
# 工序（= 画面）：编号, 单元, 名称, 顺序, 画面, 工段编号, 设备匹配(正则), 子工序
OPS = [
    ("OP-01", "U01", "集配气单元", 1, "集配气单元", "S01", "", "进站汇管、除油、除尘、计量、界区排污、燃料气、干气外输、返输气、轻烃外输"),
    ("OP-02", "U02", "压缩单元", 1, "压缩单元", "S02", "", "入口分离、三级压缩、级间空冷与分离、重烃收集、压缩机水站、干气密封回收"),
    ("OP-03", "U03", "脱水单元", 1, "脱水单元", "S03", "", "过滤分离、分子筛吸附、降压再生（降压—热吹—冷吹—升压—并行）、干气过滤"),
    ("OP-04", "U03", "三甘醇", 2, "三甘醇", "S04", "", "冬季再生气深度脱水、甘醇再生"),
    ("OP-05", "U03", "三甘醇尾气回收撬", 3, "三甘醇尾气回收撬", "S05", "", "尾气冷凝、分离、射流回收"),
    ("OP-06", "U03", "导热油炉", 4, "导热油炉", "S06", "", "导热油加热、循环、膨胀与储油"),
    ("OP-07", "U04", "冷冻单元", 1, "冷冻单元", "S07", "", "冷箱Ⅰ/Ⅱ换热、丙烷预冷、低温分离、膨胀制冷、脱甲烷塔、甲醇注入"),
    ("OP-08", "U04", "1号膨胀机", 2, "1号膨胀机", "S08", "^1#", "膨胀端、增压端、润滑油、密封气、防喘振、喷嘴"),
    ("OP-09", "U04", "2号膨胀机", 3, "2号膨胀机", "S08", "^2#", "膨胀端、增压端、润滑油、密封气、防喘振、喷嘴"),
    ("OP-10", "U04", "丙烷机", 4, "丙烷机", "S10", "", "螺杆压缩、油分、冷凝、经济器、蒸发器"),
    ("OP-11", "U04", "APC控制", 5, "APC控制", "S18", "", "APC 控制器 K1、RTO 优化与 CO2 冻堵预测"),
    ("OP-12", "U05", "储运单元", 1, "储运单元", "S11", "", "轻烃储存、重烃储存与切水、二次闪蒸、外输、污水 / 污油外排、罐区甲醇"),
    ("OP-13", "U06", "火炬单元", 1, "火炬单元", "S12", "", "冷 / 暖放空分液、压力排污、阻火、点火"),
    ("OP-14", "U06", "空氮站", 2, "空氮站", "S13", "", "空压、干燥、净化风储存、变压吸附制氮"),
    ("OP-15", "U06", "锅炉单元", 3, "锅炉单元", "S14", "", "热水锅炉、蒸汽锅炉、软化水、循环 / 补水 / 上水"),
    ("OP-16", "U06", "循环水厂", 4, "循环水厂", "S15", "", "凉水塔、循环水泵、消防水、清水"),
    ("OP-17", "U06", "ESD", 5, "ESD", "S16", "", "全厂紧急停车、压缩机 / 膨胀机 / 丙烷机 / 导热油炉停机、紧急切断阀"),
    ("OP-18", "U06", "可燃气体报警器", 6, "可燃气体报警器", "S17", "", "可燃气体探测器、声光报警、联锁"),
]
INCLUDE_ROLES = {"测量", "测量（通讯）", "阀位反馈", "变频反馈", "控制输出", "变频输出", "手操输出", "控制回路", "设备控制块",
                 "报警开关", "阀位开关反馈", "就地操作", "设备报警", "运行状态", "控制命令", "流量计算", "计算量",
                 "状态 / 报警（通讯）", "ESD / 通讯开关量"}
PTYPE = {"测量": "过程测量(PV)", "测量（通讯）": "过程测量(PV)", "计算量": "过程测量(PV)", "流量计算": "过程测量(PV)",
         "阀位反馈": "过程测量(PV)", "变频反馈": "过程测量(PV)", "控制输出": "控制输出(OP)", "变频输出": "控制输出(OP)",
         "手操输出": "控制输出(OP)", "控制回路": "控制输出(OP)", "控制命令": "开关控制(DO)"}
VARCAT = {"阀位反馈": "调节阀开度反馈", "变频反馈": "频率反馈", "控制输出": "调节阀开度指令", "变频输出": "变频频率给定",
          "手操输出": "调节阀开度指令", "控制回路": "PID回路", "报警开关": "故障/报警状态", "设备报警": "故障/报警状态",
          "阀位开关反馈": "阀位开关反馈", "运行状态": "运行状态反馈", "就地操作": "远程/就地状态", "控制命令": "启停/开关指令",
          "状态 / 报警（通讯）": "故障/报警状态", "ESD / 通讯开关量": "ESD信号"}


def ptype(p) -> str:
    r = p["role"]
    if r == "设备控制块":
        return "阀门控制(VAL)" if p["block"] == "VAL2" else "电机控制(MOT)"
    return PTYPE.get(r, "状态反馈(DI)")


def varcat(p) -> str:
    r = p["role"]
    if r == "设备控制块":
        return "开关阀控制块" if p["block"] == "VAL2" else "电动阀控制块"
    if r in VARCAT:
        return VARCAT[r]
    return p["qty"] or "其他模拟量"


def wb_sheet(wb, title, header, rows, pre=()):
    ws = wb.create_sheet(title)
    for line in pre:
        ws.append(list(line))
    ws.append(header)
    hr = ws.max_row
    for c in ws[hr]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = ws.cell(hr + 1, 1)
    for j, h in enumerate(header, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = min(max(len(str(h)) + 4, 12), 40)
    return ws


def new_wb():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    return wb


# ------------------------------------------------------------------------------------------
class Model:
    """把本体梳理结果整理成 Demo 的对象：设备（含阀门、公共测点）、设备组、位号。"""

    def __init__(self):
        pts, _ = load_points()
        self.valves = build_valves(pts)
        self.matcher = Matcher(K.EQUIPMENT, self.valves)
        bind_points(pts, self.matcher, self.valves)
        self.pts = pts
        self.doc, self.tables = doc_tables()
        self.limits_raw, self.mapping = build_limits(self.tables, pts, self.matcher)
        self.unit_name = {u[0]: u[1] for u in K.UNITS}
        groups = {g[0]: g for g in K.GROUPS}
        # 设备
        self.equip: dict[str, dict] = {}
        for e in K.EQUIPMENT:
            sc = (e["screen"] or "").split("/")[0]
            area = SPECIAL_AREA.get(e["id"]) or SCREEN_AREA.get(sc) or ("S01" if e["id"].startswith("BALL") else "S99")
            name = e["name"].replace("（组级测点）", "·公共测点").replace("（撬级测点）", "·公共测点")
            self.equip[e["id"]] = dict(id=e["id"], name=name, cls=e["cls"], group=e["group"], area=area, sop=e["sop_id"],
                                       spec=e["spec"], note=e["note"], kind="设备", pseudo=e["id"] == e["group"] or "公共测点" in name)
        for v in self.valves:
            host = v.get("host")
            area = self.equip[host]["area"] if host in self.equip else UNIT_DEFAULT_AREA.get(v["unit_code"], "S99")
            self.equip[v["id"]] = dict(id=v["id"], name=v["name"], cls=v["cls"], group=f"G-V-{area}", area=area, sop="",
                                       spec="", note=v["basis"], kind="阀门", pseudo=False, host=host)
        # 设备组：画面所在工段；系统组不建组
        self.groups: dict[str, dict] = {}
        for gid, name, cls, unit, screen, desc in K.GROUPS:
            if not screen:
                continue
            self.groups[gid] = dict(id=gid, name=name, cls=cls, area=SCREEN_AREA[screen.split("/")[0]], desc=desc)
        for a in {e["area"] for e in self.equip.values() if e["kind"] == "阀门"}:
            self.groups[f"G-V-{a}"] = dict(id=f"G-V-{a}", name=f"{AREA_NAME[a]}阀门", cls="阀门", area=a,
                                            desc=f"{AREA_NAME[a]}画面上的调节阀、程控阀、电动阀、切断阀")
        for e in self.equip.values():
            g = self.groups.get(e["group"] or "")
            if not g or g["area"] != e["area"]:
                e["group"] = None
        # 名称唯一性
        dup = [n for n, c in Counter(e["name"] for e in self.equip.values()).items() if c > 1]
        assert not dup, f"设备名称重复：{dup}"
        # 位号
        self.tags = [p for p in pts if not p["spare"] and p["role"] in INCLUDE_ROLES]
        # REAL 计算量里有与 AI 测点同描述的副本（如 105PT104M1「1#重烃储罐压力」，量程是默认 0～100），不进 Demo，避免一个参数混入假量程
        ai_desc = {(p["eq"], p["desc"]) for p in self.tags if p["block"] in ("AI", "REALM")}
        self.tags = [p for p in self.tags if not (p["role"] == "计算量" and p["block"] in ("REAL", "AM") and (p["eq"], p["desc"]) in ai_desc)]
        st = defaultdict(Counter)
        for p in self.tags:
            if p["eq"] in self.equip:
                st[p["eq"]][str(p["station"] or "10")] += 1
        for e in self.equip.values():
            e["station"] = st[e["id"]].most_common(1)[0][0] if st[e["id"]] else "10"
            e["owl"] = f":Dev_{e['station']}_{e['name']}"
        self.tag_names = {p["tag"] for p in self.tags}

    def area_of_tag(self, p):
        e = self.equip.get(p["eq"] or "")
        return e["area"] if e else "S99"

    def name_of(self, oid):
        if oid in self.equip:
            return self.equip[oid]["name"]
        if oid in self.groups:
            return self.groups[oid]["name"]
        m = next((m for m in K.MATERIALS if m[0] == oid), None)
        if m:
            return m[1]
        if oid == K.PLANT["id"]:
            return K.PLANT["name"]
        return oid


# ------------------------------------------------------------------------------------------ DCS
def write_dcs(M: Model):
    wb = new_wb()
    schema = [("核心类 (Class)", ":ProductionArea", "工段（一张或一组 DCS 流程画面）", "owl:Thing", "-", ":Area_S07_Cryogenic a :ProductionArea"),
              ("核心类 (Class)", ":ProductionEquipment", "设备 / 阀门 / 管线", "owl:Thing", "-", ":Dev_10_脱甲烷塔 a :ProductionEquipment"),
              ("核心类 (Class)", ":DCSTag", "DCS 位号（和利时 MACS 点名）", "owl:Thing", "-", "104TT115 a :DCSTag"),
              ("对象属性", ":hasTag", "设备具有测点", ":ProductionEquipment", ":DCSTag", ":Dev_10_脱甲烷塔 :hasTag 104TT115")]
    wb_sheet(wb, "本体架构与设计规范(Schema)", ["本体建模要素", "本体概念 / 属性名 (URI / ID)", "中文语义说明", "所属域 (Domain)", "值域 (Range)", "应用示例与三元组映射"],
             schema, pre=[("北I-2 深冷装置本体：点表 → 本体映射规范",), ("位号以和利时 DCS 点表为准；设备编号以 DCS 流程画面为准",), ()])
    # 工段间物料衔接
    links = defaultdict(set)
    for a, pred, b, med, basis in K.FLOWS:
        ea, eb = M.equip.get(a) or M.groups.get(a), M.equip.get(b) or M.groups.get(b)
        if ea and eb and ea["area"] != eb["area"]:
            links[(ea["area"], eb["area"])].add(med)
    tag_count = Counter(M.area_of_tag(p) for p in M.tags)
    area_rows = []
    for code, name, en, unit, screens in AREAS:
        up = "；".join(f"{a}({'、'.join(sorted(m))})" for (a, b), m in sorted(links.items()) if b == code)
        down = "；".join(f"{b}({'、'.join(sorted(m))})" for (a, b), m in sorted(links.items()) if a == code)
        area_rows.append((code, name, en, f":Area_{code}_{en}", "、".join(name for s in screens for x in K.SCREENS if x[0] == s for name in [x[2]]) or name,
                          "10,11", next((s[4] for s in K.SCREENS if s[0] in screens), M.unit_name.get(unit, "")),
                          up, down, tag_count.get(code, 0), None, None, sum(1 for g in M.groups.values() if g["area"] == code), None))
    wb_sheet(wb, "工段划分", ["工段编号", "工段名称", "英文标识", "本体URI", "对应流程画面", "涉及DCS控制站", "工艺定位", "上游工段", "下游工段",
                           "DCS点位数", "其中高置信", "其中画面可见", "设备组数", "本体属性数"], area_rows,
             pre=[("北I-2 深冷装置工段划分（按 DCS 流程画面）",), ("口径：" + K.AUTHORITY,), ()])
    # 设备主数据
    members = defaultdict(list)
    for e in M.equip.values():
        if e["group"]:
            members[e["group"]].append(e)
    grows = []
    for g in M.groups.values():
        mem = members.get(g["id"], [])
        key = "/".join(p["tag"] for p in M.tags if p["eq"] in {m["id"] for m in mem} and p["role"] == "测量")[:120]
        grows.append((":" + g["id"], g["name"], g["area"], AREA_NAME[g["area"]], g["cls"], len(mem),
                      "、".join(m["name"] for m in mem), "", key, "", sum(1 for p in M.tags if p["eq"] in {m["id"] for m in mem})))
    wb_sheet(wb, "设备主数据", ["设备组URI", "设备组名称", "工段编号", "工艺工段", "设备类型", "实例数", "实例清单", "主要部件",
                           "画面位号/关键测点", "本体属性", "关联点位数"], grows,
             pre=[("北I-2 深冷装置设备组（本体设备组 → 实例 → DCS 测点）",), ("依据 DCS 流程画面与点表整理",), ()])
    # 设备统计
    stat = defaultdict(Counter)
    for p in M.tags:
        if p["eq"] in M.equip:
            pt = ptype(p)
            stat[p["eq"]]["total"] += 1
            stat[p["eq"]][{"过程测量(PV)": "pv", "控制输出(OP)": "op", "电机控制(MOT)": "mot", "阀门控制(VAL)": "val"}.get(pt, "dido")] += 1
    srows = []
    for e in M.equip.values():
        s = stat[e["id"]]
        g = M.groups.get(e["group"] or "")
        ov = "、".join(p["param"] for p in M.tags if p["eq"] == e["id"])[:80]
        note = f"编号 {e['id']}" + (f"；规程（旧版）编号 {e['sop']}" if e["sop"] else "") + (f"；{e['note']}" if e["note"] else "")
        srows.append((e["station"], M.unit_name.get(next((a[3] for a in AREAS if a[0] == e["area"]), ""), ""), e["name"],
                      s["total"], s["pv"], s["op"], s["mot"], s["val"], s["dido"], ov, e["area"], AREA_NAME[e["area"]],
                      g["name"] if g else None, "高" if not e["pseudo"] else "中", note))
    wb_sheet(wb, "设备统计", ["控制站(SN)", "生产工段名称 (Process Area)", "生产设备/装置名称 (Equipment Entity)", "总点位数", "过程测量(PV)",
                          "控制输出(OP)", "电机控制(MOT)", "阀门控制(VAL)", "开关反馈(DI/DO)", "核心参数/测点概览", "工段编号(流程图口径)",
                          "工艺工段(流程图口径)", "标准设备组(本体)", "归属置信度", "说明"], srows)
    # 点位明细
    trows = []
    for p in M.tags:
        e = M.equip.get(p["eq"] or "")
        area = M.area_of_tag(p)
        g = M.groups.get((e or {}).get("group") or "")
        screen = next((x[2] for x in K.SCREENS if SCREEN_AREA.get(x[0]) == area), AREA_NAME[area])
        trows.append((p["tag"], p["desc"], str(p["station"] or ""), M.unit_name.get(next((a[3] for a in AREAS if a[0] == area), ""), ""),
                      e["name"] if e else None, p["param"] if e else None, ptype(p), p["unit"] or None, p["block"],
                      e["owl"] if e else None, area, AREA_NAME[area], g["name"] if g else None, (":" + g["id"]) if g else None,
                      None, varcat(p), p["unit"] or None, screen, p["how"] or "未归属", p["conf"] or "低",
                      p["lo"], p["hi"]))
    wb_sheet(wb, "DCS点位明细", ["DCS点名 (Tag PN)", "原点描述 (DCS Description)", "控制站 (SN)", "所属工段 (Process Area)",
                              "生产设备/装置 (Equipment Entity)", "参数语义名称 (Parameter Name)", "参数分类 (Parameter Type)",
                              "工程单位 (Unit)", "DCS块类型 (Block Type)", "本体三元组主体 (OWL Subject URI)", "工段编号(流程图口径)",
                              "工艺工段(流程图口径)", "标准设备组(本体)", "标准设备组URI", "绑定本体属性", "变量类别", "标准单位",
                              "所在流程画面", "归属依据", "归属置信度", "量程下限", "量程上限"], trows)
    # 画面补充测点：丙烷机画面上的位号（点表通讯块无描述）
    extra = [("104PT160", "丙烷机", "吸气压力（kPa）", "S10", "丙烷制冷机组", "待补录"),
             ("104TI160", "丙烷机", "吸气温度", "S10", "丙烷制冷机组", "待补录"),
             ("104PT161", "丙烷机", "排气压力（kPa）", "S10", "丙烷制冷机组", "待补录"),
             ("104TI161", "丙烷机", "排气温度", "S10", "丙烷制冷机组", "待补录"),
             ("104PI162", "丙烷机", "油压（kPa）", "S10", "丙烷制冷机组", "待补录"),
             ("104PdI162-163", "丙烷机", "油滤压差（kPa）", "S10", "丙烷制冷机组", "待补录"),
             ("104TE163", "丙烷机", "油分温度", "S10", "丙烷制冷机组", "待补录"),
             ("104IT160", "丙烷机", "主电机电流（A）", "S10", "丙烷制冷机组", "待补录"),
             ("104LT161", "丙烷机", "蒸发器液位（%）", "S10", "丙烷制冷机组", "待补录"),
             ("104TE164～166", "丙烷机", "绕组 A/B/C 温度", "S10", "丙烷制冷机组", "待补录"),
             ("104TE170 / 171", "丙烷机", "前 / 后轴承温度", "S10", "丙烷制冷机组", "待补录")]
    wb_sheet(wb, "画面补充测点", ["画面位号", "所在画面", "推断含义", "工段编号", "建议挂接设备组", "补录状态"], extra,
             pre=[("流程画面可见、但 DCS 点表未收录（或通讯块无描述）的位号",), ("丙烷机为撬装 PLC，经 Modbus 通讯接入（点表 PN10_* 无描述）",), ()])
    diff = [(i[2], "", i[1], "", i[3], i[4]) for i in K.OPEN_ISSUES if i[0] in ("设备编号", "位号")]
    wb_sheet(wb, "画面与点表差异", ["位号/对象", "所在画面", "画面标注", "点表描述", "影响与处理建议", "确认结果"], diff,
             pre=[("画面 / 点表 / 规程（旧版）不一致项及处理（以画面、点表为准）",), ()])
    wb.save(SRC / "DCS.xlsx")
    return len(trows)


# ------------------------------------------------------------------------------------------ 工业关系
def write_relations(M: Model):
    rows = []
    seq = [1000]

    def kind_of(oid):
        if oid in M.equip or oid in M.groups:
            return "生产设备"
        m = next((m for m in K.MATERIALS if m[0] == oid), None)
        if m:
            return "公用介质" if m[2] in ("公用", "热媒", "冷剂") else "物料流股"
        return "工艺属性"

    def area_of(oid):
        o = M.equip.get(oid) or M.groups.get(oid)
        return o["area"] if o else None

    def add(area, cat, stype, subj, pred, otype, obj, desc="", scen="常态", tags="", basis="", conf="高", screen=None):
        seq[0] += 1
        area = area or "S99"
        rows.append((AREA_NAME[area], cat, stype, subj, pred, otype, obj, desc, scen, 1, area, f"R{seq[0]}", "", "", "",
                     tags or None, basis, conf, screen or AREA_NAME[area], "深冷"))

    # 工段衔接
    seen = set()
    for a, pred, b, med, basis in K.FLOWS:
        aa, ab = area_of(a), area_of(b)
        if aa and ab and aa != ab and (aa, ab) not in seen:
            seen.add((aa, ab))
            add(aa, "工段衔接", "生产工段", AREA_NAME[aa], "串联下游", "生产工段", AREA_NAME[ab], f"衔接物料：{med}", "工段衔接",
                basis=basis)
    # 设备组包含实例
    for e in M.equip.values():
        if e["group"]:
            g = M.groups[e["group"]]
            add(g["area"], "结构关系", "生产设备", g["name"], "包含实例", "设备实例", e["name"], f"{g['name']}包含{e['name']}",
                basis="DCS 流程画面")
    # 阀门作用于设备
    for e in M.equip.values():
        if e["kind"] == "阀门" and e.get("host") in M.equip:
            add(e["area"], "控制关系", "执行机构", e["name"], "作用于", "生产设备", M.equip[e["host"]]["name"],
                f"{e['name']}安装在{M.equip[e['host']]['name']}的管线上", basis="DCS 流程画面 / 点表")
    # 部件
    for a, pred, obj, basis in K.STRUCTURE:
        n = M.name_of(a)
        for part in re.split(r"[、，]", obj):
            part = part.strip()
            if part:
                add(area_of(a), "结构关系", "生产设备", n, "具有部件", "设备部件", f"{n}·{part}", "", basis=basis)
    # 物理拓扑
    for a, pred, b, med, basis in K.FLOWS:
        ka, kb = kind_of(a), kind_of(b)
        add(area_of(a) or area_of(b), "物理拓扑关系", ka, M.name_of(a), pred, kb, M.name_of(b), f"{pred}（{med}）",
            "常态", basis=basis, conf="中" if "推断" in basis else "高")
    # 工艺影响
    tagre = re.compile(r"\b(\d{3}[A-Z_]*\d{2,3}[A-Z]?)\b")
    for s, p, o, mech, basis, conf in K.INFLUENCES:
        tags = [t for t in tagre.findall(s + " " + o) if t in M.tag_names]
        cat = "影响关系"
        pred = {"导致": "影响", "约束": "影响"}.get(p, p)
        add(None, cat, "工艺属性", s, pred, "工艺属性", o, mech, "工艺传导", "、".join(tags), basis, conf)
    # 控制回路：控制仪表 控制 执行机构；工艺属性（测量）反馈给 控制仪表
    valve_by_tag = {}
    for v in M.valves:
        for t in v["tags"]:
            valve_by_tag[t] = v["id"]
    for lp in K.LOOPS:
        tag, name, eqid, pv, op = lp[:5]
        if tag not in M.tag_names:
            continue
        loop = f"{name}（{tag}）"
        area = area_of(eqid)
        vid = valve_by_tag.get(op) or valve_by_tag.get(op.split("（")[0])
        target = M.equip[vid]["name"] if vid in M.equip else op
        add(area, "控制关系", "控制仪表", loop, "控制", "执行机构", target, lp[10] or "", "控制回路", tag, K.SOP + " 4.1.1 / 点表 PIDA")
    wb = new_wb()
    wb_sheet(wb, "关系明细", ["工段 (Area)", "关系大类 (Category)", "起始对象类型 (Subject Type)", "起始对象语义名称 (Subject Entity)",
                          "关系谓词 / 边类型 (Predicate)", "目标对象类型 (Object Type)", "目标对象语义名称 (Object Entity)",
                          "工艺机理与业务因果说明 (Domain Description)", "子场景", "权重", "工段编号", "关系ID", "主体URI", "谓词URI",
                          "客体URI", "关联DCS位号", "依据来源", "置信度", "流程画面", "变更标记"], rows)
    cats = Counter((r[1], r[4]) for r in rows)
    wb_sheet(wb, "关系分类与统计(Overview)", ["关系大类", "关系谓词", "含义", "典型主体类型", "典型客体类型", "数量"],
             [(c, p, "", "", "", n) for (c, p), n in sorted(cats.items())], pre=[("北I-2 深冷装置关系分类与统计",), ()])
    wb.save(SRC / "工业关系.xlsx")
    return len(rows)


# ------------------------------------------------------------------------------------------ 工艺限值
MODE_ORDER = {"正常运行": 0, "报警 / 联锁": 1, "报警 / 停机": 1, "自动控制·设定值范围": 2}


def write_limits(M: Model):
    by_tag: dict[str, dict] = {}
    extra: list[dict] = []
    tag_area = {p["tag"]: M.area_of_tag(p) for p in M.tags}
    for x in sorted(M.limits_raw, key=lambda x: MODE_ORDER.get(x["mode"], 3)):
        for tag in [t.strip() for t in (x["dcs"] or "").split("、") if t.strip()]:
            if tag not in tag_area:
                continue
            mode = x["mode"]
            if "（热吹）" in x["name"] or "（冷吹）" in x["name"]:
                mode = "热吹" if "热吹" in x["name"] else "冷吹"
            if mode in ("正常运行", "报警 / 联锁", "报警 / 停机"):
                cur = by_tag.get(tag)
                if cur is None:
                    cur = by_tag[tag] = dict(x, dcs=tag, mode="正常运行", srcs=[x["src"]], raws=[x["raw"]])
                    cur["id"] = f"PL-{tag}"
                    continue
                for k in ("LL", "L", "NL", "NH", "H", "HH", "op"):
                    if cur.get(k) is None and x.get(k) is not None:
                        cur[k] = x[k]
                if x["src"] not in cur["srcs"]:
                    cur["srcs"].append(x["src"])
                    cur["raws"].append(x["raw"])
            else:
                y = dict(x, dcs=tag, mode=mode, srcs=[x["src"]], raws=[x["raw"]])
                y["id"] = f"PL-{tag}-{'C' if '自动控制' in mode else ('R' if mode in ('热吹', '冷吹') else 'S')}"
                extra.append(y)
    items = list(by_tag.values())
    ids = Counter()
    for y in extra:
        ids[y["id"]] += 1
        if ids[y["id"]] > 1:
            y["id"] += str(ids[y["id"]])
        items.append(y)
    rows = []
    for x in items:
        area = tag_area[x["dcs"]]
        note = "规程原文：" + "；".join(r for r in x["raws"] if r) + (f"；{x['note']}" if x.get("note") else "")
        if x.get("op") is not None:
            note += f"；操作点 / 设定值 {x['op']}"
        rows.append((x["id"], "DCS点", x["dcs"], AREA_NAME[area], x["mode"], x["name"], x["unit"] or None,
                     x["LL"], x["L"], x["NL"], x["NH"], x["H"], x["HH"], "；".join(s.replace(K.SOP, OLD_SOP) for s in x["srcs"]),
                     "规程（旧版）参考", "中", DRAFT, note))
    rows.sort(key=lambda r: (0 if r[4] == "正常运行" else 1, r[0]))
    wb = new_wb()
    wb_sheet(wb, "工艺限值", ["限值编号 (Limit ID)", "适用对象类型 (Applies To Type)", "适用对象 (Applies To)", "适用工段 (Area)",
                          "适用工况 (Operating Mode)", "参数含义 (Parameter)", "单位 (Unit)", "低低限 LL", "低限 L", "正常下限 (Normal Low)",
                          "正常上限 (Normal High)", "高限 H", "高高限 HH", "限值依据 (Basis)", "依据类型 (Basis Type)", "置信度 (Confidence)",
                          "确认状态 (Status)", "备注 (Note)"], rows)
    wb_sheet(wb, "使用说明", ["项目", "说明"], [
        ("用途", "北I-2 深冷装置工艺限值；适用对象类型均为「DCS点」，直接挂点表位号。"),
        ("来源", "数值取自操作规程（旧版）附录二（主要运行参数）、附录四（报警联锁值）、表 4-1（PID 设定范围）、表 2-1～2-10 / 2.3（开车确认）。"),
        ("口径", "规程为旧版，限值仅作参考，全部「草案·待工艺确认」；点表组态的报警限当前值导出为 0，待从 DCS 在线导出后替换。"),
        ("合并", "同一位号的「正常运行」区间与报警 / 联锁值合并成一条（PL-<位号>）；开车确认 -S、自动控制设定 -C、热吹 / 冷吹 -R 另列。"),
    ])
    wb.save(SRC / "工艺限值.xlsx")
    return rows


# ------------------------------------------------------------------------------------------ 能力 / 处置规程
def write_capabilities():
    src = ROOT / "data" / "archive" / "6apa" / "source" / "6APA_能力.xlsx"
    old = openpyxl.load_workbook(src, read_only=True)
    caps = [r for r in old["能力"].iter_rows(min_row=2, values_only=True) if r[0] in ("CAP-001", "CAP-002")]
    params = [r for r in old["能力参数"].iter_rows(min_row=2, values_only=True) if r[0] in ("CAP-001", "CAP-002")]
    caps = [tuple((str(v).replace("实时数据库 HSM", "DCS 实时库（和利时 MACS 实时库服务）").replace("历史数据库 timing-svc", "DCS 历史库（和利时 MACS 历史库服务）")
                   if isinstance(v, str) else v) for v in r) for r in caps]
    caps += [
        ("CAP-C04", "流量计算 / 累计", "计算", "孔板差压 + 压力 + 温度 → 标况流量；瞬时 / 小时累计", "设备、设备组", None,
         "DCS GASCAL / FLOWSUM 块", "DCS 组态", "—", None, "标况瞬时流量（*M）、累计（*MLJ / *MLJH）", None, "已登记", "7 个计量点"),
        ("CAP-C05", "分子筛顺控程序", "控制·程序", "降压—热吹—冷吹—升压—等待—并行 时序控制，自动 / 暂停 / 手动步进", "设备组", "吸附器",
         "DCS SFC 程序 FZSKZ", "DCS 组态", "—", None, "各阶段进度与计时", None, "已登记", "本体只读程序状态，不下发控制"),
        ("CAP-C07", "APC 先进控制（K1）", "控制·优化", "冷冻分离单元多变量控制：TV113、TV119、J-T 阀、膨胀机喷嘴、增压机空冷、再生气流量", "工段", None,
         "APC 控制器 K1", "OPC", "—", None, "CV / MV 投用状态、设定、计算值", None, "已登记", "本体只读"),
        ("CAP-C08", "RTO 优化 / CO2 冻堵预测", "分析·模型", "输入天然气化验组分，输出 CO2 冻堵预测与优化约束", "设备", "塔器",
         "RTO 优化器 Y1", "OPC", "—", None, "AM10_RTO_OUT1～3", None, "已登记", "本体只读"),
    ]
    wb = new_wb()
    wb_sheet(wb, "能力", ["能力ID", "能力名称", "能力类型", "能力描述", "适用对象", "适用设备类型", "提供方", "调用方式", "端点",
                        "本体代调入口", "输出", "前置条件", "登记状态", "说明"], caps)
    wb_sheet(wb, "能力参数", ["能力ID", "参数名", "类型", "必填", "说明", "绑定"], params)
    wb_sheet(wb, "说明", ["项目", "说明"], [("定位", "本体挂载的能力 = 能力描述 + 调用契约 + 本对象参数绑定。能力由外部系统实现，本体不实现、不代为下发控制指令。")])
    wb.save(SRC / "能力.xlsx")


def write_procedures(M: Model):
    procs = parse_procedures(M.doc, M.matcher, {})
    by_sec = defaultdict(list)
    for chap, sec, step, post, act, text, eqs, tags in procs:
        by_sec[sec.split(" ")[0].strip()].append(text)

    def steps_of(sec):
        out = []
        for t in by_sec.get(sec, []):
            out += [s.strip("。； ") for s in re.split(r"[；;]", t) if s.strip("。； ")]
        return out
    # 卡片编号, 名称, 报警名称, 触发对象, 触发位号, 级别, 设定值, 单位, 工段, 关联设备, 关联联锁, 现象DCS, 后果, 规程章节, 原因[(类别,描述,验证位号)], 禁止
    cards = [
        ("ARP-01", "仪表风系统故障", "仪表风总管压力低", "净化风储罐", "108PT101", "L", "0.50", "MPa", "S13", "净化风储罐", "",
         "仪表风总管压力下降", "仪表风可维持约 20 min，超过后气动阀失控，装置停车", "3.3.2",
         [("机", "空压机停机或故障（综合报警 / 综合停机）", "108_US_102"), ("机", "干燥器 / 过滤器堵塞", "108PT202")], []),
        ("ARP-02", "循环水系统故障", "循环水中断", "循环水系统·公共测点", "110PT133", "L", "0.45", "MPa", "S15", "主泵房1#循环水泵", "",
         "循环水泵压力下降、冷却水给水温度上升", "润滑油温度快速升高，压缩机 / 膨胀机 / 丙烷机油温高停机", "3.3.3",
         [("机", "循环水泵停运", "110PT133"), ("环", "凉水塔风机故障或环境温度高", "112TT101")], []),
        ("ARP-03", "原料气压缩机联锁停机", "压缩机停机", "原料气压缩机", "S102ZS220", "HH", "", "", "S02", "原料气压缩机", "IL-19、IL-20",
         "压缩机停机状态指示；入口放空阀全开、防喘振阀全开、入口阀关、塔顶压力调节阀关", "膨胀机联锁停机，装置停运", "3.3.5.1",
         [("机", "轴振动 / 轴位移 / 轴承温度达停机值", "a102_VIA130"), ("机", "润滑油压力低", "a102_PINSA171"),
          ("料", "入口分离器液位超高", "a102_LICA120")], ["未查明停机原因不得强行启机"]),
        ("ARP-04", "膨胀机联锁停机", "膨胀机停机", "1#膨胀压缩机", "104SI180A", "LL", "", "rpm", "S08", "1#膨胀压缩机", "IL-11～IL-17",
         "膨胀机转速下降、ESD 返回停机状态", "制冷温度升高；压缩机三级出口憋压", "3.3.5.2",
         [("机", "膨胀机振动高（> 48 μm）", "104XE180AX"), ("机", "供油压差低", "104PDT182A"), ("法", "增压端流量低（防喘振）", "104FT180A")],
         ["不允许在 2000 r/min 以下长时间运行"]),
        ("ARP-05", "丙烷机联锁停机", "丙烷机故障报警", "丙烷机", "104_UIC_162", "H", "", "", "S10", "丙烷机", "IL-22",
         "丙烷机故障报警亮", "丙烷蒸发器预冷消失，膨胀机入口及制冷温度升高", "3.3.5.3",
         [("机", "吸 / 排气压力、温度、油压、油温越联锁值", "104_UIC_161")], []),
        ("ARP-06", "冷冻系统冻堵", "换热器原料气差压高", "一级贫富气换热器", "104PDT101", "H", "30", "kPa", "S07", "一级贫富气换热器", "",
         "一级 / 二级贫富气换热器、冷箱Ⅰ原料气差压逐步升高", "换热器 / 填料段冻堵，处理量下降，严重时停车", "4.2.4.3",
         [("料", "原料气 CO2 含量高、制冷温度过低", "104TT115"), ("料", "脱水后露点偏高（水合物）", "103AT101")], []),
        ("ARP-07", "脱甲烷塔顶温度过低（CO2 冻塔先兆）", "塔顶温度低", "脱甲烷塔", "104TT115", "L", "-81", "℃", "S07", "脱甲烷塔", "",
         "塔顶温度低于 -81 ℃（塔顶 1.35 MPa）", "CO2 析出冻塔", "4.1.2",
         [("法", "喷嘴开度过大或 J-T 阀设定过高，制冷过度", "104_SI_180A")], ["原则上塔顶制冷温度不低于 -81 ℃"]),
        ("ARP-08", "紧急停车", "全厂紧急停车", "ESD 紧急停车系统", "ANNIU1", "HH", "", "", "S16", "原料气压缩机", "IL-26",
         "全厂紧急停车按钮动作", "主要运行设备停运", "3.4", [("人", "现场或主控室按下紧急停车按钮", "S114ES201")], []),
    ]
    card_rows, cause_rows, step_rows, forbid_rows = [], [], [], []
    for (cid, name, alarm, obj, tag, lvl, sp, unit, area, eqn, il, dcs, cons, sec, causes, forbid) in cards:
        basis = f"{OLD_SOP} {sec}"
        card_rows.append((cid, name, alarm, obj, tag, lvl, sp, unit, None, area, eqn, il or None, "高", "立即", dcs, None, cons, eqn,
                          "参数恢复正常并查明原因", "向大队调度汇报停机 / 异常原因与处理情况", "交接班记录", DRAFT, basis))
        for i, (cat, desc, vt) in enumerate(causes, 1):
            cause_rows.append((cid, i, cat, desc, eqn, "查看相关参数趋势与报警", vt, "", basis))
        st = steps_of(sec) or [f"按{basis}处理"]
        for i, s in enumerate(st, 1):
            post = "中控" if re.search(r"主控室|控制系统|设定|ME", s) else "现场"
            step_rows.append((cid, i, "处置", post, "操作", s, eqn, None, None, basis))
        for i, f in enumerate(forbid, 1):
            forbid_rows.append((cid, i, f, eqn, basis))
    # 现场异常排查表（用户提供）：重烃收集罐烃室液位持续上涨 —— 7 项排查方式 + 处置方式，原文照录
    src = "现场异常排查表（用户提供，重烃收集罐烃室液位）"
    card_rows.append(("ARP-09", "重烃收集罐烃室液位持续上涨", "重烃收集罐烃室液位持续上涨", "重烃收集罐", "102LT102", "H", "30", "%",
                      None, "S02", "重烃收集罐", None, "高", "立即", "烃室液位 102LT102 持续上涨（运行值 30%）", None,
                      "烃室液位高，三相分离变差，凝液带入压缩机入口 / 闪蒸气系统", "重烃收集罐",
                      "烃室液位回落并稳定", "向相关专业汇报排查结果", "交接班记录", DRAFT, src))
    checks = [  # 原因类别, 原因描述（排查方式原文）, 关联对象, 验证方法, 验证位号, 判据
        ("机", "查看重烃泵是否处于运行状态", "重烃泵组", "看 1#/2# 重烃泵运行状态", "102_Z_101、102_Z_102", "两台均为 0 即停运（现象 PH-37）"),
        ("机", "查看变频重烃泵输出及反馈是否匹配，是否处于全开或正在开大", "重烃泵组", "对比变频控制输出与变频反馈",
         "102LRC101、102SI101、102LRC102、102SI102", "偏差大或输出已全开 / 持续开大（现象 PH-38）"),
        ("法", "查看任意一重烃储罐入口阀处于开启状态", "重烃储罐组", "看倒罐（入口）阀开反馈", "HZO_106、HZO_111A",
         "两台均未开（现象 PH-39）"),
        ("法", "查看重烃进罐总线阀门处于开启状态", "重烃进罐管线总阀", "看开 / 关反馈", "105_LZO_104、105_LZC_104", "未开（现象 PH-40）"),
        ("料", "查看开启入口阀的重烃储罐压力是否异常", "重烃储罐组", "看入口阀开启那台的储罐压力", "105PT104、105PT105",
         "压力偏高（现象 PH-41）"),
        ("料", "查看重烃收集罐压力是否过低（正常 0.3 左右）", "重烃收集罐", "看收集罐压力", "102PT102", "明显低于 0.3 MPa（现象 PH-42）"),
    ]
    for i, (cat, desc, obj, how, vt, crit) in enumerate(checks, 1):
        cause_rows.append(("ARP-09", i, cat, desc, obj, how, vt, crit, src))
    steps = [  # 阶段, 岗位, 动作, 描述, 关联对象, 关联位号, 前置条件
        ("排查", "中控", "确认", "查看重烃泵是否处于运行状态", "重烃泵组", "102_Z_101、102_Z_102", None),
        ("排查", "中控", "确认", "查看变频重烃泵输出及反馈是否匹配，是否处于全开或正在开大", "重烃泵组", "102LRC101、102SI101、102LRC102、102SI102", None),
        ("排查", "中控", "确认", "查看任意一重烃储罐入口阀处于开启状态", "重烃储罐组", "HZO_106、HZO_111A", None),
        ("排查", "中控", "确认", "查看重烃进罐总线阀门处于开启状态", "重烃进罐管线总阀", "105_LZO_104", None),
        ("排查", "中控", "确认", "查看开启入口阀的重烃储罐压力是否异常", "重烃储罐组", "105PT104、105PT105", None),
        ("排查", "中控", "确认", "查看重烃收集罐压力是否过低（正常 0.3 左右）", "重烃收集罐", "102PT102", None),
        ("处置", "中控", "汇报 / 操作", "如重烃泵处于停运状态需汇报相关专业并启用备用机泵", "重烃泵组", None, "排查 1 发现停运"),
        ("处置", "中控", "操作", "如不匹配或未处于全开或正在开大需查看 PID 调节是否未投用自动，如处于自动状态汇报相关专业并切换工频运行",
         "重烃泵组", "102LIC101、102LIC102", "排查 2 发现异常"),
        ("处置", "现场", "操作", "如未有阀门处于开启状态需立即开启", "重烃储罐组", "105HV106A、105HV111A", "排查 3 发现均未开"),
        ("处置", "现场", "操作", "如未处于开启状态需立即开启", "重烃进罐管线总阀", "105LV104", "排查 4 发现未开"),
        ("汇报", "中控", "汇报", "如无上述故障需汇报相关专业", "重烃收集罐", None, "排查 1～6 均正常"),
    ]
    for i, (stage, post, act, desc, obj, tags, pre) in enumerate(steps, 1):
        step_rows.append(("ARP-09", i, stage, post, act, desc, obj, tags, pre, src))
    wb = new_wb()
    wb_sheet(wb, "处置卡", ["卡片编号", "卡片名称", "报警名称", "触发对象", "触发位号", "报警级别", "设定值", "单位", "关联限值", "所属工段",
                         "关联设备", "关联联锁", "优先级", "允许响应时间", "报警现象·DCS", "报警现象·现场", "未及时处置后果", "后果关联对象",
                         "解除条件", "汇报要点", "记录要求", "状态", "依据"], card_rows)
    wb_sheet(wb, "可能原因", ["卡片编号", "序号", "原因类别", "原因描述", "关联对象", "验证方法", "验证位号", "判据", "依据"], cause_rows)
    wb_sheet(wb, "处置步骤", ["卡片编号", "序号", "阶段", "岗位", "动作类型", "步骤描述", "关联对象", "关联位号", "前置条件", "依据"], step_rows)
    wb_sheet(wb, "禁止操作", ["卡片编号", "序号", "禁止内容", "关联对象", "依据"], forbid_rows)
    wb.save(SRC / "处置规程.xlsx")
    return len(card_rows)


# ------------------------------------------------------------------------------------------ 配置
def write_config(M: Model):
    wb = new_wb()
    wb_sheet(wb, "车间", ["车间编号", "车间名称", "说明", "状态"],
             [("PLANT-B12", K.PLANT["name"], K.PLANT["desc"], "已确认")])
    wb_sheet(wb, "工艺段", ["工艺段编号", "车间编号", "工艺段名称", "顺序", "说明"],
             [(f"SEG-{u[0][1:]}", "PLANT-B12", u[1], u[2], u[4]) for u in K.UNITS])
    wb_sheet(wb, "工序", ["工序编号", "工艺段编号", "工序名称", "顺序", "流程画面", "工段编号", "设备匹配(正则)", "子工序(写在图纸上)", "说明", "状态"],
             [(o[0], f"SEG-{o[1][1:]}", o[2], o[3], o[4], o[5], o[6] or None, o[7], None, "已确认") for o in OPS])
    wb_sheet(wb, "未纳入工段", ["工段编号", "工段名称", "原因"], [("S99", "系统与未归属点", "DCS 控制站 / 操作站诊断、环境监测、无描述的通讯点")])
    wb_sheet(wb, "说明", ["项", "内容"], [
        ("层级", "装置 → 工艺单元 → 流程画面；画面 = 一张 DCS 流程画面，子工序写在图纸上"),
        ("设备归属", "按「工段编号」取点表设备；1号 / 2号膨胀机两张画面共用工段 S08，按名称 1# / 2# 认领"),
        ("口径", K.AUTHORITY),
    ])
    wb.save(CFG / "空间层级.xlsx")
    # 设备设计参数：模板按设备类，值取规程（旧版）的型号规格
    wb = new_wb()
    kw_extra = {"离心压缩机组": "压缩机", "膨胀压缩机组": "膨胀", "螺杆制冷压缩机组": "丙烷机", "离心泵": "泵", "计量泵": "甲醇泵、污水泵、污油泵、三甘醇泵",
                "分离器": "分离器、除油器、分水罐、分液罐、闪蒸罐、切水罐、收集罐、缓冲罐", "储罐": "储罐、甲醇罐、膨胀罐、储油罐、水罐、水箱",
                "吸附器": "吸附器、制氮", "塔器": "塔", "板翅式换热器": "贫富气换热器、过冷器、重沸器、侧沸器", "管壳式换热器": "换热器、加热器、蒸发器",
                "加热炉": "炉", "空冷器": "空冷器", "过滤器": "过滤", "火炬": "火炬", "凉水塔": "凉水塔", "压力排污罐": "压力排污罐",
                "调节阀": "调节阀", "开关阀": "阀", "螺杆空压机": "空压机"}
    trows = []
    order = ["离心压缩机组", "膨胀压缩机组", "螺杆制冷压缩机组", "螺杆空压机", "压力排污罐", "计量泵", "离心泵", "空冷器", "塔器", "吸附器",
             "板翅式换热器", "管壳式换热器", "加热炉", "凉水塔", "火炬", "过滤器", "分离器", "储罐", "调节阀", "开关阀"]
    tpl = {c[0]: c for c in K.CLASSES}
    for name in order:
        c = tpl[name]
        trows.append((name, kw_extra.get(name, name), "设备位号", None, "DCS 流程画面上的设备编号"))
        trows.append((name, kw_extra.get(name, name), "规格 / 型号", None, "规程（旧版）中的型号或规格说明"))
        for p in [x.strip() for x in c[3].split("、") if x.strip()]:
            trows.append((name, kw_extra.get(name, name), p, None, ""))
    vrows = [(e["name"], "规格 / 型号", e["spec"], OLD_SOP + "（规格说明）", DRAFT) for e in M.equip.values() if e["spec"]]
    vrows += [(e["name"], "设备位号", e["id"], "DCS 流程画面", "画面") for e in M.equip.values() if e["kind"] == "设备" and not e["pseudo"]]
    wb_sheet(wb, "参数模板", ["模板", "匹配关键字", "参数名", "单位", "说明"], trows)
    wb_sheet(wb, "参数值", ["对象名称", "参数名", "值", "依据 / 来源", "状态"], vrows)
    wb_sheet(wb, "说明", ["项", "内容"], [("用途", "设备固定参数；模板按设备类，关键字先匹配设备名称再匹配设备组类型；设备位号取画面编号")])
    wb.save(CFG / "设备设计参数.xlsx")


def main():
    SRC.mkdir(parents=True, exist_ok=True)
    CFG.mkdir(parents=True, exist_ok=True)
    M = Model()
    n_tags = write_dcs(M)
    n_rel = write_relations(M)
    lim = write_limits(M)
    write_capabilities()
    n_cards = write_procedures(M)
    write_config(M)
    print(f"设备 / 阀门 {len(M.equip)}，设备组 {len(M.groups)}，位号 {n_tags}，关系 {n_rel}，限值 {len(lim)}，处置卡 {n_cards}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
