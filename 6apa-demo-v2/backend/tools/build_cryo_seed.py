"""北I-2 深冷装置种子数据：现象（带判定规则）、根因影响关系、计算组态。

    python3 -m backend.tools.build_cryo_seed            # data/seed/*.json 已存在则不覆盖
    python3 -m backend.tools.build_cryo_seed --force    # 覆盖（不影响 data/store 里的运行时编辑）

先运行 build_cryo_sources 生成数据源：这里按名称从本体里取设备 / 设备组 ID、按位号取参数名、按限值编号引用限值。
全部「草案·待工艺确认」；阈值优先引用工艺限值（规程旧版参考值），没有限值的写数值并在备注说明来源。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.ontology.indexes import OntologyStore
from backend.services import process_limits

from . import cryo_knowledge as K

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
DRAFT = K.DRAFT
OLD = "北I-2装置操作规程（旧版）"


class Ctx:
    def __init__(self):
        self.store = OntologyStore()
        d = self.store.dcs
        self.equip = {e["name"]: e for e in d.equipment.values()}
        self.group = {g["name"]: g for g in d.equipment_groups.values()}
        self.tag = {t["name"]: t for t in d.tags.values()}
        self.limits = {l["id"]: l for l in process_limits._load()}
        self.missing: list[str] = []

    def anchor(self, name: str) -> dict:
        if name in self.group:
            g = self.group[name]
            return {"kind": "group", "id": g["id"], "name": name, "areaCode": g.get("areaCode")}
        e = self.equip[name]
        return {"kind": "equipment", "id": e["id"], "name": name, "areaCode": e.get("areaCode")}

    def P(self, tag: str) -> str:
        """位号 → 参数语义名称（规则主体按参数写，组上的现象逐台落到本台测点）。"""
        return self.tag[tag]["parameterName"]

    def thr(self, limit_id: str, field: str, value: float, why: str = "") -> dict:
        lim = self.limits.get(limit_id)
        if lim and lim.get(field) is not None:
            return {"kind": "limit", "limitId": limit_id, "field": field}
        self.missing.append(f"{limit_id}.{field}→{value}{('（' + why + '）') if why else ''}")
        return {"kind": "value", "value": value}


def cond(param, op, threshold, dur=0, agg="any"):
    return {"type": "condition", "subject": {"kind": "parameter", "name": param}, "operator": op,
            "aggregate": agg, "durationSec": dur, "threshold": threshold}


def tag_cond(tag, op, threshold, dur=0):
    return {"type": "condition", "subject": {"kind": "tag", "tag": tag}, "operator": op, "aggregate": "any",
            "durationSec": dur, "threshold": threshold}


def calc_cond(calc_id, op, value, dur=0):
    return {"type": "condition", "subject": {"kind": "calc", "calcId": calc_id}, "operator": op, "aggregate": "any",
            "durationSec": dur, "threshold": {"kind": "value", "value": value}}


def change(param, frm, to):
    return {"type": "condition", "subject": {"kind": "parameter", "name": param}, "operator": "change",
            "from": frm, "to": to, "aggregate": "any", "durationSec": 0}


def OR(*c):
    return {"type": "group", "op": "OR", "children": list(c)}


def AND(*c):
    return {"type": "group", "op": "AND", "children": list(c)}


def V(x):
    return {"kind": "value", "value": x}


def build(c: Ctx):
    P, T = c.P, c.thr
    meta = {p[0]: p for p in K.PHENOMENA}
    rules = {
        "PH-01": ("脱甲烷塔", OR(cond(P("104TT115"), "<", V(-81), 300)), "规程 4.1.2.1：塔顶 1.35 MPa 时低于 -81 ℃ 出现冻塔先兆"),
        "PH-02": ("一级贫富气换热器", OR(cond(P("104PDT101"), ">", V(30), 300), cond(P("104PDT101"), ">", T("PL-104PDT101", "high", 50))),
                  "30 kPa 为规程表 4-4 甲醇加注操作点"),
        "PH-03": ("二级贫富气换热器", OR(cond(P("104PDT102"), ">", V(30), 300), cond(P("104PDT102"), ">", T("PL-104PDT102", "high", 50))),
                  "30 kPa 为规程表 4-4 甲醇加注操作点"),
        "PH-04": ("冷箱Ⅰ·公共测点", OR(cond(P("104PDT103"), ">", V(30), 300), cond(P("104PDT103"), ">", T("PL-104PDT103", "high", 50))),
                  "30 kPa 为规程表 4-4 甲醇加注操作点"),
        "PH-05": ("脱甲烷塔", OR(cond(P("104PDT104"), ">", V(5), 300), cond(P("104PDT105"), ">", V(5), 300),
                                cond(P("104PDT106"), ">", V(5), 300)), "5 kPa 为规程表 4-4 操作点（报警 10 kPa）"),
        "PH-06": ("冷箱Ⅱ", AND(cond("原料气压差", ">", V(30), 600), calc_cond("CALC-05", ">", 0.05, 600)),
                  "差压超过加注操作点且持续上升；上升速率 0.05 kPa/min 为占位阈值，待现场提供"),
        "PH-07": ("脱甲烷塔", OR(cond(P("104TT115"), ">", T("PL-104TT115", "normalHigh", -75), 600)), "塔顶温度高于运行范围上限"),
        "PH-08": ("J-T阀", OR(cond(P("104_PZT_107"), ">", V(5), 120)), "阀位反馈 > 5% 视为开启（占位阈值，待现场提供）"),
        "PH-09": ("原料气出脱水单元管线", OR(cond(P("103AT101"), ">", V(-85), 300)), "规程 2.2.2.3：露点 < -85 ℃"),
        "PH-10": ("分子筛吸附器组·公共测点", None, "需结合分子筛程序阶段（热吹结束时床层出口 ≥ 185 ℃），判定规则待定义"),
        "PH-11": ("过滤分离器", OR(cond(P("103PDT107"), ">", T("PL-103PDT107", "normalHigh", 100), 300)), ""),
        "PH-12": ("干气粉尘过滤器组·公共测点", OR(cond(P("103PDT108"), ">=", T("PL-103PDT108", "normalHigh", 100), 300)),
                  "规程 4.2.3.3：差压 ≥ 0.1 MPa 切换备用过滤器"),
        "PH-13": ("原料气压缩机", OR(cond(P("a102_PI135"), ">", T("PL-a102_PI135", "normalHigh", 3.65), 120)), ""),
        "PH-14": ("原料气压缩机", OR(*[cond(P(t), ">", T("PL-" + t, "high", 63.5)) for t in ("a102_VIA130", "a102_VIA132", "a102_VIA134", "a102_VIA136")]),
                  "低 / 高压缸止推与支撑轴承振动任一超过报警值"),
        "PH-15": ("原料气压缩机", OR(*[cond(P(t), ">", T("PL-" + t, "high", 105)) for t in ("a102_TISA144", "a102_TISA146", "a102_TISA148", "a102_TISA150",
                                                                                               "a102_TISA153", "a102_TISA152", "a102_TISA156", "a102_TISA158")]),
                  "低 / 高压缸各轴承温度任一超过报警值"),
        "PH-16": ("原料气压缩机", OR(cond(P("a102_PINSA171"), "<", T("PL-a102_PINSA171", "normalLow", 0.25), 60)), "规程 4.2.2.2：0.25～0.30 MPa"),
        "PH-17": ("膨胀压缩机组", OR(*[cond(P(t), ">", V(38)) for t in ("104XE180AX", "104XE180AY", "104XE181AX", "104XE181AY")]),
                  "规程附录四：报警 > 38 μm，联锁 > 48 μm"),
        "PH-18": ("膨胀压缩机组", OR(cond(P("104TE180A"), ">", V(70), 60), cond(P("104TE181A"), ">", V(75), 60)),
                  "规程附录四：膨胀端 > 70 ℃、增压端 > 75 ℃ 报警"),
        "PH-19": ("膨胀压缩机组", OR(cond(P("104PDT182A"), "<", V(800), 30)), "规程附录四：供油压差 < 0.8 MPa 报警（点表单位 kPa）"),
        "PH-20": ("膨胀压缩机组", OR(cond(P("104FT180A"), "<", V(8600), 30)), "规程附录四：增压端入口流量 < 8600 m³/h 联锁"),
        "PH-21": ("膨胀压缩机组", OR(cond(P("104SI180A"), "<", V(2000), 60)), "规程 2.2.5.3：不允许在 2000 r/min 以下长时间运行"),
        "PH-22": ("原料气压缩机", OR(change(P("S102ZS220"), 0, 1)), "ESD 记录点「压缩机停机状态」由 0 变 1"),
        "PH-23": ("丙烷机", OR(cond(P("104_UIC_161"), "=", V(1)), cond(P("104_UIC_162"), "=", V(1))), ""),
        "PH-24": ("脱甲烷塔", OR(cond(P("104PT111"), ">", T("PL-104PT111", "high", 1.5), 60)), "附录四写「塔釜压力」，按点表取塔顶压力 104PT111"),
        "PH-25": ("脱甲烷塔", OR(cond(P("104TT114"), "<", T("PL-104TT114", "low", -10), 60)), ""),
        "PH-26": ("塔底泵组", OR(cond(P("104TE125"), ">", V(150), 60)), "规程附录四：定子温度 > 150 ℃ 报警、> 165 ℃ 联锁"),
        "PH-27": ("低温分离器", OR(cond(P("104LT101"), ">", T("PL-104LT101", "normalHigh", 30), 300)), ""),
        "PH-28": ("轻烃储罐组", OR(cond(P("105PT101"), ">", V(2.5), 60)), "规程附录四：轻烃储罐压力 > 2.5 MPa 报警"),
        "PH-29": ("重烃储罐组", OR(cond(P("105LT104"), ">=", V(70), 60)), "规程 4.2.5.3：液位达 70% 倒罐"),
        "PH-30": ("导热油加热炉", OR(cond(P("DRY_TT_CK"), ">", T("PL-DRY_TT_CK", "high", 290), 60)), ""),
        "PH-31": ("循环水系统·公共测点", OR(cond(P("112TT101"), ">", V(32), 600)), "规程 1.2.7.2：设计出水温度 32 ℃"),
        "PH-32": ("循环水系统", None, "需综合 3 台循环水泵运行状态与供水压力，判定规则待定义"),
        "PH-33": ("净化风储罐", OR(cond(P("108PT101"), "<", V(0.5), 60)), "规程 1.2.7.1：仪表风进站 0.50～0.60 MPa"),
        "PH-34": ("膨胀压缩机组", OR(cond(P("104TE183A"), ">", V(60), 300)), "规程附录四：油箱温度 > 60 ℃ 报警"),
        "PH-35": ("再生气空冷器", OR(cond(P("103TT104"), ">", T("PL-103TT104", "high", 45), 300)), ""),
        # 现场异常排查表：重烃收集罐烃室液位持续上涨（PH-36）及 6 项排查（PH-37～42 → PH-36）
        "PH-36": ("重烃收集罐", AND(calc_cond("CALC-07", ">", 0.1, 600), cond(P("102LT102"), ">", V(30), 600)),
                  "运行值 30% 取自排查表；上升速率 0.1 %/min 为占位阈值，待现场提供"),
        "PH-37": ("重烃收集罐", AND(tag_cond("102_Z_101", "=", V(0), 120), tag_cond("102_Z_102", "=", V(0), 120)),
                  "排查 1：两台泵都不在运行（一用一备时只有一台停属正常）"),
        "PH-38": ("重烃泵组", OR(calc_cond("CALC-08", ">", 10, 300), cond(P("102LRC101"), ">=", V(95), 300)),
                  "排查 2：偏差 10%、全开 95% 为占位阈值，待现场提供"),
        "PH-39": ("重烃储罐组·公共测点", AND(tag_cond("HZO_106", "=", V(0), 60), tag_cond("HZO_111A", "=", V(0), 60)),
                  "排查 3：入口阀即画面上的倒罐阀 105HV106A / 105HV111A，按开反馈判断"),
        "PH-40": ("重烃进罐管线总阀", OR(cond(P("105_LZO_104"), "=", V(0), 60)), "排查 4：按开反馈判断"),
        "PH-41": ("重烃储罐组", OR(cond(P("105PT104"), ">", V(1.4), 120)),
                  "排查 5：1.4 MPa 取规程（旧版）附录四重烃储罐压力高报警；只有入口阀开启的那台有意义"),
        "PH-42": ("重烃收集罐", OR(cond(P("102PT102"), "<", T("PL-102PT102", "normalLow", 0.2), 300)),
                  "排查 6：排查表写「正常 0.3 左右」"),
    }
    phen = []
    for pid, (anchor, rule, note) in rules.items():
        _, name, _, cat, sev, text, tags, basis = meta[pid]
        phen.append({"id": pid, "name": name, "anchor": c.anchor(anchor), "category": cat, "severity": sev,
                     "description": text, "rule": rule, "note": note, "status": DRAFT,
                     "source": {"kind": "现场异常排查表" if "排查表" in basis else "规程（旧版）/ 点表",
                                "ref": basis.replace(K.SOP, OLD)}})
    links = [{"id": f"CL-{i:02d}", "cause": a, "effect": b, "mechanism": m, "basis": s.replace(K.SOP, OLD), "confidence": conf,
              "status": DRAFT, "source": {"kind": "现场异常排查表" if "排查表" in s else "规程（旧版）/ 机理",
                                         "ref": s.replace(K.SOP, OLD)}}
             for i, (a, b, m, s, conf) in enumerate([x for x in K.CAUSAL if not (x[0] == "PH-25" and x[1] == "PH-26")], 1)]
    segs = {u[1]: f"SEG-{u[0][1:]}" for u in K.UNITS}

    def seg(name):
        return {"kind": "segment", "id": segs[name], "name": name}
    calcs = [
        {"id": "CALC-01", "name": "塔顶温度变化速率", "anchor": c.anchor("脱甲烷塔"), "algorithmId": "ALG-RATE",
         "bindings": {"series": {"kind": "parameter", "name": P("104TT115")}, "windowMin": {"kind": "const", "value": 30}},
         "unit": "℃/min", "description": "脱甲烷塔顶部温度 30 分钟平均变化速率；规程要求降温速度 ≤ 20 ℃/h（-60 ℃ 以下 ≤ 10 ℃/h）",
         "basis": OLD + " 2.2.5.3", "status": DRAFT},
        {"id": "CALC-02", "name": "重烃储罐液位上升速率", "anchor": c.anchor("重烃储罐组"), "algorithmId": "ALG-RATE",
         "bindings": {"series": {"kind": "parameter", "name": P("105LT104")}, "windowMin": {"kind": "const", "value": 30}},
         "unit": "%/min", "description": "逐台计算；判断何时到 70% 需倒罐", "basis": OLD + " 4.2.5.3", "status": DRAFT},
        {"id": "CALC-03", "name": "两台膨胀机转速差", "anchor": seg("冷冻分离单元"), "algorithmId": "ALG-RANGE",
         "bindings": {"series": {"kind": "groupParameter", "groupId": c.group["膨胀压缩机组"]["id"], "name": P("104SI180A")}},
         "unit": "rpm", "description": "1#/2# 膨胀机转速逐时刻 最高 − 最低，看两台负荷是否均衡（跨装置统计示例）",
         "basis": "跨装置统计示例", "status": DRAFT},
        {"id": "CALC-04", "name": "压缩机电机定子平均温度", "anchor": c.anchor("原料气压缩机"), "algorithmId": "ALG-MEAN",
         "bindings": {"series": {"kind": "parameter", "name": P("a102_TISA136")}},
         "unit": "℃", "description": "电机定子 3 支温度（a102_TISA136～138）的均值", "basis": "点表", "status": DRAFT},
        {"id": "CALC-05", "name": "换热器原料气差压上升速率", "anchor": c.anchor("冷箱Ⅱ"), "algorithmId": "ALG-RATE",
         "bindings": {"series": {"kind": "parameter", "name": "原料气压差"}, "windowMin": {"kind": "const", "value": 60}},
         "unit": "kPa/min", "description": "一级 / 二级贫富气换热器原料气差压 60 分钟平均上升速率，冻堵时持续上升",
         "basis": OLD + " 1.2.7.3", "status": DRAFT},
        {"id": "CALC-06", "name": "膨胀机膨胀端 / 增压端振动差", "anchor": c.anchor("膨胀压缩机组"), "algorithmId": "ALG-ABS-DIFF",
         "bindings": {"a": {"kind": "parameter", "name": P("104XE180AX")}, "b": {"kind": "parameter", "name": P("104XE181AX")}},
         "unit": "μm", "description": "逐台计算膨胀端与增压端 X 轴振动之差", "basis": "点表", "status": DRAFT},
        {"id": "CALC-07", "name": "重烃收集罐烃室液位上升速率", "anchor": c.anchor("重烃收集罐"), "algorithmId": "ALG-RATE",
         "bindings": {"series": {"kind": "parameter", "name": P("102LT102")}, "windowMin": {"kind": "const", "value": 10}},
         "unit": "%/min", "description": "烃室液位 102LT102 在 10 分钟时间窗内的平均变化速率（正为上涨），判「持续上涨」用",
         "basis": "现场异常排查表", "status": DRAFT},
        {"id": "CALC-08", "name": "变频重烃泵输出与反馈偏差", "anchor": c.anchor("重烃泵组"), "algorithmId": "ALG-ABS-DIFF",
         "bindings": {"a": {"kind": "parameter", "name": P("102LRC101")}, "b": {"kind": "parameter", "name": P("102SI101")}},
         "unit": "%", "description": "逐台：变频控制（输出）与变频反馈之差的绝对值", "basis": "现场异常排查表 排查 2", "status": DRAFT},
    ]
    return phen, links, calcs


def main(argv=None):
    force = "--force" in (argv or sys.argv[1:])
    SEED.mkdir(parents=True, exist_ok=True)
    targets = {n: SEED / f"{n}.json" for n in ("phenomena", "causal_links", "calculations")}
    if not force and all(p.exists() and json.loads(p.read_text("utf-8")).get("items") for p in targets.values()):
        print("种子数据已存在，未覆盖（--force 覆盖）")
        return 0
    c = Ctx()
    phen, links, calcs = build(c)
    note = "种子数据：由 backend/tools/build_cryo_seed.py 生成，全部为草案·待工艺确认（规程为旧版，阈值仅作参考）"
    for name, items in (("phenomena", phen), ("causal_links", links), ("calculations", calcs)):
        targets[name].write_text(json.dumps({"note": note, "items": items}, ensure_ascii=False, indent=1), "utf-8")
    print(f"现象 {len(phen)}，根因关系 {len(links)}，计算组态 {len(calcs)}")
    if c.missing:
        print("以下阈值没有对应限值，按数值写入：", "；".join(c.missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
