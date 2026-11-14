"""工程态对象的手动编辑：参数、参数约束、拓扑关系的新增 / 修改 / 删除（需求 SW-042～044）。

存储 data/store/object_edits.json，按 对象 ID → 页签 记录三类改动：
- added：本对象新增的条目（参数 UP-xxxx、约束 UC-xxxx）；
- modified：对已有条目的修改（参数按名称；约束的限值修改走 overrides.json 的限值覆盖，参与判定）；
- removed：从本对象移除的已有条目（可恢复）。拓扑关系的新增 / 修改走 user_relations.json，这里只记移除的推导关系。

合并在 tabs.tab() 里做（merge_*），单文件版的 frontend/src/api/static.ts 有同一套合并逻辑（改这里要同步改那边）。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.v2.userdata import LIMIT_FIELDS, UserDataError, _JsonFile, now

TABS = ("parameters", "constraints", "topology")
ATTR_CATEGORIES = ["基本信息", "设计参数"]
PARAM_CATEGORIES = ["测量值", "设定值", "阀位", "控制指令", "状态", "计算值"]
BINDING_STATES = ["已绑定", "待确认", "未绑定", "失效"]
PARAM_FIELDS = ("name", "category", "valueType", "value", "description", "tags")
CONS_FIELDS = ("appliesTo", "operatingMode", "unit", "values", "note")
DRAFT = "草案·待工艺确认"


class ObjectEdits(_JsonFile):
    def __init__(self) -> None:
        super().__init__("object_edits.json", {"objects": {}})

    def get(self, oid: str, tab: str) -> dict[str, Any]:
        return (self.data["objects"].get(oid) or {}).get(tab) or {"added": [], "modified": {}, "removed": []}

    def _slot(self, oid: str, tab: str) -> dict[str, Any]:
        if tab not in TABS:
            raise UserDataError(f"不支持编辑的页签：{tab}")
        return self.data["objects"].setdefault(oid, {}).setdefault(tab, {"added": [], "modified": {}, "removed": []})

    def add(self, oid: str, tab: str, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            s = self._slot(oid, tab)
            prefix = {"parameters": "UP", "constraints": "UC"}.get(tab, "UT")
            nums = [int(str(x["key"]).rsplit("-", 1)[-1]) for x in s["added"] if str(x.get("key", "")).startswith(prefix)]
            item = {**item, "key": f"{prefix}-{(max(nums) if nums else 0) + 1:04d}", "createdAt": now(), "createdBy": "演示用户"}
            s["added"].append(item)
            self.save()
            return item

    def update(self, oid: str, tab: str, key: str, patch: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """返回 (修改前, 修改后)。新增的条目直接改；已有条目记一份修改（patch）。"""
        with self._lock:
            s = self._slot(oid, tab)
            added = next((x for x in s["added"] if x["key"] == key), None)
            if added:
                before = dict(added)
                added.update(patch, updatedAt=now())
                self.save()
                return before, added
            before = s["modified"].get(key)
            s["modified"][key] = {**(before or {}), **patch, "updatedAt": now(), "updatedBy": "演示用户"}
            self.save()
            return before, s["modified"][key]

    def remove(self, oid: str, tab: str, key: str) -> str:
        """新增的条目直接删掉；已有条目记为移除（可恢复）。返回「删除」或「移除」。"""
        with self._lock:
            s = self._slot(oid, tab)
            added = next((x for x in s["added"] if x["key"] == key), None)
            if added:
                s["added"].remove(added)
                self.save()
                return "删除"
            if key not in s["removed"]:
                s["removed"].append(key)
            s["modified"].pop(key, None)
            self.save()
            return "移除"

    def restore(self, oid: str, tab: str, key: str) -> None:
        with self._lock:
            s = self._slot(oid, tab)
            if key in s["removed"]:
                s["removed"].remove(key)
            s["modified"].pop(key, None)
            self.save()


# ------------------------------------------------------------------ 校验
def clean_param(body: dict[str, Any]) -> dict[str, Any]:
    out = {k: body[k] for k in PARAM_FIELDS if k in body}
    if "name" in out:
        out["name"] = str(out["name"] or "").strip()
        if not out["name"]:
            raise UserDataError("参数名称不能为空")
    if "category" in out and out["category"] not in ATTR_CATEGORIES + PARAM_CATEGORIES:
        raise UserDataError(f"类别只能是：{'、'.join(ATTR_CATEGORIES + PARAM_CATEGORIES)}")
    if "tags" in out:
        tags = out["tags"] if isinstance(out["tags"], list) else str(out["tags"] or "").replace("，", ",").replace("、", ",").split(",")
        out["tags"] = list(dict.fromkeys(str(t).strip().upper() for t in tags if str(t).strip()))
    return out


def clean_constraint(body: dict[str, Any]) -> dict[str, Any]:
    out = {k: body[k] for k in CONS_FIELDS if k in body}
    if "appliesTo" in out and not str(out["appliesTo"] or "").strip():
        raise UserDataError("适用参数不能为空")
    if "values" in out:
        vals: dict[str, float] = {}
        for f in LIMIT_FIELDS:
            v = (out["values"] or {}).get(f)
            if v in (None, ""):
                continue
            try:
                vals[f] = float(v)
            except (TypeError, ValueError):
                raise UserDataError(f"限值 {f} 不是数字：{v}") from None
        order = [vals[f] for f in LIMIT_FIELDS if f in vals]
        if order != sorted(order):
            raise UserDataError("限值要满足 低低限 ≤ 低限 ≤ 正常下限 ≤ 正常上限 ≤ 高限 ≤ 高高限")
        out["values"] = vals
    return out


# ------------------------------------------------------------------ 合并（与 static.ts 的 mergeParameters / mergeConstraints / mergeTopology 一致）
TagInfo = Callable[[str], "dict[str, Any] | None"]


def _link(tag: str, info: TagInfo) -> dict[str, Any]:
    t = info(tag) or {}
    return {"tag": tag, "desc": t.get("desc") or "", "unit": t.get("unit") or "", "block": t.get("block") or "", "station": "",
            "equipment": t.get("equipment") or "", "limit": t.get("limit"), "own": True, "manual": True}


def _apply_param(x: dict[str, Any], p: dict[str, Any], info: TagInfo) -> dict[str, Any]:
    for f in ("name", "category", "valueType", "value", "description"):
        if f in p:
            x[f] = p[f]
    if "tags" in p:
        x["links"] = [_link(t, info) for t in p["tags"]]
    if x.get("category") in ATTR_CATEGORIES:
        x["section"], x["group"], x["binding"], x["bindingNote"] = "属性", x["category"], None, ""
    else:
        x["section"] = "参数"
        if "tags" in p or x.get("edit") == "新增":
            own = [l for l in x.get("links") or [] if l.get("own", True)]
            missing = [l["tag"] for l in own if not info(l["tag"])]
            x["binding"], x["bindingNote"] = (("失效", f"位号不在点表中：{'、'.join(missing)}") if missing else
                                              ("已绑定", "人工绑定") if own else ("未绑定", "未关联位号"))
    return x


def merge_parameters(resp: dict[str, Any], e: dict[str, Any], info: TagInfo) -> dict[str, Any]:
    removed, mod = set(e.get("removed") or []), e.get("modified") or {}
    items, gone = [], []
    for x in resp["items"]:
        k = x["name"]
        if k in removed:
            gone.append({"key": k, "name": x["name"], "category": x.get("category")})
            continue
        x["editKey"] = k
        if k in mod:
            x = _apply_param(x, mod[k], info)
            x["edit"] = "已修改"
        items.append(x)
    for a in e.get("added") or []:
        x = {"group": a.get("category"), "name": "", "valueType": "", "value": None, "description": "", "note": "", "links": [],
             "edit": "新增", "editKey": a["key"], "userParam": True}
        _apply_param(x, a, info)
        x["inherited"], x["inheritedFrom"] = False, None
        items.append(x)
    order = ATTR_CATEGORIES + PARAM_CATEGORIES
    items.sort(key=lambda x: (order.index(x["category"]) if x.get("category") in order else len(order), 0 if x.get("semantic") else 1))
    counts = {g: sum(1 for x in items if x.get("category") == g) for g in order}
    resp.update(items=items, removedItems=gone, counts=counts, groups=[g for g in order if counts[g]],
                attrGroups=[g for g in ATTR_CATEGORIES if counts[g]], paramGroups=[g for g in PARAM_CATEGORIES if counts[g]],
                bindingCounts={b: sum(1 for x in items if x.get("binding") == b) for b in BINDING_STATES},
                tagTotal=len({l["tag"] for x in items for l in x.get("links") or [] if l.get("own")}), canEdit=True,
                categories={"属性": ATTR_CATEGORIES, "参数": PARAM_CATEGORIES})
    return resp


def constraint_row(a: dict[str, Any]) -> dict[str, Any]:
    v = a.get("values") or {}
    lo, hi = v.get("normalLow"), v.get("normalHigh")
    return {"id": a["key"], "appliesTo": a.get("appliesTo") or "", "basis": a.get("note") or "人工新增",
            "operatingMode": a.get("operatingMode") or "", "modePhenomenon": None,
            "alarm": {f: v.get(f) for f in ("lowLow", "low", "high", "highHigh")},
            "normal": f"{'' if lo is None else lo}~{'' if hi is None else hi}" if (lo is not None or hi is not None) else None,
            "hasValues": bool(v), "unit": a.get("unit") or "", "versions": [], "status": DRAFT,
            "limitValues": {f: v.get(f) for f in LIMIT_FIELDS}, "inherited": False, "inheritedFrom": None,
            "edit": "新增", "editKey": a["key"], "userConstraint": True, "note": a.get("note") or ""}


def merge_constraints(resp: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
    removed = set(e.get("removed") or [])
    rows, gone = [], []
    for c in resp["operating"]:
        if c["id"] in removed:
            gone.append({"key": c["id"], "name": f"{c['id']} {c.get('appliesTo') or ''}"})
            continue
        c["editKey"] = c["id"]
        rows.append(c)
    rows += [constraint_row(a) for a in e.get("added") or []]
    resp.update(operating=rows, removedItems=gone, canEdit=True)
    return resp


def topology_key(r: dict[str, Any]) -> str:
    return f"{r.get('predicate')}|{r.get('direction')}|{r.get('targetId') or r.get('target')}"


def merge_topology(resp: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
    removed = set(e.get("removed") or [])
    items, gone = [], []
    for r in resp["items"]:
        k = topology_key(r)
        if not r.get("userRelation") and k in removed:
            gone.append({"key": k, "name": f"{'→' if r.get('direction') == 'out' else '←'} {r.get('predicate')}：{r.get('target')}"})
            continue
        r["editKey"] = k
        items.append(r)
    resp.update(items=items, removedItems=gone)
    return resp
