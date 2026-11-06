"""判定规则求值：在模拟数据上试算现象是否成立。

- 现象挂在设备组上时，对组内每台设备分别判定（「本对象.属性」落到本台的测点）；
- 条件只用位号时与台号无关，只判定一次；
- 持续时长：原始条件连续成立满 durationSec 才算成立；
- 由…变为…：上一采样点等于 from、本采样点等于 to 的时刻成立；
- 限值引用按基础版本（V0）取值；
- 主体无法落到测点时，该条件记为「无法判定」，按不成立处理并在结果里列出。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from backend.v2 import calculations, simulator
from backend.v2.context import AppContext
from backend.v2.phenomena import iter_conditions, rule_text, subject_text, threshold_text

MAX_TARGETS = 12
MAX_POINTS = 360


class EvalError(ValueError):
    pass


class _Evaluator:
    def __init__(self, ctx: AppContext, times: np.ndarray) -> None:
        self.ctx = ctx
        self.times = times
        self.step = int(times[1] - times[0]) if len(times) > 1 else 60
        self._series: dict[str, np.ndarray] = {}

    def tag_series(self, tag: dict[str, Any]) -> np.ndarray:
        name = tag["name"]
        if name not in self._series:
            self._series[name] = simulator.series(tag, self.ctx.limit_of_tag.get(name), self.times)
        return self._series[name]

    def resolve(self, subject: dict[str, Any], target: str) -> list[tuple[str, np.ndarray]]:
        kind = subject.get("kind")
        if kind == "context":
            return []  # 运行上下文（EBR / MOM）本 Demo 未接入
        if kind == "tag":
            tag = self.ctx.tag_by_name.get(subject.get("tag") or "")
            return [(tag["name"], self.tag_series(tag))] if tag else []
        if kind == "parameter":
            return [(t["name"], self.tag_series(t)) for t in self.ctx.parameter_tags(target, subject.get("name") or "")]
        if kind == "calc":
            try:
                calc = self.ctx.calcs.get(subject.get("calcId") or "")
            except LookupError:
                return []
            anchor = (calc.get("anchor") or {}).get("id")
            calc_target = target if self._covers(anchor, target) else anchor
            result = calculations.compute(calc, lambda s: self.resolve(s, calc_target), self.times)
            if result["values"] is None:
                return []
            return [(f"{calc['name']}", result["values"])]
        return []

    def _covers(self, anchor: str | None, target: str) -> bool:
        if not anchor:
            return False
        if anchor == target:
            return True
        equip = self.ctx.store.dcs.equipment.get(target)
        return bool(equip and equip.get("equipmentGroupId") == anchor)

    def threshold(self, th: dict[str, Any]) -> float | None:
        if th.get("kind") == "limit":
            limit = self.ctx.limits.get(th.get("limitId") or "")
            value = (limit or {}).get(th.get("field") or "")
            return None if value is None else float(value)
        try:
            return float(th.get("value"))
        except (TypeError, ValueError):
            return None

    def _hold(self, raw: np.ndarray, duration: float) -> np.ndarray:
        need = int(np.ceil(float(duration or 0) / self.step))
        if need <= 1:
            return raw
        out = np.zeros(len(raw), dtype=bool)
        run = 0
        for i, v in enumerate(raw):
            run = run + 1 if v else 0
            out[i] = run >= need
        return out

    def condition(self, c: dict[str, Any], target: str, report: list[dict[str, Any]]) -> np.ndarray:
        found = self.resolve(c.get("subject") or {}, target)
        entry: dict[str, Any] = {
            "text": rule_text(c, self.ctx.limits, {k: v["name"] for k, v in self.ctx.calcs.items.items()}),
            "tags": [n for n, _ in found],
        }
        n = len(self.times)
        if not found and (c.get("subject") or {}).get("kind") == "context":
            entry.update(status="无法判定", reason="运行上下文（EBR 批次 / 换酶记录）本 Demo 未接入，需在线环境取数")
            report.append(entry)
            return np.zeros(n, dtype=bool)
        if not found:
            entry.update(status="无法判定", reason="条件主体没有落到任何测点 / 计算输入不全")
            report.append(entry)
            return np.zeros(n, dtype=bool)
        op = c.get("operator")
        mat = np.vstack([s for _, s in found])
        agg = c.get("aggregate") or "any"
        if op == "change":
            a, b = float(c.get("from")), float(c.get("to"))
            prev = np.concatenate([mat[:, :1], mat[:, :-1]], axis=1)
            per = (np.isclose(prev, a)) & (np.isclose(mat, b))
            raw = per.all(axis=0) if agg == "all" else per.any(axis=0)
            th_value = None
        else:
            th_value = self.threshold(c.get("threshold") or {})
            if th_value is None:
                entry.update(status="无法判定", reason=f"阈值 {threshold_text(c.get('threshold'))} 没有数值")
                report.append(entry)
                return np.zeros(n, dtype=bool)
            data = mat.mean(axis=0, keepdims=True) if agg == "mean" else mat
            if op == ">":
                per = data > th_value
            elif op == ">=":
                per = data >= th_value
            elif op == "<":
                per = data < th_value
            elif op == "<=":
                per = data <= th_value
            elif op == "=":
                per = np.isclose(data, th_value)
            else:
                per = ~np.isclose(data, th_value)
            raw = per.all(axis=0) if agg == "all" else per.any(axis=0)
        result = self._hold(raw, c.get("durationSec") or 0)
        entry.update(status="成立" if result[-1] else "不成立", trueRatio=round(float(result.mean()), 4),
                     threshold=th_value, chart=self._chart(found, agg))
        report.append(entry)
        return result

    def _chart(self, found: list[tuple[str, np.ndarray]], agg: str) -> dict[str, Any]:
        idx = np.linspace(0, len(self.times) - 1, min(MAX_POINTS, len(self.times))).astype(int)
        lines = [{"name": n, "values": [round(float(v), 4) for v in s[idx]]} for n, s in found[:4]]
        if agg == "mean" and len(found) > 1:
            mean = np.vstack([s for _, s in found]).mean(axis=0)
            lines.append({"name": "均值", "values": [round(float(v), 4) for v in mean[idx]]})
        return {"times": [simulator.fmt_times(self.times[i:i + 1])[0] for i in idx], "lines": lines}

    def rule(self, rule: dict[str, Any], target: str, report: list[dict[str, Any]]) -> np.ndarray:
        if rule.get("type") == "group":
            parts = [self.rule(child, target, report) for child in rule.get("children") or []]
            if not parts:
                return np.zeros(len(self.times), dtype=bool)
            stack = np.vstack(parts)
            return stack.all(axis=0) if rule.get("op") == "AND" else stack.any(axis=0)
        return self.condition(rule, target, report)

    def events(self, mask: np.ndarray) -> list[dict[str, Any]]:
        out = []
        i, n = 0, len(mask)
        while i < n:
            if mask[i]:
                j = i
                while j + 1 < n and mask[j + 1]:
                    j += 1
                start, end = int(self.times[i]), int(self.times[j])
                out.append({"start": simulator.fmt_times(np.array([start]))[0],
                            "end": simulator.fmt_times(np.array([end]))[0],
                            "minutes": round((end - start + self.step) / 60.0, 1), "ongoing": j == n - 1})
                i = j + 1
            else:
                i += 1
        return out


def _parameter_names(rule: dict[str, Any] | None, ctx: AppContext) -> list[str]:
    """规则（含其引用的计算组态输入）用到的「本对象.属性」名称。"""
    names: list[str] = []
    for c in iter_conditions(rule):
        subject = c.get("subject") or {}
        if subject.get("kind") == "parameter":
            names.append(subject.get("name") or "")
        elif subject.get("kind") == "calc":
            try:
                calc = ctx.calcs.get(subject.get("calcId") or "")
            except LookupError:
                continue
            names += [i["subject"].get("name") or "" for i in calc.get("inputs") or []
                      if (i.get("subject") or {}).get("kind") == "parameter"]
    return [n for n in names if n]


def _uses_parameters(rule: dict[str, Any] | None, ctx: AppContext) -> bool:
    return bool(_parameter_names(rule, ctx))


def targets_for(ctx: AppContext, anchor_id: str, rule: dict[str, Any] | None, op_id: str | None = None,
                target_id: str | None = None) -> list[str]:
    if target_id:
        return [target_id]
    if anchor_id.startswith("egrp-") and _uses_parameters(rule, ctx):
        members = ctx.group_members(anchor_id, op_id)
        # 只判定能落到测点的成员（公共点位、未接线的成员跳过）
        names = _parameter_names(rule, ctx)
        usable = [m for m in members if any(ctx.parameter_tags(m, n) for n in names)]
        return usable[:MAX_TARGETS] or [anchor_id]
    return [anchor_id]


def evaluate(ctx: AppContext, rule: dict[str, Any] | None, anchor_id: str, *, hours: float = 24,
             op_id: str | None = None, target_id: str | None = None) -> dict[str, Any]:
    if not rule:
        raise EvalError("该现象还没有判定规则，无法试算")
    if hours <= 0 or hours > 72:
        raise EvalError("试算时间窗取 0～72 小时")
    times = simulator.time_axis(hours=hours, step_sec=60)
    ev = _Evaluator(ctx, times)
    results = []
    for target in targets_for(ctx, anchor_id, rule, op_id, target_id):
        report: list[dict[str, Any]] = []
        mask = ev.rule(rule, target, report)
        events = ev.events(mask)
        results.append({
            "targetId": target, "targetName": ctx.object_name(target),
            "current": bool(mask[-1]), "eventCount": len(events),
            "totalMinutes": round(sum(e["minutes"] for e in events), 1),
            "events": events[-20:], "conditions": report,
        })
    return {
        "window": {"start": simulator.fmt_times(times[:1])[0], "end": simulator.fmt_times(times[-1:])[0],
                   "hours": hours, "stepSec": ev.step},
        "ruleText": rule_text(rule, ctx.limits, {k: v["name"] for k, v in ctx.calcs.items.items()}),
        "limitVersion": "按工艺限值基础版本（V0）取值",
        "results": results,
        "dataSource": simulator.DATA_SOURCE,
    }


def run_calc(ctx: AppContext, calc: dict[str, Any], *, hours: float = 6, op_id: str | None = None,
             target_id: str | None = None) -> dict[str, Any]:
    times = simulator.time_axis(hours=hours, step_sec=60)
    ev = _Evaluator(ctx, times)
    anchor = (calc.get("anchor") or {}).get("id") or ""
    if target_id:
        targets = [target_id]
    elif anchor.startswith("egrp-") and any((i.get("subject") or {}).get("kind") == "parameter" for i in calc.get("inputs") or []):
        members = ctx.group_members(anchor, op_id)
        targets = [m for m in members if all(
            ev.resolve(i["subject"], m) for i in calc["inputs"])][:MAX_TARGETS] or [anchor]
    else:
        targets = [anchor]
    idx = np.linspace(0, len(times) - 1, min(MAX_POINTS, len(times))).astype(int)
    out = []
    for target in targets:
        r = calculations.compute(calc, lambda s: ev.resolve(s, target), times)
        item = {"targetId": target, "targetName": ctx.object_name(target), "inputs": r["inputs"], "unresolved": r["unresolved"]}
        if r["values"] is not None:
            v = r["values"]
            item.update(current=round(float(v[-1]), 4), mean=round(float(np.mean(v)), 4),
                        max=round(float(np.max(v)), 4), min=round(float(np.min(v)), 4),
                        values=[round(float(x), 4) for x in v[idx]])
        out.append(item)
    return {"times": simulator.fmt_times(times[idx]), "results": out, "unit": calc.get("unit") or "",
            "dataSource": simulator.DATA_SOURCE}


__all__ = ["evaluate", "run_calc", "EvalError", "subject_text"]
