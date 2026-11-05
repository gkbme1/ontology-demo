"""运行时上下文：一次加载本体（复制来的加载器）+ 层级 + 现象 / 根因 / 计算组态仓库，供各接口共用。"""
from __future__ import annotations

import threading
from typing import Any

from backend.ontology.indexes import OntologyStore
from backend.services import asset_model, process_limits
from backend.v2.calculations import CalcStore
from backend.v2.hierarchy import Hierarchy
from backend.v2.phenomena import PhenomenonStore


class AppContext:
    def __init__(self) -> None:
        self.store = OntologyStore()
        self.hierarchy = Hierarchy(self.store)
        self.phen = PhenomenonStore()
        self.calcs = CalcStore()
        self.limits = {l["id"]: l for l in process_limits._load()}
        dcs = self.store.dcs
        self.tag_by_name = {t["name"]: t for t in dcs.tags.values()}
        self.tags_of_equipment: dict[str, list[dict[str, Any]]] = {}
        for t in dcs.tags.values():
            if t.get("equipmentId"):
                self.tags_of_equipment.setdefault(t["equipmentId"], []).append(t)
        # 位号 → 限值（按限值的适用对象落到的位号）
        self.limit_of_tag: dict[str, dict[str, Any]] = {}
        for limit in self.limits.values():
            try:
                tags, _ = process_limits.resolve_targets(self.store, limit)
            except Exception:  # noqa: BLE001 个别限值解析失败不影响整体
                continue
            for tag in tags:
                # 同一位号落到多条限值时，优先与位号同工段的那条
                current = self.limit_of_tag.get(tag["name"])
                same = lambda l: l.get("area") and l.get("area") == tag.get("areaName")  # noqa: E731
                if current is None or (not same(current) and same(limit)):
                    self.limit_of_tag[tag["name"]] = limit
        self._profile_cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 本体对象
    def profile(self, object_id: str) -> dict[str, Any]:
        with self._lock:
            if object_id not in self._profile_cache:
                self._profile_cache[object_id] = asset_model.profile(self.store, object_id)
            return self._profile_cache[object_id]

    def object_name(self, object_id: str) -> str:
        dcs = self.store.dcs
        if object_id in dcs.equipment:
            return dcs.equipment[object_id]["name"]
        if object_id in dcs.equipment_groups:
            return dcs.equipment_groups[object_id]["name"]
        if object_id in self.hierarchy.ops:
            return self.hierarchy.ops[object_id]["name"]
        return object_id

    def object_kind(self, object_id: str) -> str:
        if object_id.startswith("equip-"):
            return "equipment"
        if object_id.startswith("egrp-"):
            return "group"
        return "other"

    def group_members(self, group_id: str, op_id: str | None = None) -> list[str]:
        h = self.hierarchy
        if op_id:
            return list(h.op_group_members.get((op_id, group_id), []))
        out: list[str] = []
        for op in h.ops_of_group.get(group_id, []):
            out += [e for e in h.op_group_members.get((op, group_id), []) if e not in out]
        return out

    def parameter_tags(self, object_id: str, name: str) -> list[dict[str, Any]]:
        """对象上名为 name 的属性（工艺属性 / 测量 / 状态 / 控制）落到的测点。"""
        prof = self.profile(object_id)
        out: list[dict[str, Any]] = []
        for attr in prof.get("attributes") or []:
            if attr.get("name") != name:
                continue
            for link in attr.get("dataLinks") or []:
                tag = self.tag_by_name.get(link.get("tag"))
                if tag and tag not in out:
                    out.append(tag)
        return out

    def parameter_names(self, object_id: str) -> list[dict[str, Any]]:
        prof = self.profile(object_id)
        out = []
        for attr in prof.get("attributes") or []:
            if attr.get("kind") == "固有":
                continue
            out.append({"name": attr["name"], "kind": attr.get("kind"),
                        "tags": [l.get("tag") for l in attr.get("dataLinks") or []]})
        return out

    # ------------------------------------------------------------ 现象作用域
    def phenomenon_ops(self, phenomenon: dict[str, Any]) -> list[str]:
        anchor = (phenomenon.get("anchor") or {}).get("id") or ""
        return self.hierarchy.ops_of_object(self.store, anchor)

    def phenomena_for_object(self, object_id: str) -> list[tuple[dict[str, Any], str]]:
        """对象自己的现象 + 继承自所属设备组的现象。返回 (现象, 来源说明)。"""
        out = []
        group_id = None
        if object_id in self.store.dcs.equipment:
            group_id = self.store.dcs.equipment[object_id].get("equipmentGroupId")
        for p in self.phen.phenomena.values():
            aid = (p.get("anchor") or {}).get("id")
            if aid == object_id:
                out.append((p, "本对象"))
            elif group_id and aid == group_id:
                out.append((p, "继承自设备组"))
        return out


_ctx: AppContext | None = None


def get_ctx() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = AppContext()
    return _ctx


def reload_ctx() -> AppContext:
    global _ctx
    _ctx = AppContext()
    return _ctx
