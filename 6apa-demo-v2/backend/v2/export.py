"""本体数据导出（需求 ONTO-SR-SW-067 Excel、ONTO-SR-SW-069 TTL）。

- Excel：全量或按工艺段导出；每张表一个工作表，对象引用列同时输出 ID 和名称（导入时以 ID 为准）；
- TTL（RDF 1.1 Turtle）：类 → owl:Class / rdfs:subClassOf，实例 → 具名个体 + rdf:type，关系类型 → owl:ObjectProperty（含 domain / range，
  包含关系声明为 owl:TransitiveProperty），名称用 rdfs:label "…"@zh；带置信度的导致关系采用关系对象化（onto:CausalLink 个体）；
  URI = 命名空间前缀 + 对象类型 + 对象 ID，多次导出不变；导出后用 rdflib（已安装时）做语法自检。
命名空间前缀需在组态基础信息中配置，本 Demo 用 http://example.org/6apa/ 占位。
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime
from typing import Any
from urllib.parse import quote

from backend.v2.context import AppContext

NS = "http://example.org/6apa/"  # 占位：命名空间前缀待组态


# ------------------------------------------------------------------ 范围
def scope_ops(ctx: AppContext, seg: str | None) -> set[str]:
    h = ctx.hierarchy
    if seg:
        if seg not in h.segments:
            raise LookupError(seg)
        return set(h.segments[seg]["opIds"])
    return set(h.ops)


def _objects(ctx: AppContext, ops: set[str]) -> tuple[list[str], list[str]]:
    h = ctx.hierarchy
    groups = [g for g, o in h.ops_of_group.items() if set(o) & ops]
    equips = [e for e, o in h.op_of_equipment.items() if o in ops]
    return groups, equips


# ------------------------------------------------------------------ Excel
def excel(ctx: AppContext, seg: str | None = None) -> tuple[bytes, dict[str, int]]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from backend.v2 import procedures, tabs
    from backend.v2.calculations import binding_text
    from backend.v2.phenomena import rule_text
    import json

    h, dcs = ctx.hierarchy, ctx.store.dcs
    ops = scope_ops(ctx, seg)
    groups, equips = _objects(ctx, ops)
    objs = set(groups) | set(equips)
    calc_names = {k: v["name"] for k, v in ctx.calcs.items.items()}
    wb = Workbook()
    counts: dict[str, int] = {}

    def sheet(title: str, header: list[str], rows: list[list[Any]], widths: list[int] | None = None) -> None:
        ws = wb.create_sheet(title)
        ws.append(header)
        for r in rows:
            ws.append(["" if v is None else v for v in r])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0E8FA3")
            c.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"
        for i, w in enumerate(widths or [], start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        counts[title] = len(rows)

    # 说明
    info = wb.active
    info.title = "说明"
    from backend.v2 import release
    cur = release.list_releases()["current"]
    for row in [["本体数据导出（6APA 105 车间）"], ["导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                ["范围", h.segments[seg]["name"] if seg else "全车间"],
                ["当前发布版本", f"{cur['version']}（{cur['time']}）" if cur else "未发布"],
                ["说明", "对象引用列同时给出 ID 和名称，导入时以 ID 为准；种子 / 预填条目状态为「草案·待工艺确认」"],
                ["状态口径", "草案·待工艺确认 / 生效 / 停用；只有生效的现象、导致关系、计算组态进入发布版本"]]:
        info.append(row)
    info.column_dimensions["A"].width = 16
    info.column_dimensions["B"].width = 90
    info["A1"].font = Font(bold=True, size=13)

    rows = [[w["id"], w["name"], "车间", "", "", 0, ""] for w in h.workshops] if not seg else []
    for s in h.segments.values():
        if not seg or s["id"] == seg:
            rows.append([s["id"], s["name"], "工艺段", s.get("workshopId"), next((w["name"] for w in h.workshops if w["id"] == s.get("workshopId")), ""), s.get("order"), ""])
    for o in sorted(ops):
        op = h.ops[o]
        rows.append([o, op["name"], "工序", op["segmentId"], h.segments[op["segmentId"]]["name"], op.get("order"), op.get("screen")])
    sheet("空间层级", ["ID", "名称", "层级类型", "上级ID", "上级名称", "顺序", "流程画面"], rows, [12, 24, 10, 12, 18, 6, 18])

    sheet("设备组", ["ID", "名称", "设备类型", "主归属工序ID", "主归属工序", "本范围成员数"],
          [[g, dcs.equipment_groups[g]["name"], dcs.equipment_groups[g].get("equipmentType"), h.ops_of_group[g][0],
            h.ops[h.ops_of_group[g][0]]["name"], len([e for e in ctx.group_members(g) if e in objs])] for g in groups],
          [16, 32, 16, 12, 16, 10])
    sheet("设备", ["ID", "名称", "设备组ID", "设备组名称", "所属工序ID", "所属工序", "DCS 点数"],
          [[e, dcs.equipment[e]["name"], dcs.equipment[e].get("equipmentGroupId"),
            (dcs.equipment_groups.get(dcs.equipment[e].get("equipmentGroupId") or "") or {}).get("name"),
            h.op_of_equipment[e], h.ops[h.op_of_equipment[e]]["name"], len(ctx.tags_of_equipment.get(e, []))] for e in equips],
          [16, 28, 16, 28, 12, 16, 8])

    prow, tag_names = [], set()
    for oid in groups + equips:
        try:
            d = tabs.tab(ctx, oid, "parameters")
        except Exception:  # noqa: BLE001
            continue
        for x in d["items"]:
            if x["section"] != "参数":
                continue
            tags = [l["tag"] for l in x["links"] if l.get("own", True)]
            tag_names |= set(tags)
            prow.append([oid, ctx.object_name(oid), x["name"], x["category"], "是" if x.get("semantic") else "", x["valueType"],
                         "、".join(tags), x["binding"], x.get("bindingNote") or "", "设备组" if x.get("inherited") else "本对象"])
    sheet("参数", ["对象ID", "对象名称", "参数名", "参数类别", "工艺属性", "类型 · 单位", "位号", "绑定状态", "绑定说明", "来源"], prow,
          [16, 26, 22, 10, 8, 14, 30, 10, 30, 8])

    trow = []
    for e in equips:
        for t in ctx.tags_of_equipment.get(e, []):
            trow.append([t["name"], t.get("rawDescription"), t.get("unit"), t.get("blockType"), t.get("variableCategory"),
                         e, dcs.equipment[e]["name"], t.get("confidence"), t.get("attributionBasis")])
    sheet("位号映射", ["位号", "点描述", "单位", "块类型", "变量类别", "设备ID", "设备名称", "归属置信度", "归属依据"], trow,
          [16, 30, 8, 8, 14, 16, 24, 8, 30])

    lrow = []
    for lid, l in ctx.limits.items():
        if seg and not any(t in tag_names for t, lim in ctx.limit_of_tag.items() if lim.get("id") == lid):
            continue
        lrow.append([lid, l.get("appliesTo"), l.get("area"), l.get("operatingMode"), l.get("lowLow"), l.get("low"), l.get("normalLow"),
                     l.get("normalHigh"), l.get("high"), l.get("highHigh"), l.get("unit"), l.get("status")])
    sheet("工艺限值", ["限值ID", "适用参数", "工段", "适用工况", "LL", "L", "正常下限", "正常上限", "H", "HH", "单位", "状态"], lrow,
          [10, 20, 16, 14, 6, 6, 8, 8, 6, 6, 8, 14])

    phen = [p for p in ctx.phen.phenomena.values() if set(ctx.phenomenon_ops(p)) & ops]
    pids = {p["id"] for p in phen}
    sheet("现象", ["ID", "名称", "类别", "严重程度", "挂载对象ID", "挂载对象名称", "判定规则", "判定规则（JSON）", "状态", "来源", "备注"],
          [[p["id"], p["name"], p.get("category"), p.get("severity"), (p.get("anchor") or {}).get("id"), (p.get("anchor") or {}).get("name"),
            rule_text(p.get("rule"), ctx.limits, calc_names) if p.get("rule") else "（判定规则待定义）",
            json.dumps(p.get("rule"), ensure_ascii=False) if p.get("rule") else "", p.get("status"),
            f"{(p.get('source') or {}).get('kind', '')} {(p.get('source') or {}).get('ref', '')}".strip(), p.get("note")] for p in phen],
          [12, 26, 8, 8, 16, 26, 60, 40, 14, 24, 30])
    links = [l for l in ctx.phen.links.values() if l["cause"] in pids or l["effect"] in pids]
    pn = {k: v["name"] for k, v in ctx.phen.phenomena.items()}
    sheet("导致关系", ["ID", "原因现象ID", "原因现象", "结果现象ID", "结果现象", "机理", "依据", "置信度", "状态"],
          [[l["id"], l["cause"], pn.get(l["cause"]), l["effect"], pn.get(l["effect"]), l.get("mechanism"), l.get("basis"),
            l.get("confidence"), l.get("status")] for l in links], [12, 12, 26, 12, 26, 40, 24, 8, 14])

    calcs = [c for c in ctx.calcs.items.values() if set(ctx.scope_ops((c.get("anchor") or {}).get("id") or "")) & ops]
    names = {**{g: x["name"] for g, x in dcs.equipment_groups.items()}, **calc_names}
    sheet("计算组态", ["ID", "名称", "作用范围ID", "作用范围", "算法ID", "参数绑定", "执行方式", "周期(秒)", "超时(秒)", "输出测点", "单位", "状态"],
          [[c["id"], c["name"], (c.get("anchor") or {}).get("id"), (c.get("anchor") or {}).get("name"), c.get("algorithmId"),
            "；".join(f"{k} = {binding_text(b, names)}" for k, b in (c.get("bindings") or {}).items()),
            (c.get("execution") or {}).get("mode", "按需"), (c.get("execution") or {}).get("periodSec"), (c.get("execution") or {}).get("timeoutSec"),
            (c.get("output") or {}).get("tag"), c.get("unit"), c.get("status")] for c in calcs],
          [12, 24, 16, 24, 18, 60, 8, 8, 8, 16, 8, 14])

    cards = {}
    for oid in groups + equips:
        for c in (ctx.profile(oid).get("procedures") or []):
            cards[c["id"]] = ctx.store.procedures.cards.get(c["id"]) or c
    pindex = procedures.phenomenon_index(ctx)
    views = [procedures.card_view(ctx, c, pindex) for c in cards.values()]
    sheet("处置规程", ["ID", "名称", "版本", "状态", "适用范围", "触发", "原因数", "已拆分", "自动执行", "授权要求", "解除条件"],
          [[v["id"], v["name"], v["version"], v["status"], v["scope"], f"{(v.get('trigger') or {}).get('level') or ''} {(v.get('trigger') or {}).get('setpoint') or ''}",
            len(v["causes"]), v["splitCount"], v["autoExecution"], v["authorization"], v.get("clearCondition")] for v in views],
          [12, 26, 10, 18, 24, 18, 6, 6, 30, 16, 40])
    sheet("处置步骤", ["规程ID", "规程名称", "序号", "阶段", "角色", "操作说明", "前置条件", "预期结果", "注意事项", "需人工确认"],
          [[v["id"], v["name"], s.get("seq"), s.get("phase"), s.get("role"), s.get("description"), s.get("precondition"), s.get("expected"),
            s.get("caution"), "是" if s.get("manualConfirm") else "系统辅助"] for v in views for s in v["steps"]],
          [12, 22, 6, 10, 10, 50, 20, 20, 20, 10])
    sheet("人工关系", ["ID", "关系类型", "方向 / 标签", "起点ID", "起点", "终点ID", "终点", "机理", "状态", "创建时间"],
          [[r["id"], r["type"], r["label"], r["from"]["id"], r["from"]["name"], r["to"]["id"], r["to"]["name"], r.get("mechanism"),
            r.get("status"), r.get("createdAt")] for r in ctx.relations.items
           if not seg or {r["from"]["id"], r["to"]["id"]} & (objs | set())], [12, 10, 10, 16, 24, 16, 24, 30, 14, 18])
    ov = ctx.overrides.data
    sheet("继承覆盖", ["类型", "设备ID", "设备名称", "现象 / 限值", "禁用", "覆盖内容", "原因", "时间"],
          [["现象", v["objectId"], ctx.object_name(v["objectId"]), v["phenomenonId"], "是" if v["disabled"] else "",
            rule_text(v["rule"], ctx.limits, calc_names) if v.get("rule") else "", v.get("note"), v.get("updatedAt")]
           for v in ov["phenomena"].values() if v["objectId"] in objs] +
          [["限值", v["objectId"], ctx.object_name(v["objectId"]), v["limitId"], "是" if v["disabled"] else "",
            json.dumps(v.get("values"), ensure_ascii=False), v.get("note"), v.get("updatedAt")]
           for v in ov["limits"].values() if v["objectId"] in objs], [8, 16, 20, 14, 6, 50, 30, 18])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), counts


# ------------------------------------------------------------------ TTL
def _lit(text: Any) -> str:
    s = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    return f'"{s}"'


def _iri(kind: str, oid: str) -> str:
    return f"inst:{kind}_{quote(str(oid), safe='')}".replace("%", "_")


TTL_TYPES = {"车间": ("Workshop", "车间"), "工艺段": ("ProcessSegment", "工艺段"), "工序": ("Operation", "工序"),
             "设备组": ("EquipmentGroup", "设备组"), "设备": ("Equipment", "设备"), "工艺参数": ("ProcessParameter", "工艺参数"),
             "质量指标": ("QualityIndicator", "质量指标"), "物料流股": ("MaterialStream", "物料流股"), "公用介质": ("Utility", "公用介质"),
             "现象": ("Phenomenon", "现象"), "工况": ("OperatingCondition", "工况")}
TTL_PROPS = {  # 关系类型 → (谓词, 中文名, 定义域, 值域, 特性)
    "包含": ("contains", "包含", None, None, "owl:TransitiveProperty"),
    "工序衔接": ("connectsOperation", "工序衔接", "onto:Operation", "onto:Operation", None),
    "物理拓扑": ("physicallyConnectedTo", "物理拓扑", None, None, None),
    "具有属性": ("hasProperty", "具有属性", None, None, None),
    "工艺影响": ("influences", "工艺影响", None, None, None),
    "挂载": ("mountedOn", "挂载", "onto:Phenomenon", None, None),
    "导致": ("causes", "导致", "onto:Phenomenon", "onto:Phenomenon", None),
}


def ttl(ctx: AppContext, seg: str | None = None) -> tuple[str, dict[str, Any]]:
    from backend.v2 import global_graph
    from backend.v2.phenomena import rule_text
    g = global_graph.build(ctx)
    nodes = {n["id"]: n for n in g["nodes"] if not seg or n.get("segId") == seg or n["type"] == "车间"}
    kind_of = {nid: TTL_TYPES.get(n["type"], ("Thing", ""))[0] for nid, n in nodes.items()}
    out = [f"# 6APA 105 车间工业本体（RDF 1.1 Turtle），导出于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
           f"# 范围：{ctx.hierarchy.segments[seg]['name'] if seg else '全车间'}；命名空间前缀为占位，待组态",
           f"@prefix onto: <{NS}ontology#> .", f"@prefix inst: <{NS}id/> .",
           "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .", "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
           "@prefix owl: <http://www.w3.org/2002/07/owl#> .", "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", "",
           f"<{NS}ontology> a owl:Ontology ; rdfs:label {_lit('6APA 105 车间工业本体')}@zh .", "", "# ---- 元类 / 类"]
    for cls, label in TTL_TYPES.values():
        out.append(f"onto:{cls} a owl:Class ; rdfs:label {_lit(label)}@zh .")
    out.append(f"onto:CausalLink a owl:Class ; rdfs:label {_lit('根因影响关系（对象化）')}@zh .")
    # 设备类型 → 子类
    dcs = ctx.store.dcs
    etypes = sorted({(x.get("equipmentType") or "").strip() for x in dcs.equipment_groups.values()} - {""})
    etype_iri = {t: "onto:EquipmentType_" + hashlib.md5(t.encode()).hexdigest()[:8] for t in etypes}
    for t, iri in etype_iri.items():
        out.append(f"{iri} a owl:Class ; rdfs:subClassOf onto:Equipment ; rdfs:label {_lit(t)}@zh .")
    out += ["", "# ---- 关系类型"]
    for pred, label, dom, rng, extra in TTL_PROPS.values():
        line = f"onto:{pred} a owl:ObjectProperty{', ' + extra if extra else ''} ; rdfs:label {_lit(label)}@zh"
        line += f" ; rdfs:domain {dom}" if dom else ""
        line += f" ; rdfs:range {rng}" if rng else ""
        out.append(line + " .")
    for p, label, rng in (("cause", "原因", "onto:Phenomenon"), ("effect", "结果", "onto:Phenomenon")):
        out.append(f"onto:{p} a owl:ObjectProperty ; rdfs:label {_lit(label)}@zh ; rdfs:domain onto:CausalLink ; rdfs:range {rng} .")
    for p, label in (("status", "状态"), ("ruleText", "判定规则"), ("confidence", "置信度"), ("mechanism", "机理"), ("category", "类别")):
        out.append(f"onto:{p} a owl:DatatypeProperty ; rdfs:label {_lit(label)}@zh ; rdfs:range xsd:string .")
    out += ["", "# ---- 实例"]
    phen = ctx.phen.phenomena
    iri = {nid: _iri(kind_of[nid], nid) for nid in nodes}
    for nid, n in nodes.items():
        types = [f"onto:{kind_of[nid]}"]
        if n["type"] == "设备组":
            t = (dcs.equipment_groups.get(nid) or {}).get("equipmentType")
            if t in etype_iri:
                types.append(etype_iri[t])
        line = f"{iri[nid]} a {', '.join(types)} ; rdfs:label {_lit(n['name'])}@zh"
        p = phen.get(nid)
        if p:
            line += f" ; onto:status {_lit(p.get('status') or '')} ; onto:category {_lit(p.get('category') or '')}"
            if p.get("rule"):
                line += f" ; onto:ruleText {_lit(rule_text(p['rule'], ctx.limits, {k: v['name'] for k, v in ctx.calcs.items.items()}))}@zh"
        out.append(line + " .")
    out += ["", "# ---- 关系"]
    edges = 0
    for e in g["edges"]:
        if e["s"] not in nodes or e["t"] not in nodes or e["type"] not in TTL_PROPS:
            continue
        if e["type"] == "导致":
            continue
        out.append(f"{iri[e['s']]} onto:{TTL_PROPS[e['type']][0]} {iri[e['t']]} .")
        edges += 1
    links = 0
    for l in ctx.phen.links.values():
        if l["cause"] in nodes and l["effect"] in nodes:
            out.append(f"{iri[l['cause']]} onto:causes {iri[l['effect']]} .")
            out.append(f"{_iri('CausalLink', l['id'])} a onto:CausalLink ; onto:cause {iri[l['cause']]} ; onto:effect {iri[l['effect']]} ; "
                       f"onto:confidence {_lit(l.get('confidence') or '')} ; onto:status {_lit(l.get('status') or '')} ; "
                       f"onto:mechanism {_lit(l.get('mechanism') or '')}@zh .")
            links += 1
    text = "\n".join(out) + "\n"
    check: dict[str, Any] = {"nodes": len(nodes), "edges": edges, "causalLinks": links, "classes": len(TTL_TYPES) + len(etype_iri) + 1}
    try:
        import rdflib
        gr = rdflib.Graph()
        gr.parse(data=text, format="turtle")
        check.update(syntax="通过（rdflib 解析）", triples=len(gr))
    except ImportError:
        check["syntax"] = "未自检（未安装 rdflib）"
    except Exception as exc:  # noqa: BLE001
        check["syntax"] = f"失败：{exc}"
    return text, check
