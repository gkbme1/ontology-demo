"""算法库：读 data/config/算法库.json（调用契约），并提供本 Demo 的内置实现（代替外部算法服务）。

本体里的计算组态只引用算法编号并绑定参数，不包含算法本身。真实部署时 invoke() 换成调用算法服务
（按契约里的 protocol / method / endpoint），计算组态不用改。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "data" / "config" / "算法库.json"


class AlgorithmError(ValueError):
    pass


# ------------------------------------------------------------------ 内置实现（代替算法服务）
def _drops_per_step(values: np.ndarray, deadband: float) -> np.ndarray:
    """逐点版液位跟踪：只计入超过死区的下降量（上升视为补液，重置锚点）。复制自 Agent Demo 的 level_movements。"""
    out = np.zeros(len(values))
    anchor = float(values[0])
    for i in range(1, len(values)):
        v = float(values[i])
        if v < anchor - deadband:
            out[i] = anchor - v
            anchor = v
        elif v > anchor + deadband:
            anchor = v
    return out


def _rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(x)])
    idx = np.arange(1, len(x) + 1)
    return c[idx] - c[np.maximum(0, idx - window)]


def _window(args: dict[str, Any], step_min: float) -> int:
    return max(1, int(round(float(args.get("windowMin") or 10) / step_min)))


def _level_consumption(args: dict[str, Any], step_min: float) -> np.ndarray:
    mat = np.atleast_2d(args["level"])
    w = _window(args, step_min)
    total = np.zeros(mat.shape[1])
    for row in mat:
        span = float(np.max(row) - np.min(row))
        deadband = span * float(args.get("deadbandRatio") or 0.01) if span > 0 else 0.0
        total += _rolling_sum(_drops_per_step(row, deadband), w)
    return total / (w * step_min)


def _rate(args: dict[str, Any], step_min: float) -> np.ndarray:
    row = np.atleast_2d(args["series"]).mean(axis=0)
    w = _window(args, step_min)
    shifted = np.concatenate([np.full(w, row[0]), row[:-w]])
    return (row - shifted) / (w * step_min)


IMPLEMENTATIONS: dict[str, Callable[[dict[str, Any], float], np.ndarray]] = {
    "ALG-LEVEL-CONSUMPTION": _level_consumption,
    "ALG-RATE": _rate,
    "ALG-ABS-DIFF": lambda a, s: np.abs(np.atleast_2d(a["a"])[0] - np.atleast_2d(a["b"])[0]),
    "ALG-MEAN": lambda a, s: np.atleast_2d(a["series"]).mean(axis=0),
    "ALG-RANGE": lambda a, s: np.atleast_2d(a["series"]).max(axis=0) - np.atleast_2d(a["series"]).min(axis=0),
    "ALG-SUM": lambda a, s: np.atleast_2d(a["series"]).sum(axis=0),
}


class AlgorithmLibrary:
    def __init__(self, path: Path = FILE) -> None:
        raw = json.loads(path.read_text("utf-8")) if path.exists() else {"items": []}
        self.note = raw.get("note", "")
        self.items: dict[str, dict[str, Any]] = {a["id"]: a for a in raw.get("items") or []}

    def get(self, aid: str) -> dict[str, Any]:
        if aid not in self.items:
            raise AlgorithmError(f"算法库里没有登记算法：{aid}")
        return self.items[aid]

    def invoke(self, aid: str, args: dict[str, Any], step_min: float) -> np.ndarray:
        """按契约调用算法。本 Demo 用内置实现；部署时改为请求算法服务。"""
        algo = self.get(aid)
        fn = IMPLEMENTATIONS.get(aid)
        if not fn:
            raise AlgorithmError(f"算法 {algo['name']} 的服务未接入（{algo['invoke'].get('endpoint')}）")
        for inp in algo["inputs"]:
            if inp["name"] not in args and inp.get("default") is not None:
                args[inp["name"]] = inp["default"]
        return np.asarray(fn(args, step_min), dtype=float)
