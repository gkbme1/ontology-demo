"""稳定标识符生成。

所有本体对象的 ID 必须可重复生成、与显示名称解耦，
避免同名对象或重复关系导致数据覆盖（需求文档 9.2）。
"""
from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def normalize(value) -> str:
    """规范化用于生成 ID 的字段值。"""
    if value is None:
        return ""
    text = str(value).strip()
    text = _WS.sub(" ", text)
    return text


def _hash(parts: list[str], length: int = 8) -> str:
    key = "|".join(normalize(p) for p in parts)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:length]


def stable_key(parts: list[str]) -> str:
    """关系唯一标识所依据的规范化键，原样保留以便追溯。"""
    return "|".join(normalize(p) for p in parts)


def area_id(area_code: str) -> str:
    """工段 ID。

    v2 起工段按流程图口径划分，工段编号（S01…S23、S99）本身就是稳定且可读的键，
    因此不再做哈希，直接拼成 area-S01。旧口径的哈希 ID 随控制站工段一起废弃。
    """
    code = normalize(area_code)
    return "area-" + code if code else ""


def equipment_group_id(group_uri: str, group_name: str = "") -> str:
    """标准设备组（v2 新增，来自 DCS 点表「设备主数据」Sheet）。"""
    return "egrp-" + _hash([group_uri or group_name])


def equipment_id(owl_subject: str) -> str:
    """设备实例以 OWL Subject URI 为唯一标识（需求文档第七章）。"""
    return "equip-" + _hash([owl_subject])


def parameter_id(owl_subject: str, parameter_name: str) -> str:
    return "param-" + _hash([owl_subject, parameter_name])


def tag_id(tag_name: str) -> str:
    return "tag-" + _hash([tag_name])


def relation_id(parts: list[str]) -> str:
    return "relation-" + _hash(parts)


def relation_entity_id(entity_type: str, entity_name: str) -> str:
    return "robj-" + _hash([entity_type, entity_name])


def rule_id(rule_code: str, name: str) -> str:
    return "rule-" + _hash([rule_code, name])
