"""生成开发态类库种子 data/seed/classlib.json（由 105 车间实例归纳；已存在不覆盖，--force 覆盖）。

    python3 -m backend.tools.build_classlib [--force]

- 元类：需求 4.2.1 预置 17 个 + 扩展 2 个（能源计量点、组织单元，预留），含可用属性、可用页签、可参与关系、图谱样式；
- 层级类型 / 模板：车间—工艺段—工序—子工序（105 车间在用）、资产分类、工艺参数目录；
- 类：元类「设备」根类（抽象）→ 资产大类（抽象）→ 设备类型（类）；另有 设备组 / 参数 / 物料流股 / 公用介质 / 质量指标 / 业务指标 根类；
  各类模板取自该类设备组上已有定义：属性（设计参数模板）、参数模板（参数页签）、约束模板（工艺限值）、现象 / 工况模板、根因模板、
  工艺影响模板；所有子类都有的设计属性上提到根类、同一资产大类下所有子类都有的参数模板上提到资产大类，形成继承；
- 关系类型（附录 B）、映射规则（位号解析 / 设备识别 / P&ID 图元 / 外部编码）、能力（能力登记表 + 计算组态）；
- 版本：v0.1 已发布（快照）+ v0.2 编辑中。全部为草案·待工艺确认。
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from typing import Any

from backend.v2.classlib import SEED
from backend.v2.context import get_ctx
from backend.v2 import devtime
from backend.v2.search import initials

STAMP = datetime.now().strftime("%Y-%m-%d %H:%M")


def code_of(name: str, prefix: str = "") -> str:
    ini = initials(name).upper()
    ini = "".join(ch for ch in ini if ch.isalnum()) or "X"
    return prefix + ini[:12]


def quantity(name: str, unit: str) -> str:
    u = (unit or "").lower()
    for k, q in (("℃", "温度"), ("°c", "温度"), ("mpa", "压力"), ("kpa", "压力"), ("ph", "pH"), ("l/h", "流量"), ("m3/h", "流量"),
                 ("开关量", "开关量"), ("hz", "频率"), ("%", "开度")):
        if k in u:
            return q
    for k in ("温度", "压力", "液位", "流量", "pH", "转速", "振动", "频率", "开度", "电流"):
        if k in name:
            return k
    return ""


METACLASSES = [
    ("MC_NODE", "层级节点", "空间层级的节点（车间 / 工艺段 / 工序 / 子工序）", "#1e40af", "圆角矩形"),
    ("MC_EQGRP", "设备组", "同一工序内功能、类型相同的设备集合，成套机组", "#ea7a1a", "圆形"),
    ("MC_EQUIP", "设备", "现场具有稳定身份的具体设备实例，如水解罐、离心机、泵", "#f59e0b", "圆形"),
    ("MC_PARAM", "参数", "设备 / 设备组 / 物料流股等对象的工艺量或设备量", "#22c55e", "圆形"),
    ("MC_TAG", "位号引用", "XBase 位号目录中的位号（本 Demo 以点表代替）", "#64748b", "小圆"),
    ("MC_STREAM", "物料流股", "工艺物料", "#6366f1", "菱形"),
    ("MC_UTIL", "公用介质", "水、汽、气等公用介质", "#10b981", "菱形"),
    ("MC_PRODUCT", "产品", "产品（暂无数据源）", "#0ea5e9", "菱形"),
    ("MC_QI", "质量指标", "质量指标（LIMS / 在线分析）", "#a855f7", "三角"),
    ("MC_KPI", "业务指标", "经营与成本指标", "#9333ea", "三角"),
    ("MC_PHEN", "现象", "带判定规则的状态描述", "#dc2626", "圆形"),
    ("MC_COND", "工况", "运行状态（开车、正常、反应期…），被约束引用", "#64748b", "矩形"),
    ("MC_CALC", "计算组态", "引用算法 + 参数绑定", "#0e8fa3", "矩形"),
    ("MC_ALGO", "算法", "算法库登记的调用契约", "#7c3aed", "矩形"),
    ("MC_PROC", "处置规程", "处置卡：步骤、检查项、执行边界", "#b45309", "矩形"),
    ("MC_DWG", "图纸", "P&ID / DCS 画面 / 示意图", "#334155", "矩形"),
    ("MC_ELEM", "图元", "图纸上的图元与热区", "#94a3b8", "小矩形"),
]
EQ_ATTRS = [("tag_no", "设备位号", "文本", True), ("eq_group", "所属设备组", "对象引用", False),
            ("home_node", "主归属层级节点", "对象引用", True), ("vendor", "制造商 / 型号", "文本", False), ("in_service", "投用日期", "日期", False)]
META_RELS = {"MC_EQUIP": ["REL_CONTAINS", "REL_TOPO", "REL_FLOW", "REL_SUPPLY", "REL_HASPROP", "REL_MOUNT", "REL_ELEM", "REL_TYPE"],
             "MC_EQGRP": ["REL_CONTAINS", "REL_TOPO", "REL_FLOW", "REL_SUPPLY", "REL_HASPROP", "REL_MOUNT", "REL_TYPE"],
             "MC_NODE": ["REL_CONTAINS", "REL_SCREEN", "REL_FLOW"], "MC_PARAM": ["REL_HASPROP", "REL_MAP", "REL_INFL", "REL_CALC", "REL_MOUNT"],
             "MC_PHEN": ["REL_MOUNT", "REL_CAUSES", "REL_PROC"], "MC_COND": ["REL_MOUNT", "REL_CAUSES", "REL_COND"],
             "MC_STREAM": ["REL_FLOW", "REL_HASPROP"], "MC_UTIL": ["REL_SUPPLY"], "MC_TAG": ["REL_MAP"], "MC_QI": ["REL_INFL", "REL_HASPROP"],
             "MC_CALC": ["REL_CALC"], "MC_PROC": ["REL_PROC"], "MC_DWG": ["REL_SCREEN"], "MC_ELEM": ["REL_ELEM"]}


def build() -> dict[str, Any]:
    ctx = get_ctx()
    dcs = ctx.store.dcs

    metas = []
    for code, name, desc, color, shape in METACLASSES:
        metas.append({"code": code, "name": name, "desc": desc, "preset": True, "style": {"color": color, "shape": shape},
                      "attrs": [{"code": c, "name": n, "dtype": t, "required": r} for c, n, t, r in EQ_ATTRS] if code in ("MC_EQUIP", "MC_EQGRP") else [],
                      "tabs": devtime_tabs(code), "relations": META_RELS.get(code, [])})
    metas += [{"code": "MC_X_ENERGY", "name": "能源计量点", "desc": "扩展元类（预留，暂无数据源）", "preset": False,
               "style": {"color": "#f97316", "shape": "圆形"}, "attrs": [], "tabs": ["参数", "拓扑关系"], "relations": ["REL_SUPPLY"]},
              {"code": "MC_X_ORG", "name": "组织单元", "desc": "扩展元类（预留，暂无数据源）", "preset": False,
               "style": {"color": "#0f766e", "shape": "圆角矩形"}, "attrs": [], "tabs": [], "relations": ["REL_CONTAINS"]}]

    htypes = [
        {"code": "WORKSHOP", "name": "车间", "parents": [], "children": ["SECTION"], "drawing": False, "card": True, "ordered": False},
        {"code": "SECTION", "name": "工艺段", "parents": ["WORKSHOP"], "children": ["PROCESS"], "drawing": False, "card": True, "ordered": True},
        {"code": "PROCESS", "name": "工序", "parents": ["SECTION"], "children": ["SUBPROC", "MC_EQGRP", "MC_EQUIP"], "drawing": True, "card": False, "ordered": True},
        {"code": "SUBPROC", "name": "子工序", "parents": ["PROCESS"], "children": ["MC_EQGRP", "MC_EQUIP"], "drawing": False, "card": False, "ordered": True,
         "note": "105 车间的子工序写在图纸 / 示意图顶部（工序链），不单独成层"},
        {"code": "ASSET_CAT", "name": "资产大类", "parents": [], "children": ["ASSET_TYPE"], "drawing": False, "card": False, "ordered": False},
        {"code": "ASSET_TYPE", "name": "设备类型", "parents": ["ASSET_CAT"], "children": ["MC_EQGRP"], "drawing": False, "card": False, "ordered": False},
        {"code": "PARAM_SEG", "name": "工段（参数目录）", "parents": [], "children": ["MC_PARAM"], "drawing": False, "card": False, "ordered": False},
    ]
    for t in htypes:
        t.setdefault("maxDepth", 8)
        t["preset"] = False
    htemplates = [
        {"code": "TPL_WORKSHOP", "name": "车间模板", "levels": ["WORKSHOP", "SECTION", "PROCESS", "SUBPROC"], "projects": ["105车间"], "kind": "空间层级"},
        {"code": "TPL_ASSET", "name": "资产分类", "levels": ["ASSET_CAT", "ASSET_TYPE"], "projects": ["105车间"], "kind": "工业资产视角"},
        {"code": "TPL_PARAM", "name": "工艺参数目录", "levels": ["PARAM_SEG"], "projects": ["105车间"], "kind": "工艺参数视角"},
    ]

    # ---- 类
    classes: list[dict[str, Any]] = []

    def new_class(cid: str, code: str, name: str, meta: str, parent: str | None, abstract: bool, order: int, desc: str = "") -> dict[str, Any]:
        c = {"id": cid, "code": code, "name": name, "metaclass": meta, "parent": parent, "abstract": abstract, "status": "草案",
             "icon": "", "desc": desc, "tabs": None, "order": order, "attrs": [], "params": [], "constraints": [], "phenomena": [],
             "causes": [], "influences": [], "caps": [], "createdAt": STAMP, "updatedAt": STAMP}
        classes.append(c)
        return c

    root = new_class("cls-equipment", "CLS-EQ", "设备", "MC_EQUIP", None, True, 1, "设备根类（抽象）：所有设备类继承其属性与能力")
    for i, (n, label, mc) in enumerate((("设备组", "设备组根类（抽象）", "MC_EQGRP"), ("参数", "参数根类（抽象）", "MC_PARAM"),
                                        ("物料流股", "物料流股根类（抽象）", "MC_STREAM"), ("公用介质", "公用介质根类（抽象）", "MC_UTIL"),
                                        ("质量指标", "质量指标根类（抽象）", "MC_QI"), ("业务指标", "业务指标根类（抽象）", "MC_KPI"))):
        new_class(f"cls-root-{mc.lower()}", f"CLS-{mc[3:]}", n, mc, None, True, 2 + i, label)

    tree = devtime.class_tree(ctx)["items"][0]
    tpl_params: list[set[str]] = []
    type_classes = []
    for ci, cat in enumerate(tree["children"]):
        cat_name = cat["label"]
        cc = new_class(f"cls-cat-{code_of(cat_name).lower()}", code_of(cat_name, "CLS-EQ-"), cat_name, "MC_EQUIP", root["id"], True, ci,
                       f"资产大类「{cat_name}」（抽象）")
        for ti, t in enumerate(cat["children"]):
            d = devtime.class_detail(ctx, t["id"])
            tc = new_class(f"cls-type-{code_of(d['name']).lower()}", code_of(d["name"], cc["code"] + "-"), d["name"], "MC_EQUIP", cc["id"], False, ti,
                           f"设备类型「{d['name']}」：由 {d['counts']['groups']} 个设备组 / {d['counts']['equipment']} 台设备归纳")
            tc["_groups"] = [i["id"] for i in d["instances"]]
            # 属性：设计参数模板
            root_names = {n for _, n, _, _ in EQ_ATTRS} | {"制造厂家"}
            for a in d["attributes"]:
                if a["from"].startswith("本类") and a["name"] not in root_names:
                    tc["attrs"].append({"code": code_of(a["name"], "A_"), "name": a["name"], "group": "设计", "dtype": "实数" if a["type"] not in ("文本", "") else "文本",
                                        "unit": a["type"] if a["type"] not in ("文本",) else "", "required": False, "default": "", "enum": "",
                                        "range": "", "desc": a.get("note") or ""})
            tpl_params.append({x["name"] for x in tc["attrs"]})
            # 参数模板
            used = set()
            for p in d["parameters"]:
                pcode = code_of(p["name"].rstrip("*"), "P_")
                while pcode in used:
                    pcode += "_"
                used.add(pcode)
                unit = (p["valueType"].split("·")[-1].strip() if "·" in p["valueType"] else "")
                funcs = sorted({e.split("_")[0] for e in p["tagExamples"] if "_" in e})
                rep = any(e[-1:].isdigit() and e.split("_")[0] in ("AT",) for e in p["tagExamples"])
                tc["params"].append({"code": pcode, "name": p["name"].rstrip("*"), "category": p["category"], "quantity": quantity(p["name"], unit),
                                     "unit": unit, "dtype": "布尔" if "bool" in p["valueType"] else ("实数" if p["valueType"] not in ("—", "") else "实数"),
                                     "repeatable": rep, "dims": [{"name": "序号", "values": ["1", "2"]}] if rep else [],
                                     "tagRule": {"funcs": "|".join(funcs), "keywords": quantity(p["name"], unit) or p["name"].rstrip("*")},
                                     "required": p["required"], "semantic": p["semantic"], "desc": "工艺属性（语义参数）" if p["semantic"] else ""})
            # 约束模板
            for c in d["constraints"]:
                lim = ctx.limits.get(c["id"]) or {}
                tc["constraints"].append({"code": c["id"], "param": c["parameter"], "ctype": "工艺限值", "ll": lim.get("lowLow"), "l": lim.get("low"),
                                          "nl": lim.get("normalLow"), "nh": lim.get("normalHigh"), "h": lim.get("high"), "hh": lim.get("highHigh"),
                                          "unit": c.get("unit") or "", "source": "模板默认值", "expr": "", "cond": c["mode"], "priority": 1,
                                          "override": "允许 · 覆盖时保留模板值对比"})
            # 现象 / 工况模板
            gset = set(tc["_groups"])
            seen = {}
            for p in ctx.phen.phenomena.values():
                if (p.get("anchor") or {}).get("id") in gset and p["name"] not in seen:
                    seen[p["name"]] = p
            for k, (pname, p) in enumerate(seen.items()):
                tc["phenomena"].append({"code": f"PHT-{tc['code'][-6:]}-{k + 1:02d}", "name": pname, "category": p.get("category"),
                                        "severity": p.get("severity"), "desc": p.get("description") or "", "rule": copy.deepcopy(p.get("rule")),
                                        "status": "草案"})
            for k, cz in enumerate(d["causes"]):
                tc["causes"].append({"code": f"CT-{tc['code'][-6:]}-{k + 1:02d}", "cause": cz["cause"], "effect": cz["effect"],
                                     "mechanism": cz["mechanism"], "confidence": cz["confidence"] or "中", "evidence": "处置卡 / 规则表",
                                     "cond": "全部工况", "path": "" if cz["scope"] == "类内" else f"{cz['scope']}：两者存在连接 / 供应关系时生成"})
            for k, r in enumerate(d["influences"]):
                tc["influences"].append({"code": f"IT-{tc['code'][-6:]}-{k + 1:02d}", "from": r["from"], "to": r["to"],
                                         "direction": {"正向影响": "正相关", "负向影响": "负相关"}.get(r["direction"], "非单调"),
                                         "strength": "中", "lag": "", "cond": "", "mechanism": r["mechanism"], "scope": "类内"})
            type_classes.append(tc)

    # 所有设备类型都有的设计属性 → 根类；同一资产大类下所有子类都有的参数模板 → 资产大类
    common = set.intersection(*tpl_params) if tpl_params else set()
    lifted = {}
    for tc in type_classes:
        keep = []
        for a in tc["attrs"]:
            if a["name"] in common:
                lifted.setdefault(a["code"], a)
            else:
                keep.append(a)
        tc["attrs"] = keep
    root["attrs"] = [{"code": c, "name": n, "group": "基础", "dtype": t, "unit": "", "required": r, "default": "",
                      "enum": "", "range": "", "desc": "元类「设备」可用属性"} for c, n, t, r in EQ_ATTRS] + \
                    [{**a, "group": "铭牌"} for a in lifted.values()]
    for cc in [c for c in classes if c["id"].startswith("cls-cat-")]:
        kids = [t for t in type_classes if t["parent"] == cc["id"]]
        if len(kids) < 2:
            continue
        names = set.intersection(*[{p["name"] for p in k["params"]} for k in kids])
        for n in sorted(names):
            p = next(p for p in kids[0]["params"] if p["name"] == n)
            cc["params"].append(copy.deepcopy(p))
            for k in kids:
                k["params"] = [x for x in k["params"] if x["name"] != n]

    # ---- 能力
    caps = []
    prof = ctx.profile(next(iter(dcs.equipment_groups)))
    for c in prof.get("capabilities") or []:
        caps.append({"code": c["id"], "name": c["name"], "classes": [root["id"]], "algorithm": "", "version": "", "mode": "同步", "timeout": 10,
                     "desc": c.get("description") or "", "provider": c.get("provider") or "", "inputs": [], "outputs": []})
    root["caps"] = [c["code"] for c in caps]
    type_of_group = {gid: tc["id"] for tc in type_classes for gid in tc["_groups"]}
    for calc in ctx.calcs.items.values():
        gid = (calc.get("anchor") or {}).get("id")
        cid = type_of_group.get(gid)
        algo = ctx.algos.items.get(calc.get("algorithmId") or "") or {}
        code = "CAP-" + calc["id"].replace("CALC-", "")
        caps.append({"code": code, "name": calc["name"], "classes": [cid] if cid else [], "algorithm": calc.get("algorithmId"),
                     "version": algo.get("version") or "", "mode": "同步", "timeout": 30, "desc": calc.get("description") or "",
                     "provider": "算法服务（本 Demo 内置实现）",
                     "inputs": [{"name": k, "type": next((i["type"] for i in algo.get("inputs") or [] if i["name"] == k), ""),
                                 "unit": next((i.get("unit") or "" for i in algo.get("inputs") or [] if i["name"] == k), ""),
                                 "bind": b.get("name") or b.get("tag") or str(b.get("value", ""))} for k, b in (calc.get("bindings") or {}).items()],
                     "outputs": [{"name": (algo.get("output") or {}).get("name") or "out", "type": "实数", "unit": calc.get("unit") or "",
                                  "write": calc["name"] + "（计算值）"}]})
        if cid:
            next(t for t in type_classes if t["id"] == cid)["caps"].append(code)
    for tc in type_classes:
        tc.pop("_groups", None)

    # ---- 关系类型（附录 B）
    rel_rows = devtime.relation_types(ctx)["items"]
    rel_codes = ["REL_CONTAINS", "REL_SCREEN", "REL_TOPO", "REL_FLOW", "REL_SUPPLY", "REL_HASPROP", "REL_MAP", "REL_INFL", "REL_CALC",
                 "REL_MOUNT", "REL_CAUSES", "REL_COND", "REL_PROC", "REL_TYPE", "REL_ELEM"]
    attrs = {"REL_CAUSES": [{"name": "置信度", "type": "枚举", "values": "高 / 中 / 低"}, {"name": "机理说明", "type": "文本", "values": ""},
                            {"name": "证据依据", "type": "枚举+文本", "values": "经验 / 文档 / 历史事件 / 数据分析"}, {"name": "适用条件", "type": "工况引用", "values": ""}],
             "REL_INFL": [{"name": "方向", "type": "枚举", "values": "正相关 / 负相关 / 非单调"}, {"name": "强度", "type": "枚举", "values": "强 / 中 / 弱"},
                          {"name": "典型时滞", "type": "文本", "values": ""}],
             "REL_MAP": [{"name": "映射类型", "type": "枚举", "values": "一对一 / 合成 / 公共测点"}, {"name": "单位换算", "type": "文本", "values": ""}],
             "REL_ELEM": [{"name": "映射状态", "type": "枚举", "values": "已对应 / 待确认"}]}
    rels = []
    for code, r in zip(rel_codes, rel_rows):
        views = [v for v in ("工艺流程", "设备与参数", "现象因果") if v in r["views"]]
        rels.append({"code": code, "name": r["name"], "inverse": r["inverse"], "from": r["from"], "to": r["to"],
                     "direction": "有向", "cardinality": "多对多", "transitive": code == "REL_CONTAINS", "symmetric": False,
                     "noCycle": code in ("REL_CAUSES", "REL_CONTAINS"), "views": views, "ttl": r["ttl"].split(" ")[0] if r["ttl"] != "—" else "",
                     "attrs": attrs.get(code, []), "desc": r["attrs"], "preset": True,
                     "style": {"line": "实线", "color": "#dc2626" if code == "REL_CAUSES" else "#6366f1", "lowConfidence": "虚线" if code == "REL_CAUSES" else ""}})

    # ---- 映射规则
    func_map = devtime.FUNC
    mrules = []
    segs = {"MR-01": ["$1 仪表功能字母", "$2 区域号", "$3 回路号", "$4 台号", "$5 序号"],
            "MR-02": ["$1 设备功能字母", "$2 区域号", "$3 回路号", "$4 台号", "$5 块后缀"],
            "MR-03": ["$1 拼音缩写", "$2 台号"], "MR-04": []}
    for i, r in enumerate(devtime.MAP_RULES):
        pat = r["pattern"].replace("?P<func>", "").replace("?P<area>", "").replace("?P<loop>", "").replace("?P<unit>", "") \
            .replace("?P<seq>", "").replace("?P<suffix>", "").replace("?P<equip>", "")
        mrules.append({"code": r["code"], "kind": "位号解析", "name": r["name"], "priority": (i + 1) * 10, "pattern": pat,
                       "segments": segs[r["code"]], "target": r["target"], "descMatch": "按位号描述关键字匹配参数模板（温度 / 液位 / pH / 流量…）",
                       "locate": "台号 + 区域号 → 同区域内同台号设备；或描述中出现的设备名称", "threshold": 0.9,
                       "status": "草案" if r["code"] == "MR-04" else "生效", "confidence": r["confidence"]})
    names = {tc["name"]: tc for tc in type_classes}
    for k, t in enumerate(ctx.design.templates, start=1):
        kws = [w for w in t.get("keywords") or [] if w]
        if not kws:
            continue
        target = names.get(t["name"])
        mrules.append({"code": f"ER-{k:02d}", "kind": "设备识别", "name": f"名称含「{'|'.join(kws)}」→ {t['name']}", "priority": k * 10,
                       "pattern": "(" + "|".join(kws) + ")", "segments": ["$1 名称关键字"],
                       "target": f"类 {t['name']}" if target else f"设计参数模板「{t['name']}」", "descMatch": "", "locate": "",
                       "threshold": 0.8, "status": "生效", "confidence": "中"})
    mrules += [{"code": "PR-01", "kind": "P&ID 图元", "name": "互时图元类型 → 本体类（待互时图元清单）", "priority": 10, "pattern": "", "segments": [],
                "target": "设备 / 设备组", "descMatch": "", "locate": "", "threshold": 0.9, "status": "草案", "confidence": "—"},
               {"code": "XR-01", "kind": "外部编码", "name": "MOM 物料编码 → 物料流股（待 MOM 编码表）", "priority": 10, "pattern": "", "segments": [],
                "target": "物料流股", "descMatch": "", "locate": "", "threshold": 0.9, "status": "草案", "confidence": "—"}]

    content = {"metaclasses": metas, "hierarchyTypes": htypes, "hierarchyTemplates": htemplates, "classes": classes,
               "relationTypes": rels, "mappingRules": mrules, "capabilities": caps}
    return {"library": {"name": "105 车间工业类库", "note": "由 105 车间实例归纳生成，全部为草案·待工艺确认", "funcMap": func_map},
            **content,
            "versions": [{"version": "v0.1", "status": "已发布", "createdAt": STAMP, "publishedAt": STAMP, "note": "由 105 车间实例归纳生成（初始版本）",
                          "snapshot": None},  # 加载时补成当前内容的快照（种子文件不重复存一份）
                         {"version": "v0.2", "status": "编辑中", "createdAt": STAMP, "base": "v0.1", "note": ""}]}


def devtime_tabs(code: str) -> list[str]:
    from backend.v2.classlib import TABS
    if code in ("MC_EQUIP", "MC_EQGRP"):
        return list(TABS)
    if code == "MC_PARAM":
        return ["参数约束", "工艺影响关系", "计算组态"]
    if code in ("MC_STREAM", "MC_UTIL"):
        return ["参数", "拓扑关系"]
    if code in ("MC_PHEN", "MC_COND"):
        return ["现象/工况定义", "根因影响关系", "处置规程"]
    return []


def main() -> None:
    if SEED.exists() and "--force" not in sys.argv:
        print(f"{SEED} 已存在（--force 覆盖）")
        return
    data = build()
    SEED.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    c = data["classes"]
    print(f"已生成 {SEED}：元类 {len(data['metaclasses'])}、类 {len(c)}、关系类型 {len(data['relationTypes'])}、"
          f"映射规则 {len(data['mappingRules'])}、能力 {len(data['capabilities'])}")


if __name__ == "__main__":
    main()
