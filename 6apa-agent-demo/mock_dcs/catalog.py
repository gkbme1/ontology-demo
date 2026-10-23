"""点表目录：nodeId ↔ 本体中的 DCS 点。

nodeId 约定：``{控制站号}:{位号}.{属性}``，例如 ``10:PT_1003.PV``。
本体点表里 (控制站号, 位号) 唯一，所以能一一对上。

点表元数据从本体服务拉取（单位、现场描述、点类型等），用来决定"这个点应该是多少"。
本体服务不可达时不影响服务可用：所有点都退化为按位号名推断。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass

import httpx

from .profiles import TagMeta

logger = logging.getLogger("mock_dcs.catalog")

_ATTRS = {"PV", "SV", "SP", "OP", "MV", "OUT", "VALUE", "V", "AV", "DV"}
_RETRY_SECONDS = 60


@dataclass(frozen=True)
class NodeRef:
    node_id: str
    station: str
    path: str
    attr: str


def parse_node_id(node_id: str) -> NodeRef | None:
    text = (node_id or "").strip()
    if not text:
        return None
    station, sep, rest = text.partition(":")
    if not sep:
        station, rest = "", text
    rest = rest.strip()
    if not rest:
        return None
    attr = "PV"
    head, dot, tail = rest.rpartition(".")
    if dot and tail.upper() in _ATTRS:
        rest, attr = head, tail.upper()
    return NodeRef(node_id=text, station=station.strip(), path=rest, attr=attr)


class Catalog:
    def __init__(self, ontology_base_url: str) -> None:
        self.ontology_base_url = ontology_base_url.rstrip("/")
        self._by_key: dict[tuple[str, str], TagMeta] = {}
        self._loaded_at: float | None = None
        self._last_attempt = 0.0
        self._last_error: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 加载

    def ensure_loaded(self) -> None:
        """首次使用时加载；失败后每 60 秒最多重试一次，不阻塞请求。"""
        if self._loaded_at is not None:
            return
        if time.time() - self._last_attempt < _RETRY_SECONDS and self._last_attempt:
            return
        with self._lock:
            if self._loaded_at is not None:
                return
            self._last_attempt = time.time()
            try:
                self._load()
            except Exception as exc:  # 本体不可达 → 退化为按位号推断
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("点表加载失败，将按位号名推断：%s", self._last_error)

    def _load(self) -> None:
        url = f"{self.ontology_base_url}/api/ontology/tags"
        response = httpx.get(url, params={"limit": 100000}, timeout=60.0)
        response.raise_for_status()
        items = response.json().get("items") or []
        index: dict[tuple[str, str], TagMeta] = {}
        for item in items:
            station = str(item.get("station") or "").strip()
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            index[(station, name.upper())] = TagMeta(
                station=station,
                name=name,
                description=str(item.get("rawDescription") or ""),
                unit=str(item.get("unit") or ""),
                parameter_type=str(item.get("parameterType") or ""),
                block_type=str(item.get("blockType") or ""),
                equipment=str(item.get("equipmentName") or ""),
                from_catalog=True,
            )
        self._by_key = index
        self._loaded_at = time.time()
        self._last_error = None
        logger.info("点表已加载：%d 个点（来源 %s）", len(index), url)

    # ------------------------------------------------------------------ 查询

    def lookup(self, ref: NodeRef) -> TagMeta | None:
        key = (ref.station, ref.path.upper())
        if key in self._by_key:
            return self._by_key[key]
        # 形如 EQ001.DI001 的层级位号，再按最后一段试一次
        last = re.split(r"\.", ref.path)[-1].upper()
        return self._by_key.get((ref.station, last))

    def guess(self, ref: NodeRef) -> TagMeta:
        """点表里没有的点：只凭位号名推断。"""
        return TagMeta(station=ref.station, name=ref.path)

    def search(
        self, keyword: str = "", station: str = "", limit: int = 50, offset: int = 0
    ) -> tuple[int, list[TagMeta]]:
        keyword = keyword.strip().lower()
        hits = [
            meta
            for meta in self._by_key.values()
            if (not station or meta.station == station)
            and (
                not keyword
                or keyword in meta.name.lower()
                or keyword in meta.description.lower()
                or keyword in meta.equipment.lower()
            )
        ]
        hits.sort(key=lambda meta: (int(meta.station) if meta.station.isdigit() else 0, meta.name))
        return len(hits), hits[offset : offset + limit]

    @property
    def loaded(self) -> bool:
        return self._loaded_at is not None

    def status(self) -> dict:
        return {
            "source": f"{self.ontology_base_url}/api/ontology/tags",
            "loaded": self._loaded_at is not None,
            "tagCount": len(self._by_key),
            "loadedAt": self._loaded_at,
            "lastError": self._last_error,
        }


def node_id_of(meta: TagMeta, attr: str = "PV") -> str:
    return f"{meta.station}:{meta.name}.{attr}"
