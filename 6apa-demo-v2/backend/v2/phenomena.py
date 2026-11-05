"""现象、判定规则、根因影响关系。

现象（Phenomenon）：对当前情况的描述，如「水解罐pH偏高」「反应期搅拌停止」。
  - 挂在一个本体对象上（设备组 / 设备），设备组上的现象对组内每台设备生效；
  - 带一条判定规则：条件树，「与 / 或」任意嵌套，叶子是单个条件；
  - 同一个现象既可以是原因，也可以是结果，角色由根因影响关系决定。

判定规则（rule）：
  组   {"type": "group", "op": "AND" | "OR", "children": [...]}
  条件 {"type": "condition",
        "subject": {"kind": "parameter", "name": "反应体系pH"}      本对象的工艺属性（自动落到本台的测点）
                 | {"kind": "tag", "tag": "AT_1301A1"}              直接指定 DCS 位号
                 | {"kind": "calc", "calcId": "CALC-S11-01"}         计算组态的输出,
        "aggregate": "any" | "all" | "mean",                         一个属性落到多个测点时如何合并（默认 any）
        "operator": ">" | ">=" | "<" | "<=" | "=" | "!=" | "change",  change = 由 from 变 to
        "threshold": {"kind": "value", "value": 8.2}
                   | {"kind": "limit", "limitId": "PL002", "field": "normalHigh"},
        "from": 1, "to": 0,                                           仅 change 用
        "durationSec": 60}                                            持续多久才算成立（0 = 即时）

根因影响关系（CausalLink）：一条记录 = 「原因现象 导致 结果现象」。

种子数据在 data/seed/，运行时编辑保存在 data/store/（首次启动从 seed 复制）。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"
# 运行时编辑保存位置；测试时用环境变量 V2_STORE_DIR 指到临时目录
STORE_DIR = Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store")

OPERATORS = {">": "大于", ">=": "大于等于", "<": "小于", "<=": "小于等于", "=": "等于", "!=": "不等于", "change": "由…变为…"}
LIMIT_FIELDS = {
    "lowLow": "低低限", "low": "低限", "normalLow": "正常下限",
    "normalHigh": "正常上限", "high": "高限", "highHigh": "高高限",
}
AGGREGATES = {"any": "任一测点", "all": "全部测点", "mean": "测点均值"}
CATEGORIES = ["工艺", "设备", "仪表", "操作", "物料", "公用工程", "环境"]
STATUSES = ["草案·待工艺确认", "已确认", "停用"]
CONFIDENCE = ["高", "中", "低"]
DRAFT = "草案·待工艺确认"


class ValidationError(ValueError):
    pass


class NotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ 规则文本
def _duration_text(sec: Any) -> str:
    try:
        sec = float(sec or 0)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    if sec % 60 == 0:
        return f" 持续 {int(sec // 60)} 分钟"
    return f" 持续 {int(sec)} 秒"


def subject_text(subject: dict[str, Any] | None, calc_names: dict[str, str] | None = None) -> str:
    subject = subject or {}
    kind = subject.get("kind")
    if kind == "parameter":
        return f"本对象.{subject.get('name') or '?'}"
    if kind == "tag":
        return f"位号 {subject.get('tag') or '?'}"
    if kind == "calc":
        cid = subject.get("calcId") or "?"
        return f"计算 {(calc_names or {}).get(cid, cid)}"
    return "?"


def threshold_text(th: dict[str, Any] | None, limits: dict[str, dict[str, Any]] | None = None) -> str:
    th = th or {}
    if th.get("kind") == "limit":
        lid = th.get("limitId") or "?"
        field = LIMIT_FIELDS.get(th.get("field") or "", th.get("field") or "?")
        value = ((limits or {}).get(lid) or {}).get(th.get("field") or "")
        suffix = f"（{value}）" if value is not None and limits else ""
        return f"{lid} {field}{suffix}"
    value = th.get("value")
    return "?" if value is None else str(value)


def rule_text(rule: dict[str, Any] | None, limits: dict | None = None, calc_names: dict | None = None, top: bool = True) -> str:
    if not rule:
        return "（判定规则待定义）"
    if rule.get("type") == "group":
        op = "且" if rule.get("op") == "AND" else "或"
        parts = [rule_text(c, limits, calc_names, top=False) for c in rule.get("children") or []]
        if not parts:
            return "（空条件组）"
        joined = f" {op} ".join(parts)
        return joined if top or len(parts) == 1 else f"（{joined}）"
    subj = subject_text(rule.get("subject"), calc_names)
    agg = rule.get("aggregate") or "any"
    agg_text = f"[{AGGREGATES.get(agg, agg)}]" if rule.get("subject", {}).get("kind") == "parameter" and agg != "any" else ""
    op = rule.get("operator")
    if op == "change":
        return f"{subj}{agg_text} 由 {rule.get('from')} 变为 {rule.get('to')}{_duration_text(rule.get('durationSec'))}"
    return f"{subj}{agg_text} {OPERATORS.get(op, op)} {threshold_text(rule.get('threshold'), limits)}{_duration_text(rule.get('durationSec'))}"


def iter_conditions(rule: dict[str, Any] | None):
    if not rule:
        return
    if rule.get("type") == "group":
        for child in rule.get("children") or []:
            yield from iter_conditions(child)
    else:
        yield rule


# ------------------------------------------------------------------ 校验
def validate_rule(rule: Any, path: str = "rule") -> None:
    if rule is None:
        return
    if not isinstance(rule, dict):
        raise ValidationError(f"{path} 必须是对象")
    kind = rule.get("type")
    if kind == "group":
        if rule.get("op") not in ("AND", "OR"):
            raise ValidationError(f"{path}.op 只能是 AND / OR")
        children = rule.get("children")
        if not isinstance(children, list) or not children:
            raise ValidationError(f"{path}.children 至少要有一个条件")
        for i, child in enumerate(children):
            validate_rule(child, f"{path}.children[{i}]")
        return
    if kind != "condition":
        raise ValidationError(f"{path}.type 只能是 group / condition")
    subject = rule.get("subject") or {}
    sk = subject.get("kind")
    if sk == "parameter" and not subject.get("name"):
        raise ValidationError(f"{path}.subject.name 不能为空")
    if sk == "tag" and not subject.get("tag"):
        raise ValidationError(f"{path}.subject.tag 不能为空")
    if sk == "calc" and not subject.get("calcId"):
        raise ValidationError(f"{path}.subject.calcId 不能为空")
    if sk not in ("parameter", "tag", "calc"):
        raise ValidationError(f"{path}.subject.kind 只能是 parameter / tag / calc")
    op = rule.get("operator")
    if op not in OPERATORS:
        raise ValidationError(f"{path}.operator 不支持：{op}")
    if op == "change":
        if rule.get("from") is None or rule.get("to") is None:
            raise ValidationError(f"{path} 「由…变为…」需要 from / to")
    else:
        th = rule.get("threshold") or {}
        if th.get("kind") == "limit":
            if not th.get("limitId") or th.get("field") not in LIMIT_FIELDS:
                raise ValidationError(f"{path}.threshold 引用限值时要给 limitId 和 field（{'/'.join(LIMIT_FIELDS)}）")
        elif th.get("kind") == "value":
            try:
                float(th.get("value"))
            except (TypeError, ValueError):
                raise ValidationError(f"{path}.threshold.value 必须是数值")
        else:
            raise ValidationError(f"{path}.threshold.kind 只能是 value / limit")
    try:
        if float(rule.get("durationSec") or 0) < 0:
            raise ValidationError(f"{path}.durationSec 不能为负")
    except (TypeError, ValueError):
        raise ValidationError(f"{path}.durationSec 必须是数值")


# ------------------------------------------------------------------ 仓库
class PhenomenonStore:
    """现象与根因关系的读写。线程安全，写入即落盘（JSON）。"""

    FILES = {"phenomena": "phenomena.json", "links": "causal_links.json"}

    def __init__(self, seed_dir: Path = SEED_DIR, store_dir: Path = STORE_DIR) -> None:
        self.seed_dir = seed_dir
        self.store_dir = store_dir
        self._lock = threading.RLock()
        self.reload()

    # ---------------------------------------------------------- 持久化
    def _path(self, key: str) -> Path:
        return self.store_dir / self.FILES[key]

    def reload(self) -> None:
        with self._lock:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            for key, name in self.FILES.items():
                target = self.store_dir / name
                if not target.exists():
                    seed = self.seed_dir / name
                    if not seed.exists():
                        raise FileNotFoundError(f"缺少种子数据 {seed}，先运行 python3 -m backend.tools.build_seed")
                    shutil.copyfile(seed, target)
            self.phenomena: dict[str, dict[str, Any]] = {
                p["id"]: p for p in json.loads(self._path("phenomena").read_text("utf-8"))["items"]
            }
            self.links: dict[str, dict[str, Any]] = {
                l["id"]: l for l in json.loads(self._path("links").read_text("utf-8"))["items"]
            }

    def reset_to_seed(self) -> None:
        with self._lock:
            for name in self.FILES.values():
                shutil.copyfile(self.seed_dir / name, self.store_dir / name)
            self.reload()

    def _save(self, key: str) -> None:
        items = list(self.phenomena.values()) if key == "phenomena" else list(self.links.values())
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps({"updatedAt": _now(), "items": items}, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self._path(key))

    def _next_id(self, prefix: str, existing: dict[str, Any]) -> str:
        n = 1
        nums = [int(k.rsplit("-", 1)[-1]) for k in existing if k.startswith(prefix) and k.rsplit("-", 1)[-1].isdigit()]
        if nums:
            n = max(nums) + 1
        return f"{prefix}{n:04d}"

    # ---------------------------------------------------------- 现象
    def get(self, pid: str) -> dict[str, Any]:
        p = self.phenomena.get(pid)
        if not p:
            raise NotFound(pid)
        return p

    def _clean_phenomenon(self, body: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        data = copy.deepcopy(current) if current else {}
        for key in ("name", "category", "description", "severity", "status", "anchor", "rule", "note"):
            if key in body:
                data[key] = body[key]
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("现象名称不能为空")
        data["name"] = name
        anchor = data.get("anchor") or {}
        if not anchor.get("id"):
            raise ValidationError("现象必须挂在一个本体对象上（anchor.id）")
        if data.get("category") and data["category"] not in CATEGORIES:
            raise ValidationError(f"类别只能是：{'、'.join(CATEGORIES)}")
        data.setdefault("status", DRAFT)
        if data["status"] not in STATUSES:
            raise ValidationError(f"状态只能是：{'、'.join(STATUSES)}")
        validate_rule(data.get("rule"))
        return data

    def create_phenomenon(self, body: dict[str, Any], user: str = "演示用户") -> dict[str, Any]:
        with self._lock:
            data = self._clean_phenomenon(body)
            data["id"] = self._next_id("PH-U-", self.phenomena)
            data["source"] = {"kind": "人工新增", "ref": user}
            data["createdAt"] = data["updatedAt"] = _now()
            data["updatedBy"] = user
            self.phenomena[data["id"]] = data
            self._save("phenomena")
            return data

    def update_phenomenon(self, pid: str, body: dict[str, Any], user: str = "演示用户") -> dict[str, Any]:
        with self._lock:
            data = self._clean_phenomenon(body, self.get(pid))
            data["updatedAt"] = _now()
            data["updatedBy"] = user
            self.phenomena[pid] = data
            self._save("phenomena")
            return data

    def delete_phenomenon(self, pid: str) -> dict[str, Any]:
        with self._lock:
            self.get(pid)
            removed = [lid for lid, l in self.links.items() if pid in (l["cause"], l["effect"])]
            for lid in removed:
                del self.links[lid]
            del self.phenomena[pid]
            self._save("phenomena")
            self._save("links")
            return {"deleted": pid, "removedLinks": removed}

    # ---------------------------------------------------------- 根因关系
    def get_link(self, lid: str) -> dict[str, Any]:
        link = self.links.get(lid)
        if not link:
            raise NotFound(lid)
        return link

    def _clean_link(self, body: dict[str, Any], current: dict[str, Any] | None = None, own_id: str | None = None) -> dict[str, Any]:
        data = copy.deepcopy(current) if current else {}
        for key in ("cause", "effect", "mechanism", "basis", "confidence", "status", "note"):
            if key in body:
                data[key] = body[key]
        cause, effect = data.get("cause"), data.get("effect")
        if cause not in self.phenomena:
            raise ValidationError(f"原因现象不存在：{cause}")
        if effect not in self.phenomena:
            raise ValidationError(f"结果现象不存在：{effect}")
        if cause == effect:
            raise ValidationError("原因和结果不能是同一个现象")
        for lid, l in self.links.items():
            if lid != own_id and l["cause"] == cause and l["effect"] == effect:
                raise ValidationError(f"这条导致关系已存在：{lid}")
        data.setdefault("status", DRAFT)
        data.setdefault("confidence", "中")
        if data["status"] not in STATUSES:
            raise ValidationError(f"状态只能是：{'、'.join(STATUSES)}")
        if data["confidence"] not in CONFIDENCE:
            raise ValidationError(f"置信度只能是：{'、'.join(CONFIDENCE)}")
        return data

    def create_link(self, body: dict[str, Any], user: str = "演示用户") -> dict[str, Any]:
        with self._lock:
            data = self._clean_link(body)
            data["id"] = self._next_id("CL-U-", self.links)
            data["source"] = {"kind": "人工新增", "ref": user}
            data["createdAt"] = data["updatedAt"] = _now()
            data["updatedBy"] = user
            self.links[data["id"]] = data
            self._save("links")
            return data

    def update_link(self, lid: str, body: dict[str, Any], user: str = "演示用户") -> dict[str, Any]:
        with self._lock:
            data = self._clean_link(body, self.get_link(lid), own_id=lid)
            data["updatedAt"] = _now()
            data["updatedBy"] = user
            self.links[lid] = data
            self._save("links")
            return data

    def delete_link(self, lid: str) -> dict[str, Any]:
        with self._lock:
            self.get_link(lid)
            del self.links[lid]
            self._save("links")
            return {"deleted": lid}

    # ---------------------------------------------------------- 图
    def causes_of(self, pid: str) -> list[dict[str, Any]]:
        return [l for l in self.links.values() if l["effect"] == pid]

    def effects_of(self, pid: str) -> list[dict[str, Any]]:
        return [l for l in self.links.values() if l["cause"] == pid]

    def chain(self, pid: str, direction: str = "up", depth: int = 6) -> dict[str, Any]:
        """沿导致关系追溯：up = 由什么导致（逐层往上找原因），down = 会导致什么。"""
        self.get(pid)
        by_effect: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_cause: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for l in self.links.values():
            by_effect[l["effect"]].append(l)
            by_cause[l["cause"]].append(l)
        nodes = {pid: 0}
        edges: list[dict[str, Any]] = []
        queue = deque([pid])
        while queue:
            cur = queue.popleft()
            if nodes[cur] >= depth:
                continue
            nexts = by_effect[cur] if direction == "up" else by_cause[cur]
            for l in nexts:
                other = l["cause"] if direction == "up" else l["effect"]
                edges.append(l)
                if other not in nodes:
                    nodes[other] = nodes[cur] + 1
                    queue.append(other)
        return {"root": pid, "direction": direction, "levels": nodes, "links": edges}

    def roles(self, pid: str) -> dict[str, int]:
        return {"asCause": len(self.effects_of(pid)), "asEffect": len(self.causes_of(pid))}
