"""开发态（需求 4.2）：元模型、层级类型、类库、关系类型、映射规则。

本 Demo 没有单独维护的类库数据：类由 105 车间的实例归纳得到（设备类型 = 类，资产大类 = 抽象父类，元类「设备」为根），
类的参数 / 约束 / 现象 / 根因 / 工艺影响「模板」= 该类各设备组上已有定义的并集，并标出覆盖了几个设备组。
全部为「草案·待工艺确认」，开发态界面只读；开发态修改触发工程态更新的联动不做。
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any

from backend.v2.context import AppContext

LIB_VERSION = {"version": "v0.1", "status": "编辑中（草案）", "note": "由 105 车间实例归纳生成，待工艺 / 产品团队整理为可复用类库"}


def _code(name: str) -> str:
    return "CLS-" + hashlib.md5(name.encode()).hexdigest()[:6].upper()


# ------------------------------------------------------------------ 类树
def class_tree(ctx: AppContext) -> dict[str, Any]:
    dcs = ctx.store.dcs
    h = ctx.hierarchy
    cats: dict[str, dict[str, list[str]]] = {}
    for gid, g in dcs.equipment_groups.items():
        etype = (g.get("equipmentType") or "").strip() or "未分类"
        path = (ctx.profile(gid).get("header") or {}).get("classPath") or []
        cat = path[1] if len(path) > 2 else "其他"
        cats.setdefault(cat, {}).setdefault(etype, []).append(gid)
    children = []
    for cat, types in sorted(cats.items()):
        kids = []
        for etype, gids in sorted(types.items()):
            equips = [e for e, x in dcs.equipment.items() if x.get("equipmentGroupId") in gids]
            in_nav = [g for g in gids if h.ops_of_group.get(g)]
            kids.append({"id": f"type:{etype}", "label": etype, "code": _code(etype), "kind": "class", "abstract": False,
                         "groups": len(gids), "groupsInNav": len(in_nav), "equipment": len(equips)})
        children.append({"id": f"cat:{cat}", "label": cat, "code": _code(cat), "kind": "class", "abstract": True,
                         "groups": sum(k["groups"] for k in kids), "equipment": sum(k["equipment"] for k in kids), "children": kids})
    root = {"id": "meta:设备", "label": "设备", "code": "META-EQUIPMENT", "kind": "metaclass", "abstract": True,
            "groups": sum(c["groups"] for c in children), "equipment": sum(c["equipment"] for c in children), "children": children}
    return {"items": [root], "version": LIB_VERSION}


def _groups_of_type(ctx: AppContext, etype: str) -> list[str]:
    return [g for g, x in ctx.store.dcs.equipment_groups.items() if ((x.get("equipmentType") or "").strip() or "未分类") == etype]


def class_detail(ctx: AppContext, class_id: str) -> dict[str, Any]:
    from backend.v2 import tabs
    from backend.v2.phenomena import rule_text
    if class_id.startswith("cat:") or class_id.startswith("meta:"):
        tree = class_tree(ctx)["items"][0]
        node = tree if class_id.startswith("meta:") else next((c for c in tree["children"] if c["id"] == class_id), None)
        if not node:
            raise LookupError(class_id)
        return {"id": class_id, "name": node["label"], "code": node["code"], "abstract": True,
                "metaclass": "设备", "parent": None if class_id.startswith("meta:") else "设备",
                "subclasses": [{"id": c["id"], "name": c["label"], "groups": c["groups"], "equipment": c["equipment"]} for c in node.get("children") or []],
                "note": "抽象类：只用于被继承，不能直接创建实例；子类继承本类的属性、参数模板、约束与现象模板"}
    etype = class_id.split(":", 1)[1]
    gids = _groups_of_type(ctx, etype)
    if not gids:
        raise LookupError(class_id)
    dcs, h = ctx.store.dcs, ctx.hierarchy
    first = ctx.profile(gids[0])
    path = (first.get("header") or {}).get("classPath") or []
    cat = path[1] if len(path) > 2 else "其他"
    n = len(gids)
    calc_names = {k: v["name"] for k, v in ctx.calcs.items.items()}

    # 类属性：元类「设备」的固有属性（继承）+ 本类设计参数模板
    attrs = [{"name": a, "type": t, "from": "继承自元类「设备」"} for a, t in
             (("设备编码", "文本"), ("设备类型", "枚举"), ("所属工段", "对象引用"), ("主要部件", "列表"), ("DCS 控制站", "文本"))]
    tpl = ctx.design.template_for(etype, dcs.equipment_groups[gids[0]]["name"]) or {}
    attrs += [{"name": p["name"], "type": p.get("unit") or "文本", "from": f"本类（设计参数模板「{tpl.get('name')}」）", "note": p.get("note") or ""}
              for p in tpl.get("params") or []]

    # 参数模板：各设备组参数的并集
    params: dict[str, dict[str, Any]] = {}
    for g in gids:
        try:
            items = tabs.tab(ctx, g, "parameters")["items"]
        except Exception:  # noqa: BLE001
            continue
        for x in items:
            if x["section"] != "参数":
                continue
            p = params.setdefault(x["name"], {"name": x["name"], "category": x["category"], "valueType": x["valueType"],
                                              "semantic": bool(x.get("semantic")), "groups": 0, "tagExamples": []})
            p["groups"] += 1
            for l in x["links"][:1]:
                if len(p["tagExamples"]) < 3 and l["tag"] not in p["tagExamples"]:
                    p["tagExamples"].append(l["tag"])
    for p in params.values():
        p["required"] = p["groups"] == n
        p["tagRule"] = _tag_pattern(p["tagExamples"])
    param_list = sorted(params.values(), key=lambda p: (-p["groups"], not p["semantic"], p["name"]))

    # 约束模板
    cons, seen = [], set()
    for g in gids:
        for c in (ctx.profile(g).get("constraints") or {}).get("operating") or []:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            l = ctx.limits.get(c["id"]) or {}
            cons.append({"id": c["id"], "parameter": c.get("appliesTo"), "mode": c.get("operatingMode") or "所有工况",
                         "values": "/".join(str(l.get(k) if l.get(k) is not None else "—") for k in ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")),
                         "unit": c.get("unit"), "source": "取工艺限值表（XBase 报警限待接入）", "status": c.get("status")})

    # 现象 / 工况模板、根因模板
    gset = set(gids)
    phen = [p for p in ctx.phen.phenomena.values() if (p.get("anchor") or {}).get("id") in gset]
    by_name: dict[str, dict[str, Any]] = {}
    for p in phen:
        t = by_name.setdefault(p["name"], {"name": p["name"], "category": p.get("category"), "severity": p.get("severity"),
                                           "ruleText": rule_text(p.get("rule"), ctx.limits, calc_names) if p.get("rule") else "（判定规则待定义）",
                                           "groups": 0, "ids": []})
        t["groups"] += 1
        t["ids"].append(p["id"])
    pid_set = {p["id"] for p in phen}
    causes = []
    for l in ctx.phen.links.values():
        inside = (l["cause"] in pid_set, l["effect"] in pid_set)
        if any(inside):
            c, e = ctx.phen.phenomena.get(l["cause"]) or {}, ctx.phen.phenomena.get(l["effect"]) or {}
            causes.append({"cause": c.get("name"), "effect": e.get("name"), "confidence": l.get("confidence"),
                           "scope": "类内" if all(inside) else f"跨类（{'原因' if not inside[0] else '结果'}在「{((c if not inside[0] else e).get('anchor') or {}).get('name')}」）",
                           "mechanism": l.get("mechanism") or ""})
    # 工艺影响模板
    infl, seen2 = [], set()
    for g in gids:
        for r in (ctx.profile(g).get("relations") or {}).get("attributeRelations") or []:
            if r.get("category") not in ("影响关系", "质量关系"):
                continue
            k = (r.get("from"), r.get("to"), r.get("predicate"))
            if k in seen2:
                continue
            seen2.add(k)
            infl.append({"from": r.get("from"), "to": r.get("to"), "direction": r.get("predicate"), "mechanism": r.get("mechanism") or ""})
    caps = {c["id"]: {k: c.get(k) for k in ("id", "name", "type", "description", "provider")} for g in gids for c in ctx.profile(g).get("capabilities") or []}
    instances = []
    for g in gids:
        ops = h.ops_of_group.get(g) or []
        members = [e for e, x in dcs.equipment.items() if x.get("equipmentGroupId") == g]
        instances.append({"id": g, "name": dcs.equipment_groups[g]["name"], "kind": "设备组", "opId": ops[0] if ops else None,
                          "segmentId": h.ops[ops[0]]["segmentId"] if ops else None, "members": len(members),
                          "inNav": bool(ops)})
    return {
        "id": class_id, "name": etype, "code": _code(etype), "metaclass": "设备", "parent": cat, "abstract": False,
        "status": "草案·待工艺确认", "libraryVersion": LIB_VERSION["version"],
        "visibleTabs": ["图纸位置与外观", "参数", "参数约束", "拓扑关系", "现象/工况定义", "根因影响关系", "工艺影响关系", "计算组态", "处置规程"],
        "attributes": attrs, "parameters": param_list, "constraints": cons,
        "phenomena": sorted(by_name.values(), key=lambda t: (-t["groups"], t["name"])), "causes": causes, "influences": infl,
        "capabilities": list(caps.values()), "instances": instances,
        "counts": {"groups": n, "equipment": sum(i["members"] for i in instances)},
        "note": f"模板由本类 {n} 个设备组上已有的定义归纳（「覆盖」= 有几个设备组有该定义；全部设备组都有的参数标为必备）",
    }


def _tag_pattern(examples: list[str]) -> str:
    if not examples:
        return ""
    pats = sorted({re.sub(r"\d", "#", re.sub(r"(?<=\d)[A-Z](?=\d?$|_)", "{x}", t)) for t in examples})
    return " / ".join(pats[:2])


# ------------------------------------------------------------------ 元模型
METACLASSES = [
    ("层级节点", "车间 / 工艺段 / 工序", "空间层级视角的节点"), ("设备组", "设备组", "同一工序内功能、类型相同的设备集合"),
    ("设备", "设备", "点表设备主数据"), ("参数", "工艺参数", "工艺属性（语义参数）与测点参数"),
    ("位号引用", "DCS 位号", "XBase 位号目录（本 Demo 用点表代替）"), ("物料流股", "物料流股", "工艺物料"),
    ("公用介质", "公用介质", "水、汽、气等"), ("产品", "—", "暂无数据源"), ("质量指标", "质量指标", "质量关系"),
    ("业务指标", "经营与成本", "成本数据待建"), ("现象", "现象", "带判定规则的状态描述"), ("工况", "工况", "类别为「工况」的现象"),
    ("计算组态", "计算组态", "引用算法 + 参数绑定"), ("算法", "算法库", "调用契约"), ("处置规程", "处置卡", "6APA_处置规程.xlsx"),
    ("图纸", "现场图纸 / 示意图", "工序图纸"), ("图元", "图纸热区", "热区与对象的对应"),
]


def metamodel(ctx: AppContext) -> dict[str, Any]:
    from backend.v2 import drawing, global_graph
    h, dcs = ctx.hierarchy, ctx.store.dcs
    g = global_graph.build(ctx)
    nc = g["nodeCounts"]
    spots = sum(len((drawing.image_view(ctx, o) or {}).get("hotspots") or []) for o in h.ops)
    counts = {"层级节点": len(h.workshops) + len(h.segments) + len(h.ops), "设备组": len(dcs.equipment_groups), "设备": len(dcs.equipment),
              "参数": nc.get("工艺参数", 0), "位号引用": len(dcs.tags), "物料流股": nc.get("物料流股", 0), "公用介质": nc.get("公用介质", 0),
              "产品": 0, "质量指标": nc.get("质量指标", 0), "业务指标": 0,
              "现象": sum(1 for p in ctx.phen.phenomena.values() if p.get("category") != "工况"),
              "工况": sum(1 for p in ctx.phen.phenomena.values() if p.get("category") == "工况"),
              "计算组态": len(ctx.calcs.items), "算法": len(ctx.algos.items), "处置规程": len(ctx.store.procedures.cards),
              "图纸": sum(1 for o in h.ops if drawing.image_path(o)) + len(h.ops), "图元": spots}
    items = [{"code": f"MC-{i + 1:02d}", "name": n, "demo": d, "note": note, "preset": True, "instances": counts.get(n, 0)}
             for i, (n, d, note) in enumerate(METACLASSES)]
    items += [{"code": "MC-X1", "name": "组织与人员", "demo": "—", "note": "扩展元类（预留，暂无数据源）", "preset": False, "instances": 0},
              {"code": "MC-X2", "name": "能源计量点", "demo": "—", "note": "扩展元类（预留，暂无数据源）", "preset": False, "instances": 0}]
    return {"items": items, "version": LIB_VERSION}


def hierarchy_types(ctx: AppContext) -> dict[str, Any]:
    h = ctx.hierarchy
    return {"templates": [
        {"name": "车间模板（105 车间在用）", "levels": [
            {"code": "HT-WS", "name": "车间", "parent": "—", "child": "工艺段", "drawing": False, "card": False, "count": len(h.workshops)},
            {"code": "HT-SEG", "name": "工艺段", "parent": "车间", "child": "工序", "drawing": False, "card": True, "count": len(h.segments)},
            {"code": "HT-OP", "name": "工序", "parent": "工艺段", "child": "设备组 / 设备", "drawing": True, "card": False, "count": len(h.ops)},
        ], "note": "子工序写在图纸 / 示意图顶部（同级顺序：工序链），不单独成层；层级配置在 data/config/6APA_空间层级.xlsx"},
        {"name": "资产分类层级", "levels": [
            {"code": "HT-ACAT", "name": "资产大类", "parent": "—", "child": "设备类型", "drawing": False, "card": False, "count": None},
            {"code": "HT-ATYPE", "name": "设备类型", "parent": "资产大类", "child": "设备组", "drawing": False, "card": False, "count": None},
        ], "note": "工业资产视角：资产大类 → 设备类型 → 设备组 → 设备"},
        {"name": "工艺参数目录", "levels": [{"code": "HT-PSEG", "name": "工段", "parent": "—", "child": "参数", "drawing": False, "card": False, "count": None}],
         "note": "工艺参数视角：工段 → 工艺属性"},
    ]}


# ------------------------------------------------------------------ 关系类型（附录 B）
def relation_types(ctx: AppContext) -> dict[str, Any]:
    from backend.v2 import drawing, global_graph
    g = global_graph.build(ctx)
    ec = g["edgeCounts"]
    nodes = {n["id"]: n for n in g["nodes"]}
    flow = sum(1 for e in g["edges"] if e["type"] == "物理拓扑" and "物料流股" in (nodes[e["s"]]["type"], nodes[e["t"]]["type"]))
    supply = sum(1 for e in g["edges"] if e["type"] == "物理拓扑" and "公用介质" in (nodes[e["s"]]["type"], nodes[e["t"]]["type"]))
    bindings = sum(len(t) for t in ctx.tags_of_equipment.values())
    calc_refs = sum(len(c.get("bindings") or {}) for c in ctx.calcs.items.values())
    limits_mode = sum(1 for l in ctx.limits.values() if l.get("operatingMode"))
    from backend.v2 import procedures
    proc_refs = sum(len(v) for v in procedures.phenomenon_index(ctx).values())
    spots = sum(len((drawing.image_view(ctx, o) or {}).get("hotspots") or []) for o in ctx.hierarchy.ops)
    rows = [
        ("RT-01", "包含", "属于", "层级节点、设备组", "层级节点、设备组、设备、参数", "有向，传递", "工艺流程、设备与参数", "onto:contains", "", ec.get("包含", 0)),
        ("RT-02", "画面衔接", "被衔接", "图纸", "图纸", "有向", "工艺流程", "onto:connectsOperation", "Demo 中由设备组跨工序的物理拓扑推出「工序衔接」", ec.get("工序衔接", 0)),
        ("RT-03", "物理拓扑（连接）", "连接", "设备、设备组", "设备、设备组", "有向", "工艺流程", "onto:physicallyConnectedTo", "", ec.get("物理拓扑", 0) - flow - supply),
        ("RT-04", "工艺流向（输入 / 输出）", "来自", "物料流股、设备", "设备、物料流股", "有向", "工艺流程", "onto:physicallyConnectedTo", "Demo 中与物理拓扑同存（物料端）", flow),
        ("RT-05", "供应", "被供应", "公用介质", "设备、设备组、工序", "有向", "工艺流程", "onto:physicallyConnectedTo", "Demo 中与物理拓扑同存（介质端）", supply),
        ("RT-06", "具有属性", "属于对象", "设备、设备组、工序、物料流股", "参数、质量指标", "有向", "设备与参数", "onto:hasProperty", "", ec.get("具有属性", 0)),
        ("RT-07", "参数映射", "映射自", "参数", "位号引用", "有向", "设备与参数", "—（未导出位号个体）", "映射类型、单位换算", bindings),
        ("RT-08", "工艺影响", "受影响于", "参数", "参数、质量指标", "有向", "设备与参数", "onto:influences", "方向、强度、时滞", ec.get("工艺影响", 0)),
        ("RT-09", "计算引用", "被计算引用", "计算组态", "参数、指标", "有向（输入 / 输出）", "设备与参数", "—", "", calc_refs),
        ("RT-10", "挂载", "挂有", "设备、设备组、参数", "现象、工况", "有向", "现象因果", "onto:mountedOn", "", ec.get("挂载", 0)),
        ("RT-11", "导致（根因影响）", "由…导致", "现象、工况", "现象", "有向", "现象因果", "onto:causes + onto:CausalLink", "置信度、机理、依据", ec.get("导致", 0)),
        ("RT-12", "适用工况", "约束", "约束", "工况", "有向", "—", "—", "", limits_mode),
        ("RT-13", "关联规程", "关联现象", "现象、工况、设备", "处置规程", "有向", "现象因果", "—", "", proc_refs),
        ("RT-14", "属于类型", "有实例", "实例", "类", "有向", "—", "rdf:type", "", len(ctx.store.dcs.equipment_groups)),
        ("RT-15", "图元对应", "对应图元", "图元", "对象", "有向", "—", "—", "已对应 / 待确认", spots),
    ]
    keys = ("code", "name", "inverse", "from", "to", "direction", "views", "ttl", "attrs", "count")
    return {"items": [dict(zip(keys, r)) for r in rows],
            "note": "预置关系类型见需求附录 B；「实例数」为本 Demo 当前本体中的关系条数；关系类型的增删改与视角配置在开发态维护（本 Demo 只读）"}


# ------------------------------------------------------------------ 映射规则（位号解析）
FUNC = {"TI": "温度指示", "TE": "温度", "TT": "温度变送", "PI": "压力指示", "PT": "压力变送", "FT": "流量变送", "FI": "流量指示",
        "LT": "液位变送", "LI": "液位指示", "AT": "分析变送（pH 等）", "AI": "分析指示", "HV": "手动 / 调节阀", "XV": "开关阀",
        "FV": "流量调节阀", "TV": "温度调节阀", "P": "泵 / 电机", "M": "电机", "SJGYW": "水解罐液位（拼音缩写）"}
SUFFIX = {"RUN": "运行反馈 → 状态", "FL": "故障 → 状态", "RM": "远程 / 就地 → 状态", "DO": "启停 / 开关指令 → 控制指令",
          "MOT2": "电机控制块 → 控制指令", "VAL2": "开关阀控制块 → 控制指令", "AO": "调节阀开度指令 → 阀位", "FT": "检测反馈 → 状态",
          "ZO": "开到位 → 状态", "ZC": "关到位 → 状态"}
MAP_RULES = [
    {"code": "MR-01", "priority": 1, "name": "仪表位号：功能字母_回路号+台号+序号", "pattern": r"^(?P<func>[A-Z]{2,3})_(?P<area>\d{2})(?P<loop>\d{2})(?P<unit>[A-Z]?)(?P<seq>\d?)$",
     "target": "参数（测量值）", "confidence": "高"},
    {"code": "MR-02", "priority": 2, "name": "设备控制块：设备字母_回路号+台号_块后缀", "pattern": r"^(?P<func>[A-Z]{1,3})_(?P<area>\d{2})(?P<loop>\d{2})(?P<unit>[A-Z]?)_(?P<suffix>[A-Z0-9]+)$",
     "target": "参数（状态 / 控制指令 / 阀位）", "confidence": "高"},
    {"code": "MR-03", "priority": 3, "name": "拼音缩写位号：缩写_台号", "pattern": r"^(?P<func>[A-Z]{3,})_(?P<unit>[A-Z0-9]+)$",
     "target": "参数（按点描述关键字匹配）", "confidence": "中"},
    {"code": "MR-04", "priority": 9, "name": "兜底：只按点描述关键字归属设备", "pattern": r"^.+$", "target": "未归属位号 → 人工审核", "confidence": "低"},
]


def parse_tag(ctx: AppContext, tag: str) -> dict[str, Any]:
    tag = tag.strip().upper()
    hit = None
    for r in MAP_RULES:
        m = re.match(r["pattern"], tag)
        if m:
            hit = (r, m.groupdict())
            break
    out: dict[str, Any] = {"tag": tag, "rule": hit[0] if hit else None, "fields": []}
    if hit:
        r, gd = hit
        if gd.get("func"):
            out["fields"].append({"name": "仪表 / 设备功能", "value": gd["func"], "meaning": FUNC.get(gd["func"], "（未登记的功能字母）")})
        if gd.get("area"):
            out["fields"].append({"name": "区域 / 工段", "value": gd["area"], "meaning": f"区段 {gd['area']}（如 13 = 水解）"})
        if gd.get("loop"):
            out["fields"].append({"name": "回路号", "value": gd["loop"], "meaning": ""})
        if gd.get("unit"):
            out["fields"].append({"name": "台号", "value": gd["unit"], "meaning": "点表台号跳过 I：J/K/L 对应水解罐 I/J/K"})
        if gd.get("seq"):
            out["fields"].append({"name": "序号", "value": gd["seq"], "meaning": "同一参数的第 n 支测点"})
        if gd.get("suffix"):
            out["fields"].append({"name": "块后缀", "value": gd["suffix"], "meaning": SUFFIX.get(gd["suffix"], "（未登记的后缀）")})
    t = ctx.tag_by_name.get(tag)
    if t:
        out["catalog"] = {"description": t.get("rawDescription"), "equipment": t.get("equipmentName"), "equipmentId": t.get("equipmentId"),
                          "blockType": t.get("blockType"), "variableCategory": t.get("variableCategory"), "unit": t.get("unit"),
                          "confidence": t.get("confidence"), "basis": t.get("attributionBasis")}
    return out


@lru_cache(maxsize=1)
def _coverage_cached(n: int, sample: tuple[str, ...]) -> dict[str, int]:
    cov = {r["code"]: 0 for r in MAP_RULES}
    for name in sample:
        for r in MAP_RULES:
            if re.match(r["pattern"], name):
                cov[r["code"]] += 1
                break
    return cov


def mapping_rules(ctx: AppContext) -> dict[str, Any]:
    names = tuple(sorted(ctx.tag_by_name))
    cov = _coverage_cached(len(names), names)
    return {"items": [{**r, "hits": cov[r["code"]]} for r in MAP_RULES], "total": len(names),
            "examples": ["TI_1301C", "AT_1301C1", "P_1303C_RUN", "XV_1304C_VAL2", "SJGYW_C", "HV_1301_AO"],
            "note": "规则按优先级依次匹配，命中后解析字段并给出置信度；低置信度结果进入人工审核。右侧「点表中」为现有位号目录的归属，用于对照规则是否正确。"}
