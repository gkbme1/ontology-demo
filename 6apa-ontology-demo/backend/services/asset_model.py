"""资产本体视图：把 Excel 加载出的本体数据组织成"资产导航树 + 对象本体档案"。

为什么要有这一层
----------------
原有接口按数据源组织（设备列表、关系清单、点表……），适合程序调用，不适合人看。
使用者要的是：
- 一棵**资产导航树**：按本体域 → 分类 → 层级 → 实例，把现场所有对象列进去，能快速找到某台设备；
- 选中一个对象后看它的**本体档案**：类与层级、属性（含数据关联）、关系（类间关系 + 属性间关系）、
  能力、约束、规则。

本模块只读取 OntologyStore 已加载的数据重新组织，不改任何原有接口和数据。

本体档案的定义（参考"类描述'是什么、能挂什么'"的建模思路）
-----------------------------------------------------------
- 类与层级：父类链（设备 → 大类 → 设备类型 → 标准设备组）、编码、归属；
- 属性：固有（静态主数据）/ 测量 / 状态 / 控制 / 工艺属性，每条属性直接带数据关联（DCS 位号），
  "数据关联"不单列，体现在属性里；
- 关系：类间关系（所属、上下游拓扑、部件、实例、控制、报警联锁……）与属性间关系（计算 / 传递 / 关联）；
- 能力：本体只提供挂载点。数据源里没有能力定义，这里按"对象已有的点位与本体内置接口"判断挂载状态，
  不编造模型或程序；
- 约束：结构约束（加载器校验的本体结构事实）、运行约束（工艺限值）、安全约束（报警联锁）；
- 规则：来自规则文件，在推理引擎中执行，档案里只列适用的规则。

资产大类划分
------------
工业资产的大类按"设备组声明的设备类型"或"设备名称关键字"归入，结果里写明归类依据（classifiedBy），
关键字表集中在 ASSET_CLASSES，现场可调整。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from backend.ontology import identifiers as ids

# ------------------------------------------------------------ 资产大类（可配置）

# 顺序有意义：先匹配到的优先（"浓碱储罐输送泵"是泵，不是储罐）
ASSET_CLASSES: list[tuple[str, tuple[str, ...]]] = [
    ("泵与输送设备", ("泵", "风机", "压缩机", "气力输送")),
    ("离心分离设备", ("离心机",)),
    ("换热设备", ("换热器", "冷凝器", "冷却器", "加热器", "再沸器")),
    ("塔器", ("塔",)),
    ("反应设备", ("反应罐", "反应釜", "中和罐", "酶反应")),
    ("结晶设备", ("结晶",)),
    ("过滤与分离设备", ("过滤器", "膜分离", "吸附柱", "吸附罐", "分层罐", "分相罐")),
    ("蒸发与干燥设备", ("蒸发器", "干燥器", "干燥")),
    ("混合与配制设备", ("混合器", "配制罐", "混合罐", "搅拌罐")),
    ("容器与储罐", ("储罐", "罐", "料仓", "槽")),
    ("阀门与管网", ("阀", "管网", "管线")),
]
OTHER_CLASS = "其他工艺单元"

# 本体域（顺序即导航树顺序）。kind=empty 的是现有数据源没有覆盖的域，如实显示为 0，不编造内容。
DOMAINS: list[dict[str, Any]] = [
    {"key": "space", "name": "空间与层级", "desc": "生产线 → 工段 → 设备组 → 设备"},
    {"key": "assets", "name": "工业资产", "desc": "资产大类 → 设备类型 → 标准设备组 → 设备实例"},
    {"key": "process", "name": "工艺", "desc": "各工段的工艺属性（工艺量）"},
    {"key": "material", "name": "物料与产品", "desc": "物料流股、公用介质"},
    {"key": "quality", "name": "质量", "desc": "质量指标"},
    {"key": "business", "name": "生产业务与经营指标", "desc": "业务指标"},
    {"key": "control", "name": "自动化与控制", "desc": "控制系统、控制仪表、执行机构、DCS 控制站"},
    {"key": "safety", "name": "安全与风险", "desc": "报警事件"},
    {"key": "org", "name": "组织与人员", "desc": "暂无数据源", "empty": True},
    {"key": "maintenance", "name": "设备维护与可靠性", "desc": "暂无数据源", "empty": True},
    {"key": "energy", "name": "能源", "desc": "暂无数据源", "empty": True},
    {"key": "environment", "name": "环保", "desc": "暂无数据源", "empty": True},
    {"key": "cost", "name": "成本与经营", "desc": "暂无数据源", "empty": True},
]

# 关系对象类型 → 所在本体域
ENTITY_DOMAIN = {
    "工艺属性": "process",
    "物料流股": "material",
    "公用介质": "material",
    "质量指标": "quality",
    "业务指标": "business",
    "控制系统": "control",
    "控制仪表": "control",
    "执行机构": "control",
    "报警事件": "safety",
}

# 参数类别 → 属性类别
PARAM_CATEGORY_KIND = {
    "过程测量(PV)": "测量",
    "状态反馈(DI)": "状态",
    "开关控制(DO)": "控制",
    "阀门控制(VAL)": "控制",
    "控制输出(OP)": "控制",
    "电机控制(MOT)": "控制",
}
ATTRIBUTE_KIND_ORDER = ["固有", "工艺属性", "测量", "状态", "控制"]

TOPOLOGY_CATEGORIES = {"物理拓扑关系", "工段衔接"}
CAUSAL_CATEGORIES = {"影响关系", "质量关系"}
MEMBERSHIP_PREDICATES = {"包含实例", "包含设备"}


def _classify(text: str) -> str:
    for cls, words in ASSET_CLASSES:
        if any(w in (text or "") for w in words):
            return cls
    return OTHER_CLASS


def _source_text(rel: dict[str, Any]) -> str:
    src = rel.get("source") or {}
    return f"{src.get('file', '')} {src.get('sheet', '')} 第{src.get('row', '?')}行".strip() if src else ""


# ================================================================ 导航索引


class AssetIndex:
    """一次性把本体对象排进导航树；之后的树节点、搜索、档案都从这里取。"""

    def __init__(self, store: Any) -> None:
        self.store = store
        dcs = store.dcs
        self.areas = sorted(dcs.areas.values(), key=lambda a: a.get("code") or "")
        self.area_by_code = {a["code"]: a for a in self.areas}
        self.groups = dcs.equipment_groups
        self.equipment = dcs.equipment
        self.entities = store.relations.entities
        self.entity_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in self.entities.values():
            self.entity_by_name[entity["name"]].append(entity)

        # 工业资产：大类 → 设备类型 → 设备组 → 设备；未入组设备按名称归大类
        self.asset_class_of_equipment: dict[str, tuple[str, str, str]] = {}  # equip → (大类, 类型, 依据)
        self.groups_by_type: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.ungrouped_by_class: dict[str, list[str]] = defaultdict(list)
        # 归类以设备自己的主设备组（equipmentGroupId）为准；设备组成员清单里还有共用设备（如离心机A 同时
        # 列在 RSE300 / RSE200 两个组里），共用设备只在主组的类型下计数，在其他组下标"共用"展示
        self.type_count: Counter = Counter()
        for group in self.groups.values():
            etype = group.get("equipmentType") or "未声明类型"
            self.groups_by_type[(self.group_class(group), etype)].append(group["id"])
        for equip in self.equipment.values():
            group = self.groups.get(equip.get("equipmentGroupId") or "")
            if group:
                etype = group.get("equipmentType") or "未声明类型"
                cls = self.group_class(group)
                self.asset_class_of_equipment[equip["id"]] = (cls, etype, f"主设备组「{group['name']}」声明的设备类型：{etype}")
                self.type_count[(cls, etype)] += 1
                continue
            cls = _classify(equip["name"])
            basis = "名称关键字" if cls != OTHER_CLASS else "名称无法归类"
            self.asset_class_of_equipment[equip["id"]] = (cls, "未入组设备", f"{basis}：{equip['name']}")
            self.ungrouped_by_class[cls].append(equip["id"])

        # 空间：工段 → 设备组 / 未入组设备
        self.ungrouped_by_area: dict[str, list[str]] = defaultdict(list)
        for equip in self.equipment.values():
            if not equip.get("equipmentGroupId") and equip.get("areaId"):
                self.ungrouped_by_area[equip["areaId"]].append(equip["id"])

        # 关系对象按本体域 / 类型 / 工段
        self.entities_by_domain: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for entity in self.entities.values():
            domain = ENTITY_DOMAIN.get(entity["type"])
            if domain:
                self.entities_by_domain[domain][entity["type"]][entity.get("areaCode") or "未分工段"].append(entity["id"])

        self.stations: dict[str, list[str]] = defaultdict(list)
        for equip in self.equipment.values():
            self.stations[str(equip.get("station") or "未知")].append(equip["id"])

    @staticmethod
    def group_class(group: dict[str, Any]) -> str:
        etype = group.get("equipmentType")
        return _classify(etype) if etype else _classify(group["name"])

    # ------------------------------------------------------------ 节点构造

    def _node(self, node_id: str, label: str, kind: str, *, count: int | None = None, children: bool = True,
              object_id: str | None = None, badge: str | None = None, hint: str | None = None) -> dict[str, Any]:
        node = {"id": node_id, "label": label, "kind": kind, "hasChildren": children}
        if count is not None:
            node["count"] = count
        if object_id:
            node["objectId"] = object_id
        if badge:
            node["badge"] = badge
        if hint:
            node["hint"] = hint
        return node

    def _equip_node(self, eid: str, parent: str) -> dict[str, Any]:
        equip = self.equipment[eid]
        return self._node(
            f"{parent}|{eid}", equip["name"], "equipment", children=False, object_id=eid,
            badge=f"{equip['tagCount']} 点", hint=f"{equip.get('owlSubject')} · 站{equip.get('station')}",
        )

    def _group_node(self, gid: str, parent: str) -> dict[str, Any]:
        group = self.groups[gid]
        return self._node(f"{parent}|{gid}", group["name"], "group", count=len(group["equipmentIds"]),
                          object_id=gid, badge=group.get("areaCode"))

    def _entity_node(self, rid: str, parent: str) -> dict[str, Any]:
        entity = self.entities[rid]
        tags = entity["match"]["tagCount"]
        return self._node(f"{parent}|{rid}", entity["name"], "entity", children=False, object_id=rid,
                          badge=f"{tags} 点" if tags else "无测点", hint=entity["type"])

    def _area_label(self, code: str) -> str:
        area = self.area_by_code.get(code)
        return f"{code} {area['name']}" if area else code

    # ------------------------------------------------------------ 子节点

    def roots(self) -> list[dict[str, Any]]:
        out = []
        for domain in DOMAINS:
            if domain.get("empty"):
                out.append(self._node(f"dom:{domain['key']}", domain["name"], "domain", count=0,
                                      children=False, hint=domain["desc"]))
                continue
            out.append(self._node(f"dom:{domain['key']}", domain["name"], "domain",
                                  count=self._domain_count(domain["key"]), hint=domain["desc"]))
        return out

    def _domain_count(self, key: str) -> int:
        if key == "space":
            return len(self.areas)
        if key == "assets":
            return len(self.equipment)
        if key == "control":
            return sum(len(v) for t in self.entities_by_domain["control"].values() for v in t.values()) + len(self.stations)
        return sum(len(v) for t in self.entities_by_domain[key].values() for v in t.values())

    def children(self, node_id: str) -> list[dict[str, Any]]:
        parts = node_id.split("|")
        head = parts[-1]
        if node_id == "":
            return self.roots()

        # ---- 空间与层级
        if node_id == "dom:space":
            return [self._node(f"{node_id}|{a['id']}", f"{a['code']} {a['name']}", "area",
                               count=a["equipmentCount"], object_id=a["id"]) for a in self.areas]
        if parts[0] == "dom:space" and head.startswith("area-"):
            area = self.store.dcs.areas.get(head)
            if not area:
                return []
            nodes = [self._group_node(g, node_id) for g in area.get("equipmentGroupIds", []) if g in self.groups]
            loose = self.ungrouped_by_area.get(head, [])
            if loose:
                nodes.append(self._node(f"{node_id}|loose", "未入组设备", "bucket", count=len(loose),
                                        hint="点表里有、但未归入标准设备组的设备"))
            return nodes
        if parts[0] == "dom:space" and head == "loose":
            return [self._equip_node(e, node_id) for e in sorted(self.ungrouped_by_area.get(parts[-2], []),
                                                                 key=lambda e: self.equipment[e]["name"])]

        # ---- 工业资产
        if node_id == "dom:assets":
            totals = Counter(cls for cls, _, _ in self.asset_class_of_equipment.values())
            order = [c for c, _ in ASSET_CLASSES] + [OTHER_CLASS]
            return [self._node(f"{node_id}|cls:{c}", c, "class", count=totals[c]) for c in order if totals[c]]
        if parts[0] == "dom:assets" and head.startswith("cls:"):
            cls = head[4:]
            types = sorted({t for (c, t) in self.groups_by_type if c == cls})
            nodes = []
            for etype in types:
                nodes.append(self._node(f"{node_id}|type:{etype}", etype, "type", count=self.type_count[(cls, etype)]))
            loose = self.ungrouped_by_class.get(cls, [])
            if loose:
                nodes.append(self._node(f"{node_id}|loose", "未入组设备", "bucket", count=len(loose),
                                        hint="未归入标准设备组，按设备名称关键字归入本大类"))
            return nodes
        if parts[0] == "dom:assets" and head.startswith("type:"):
            cls, etype = parts[-2][4:], head[5:]
            return [self._group_node(g, node_id) for g in sorted(self.groups_by_type[(cls, etype)],
                                                                 key=lambda g: self.groups[g].get("areaCode") or "")]
        if parts[0] == "dom:assets" and head == "loose":
            cls = parts[-2][4:]
            return [self._equip_node(e, node_id) for e in sorted(self.ungrouped_by_class.get(cls, []),
                                                                 key=lambda e: self.equipment[e]["name"])]

        # 设备组 → 设备实例（空间、资产两个域共用）；主组不是本组的共用设备标出来
        if head.startswith("egrp-"):
            group = self.groups.get(head) or {}
            nodes = []
            for eid in group.get("equipmentIds", []):
                if eid not in self.equipment:
                    continue
                node = self._equip_node(eid, node_id)
                primary = self.groups.get(self.equipment[eid].get("equipmentGroupId") or "")
                if primary and primary["id"] != head:
                    node["badge"] = "共用"
                    node["hint"] = f"共用设备，主组：{primary['name']}"
                nodes.append(node)
            return nodes

        # ---- 自动化与控制：多一层 DCS 控制站
        if node_id == "dom:control":
            nodes = self._entity_type_nodes("control", node_id)
            nodes.append(self._node(f"{node_id}|stations", "DCS 控制站", "type", count=len(self.stations)))
            return nodes
        if node_id == "dom:control|stations":
            return [self._node(f"{node_id}|station:{s}", f"控制站 {s}", "bucket", count=len(e))
                    for s, e in sorted(self.stations.items(), key=lambda kv: (len(kv[0]), kv[0]))]
        if head.startswith("station:"):
            return [self._equip_node(e, node_id) for e in sorted(self.stations.get(head[8:], []),
                                                                 key=lambda e: self.equipment[e]["name"])]

        # ---- 关系对象类的本体域：类型 → 工段 → 对象
        if node_id.startswith("dom:") and len(parts) == 1:
            return self._entity_type_nodes(node_id[4:], node_id)
        if head.startswith("etype:"):
            domain = parts[0][4:]
            by_area = self.entities_by_domain[domain].get(head[6:], {})
            if len(by_area) == 1:  # 只有一个工段时不多套一层
                return [self._entity_node(r, node_id) for r in sorted(next(iter(by_area.values())),
                                                                      key=lambda r: self.entities[r]["name"])]
            return [self._node(f"{node_id}|earea:{code}", self._area_label(code), "bucket", count=len(rids))
                    for code, rids in sorted(by_area.items())]
        if head.startswith("earea:"):
            domain, etype = parts[0][4:], parts[-2][6:]
            rids = self.entities_by_domain[domain].get(etype, {}).get(head[6:], [])
            return [self._entity_node(r, node_id) for r in sorted(rids, key=lambda r: self.entities[r]["name"])]
        return []

    def _entity_type_nodes(self, domain: str, parent: str) -> list[dict[str, Any]]:
        return [
            self._node(f"{parent}|etype:{etype}", etype, "type", count=sum(len(v) for v in by_area.values()))
            for etype, by_area in sorted(self.entities_by_domain[domain].items())
        ]

    # ------------------------------------------------------------ 搜索

    def path_of(self, object_id: str) -> list[str]:
        """对象在导航树里的完整路径（节点 id 列表），前端据此逐级展开。"""
        if object_id.startswith("equip-") and object_id in self.equipment:
            equip = self.equipment[object_id]
            cls, etype, _ = self.asset_class_of_equipment[object_id]
            base = ["dom:assets", f"dom:assets|cls:{cls}"]
            if equip.get("equipmentGroupId") in self.groups:
                gid = equip["equipmentGroupId"]
                group = self.groups[gid]
                gtype = group.get("equipmentType") or "未声明类型"
                p = base + [f"{base[-1]}|type:{gtype}", f"{base[-1]}|type:{gtype}|{gid}"]
            else:
                p = base + [f"{base[-1]}|loose"]
            return p + [f"{p[-1]}|{object_id}"]
        if object_id.startswith("egrp-") and object_id in self.groups:
            group = self.groups[object_id]
            gtype = group.get("equipmentType") or "未声明类型"
            cls = self.group_class(group)
            p = ["dom:assets", f"dom:assets|cls:{cls}", f"dom:assets|cls:{cls}|type:{gtype}"]
            return p + [f"{p[-1]}|{object_id}"]
        if object_id.startswith("area-") and object_id in self.store.dcs.areas:
            return ["dom:space", f"dom:space|{object_id}"]
        if object_id.startswith("robj-") and object_id in self.entities:
            entity = self.entities[object_id]
            domain = ENTITY_DOMAIN.get(entity["type"])
            if not domain:
                # 生产设备 / 设备实例 / 设备部件 / 生产工段这几类在工业资产与空间域里以 DCS 对象出现
                return []
            p = [f"dom:{domain}", f"dom:{domain}|etype:{entity['type']}"]
            by_area = self.entities_by_domain[domain].get(entity["type"], {})
            if len(by_area) > 1:
                p.append(f"{p[-1]}|earea:{entity.get('areaCode') or '未分工段'}")
            return p + [f"{p[-1]}|{object_id}"]
        return []

    def search(self, keyword: str, limit: int = 30) -> dict[str, Any]:
        kw = (keyword or "").strip()
        if not kw:
            return {"items": [], "total": 0}
        hits: list[dict[str, Any]] = []
        lower = kw.lower()

        def add(object_id: str, label: str, kind: str, hint: str, rank: int) -> None:
            path = self.path_of(object_id)
            if path:
                hits.append({"objectId": object_id, "label": label, "kind": kind, "hint": hint, "path": path, "_rank": rank})

        for equip in self.equipment.values():
            name = equip["name"] or ""
            if kw in name or lower in (equip.get("owlSubject") or "").lower():
                add(equip["id"], name, "equipment", f"{equip.get('areaCode')} · {equip.get('equipmentGroup') or '未入组'}",
                    0 if name == kw else 1)
                continue
            alias = next((a for a in equip.get("aliases") or [] if kw in a["name"]), None)
            if alias:
                add(equip["id"], name, "equipment", f"点表写法「{alias['name']}」（{alias['station']} 站）已归并到此设备",
                    0 if alias["name"] == kw else 1)
        for group in self.groups.values():
            if kw in group["name"] or any(kw in inst for inst in group["instances"]):
                add(group["id"], group["name"], "group", f"标准设备组 · {group.get('equipmentType')}", 0 if group["name"] == kw else 2)
        for area in self.areas:
            if kw in area["name"] or kw == area["code"]:
                add(area["id"], f"{area['code']} {area['name']}", "area", "工段", 0)
        for entity in self.entities.values():
            if kw in entity["name"] and ENTITY_DOMAIN.get(entity["type"]):
                add(entity["id"], entity["name"], "entity", entity["type"], 0 if entity["name"] == kw else 3)
        # 位号 / 现场描述 → 所属设备
        seen_equip = {h["objectId"] for h in hits}
        for tag in self.store.dcs.tags.values():
            if len(hits) > limit * 3:
                break
            if kw.upper() == (tag["name"] or "").upper() or (len(kw) >= 3 and kw in (tag.get("rawDescription") or "")):
                eid = tag.get("equipmentId")
                if eid and eid not in seen_equip and eid in self.equipment:
                    seen_equip.add(eid)
                    add(eid, self.equipment[eid]["name"], "equipment", f"位号 {tag['name']}（{tag.get('rawDescription')}）", 1)
        hits.sort(key=lambda h: (h["_rank"], len(h["label"])))
        total = len(hits)
        return {"items": [{k: v for k, v in h.items() if k != "_rank"} for h in hits[:limit]], "total": total}


def asset_index(store: Any) -> AssetIndex:
    index = getattr(store, "_asset_index", None)
    if index is None:
        index = AssetIndex(store)
        store._asset_index = index
    return index


# ================================================================ 本体档案


def _tag_link(tag: dict[str, Any]) -> dict[str, Any]:
    return {
        "tagId": tag["id"],
        "tag": tag["name"],
        "desc": tag.get("rawDescription"),
        "unit": tag.get("unit"),
        "blockType": tag.get("blockType"),
        "station": tag.get("station"),
    }


def _value_type(units: list[str], blocks: list[str], kind: str) -> str:
    if kind in ("状态",) or any(b in ("DI", "DO", "DOV") for b in blocks):
        return "bool · 开关量"
    unit = next((u for u in units if u), None)
    return f"float · {unit}" if unit else "float"


def _limits_by_name(store: Any, object_id: str) -> list[dict[str, Any]]:
    from backend.services import process_limits

    try:
        data = process_limits.limits_for_object(store, object_id)
    except Exception:  # 实时值模块等可选依赖缺失时不影响档案
        return []
    return data.get("items") or []


def _limit_constraint(limit: dict[str, Any]) -> dict[str, Any]:
    def band(lo: Any, hi: Any) -> str | None:
        if lo is None and hi is None:
            return None
        return f"{'' if lo is None else lo}~{'' if hi is None else hi}"

    return {
        "id": limit.get("id"),
        "appliesTo": limit.get("appliesTo"),
        "parameter": limit.get("parameter"),
        "unit": limit.get("unit"),
        "operatingMode": limit.get("operatingMode"),
        "normal": band(limit.get("normalLow"), limit.get("normalHigh")),
        "alarm": {k: limit.get(k) for k in ("lowLow", "low", "high", "highHigh") if limit.get(k) is not None},
        "hasValues": limit.get("hasValues"),
        "status": limit.get("status"),
        "confidence": limit.get("confidence"),
        "basis": limit.get("basis"),
        "matchedTargets": [t.get("tagName") for t in limit.get("matchedTargets") or []],
    }


def _relation_view(rel: dict[str, Any], anchor_ids: set[str]) -> dict[str, Any]:
    """一条关系相对档案主体的视图：主体在主语侧为 out，在宾语侧为 in。"""
    subject, obj = rel.get("subject") or {}, rel.get("object") or {}
    outgoing = subject.get("id") in anchor_ids
    other = obj if outgoing else subject
    return {
        "relationId": rel["id"],
        "category": rel.get("category"),
        "predicate": rel.get("predicate"),
        "direction": "out" if outgoing else "in",
        "from": rel.get("subjectEntity"),
        "to": rel.get("objectEntity"),
        "target": other.get("entity") or (rel.get("objectEntity") if outgoing else rel.get("subjectEntity")),
        "targetId": other.get("id"),
        "targetType": rel.get("objectType") if outgoing else rel.get("subjectType"),
        "mechanism": rel.get("domainDescription") or "",
        "tags": [t["name"] for t in rel.get("tags") or []][:6],
        "source": _source_text(rel),
    }


def _class_relations(relations: list[dict[str, Any]], anchor_ids: set[str]) -> list[dict[str, Any]]:
    """类间关系：拓扑上下游、所属、实例、部件、控制、报警联锁（因果影响放到属性间关系里）。"""
    out = []
    for rel in relations:
        if rel.get("category") in CAUSAL_CATEGORIES or rel.get("category") == "测点绑定关系":
            continue
        view = _relation_view(rel, anchor_ids)
        cat, pred = rel.get("category"), rel.get("predicate")
        if cat in TOPOLOGY_CATEGORIES:
            view["role"] = "下游" if view["direction"] == "out" else "上游"
        elif cat == "结构关系" and pred in MEMBERSHIP_PREDICATES:
            view["role"] = "包含实例" if view["direction"] == "out" else "所属"
        elif cat == "结构关系" and pred == "具有部件":
            view["role"] = "部件" if view["direction"] == "out" else "所属"
        elif cat == "结构关系" and pred == "具有属性":
            continue  # 已在"属性"里体现
        elif cat == "控制关系":
            view["role"] = "控制"
        elif cat == "报警联锁关系":
            view["role"] = "报警联锁"
        else:
            view["role"] = cat or "关系"
        out.append(view)
    return out


def _attribute_relations(relations: list[dict[str, Any]], names: set[str]) -> list[dict[str, Any]]:
    """属性间关系：涉及本对象属性的影响 / 质量关系，按"计算 / 传递 / 关联"归类。"""
    out = []
    for rel in relations:
        if rel.get("category") not in CAUSAL_CATEGORIES:
            continue
        if rel.get("subjectEntity") not in names and rel.get("objectEntity") not in names:
            continue
        mechanism = rel.get("domainDescription") or ""
        pred = rel.get("predicate") or ""
        if "计算" in mechanism or "即" in mechanism:
            kind = "计算"
        elif pred in ("正向影响", "负向影响"):
            kind = "传递"
        else:
            kind = "关联"
        out.append({
            "kind": kind,
            "from": rel.get("subjectEntity"),
            "to": rel.get("objectEntity"),
            "predicate": pred,
            "category": rel.get("category"),
            "mechanism": mechanism,
            "source": _source_text(rel),
        })
    order = {"计算": 0, "传递": 1, "关联": 2}
    out.sort(key=lambda r: order.get(r["kind"], 9))
    return out


def _capabilities(store: Any, object_id: str, tags: list[dict[str, Any]], limits: list[dict[str, Any]],
                  rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """能力挂载：本体只提供挂载点。按对象已有的点位与本体内置接口判断，不编造模型或程序。"""
    caps = []
    analog = [t for t in tags if t.get("blockType") in ("AI", "PID") or (t.get("parameterType") or "").startswith("过程测量")]
    if tags:
        caps.append({
            "type": "数据·时序", "name": "实时值 / 历史值查询", "status": "已挂载",
            "mount": f"本体时序网关 /api/ontology/{object_id}/realtime · /history",
            "basis": f"对象解析出 {len(tags)} 个 DCS 点（其中模拟量 {len(analog)} 个）",
        })
    with_values = [l for l in limits if l.get("hasValues")]
    if with_values:
        caps.append({
            "type": "能力·分析", "name": "越限判断", "status": "已挂载",
            "mount": f"本体限值检查 /api/ontology/{object_id}/limit-check",
            "basis": "适用工艺限值 " + "、".join(l["id"] for l in with_values[:4]) + ("…" if len(with_values) > 4 else ""),
        })
    elif limits:
        caps.append({
            "type": "能力·分析", "name": "越限判断", "status": "未挂载",
            "mount": "—", "basis": "适用的限值 " + "、".join(l["id"] for l in limits[:4]) + " 待现场提供数值",
        })
    specific = [r for r in rules if r.get("matchedBy") != "通用层规则（未限定工段）"]
    if rules:
        caps.append({
            "type": "能力·诊断", "name": "规则诊断", "status": "已挂载",
            "mount": "推理引擎 · 规则文件",
            "basis": f"适用规则 {len(rules)} 条（专属 / 同工段 {len(specific)} 条，通用层 {len(rules) - len(specific)} 条）",
        })
    onoff = [t for t in tags if t.get("blockType") in ("DOV", "DO") or "启停" in (t.get("variableCategory") or "")]
    if onoff:
        caps.append({
            "type": "动作", "name": "启停", "status": "具备挂载点",
            "mount": "、".join(t["name"] for t in onoff[:3]) + ("…" if len(onoff) > 3 else ""),
            "basis": "有启停 / 开关指令点；动作程序（如 OPAS）尚未挂载",
        })
    adjust = [t for t in tags if t.get("blockType") in ("AO",) or "开度指令" in (t.get("variableCategory") or "")
              or (t.get("parameterType") or "").startswith("控制输出")]
    if adjust:
        caps.append({
            "type": "动作", "name": "调节", "status": "具备挂载点",
            "mount": "、".join(t["name"] for t in adjust[:3]) + ("…" if len(adjust) > 3 else ""),
            "basis": "有调节阀开度 / 控制输出点；调节程序尚未挂载",
        })
    registry = store.model_registry()
    caps.append({
        "type": "能力·模型", "name": "机理 / 时序模型", "status": "未挂载" if not registry.get("total") else "已挂载",
        "mount": "—", "basis": "模型注册表暂无数据源" if not registry.get("total") else f"模型注册 {registry['total']} 项",
    })
    return caps


def _rules_view(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.get("ruleId") or r.get("id"),
            "name": r.get("name"),
            "condition": r.get("condition"),
            "conclusion": r.get("conclusion"),
            "severity": r.get("severity"),
            "limitRefs": r.get("limitRefs"),
            "draft": r.get("draft"),
            "matchedBy": r.get("matchedBy"),
        }
        for r in rules
    ]


def _structure_checks(items: list[tuple[str, bool, str]]) -> list[dict[str, Any]]:
    return [{"text": text, "satisfied": ok, "detail": detail} for text, ok, detail in items]


def _safety_constraints(class_relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"text": f"{r['from']} {r['predicate']} {r['to']}", "mechanism": r["mechanism"], "source": r["source"]}
        for r in class_relations if r.get("role") == "报警联锁"
    ]


def _entity_attribute(store: Any, entity: dict[str, Any], own_tags: set[str] | None = None) -> dict[str, Any]:
    """工艺属性（关系对象）作为一条属性：数据关联取它匹配到的测点。

    own_tags 给定时（设备继承设备组的属性），数据关联只保留属于本台设备的测点，
    组里其它设备的测点不算在本台名下。
    """
    tags = []
    for match in entity["match"]["matches"]:
        if match["objectType"] == "parameter":
            param = store.dcs.parameters.get(match["id"])
            tags += [store.dcs.tags[t] for t in (param or {}).get("tagIds", []) if t in store.dcs.tags]
        elif match["objectType"] == "tag" and match["id"] in store.dcs.tags:
            tags.append(store.dcs.tags[match["id"]])
    seen, unique = set(), []
    for t in tags:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)
    units = [t.get("unit") for t in unique]
    attr = {
        "kind": "工艺属性",
        "name": entity["name"],
        "entityId": entity["id"],
        "valueType": _value_type(units, [t.get("blockType") for t in unique], "测量") if unique else "—",
        "description": entity.get("description"),
        "dataLinks": [_tag_link(t) for t in unique[:12]],
        "dataLinkTotal": len(unique),
        "matchStatus": entity["match"]["matchStatusLabel"],
        "pendingConfirmation": entity["match"].get("pendingConfirmation"),
    }
    if own_tags is not None:
        own = [t for t in unique if t["id"] in own_tags]
        attr["dataLinks"] = [_tag_link(t) for t in own[:12]]
        attr["dataLinkTotal"] = len(own)
        attr["groupLinkTotal"] = len(unique)
        if unique and not own:
            attr["note"] = f"设备组共 {len(unique)} 个测点，均不在本台设备上"
        elif len(own) < len(unique):
            attr["note"] = f"本台 {len(own)} 个 / 设备组共 {len(unique)} 个测点"
    return attr


def _sort_attributes(attrs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(attrs, key=lambda a: (ATTRIBUTE_KIND_ORDER.index(a["kind"]) if a["kind"] in ATTRIBUTE_KIND_ORDER else 9))


def _equipment_profile(store: Any, index: AssetIndex, eid: str) -> dict[str, Any]:
    equip = store.dcs.equipment[eid]
    cls, etype, basis = index.asset_class_of_equipment[eid]
    group = store.dcs.equipment_groups.get(equip.get("equipmentGroupId") or "")
    tags = [store.dcs.tags[t] for t in equip["tagIds"] if t in store.dcs.tags]

    # 关联的本体对象（设备实例 / 设备组的生产设备对象）——设备实例继承设备组的拓扑与属性
    rel_info = store.relations_for_ontology_object("equipment", eid)
    anchors = {e["id"]: e for e in rel_info["entities"]}
    inherited: set[str] = set()  # 设备组层级的本体对象：它上面的属性 / 关系是整组共有的
    if group:
        for entity in index.entity_by_name.get(group["name"], []):
            if entity["type"] == "生产设备":
                inherited.add(entity["id"])
                anchors.setdefault(entity["id"], store.entity_brief(entity))
    relations: dict[str, dict[str, Any]] = {}
    for aid in anchors:
        entity = store.relations.entities.get(aid)
        for rid in (entity or {}).get("relationIds", []):
            rel = store.relations.by_id(rid)
            if rel:
                relations[rel["id"]] = rel
    relations_list = list(relations.values())
    anchor_ids = set(anchors)

    # ---- 属性
    attrs: list[dict[str, Any]] = [
        {"kind": "固有", "name": "设备编码", "valueType": "文本", "value": equip.get("owlSubject")},
        {"kind": "固有", "name": "资产大类", "valueType": "枚举", "value": cls, "note": basis},
        {"kind": "固有", "name": "设备类型", "valueType": "枚举", "value": group.get("equipmentType") if group else "未入组"},
        {"kind": "固有", "name": "标准设备组", "valueType": "引用", "value": group["name"] if group else "未入组",
         "refId": group["id"] if group else None},
        {"kind": "固有", "name": "主工段", "valueType": "引用", "value": f"{equip.get('areaCode')} {equip.get('areaName')}",
         "refId": equip.get("areaId")},
        {"kind": "固有", "name": "DCS 控制站", "valueType": "文本", "value": "、".join(equip.get("stations") or [str(equip.get("station"))])},
    ]
    if equip.get("areaSpan", 1) > 1:
        attrs.append({"kind": "固有", "name": "点位覆盖工段", "valueType": "引用列表",
                      "value": "、".join(equip.get("areaCodes") or []), "note": "点位跨多个工段"})
    if group and group.get("components"):
        attrs.append({"kind": "固有", "name": "主要部件", "valueType": "列表", "value": "、".join(group["components"])})
    attrs.append({"kind": "固有", "name": "归属置信度", "valueType": "枚举", "value": equip.get("confidence")})
    aliases = equip.get("aliases") or []
    if aliases:
        attrs.append({"kind": "固有", "name": "点表中的其他写法", "valueType": "列表",
                      "value": "、".join(f"{a['name']}（{a['station']} 站）" for a in aliases),
                      "note": "已按设备归并表合并为本设备"})

    property_entities = []
    from_group: set[str] = set()
    for rel in relations_list:
        if rel.get("category") == "结构关系" and rel.get("predicate") == "具有属性" and (rel.get("subject") or {}).get("id") in anchor_ids:
            entity = store.relations.entities.get((rel.get("object") or {}).get("id") or "")
            if entity and entity["id"] not in {p["id"] for p in property_entities}:
                property_entities.append(entity)
                if (rel.get("subject") or {}).get("id") in inherited:
                    from_group.add(entity["id"])
    own_tag_ids = set(equip["tagIds"])
    for entity in property_entities:
        inherited_attr = entity["id"] in from_group
        attr = _entity_attribute(store, entity, own_tag_ids if inherited_attr else None)
        if inherited_attr:
            attr["inheritedFrom"] = group["name"]
        attrs.append(attr)

    for pid in equip["parameterIds"]:
        param = store.dcs.parameters.get(pid)
        if not param:
            continue
        ptags = [store.dcs.tags[t] for t in param["tagIds"] if t in store.dcs.tags]
        kind = next((PARAM_CATEGORY_KIND.get(c) for c in param["categories"] if c in PARAM_CATEGORY_KIND), "测量")
        attrs.append({
            "kind": kind,
            "name": param["name"],
            "parameterId": pid,
            "valueType": _value_type(param.get("units") or [], param.get("blockTypes") or [], kind),
            "category": "、".join(param["categories"]),
            "dataLinks": [_tag_link(t) for t in ptags],
            "dataLinkTotal": len(ptags),
        })

    # ---- 关系
    class_relations = [{"role": "所属", "category": "空间层级", "predicate": "属于工段", "direction": "in",
                        "target": f"{equip.get('areaCode')} {equip.get('areaName')}", "targetId": equip.get("areaId"),
                        "mechanism": "", "source": "DCS 点表"}]
    if group:
        class_relations.append({"role": "所属", "category": "设备分类", "predicate": "属于设备组", "direction": "in",
                                "target": group["name"], "targetId": group["id"], "mechanism": "", "source": "DCS 点表 · 设备组"})
    for view in _class_relations(relations_list, anchor_ids):
        # 设备组"包含实例"的关系对单台设备而言是同组的兄弟实例
        if view["role"] == "包含实例" and view["from"] in {a["name"] for i, a in anchors.items() if i in inherited}:
            if view["target"] == equip["name"]:
                continue
            view["role"] = "同组实例"
        class_relations.append(view)
    names = {e["name"] for e in property_entities} | {a["name"] for a in anchors.values()}
    attribute_relations = _attribute_relations(store.relations.relations, names)

    # ---- 能力 / 约束 / 规则
    limits = _limits_by_name(store, eid)
    rules = store.rules_for_object(equip["name"], equip.get("areaId"))
    pv_tags = [t for t in tags if (t.get("parameterType") or "").startswith("过程测量")]
    no_unit = [t["name"] for t in pv_tags if not t.get("unit")]
    structure = _structure_checks([
        ("设备必须归属一个主工段", bool(equip.get("areaId")), f"{equip.get('areaCode')} {equip.get('areaName')}"),
        ("设备应归入标准设备组", bool(group), group["name"] if group else "未入组（点表有、设备组清单未声明）"),
        ("过程测量点必须带单位", not no_unit, "全部带单位" if not no_unit else f"缺单位：{'、'.join(no_unit[:5])}"),
        ("设备应有 DCS 点", bool(tags), f"{len(tags)} 个点"),
    ])
    return {
        "objectId": eid,
        "kind": "equipment",
        "name": equip["name"],
        "header": {
            "className": group.get("equipmentType") if group else cls,
            "classPath": ["设备", cls] + ([group.get("equipmentType"), group["name"]] if group else ["未入组设备"]),
            "code": equip.get("owlSubject"),
            "area": f"{equip.get('areaCode')} {equip.get('areaName')}",
            "station": "、".join(equip.get("stations") or [equip.get("station") or ""]),
            "stats": equip.get("stats"),
            "overview": equip.get("overview"),
            "badges": [f"{equip['tagCount']} 个 DCS 点", f"{equip['parameterCount']} 个参数"]
                      + ([f"跨 {equip['areaSpan']} 个工段"] if equip.get("areaSpan", 1) > 1 else [])
                      + ([f"合并 {len(equip['aliases'])} 种写法"] if equip.get("aliases") else []),
            "source": equip.get("source"),
            "aliases": equip.get("aliases") or [],
        },
        "attributes": _sort_attributes(attrs),
        "relations": {"classRelations": class_relations, "attributeRelations": attribute_relations},
        "capabilities": _capabilities(store, eid, tags, limits, rules),
        "constraints": {
            "structure": structure,
            "operating": [_limit_constraint(l) for l in limits],
            "safety": _safety_constraints(class_relations),
        },
        "rules": _rules_view(rules),
        "treePath": index.path_of(eid),
    }


def _group_profile(store: Any, index: AssetIndex, gid: str) -> dict[str, Any]:
    group = store.dcs.equipment_groups[gid]
    etype = group.get("equipmentType") or "未声明类型"
    cls = AssetIndex.group_class(group)
    entity = next((e for e in index.entity_by_name.get(group["name"], []) if e["type"] == "生产设备"), None)
    relations = []
    if entity:
        relations = [store.relations.by_id(r) for r in entity.get("relationIds", [])]
        relations = [r for r in relations if r]
    anchor_ids = {entity["id"]} if entity else set()

    attrs: list[dict[str, Any]] = [
        {"kind": "固有", "name": "类编码", "valueType": "文本", "value": group.get("uri")},
        {"kind": "固有", "name": "设备类型", "valueType": "枚举", "value": etype},
        {"kind": "固有", "name": "所属工段", "valueType": "引用", "value": f"{group.get('areaCode')} {group.get('areaName')}",
         "refId": group.get("areaId")},
        {"kind": "固有", "name": "声明实例数", "valueType": "int", "value": group.get("instanceCountDeclared")},
        {"kind": "固有", "name": "主要部件", "valueType": "列表", "value": "、".join(group.get("components") or []) or "—"},
        {"kind": "固有", "name": "关键测点（画面）", "valueType": "文本", "value": group.get("keyTags") or "—"},
    ]
    names = set()
    for prop in group.get("properties") or []:
        candidates = [e for e in index.entity_by_name.get(prop, []) if e["type"] in ("工艺属性", "质量指标", "业务指标")]
        if candidates:
            attrs.append(_entity_attribute(store, candidates[0]))
            names.add(prop)
        else:
            attrs.append({"kind": "工艺属性", "name": prop, "valueType": "—", "dataLinks": [], "dataLinkTotal": 0,
                          "matchStatus": "本体属性未登记为关系对象"})
    class_relations = _class_relations(relations, anchor_ids)
    instances = [store.dcs.equipment[e] for e in group["equipmentIds"] if e in store.dcs.equipment]
    tags = [store.dcs.tags[t] for t in group["tagIds"] if t in store.dcs.tags]
    limits = _limits_by_name(store, entity["id"]) if entity else []
    rules = store.rules_for_object(group["name"], group.get("areaId"))
    structure = _structure_checks([
        ("设备组必须归属一个工段", bool(group.get("areaId")), f"{group.get('areaCode')} {group.get('areaName')}"),
        ("声明实例数 = 点表中匹配到的实例数", group.get("instanceCountDeclared") in (None, len(instances)),
         f"声明 {group.get('instanceCountDeclared')}，点表匹配 {len(instances)}"),
        ("本体属性均已登记为工艺对象", all(a.get("matchStatus") != "本体属性未登记为关系对象" for a in attrs if a["kind"] == "工艺属性"),
         f"{len(names)}/{len(group.get('properties') or [])} 已登记"),
    ])
    return {
        "objectId": gid,
        "kind": "group",
        "name": group["name"],
        "header": {
            "className": group["name"],
            "classPath": ["设备", cls, etype, group["name"]],
            "code": group.get("uri"),
            "area": f"{group.get('areaCode')} {group.get('areaName')}",
            "badges": [f"{len(instances)} 台实例", f"{group['tagCount']} 个 DCS 点", "类（标准设备组）"],
            "source": group.get("source"),
        },
        "instances": [{"id": e["id"], "name": e["name"], "tagCount": e["tagCount"], "station": e.get("station")} for e in instances],
        "attributes": _sort_attributes(attrs),
        "relations": {
            "classRelations": class_relations,
            "attributeRelations": _attribute_relations(store.relations.relations, names | {group["name"]}),
        },
        "capabilities": _capabilities(store, entity["id"] if entity else gid, tags, limits, rules),
        "constraints": {
            "structure": structure,
            "operating": [_limit_constraint(l) for l in limits],
            "safety": _safety_constraints(class_relations),
        },
        "rules": _rules_view(rules),
        "treePath": index.path_of(gid),
    }


def _entity_profile(store: Any, index: AssetIndex, rid: str) -> dict[str, Any]:
    entity = store.relations.entities[rid]
    brief = store.entity_brief(entity)
    relations = [store.relations.by_id(r) for r in entity.get("relationIds", [])]
    relations = [r for r in relations if r]
    own = _entity_attribute(store, entity)
    own["kind"] = "测量" if own["dataLinks"] else "工艺属性"
    attrs = [
        {"kind": "固有", "name": "对象类型", "valueType": "枚举", "value": entity["type"]},
        {"kind": "固有", "name": "本体类", "valueType": "文本", "value": brief.get("owlClass") or "—"},
        {"kind": "固有", "name": "URI", "valueType": "文本", "value": brief.get("uri") or "—"},
        {"kind": "固有", "name": "所属对象", "valueType": "引用", "value": brief.get("belongsTo") or "—"},
        {"kind": "固有", "name": "说明", "valueType": "文本", "value": brief.get("description") or "—"},
        {"kind": "固有", "name": "DCS 匹配", "valueType": "枚举", "value": brief.get("matchStatusLabel"),
         "note": "映射待现场确认" if brief.get("pendingConfirmation") else None},
        own,
    ]
    tags = [store.dcs.tags[l["tagId"]] for l in own["dataLinks"] if l["tagId"] in store.dcs.tags]
    limits = _limits_by_name(store, rid)
    rules = store.rules_for_object(entity["name"], brief.get("areaId"))
    class_relations = _class_relations(relations, {rid})
    return {
        "objectId": rid,
        "kind": "entity",
        "name": entity["name"],
        "header": {
            "className": entity["type"],
            "classPath": [ENTITY_DOMAIN_LABEL.get(entity["type"], "关系对象"), entity["type"]],
            "code": brief.get("uri"),
            "area": index._area_label(entity.get("areaCode")) if entity.get("areaCode") else "未分工段",
            "badges": [brief.get("matchStatusLabel"), f"{entity['relationCount']} 条关系", f"{own['dataLinkTotal']} 个测点"],
            "source": {"file": "6APA_工业关系.xlsx", "sheet": "实体字典"},
        },
        "attributes": attrs,
        "relations": {
            "classRelations": class_relations,
            "attributeRelations": _attribute_relations(relations, {entity["name"]}),
        },
        "capabilities": _capabilities(store, rid, tags, limits, rules),
        "constraints": {
            "structure": _structure_checks([
                ("工艺对象应有现场测点", bool(tags), f"{len(tags)} 个测点" if tags else "未匹配 DCS 实例，相关路径无法用数据验证"),
            ]),
            "operating": [_limit_constraint(l) for l in limits],
            "safety": _safety_constraints(class_relations),
        },
        "rules": _rules_view(rules),
        "treePath": index.path_of(rid),
    }


ENTITY_DOMAIN_LABEL = {etype: next(d["name"] for d in DOMAINS if d["key"] == key) for etype, key in ENTITY_DOMAIN.items()}


def _area_profile(store: Any, index: AssetIndex, aid: str) -> dict[str, Any]:
    area = store.dcs.areas[aid]

    def flow(rows: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
        return [{"role": role, "category": "工段衔接", "predicate": "衔接物料", "direction": "out" if role == "下游" else "in",
                 "target": index._area_label(r.get("code")), "targetId": ids.area_id(r["code"]) if r.get("code") else None,
                 "mechanism": r.get("material") or "", "source": "DCS 点表 · 工段划分"} for r in rows or []]

    groups = [store.dcs.equipment_groups[g] for g in area.get("equipmentGroupIds", []) if g in store.dcs.equipment_groups]
    attrs = [
        {"kind": "固有", "name": "工段编号", "valueType": "文本", "value": area.get("code")},
        {"kind": "固有", "name": "英文标识", "valueType": "文本", "value": area.get("nameEn")},
        {"kind": "固有", "name": "工艺定位", "valueType": "文本", "value": area.get("positioning")},
        {"kind": "固有", "name": "涉及控制站", "valueType": "列表", "value": "、".join(map(str, area.get("stations") or []))},
        {"kind": "固有", "name": "流程画面", "valueType": "列表", "value": "、".join(area.get("processScreens") or []) or "—"},
        {"kind": "固有", "name": "设备 / 设备组 / 点位", "valueType": "统计",
         "value": f"{area['equipmentCount']} 台 / {len(groups)} 组 / {area['tagCount']} 点"},
    ]
    entities = [e for e in store.relations.entities.values() if e.get("areaCode") == area["code"] and e["type"] == "工艺属性"]
    attrs += [_entity_attribute(store, e) for e in entities]
    class_relations = flow(area.get("upstream"), "上游") + flow(area.get("downstream"), "下游")
    class_relations += [{"role": "包含实例", "category": "空间层级", "predicate": "包含设备组", "direction": "out",
                         "target": g["name"], "targetId": g["id"], "mechanism": g.get("equipmentType") or "", "source": "DCS 点表"}
                        for g in groups]
    limits = [l for l in _all_limits() if l.get("areaCode") == area["code"]]
    rules = [r for r in store.rules_for_object(None, aid) if r.get("matchedBy") == "同工段规则"]
    return {
        "objectId": aid,
        "kind": "area",
        "name": area["name"],
        "header": {
            "className": "生产工段",
            "classPath": ["空间与层级", "6-APA 生产线", f"{area['code']} {area['name']}"],
            "code": area.get("uri") or area["id"],
            "area": f"{area['code']} {area['name']}",
            "badges": [f"{area['equipmentCount']} 台设备", f"{area['tagCount']} 个 DCS 点", f"{area.get('relationCount', 0)} 条关系"],
            "source": area.get("source"),
        },
        "attributes": attrs,
        "relations": {
            "classRelations": class_relations,
            "attributeRelations": _attribute_relations(store.relations.relations, {e["name"] for e in entities}),
        },
        "capabilities": _capabilities(store, aid, [store.dcs.tags[t] for t in area.get("tagIds", [])[:400] if t in store.dcs.tags],
                                      limits, rules),
        "constraints": {"structure": [], "operating": [_limit_constraint(l) for l in limits], "safety": []},
        "rules": _rules_view(rules),
        "treePath": index.path_of(aid),
    }


def _all_limits() -> list[dict[str, Any]]:
    from backend.services import process_limits

    try:
        return process_limits._load()
    except Exception:
        return []


class ProfileNotFound(LookupError):
    status = 404

    def __init__(self, object_id: str) -> None:
        super().__init__(object_id)
        self.detail = f"未找到对象：{object_id}（资产档案支持 equip- / egrp- / robj- / area- / tag- 与 :Dev_ 形式的 OWL Subject）"


def profile(store: Any, object_id: str) -> dict[str, Any]:
    """对象的本体档案。tag- 返回所属设备的档案并标出焦点位号。"""
    index = asset_index(store)
    oid = ids.normalize(object_id) or ""
    if oid.startswith(":"):
        equip = store.dcs.equipment_by_owl(oid)  # 含已归并的旧写法
        oid = equip["id"] if equip else oid
    if oid.startswith("tag-") and oid in store.dcs.tags:
        tag = store.dcs.tags[oid]
        if tag.get("equipmentId") in store.dcs.equipment:
            result = _equipment_profile(store, index, tag["equipmentId"])
            result["focusTag"] = tag["name"]
            return result
    if oid in store.dcs.equipment:
        # 已归并设备的旧 ID 转到合并后的设备
        return _equipment_profile(store, index, store.dcs.equipment[oid]["id"])
    if oid in store.dcs.equipment_groups:
        return _group_profile(store, index, oid)
    resolved_group = store.resolve_group_id(oid)
    if resolved_group:
        return _group_profile(store, index, resolved_group)
    if oid in store.relations.entities:
        return _entity_profile(store, index, oid)
    area = store.dcs.resolve_area(oid)
    if area and area in store.dcs.areas:
        return _area_profile(store, index, area)
    raise ProfileNotFound(object_id)


def tree(store: Any, parent: str | None) -> dict[str, Any]:
    index = asset_index(store)
    nodes = index.children(parent or "") if parent else index.roots()
    return {"parent": parent or None, "items": nodes, "total": len(nodes)}


def search(store: Any, keyword: str, limit: int = 30) -> dict[str, Any]:
    return asset_index(store).search(keyword, limit)
