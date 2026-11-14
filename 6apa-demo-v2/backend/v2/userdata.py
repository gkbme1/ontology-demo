"""工程态在线编辑的补充数据（保存在 data/store/，不进 git；没有种子，首次为空）：

- AuditLog       变更记录（需求 SW-062 / SW-079）：时间、操作人、操作类型、对象、字段前后值、来源；
- OverrideStore  继承覆盖（需求 SW-026 / 045 / 046）：设备上覆盖或禁用设备组的现象（判定规则阈值、持续时长）与工艺限值；
- RelationStore  人工新增的拓扑 / 工艺影响关系（需求 SW-044 / 049），带端点类型校验。
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _store_dir() -> Path:
    return Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class UserDataError(ValueError):
    pass


class _JsonFile:
    def __init__(self, name: str, default: Any) -> None:
        self.path = _store_dir() / name
        self.default = default
        self._lock = threading.RLock()
        self.data = self._read()

    def _read(self) -> Any:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return copy.deepcopy(self.default)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        with self._lock:
            self.data = copy.deepcopy(self.default)
            self.save()


# ------------------------------------------------------------------ 变更记录
def diff(before: dict[str, Any] | None, after: dict[str, Any] | None, skip: tuple[str, ...] = ("updatedAt", "updatedBy", "createdAt")) -> list[dict[str, Any]]:
    before, after = before or {}, after or {}
    out = []
    for k in sorted(set(before) | set(after)):
        if k in skip or k.startswith("_"):
            continue
        a, b = before.get(k), after.get(k)
        if a != b:
            out.append({"field": k, "before": _short(a), "after": _short(b)})
    return out


def _short(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        text = json.dumps(v, ensure_ascii=False)
        return text if len(text) <= 300 else text[:297] + "…"
    return v


class AuditLog(_JsonFile):
    MAX = 5000

    def __init__(self) -> None:
        super().__init__("audit.json", {"items": []})

    def record(self, op: str, kind: str, target_id: str, name: str, *, objects: list[str] | None = None,
               changes: list[dict[str, Any]] | None = None, source: str = "手工", user: str = "演示用户", note: str = "") -> dict[str, Any]:
        with self._lock:
            items = self.data.setdefault("items", [])
            entry = {"id": f"AUD-{len(items) + 1:05d}", "time": now(), "user": user, "op": op, "kind": kind,
                     "targetId": target_id, "name": name, "objects": [o for o in (objects or []) if o],
                     "changes": changes or [], "source": source, "note": note}
            items.append(entry)
            del items[:-self.MAX]
            self.save()
            return entry

    def for_object(self, ids: set[str]) -> list[dict[str, Any]]:
        return [e for e in reversed(self.data.get("items", [])) if e["targetId"] in ids or ids & set(e.get("objects") or [])]

    def reset(self) -> None:  # 恢复种子数据时不清空变更记录，只追加一条
        self.record("恢复种子数据", "系统", "", "现象 / 根因关系 / 计算组态 / 覆盖 / 人工关系")


# ------------------------------------------------------------------ 继承覆盖
LIMIT_FIELDS = ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")


class OverrideStore(_JsonFile):
    """键 = 对象 ID | 现象 ID（或 限值 ID）。"""

    def __init__(self) -> None:
        super().__init__("overrides.json", {"phenomena": {}, "limits": {}})

    def phenomenon(self, object_id: str, pid: str) -> dict[str, Any] | None:
        return self.data["phenomena"].get(f"{object_id}|{pid}")

    def limit(self, object_id: str, limit_id: str) -> dict[str, Any] | None:
        return self.data["limits"].get(f"{object_id}|{limit_id}")

    def set_phenomenon(self, object_id: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entry = {"objectId": object_id, "phenomenonId": pid, "disabled": bool(body.get("disabled")),
                     "rule": body.get("rule") if not body.get("disabled") else None,
                     "note": body.get("note") or "", "updatedAt": now(), "updatedBy": "演示用户"}
            if not entry["disabled"] and not entry["rule"]:
                raise UserDataError("覆盖时要给出覆盖后的判定规则，或选择禁用")
            self.data["phenomena"][f"{object_id}|{pid}"] = entry
            self.save()
            return entry

    def set_limit(self, object_id: str, limit_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            values = {}
            for f in LIMIT_FIELDS:
                v = (body.get("values") or {}).get(f)
                if v in (None, ""):
                    continue
                try:
                    values[f] = float(v)
                except (TypeError, ValueError):
                    raise UserDataError(f"限值 {f} 不是数字：{v}") from None
            order = [values[f] for f in LIMIT_FIELDS if f in values]
            if order != sorted(order):
                raise UserDataError("限值要满足 低低限 ≤ 低限 ≤ 正常下限 ≤ 正常上限 ≤ 高限 ≤ 高高限")
            entry = {"objectId": object_id, "limitId": limit_id, "disabled": bool(body.get("disabled")),
                     "values": {} if body.get("disabled") else values, "note": body.get("note") or "",
                     "updatedAt": now(), "updatedBy": "演示用户"}
            if not entry["disabled"] and not values:
                raise UserDataError("覆盖时至少填写一个限值，或选择禁用")
            self.data["limits"][f"{object_id}|{limit_id}"] = entry
            self.save()
            return entry

    def clear(self, kind: str, object_id: str, ref_id: str) -> dict[str, Any] | None:
        with self._lock:
            old = self.data[kind].pop(f"{object_id}|{ref_id}", None)
            self.save()
            return old


# ------------------------------------------------------------------ 人工关系
# 关系类型 → (允许的起点类型, 允许的终点类型)。类型：equipment / group / stream / utility / parameter / quality
RELATION_TYPES: dict[str, dict[str, Any]] = {
    "物理拓扑": {"tab": "topology", "from": {"equipment", "group"}, "to": {"equipment", "group"}, "label": "串联下游"},
    "工艺流向": {"tab": "topology", "from": {"stream", "equipment", "group"}, "to": {"stream", "equipment", "group"}, "label": "流入"},
    "供应": {"tab": "topology", "from": {"utility"}, "to": {"equipment", "group"}, "label": "供给介质"},
    "工艺影响": {"tab": "influence", "from": {"parameter"}, "to": {"parameter", "quality"}, "label": "正向影响"},
}
INFLUENCE_LABELS = ["正向影响", "负向影响", "影响"]
KIND_NAMES = {"equipment": "设备", "group": "设备组", "stream": "物料流股", "utility": "公用介质", "parameter": "工艺参数", "quality": "质量指标"}


class RelationStore(_JsonFile):
    def __init__(self) -> None:
        super().__init__("user_relations.json", {"items": []})

    @property
    def items(self) -> list[dict[str, Any]]:
        return self.data["items"]

    def create(self, body: dict[str, Any], resolve_kind) -> dict[str, Any]:  # noqa: ANN001
        rtype = body.get("type")
        spec = RELATION_TYPES.get(rtype or "")
        if not spec:
            raise UserDataError(f"关系类型只能是：{'、'.join(RELATION_TYPES)}")
        src, dst = body.get("from") or {}, body.get("to") or {}
        for end, allowed, label in ((src, spec["from"], "起点"), (dst, spec["to"], "终点")):
            kind = resolve_kind(end)
            if not kind:
                raise UserDataError(f"{label}对象不存在：{end.get('name') or end.get('id')}")
            if kind not in allowed:
                raise UserDataError(f"「{rtype}」的{label}只能是{'、'.join(KIND_NAMES[k] for k in sorted(allowed))}，"
                                    f"「{end.get('name')}」是{KIND_NAMES.get(kind, kind)}")
            end["kind"] = kind
        if (src.get("id"), src.get("name")) == (dst.get("id"), dst.get("name")):
            raise UserDataError("起点和终点不能是同一个对象")
        label = body.get("label") or spec["label"]
        if rtype == "工艺影响" and label not in INFLUENCE_LABELS:
            raise UserDataError(f"影响方向只能是：{'、'.join(INFLUENCE_LABELS)}")
        with self._lock:
            for r in self.items:
                if r["type"] == rtype and r["from"] == src and r["to"] == dst:
                    raise UserDataError(f"这条关系已存在：{r['id']}")
            nums = [int(r["id"].rsplit("-", 1)[-1]) for r in self.items]
            rel = {"id": f"REL-U-{(max(nums) if nums else 0) + 1:04d}", "type": rtype, "label": label,
                   "from": src, "to": dst, "mechanism": body.get("mechanism") or "", "lag": body.get("lag") or "",
                   "status": "草案·待工艺确认", "source": "人工新增", "createdAt": now(), "createdBy": "演示用户"}
            self.items.append(rel)
            self.save()
            return rel

    def delete(self, rid: str) -> dict[str, Any]:
        with self._lock:
            rel = next((r for r in self.items if r["id"] == rid), None)
            if not rel:
                raise LookupError(rid)
            self.items.remove(rel)
            self.save()
            return rel


# ------------------------------------------------------------------ 处置规程的在线编辑
class ProcedureEdits(_JsonFile):
    """处置卡原文来自 6APA_处置规程.xlsx（只读）；在线编辑的步骤、检查项、执行边界、版本与状态按卡片 ID 覆盖保存。"""

    def __init__(self) -> None:
        super().__init__("procedure_edits.json", {"cards": {}})

    def get(self, cid: str) -> dict[str, Any] | None:
        return self.data["cards"].get(cid)

    def put(self, cid: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entry = {k: body[k] for k in ("steps", "checks", "autoExecution", "authorization", "version", "status", "scope") if k in body}
            for s in entry.get("steps") or []:
                if not str(s.get("description") or "").strip():
                    raise UserDataError("每个步骤都要有操作说明")
            entry["updatedAt"], entry["updatedBy"] = now(), "演示用户"
            self.data["cards"][cid] = {**(self.data["cards"].get(cid) or {}), **entry}
            self.save()
            return self.data["cards"][cid]
