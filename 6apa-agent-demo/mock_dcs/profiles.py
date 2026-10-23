"""数值合理性画像：一个测点"应该"长什么样。

输入是点表元数据（位号、现场描述、单位、点类型、功能块类型），
输出是 Profile：模拟量的量纲、合理范围、小数位、波动幅度；
开关量的角色（状态 / 反向状态 / 脉冲指令 / 故障）。

判定顺序：备用点 → 开关量 → 模拟量（单位优先，其次描述关键词，最后位号前缀）。
范围取的是 6-APA 酶法工艺的常见工况，只求"看起来合理"，不代表任何现场真实值。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Profile:
    kind: str  # analog | discrete
    category: str  # 人类可读类别：温度 / 压力 / 运行状态 / ...
    unit: str = ""
    lo: float = 0.0
    hi: float = 1.0
    decimals: int = 2
    # 模拟量：停机时归零（电流、频率、转速）
    follows_run: bool = False
    # 模拟量：阀位反馈，跟随同一阀门的给定值并带滞后
    is_feedback: bool = False
    # 开关量角色：state 跟随设备状态 / inverse 取反 / pulse 脉冲指令常为 0 / fault 故障常为 0 / const1 常为 1
    role: str = "state"
    # 开关量：设备处于"开/运行"的时间占比
    duty: float = 0.75
    # 备用点：未接线，模拟量返回坏质量
    spare: bool = False
    rule: str = ""  # 命中的规则，便于解释数据是怎么来的

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "category": self.category, "rule": self.rule}
        if self.kind == "analog":
            out.update(unit=self.unit, range=[self.lo, self.hi], decimals=self.decimals)
            if self.follows_run:
                out["followsRunState"] = True
            if self.is_feedback:
                out["feedbackOfSetpoint"] = True
        else:
            out.update(role=self.role, duty=self.duty)
        if self.spare:
            out["spare"] = True
        return out


@dataclass(frozen=True)
class TagMeta:
    station: str
    name: str
    description: str = ""
    unit: str = ""
    parameter_type: str = ""
    block_type: str = ""
    equipment: str = ""
    from_catalog: bool = False


# --------------------------------------------------------------------- 工具函数

# 位号尾缀：剥掉后剩下的部分视为"同一台设备 / 同一个阀门"，用来让相关测点互相一致
_SUFFIX_RE = re.compile(
    r"(_(OF|CF|RUN|RN|DO|QD|TZ|MOT2|VAL2|FB|FK|IB|AO|AI|DI|GZ|YC|PL|SP|PV|OP))+$",
    re.IGNORECASE,
)


def device_key(meta: TagMeta) -> str:
    """同一设备的多个测点（运行反馈、启停指令、电流、频率）共享的键。"""
    base = _SUFFIX_RE.sub("", meta.name) or meta.name
    return f"{meta.station}:{base.upper()}"


def _has(text: str, *words: str) -> bool:
    return any(word.lower() in text for word in words)


def _norm_unit(unit: str | None) -> str:
    u = (unit or "").strip()
    low = u.lower()
    mapping = {
        "°c": "℃", "℃": "℃", "mpa": "MPa", "kpa": "kPa", "hz": "Hz", "a": "A", "ph": "pH",
        "m3/h": "m3/h", "t/h": "t/h", "l/h": "L/h", "l/min": "L/min", "m3": "m3", "m": "m",
        "mm": "mm", "l": "L", "rpm": "rpm", "r/min": "rpm", "kg/m3": "kg/m3", "μs/cm": "μS/cm",
        "us/cm": "μS/cm", "mg/l": "mg/L", "%": "%",
    }
    return mapping.get(low, u)


# --------------------------------------------------------------------- 主入口


def classify(meta: TagMeta) -> Profile:
    text = f"{meta.name} {meta.description}".lower()
    ptype = meta.parameter_type or ""
    block = (meta.block_type or "").upper()
    name = meta.name.upper()

    # 1) 备用点
    if meta.description.strip().startswith("备用") or re.match(r"^(BY|SPA)\d", name):
        if _is_discrete(ptype, block, name):
            return Profile("discrete", "备用开关量", role="pulse", spare=True, rule="备用点：开关量恒为 0")
        return Profile("analog", "备用模拟量", unit=_norm_unit(meta.unit), lo=0, hi=0, decimals=2,
                       spare=True, rule="备用点：未接线，返回坏质量")

    # 2) 开关量
    if _is_discrete(ptype, block, name):
        return _classify_discrete(text, ptype, block, name)

    # 3) 模拟量
    return _classify_analog(meta, text, ptype)


def _is_discrete(ptype: str, block: str, name: str) -> bool:
    if any(tag in ptype for tag in ("(DI)", "(DO)", "(VAL)", "(MOT)")):
        return True
    if block in {"DI", "DO", "DOV", "VAL2", "MOT2"}:
        return True
    if not ptype and not block:
        # 无元数据：按位号尾段判断，如 EQ001.DI001 / XV_1001_OF
        last = re.split(r"[._]", name)[-1]
        return bool(re.match(r"^(DI|DO|DX|OF|CF|RUN|QD|TZ|ZT)\d*$", last))
    return False


def _classify_discrete(text: str, ptype: str, block: str, name: str) -> Profile:
    is_valve = "(VAL)" in ptype or block == "VAL2" or _has(text, "阀", "xv_", "hv_")
    duty = 0.6 if is_valve else 0.8

    if _has(text, "故障", "报警", "fault", "alm", "跳闸", "急停", "过载"):
        return Profile("discrete", "故障/报警", role="fault", duty=0.0, rule="故障类：常为 0")
    if re.search(r"_(RM|REM)$", name) or _has(text, "远程", "就地", "远控"):
        return Profile("discrete", "远程/就地", role="const1", duty=1.0, rule="远程/就地状态：常为 1（远程）")
    if re.search(r"_(QD|TZ)$", name) or _has(text, "启动指令", "停止指令", "复位"):
        return Profile("discrete", "脉冲指令", role="pulse", duty=0.0, rule="启动/停止脉冲指令：常为 0")
    if re.search(r"_CF$", name) or _has(text, "关反馈", "关到位", "关状态", "关信号", "停止反馈"):
        return Profile("discrete", "阀门关到位" if is_valve else "停止状态", role="inverse", duty=duty,
                       rule="关到位/停止反馈：与同一设备的开/运行状态互补")
    if is_valve:
        return Profile("discrete", "阀门开关状态", role="state", duty=duty, rule="阀门开到位/开关指令：跟随阀门状态")
    return Profile("discrete", "设备运行状态", role="state", duty=duty, rule="运行反馈/启停指令：跟随设备状态")


def _classify_analog(meta: TagMeta, text: str, ptype: str) -> Profile:
    unit = _norm_unit(meta.unit)
    is_op = "(OP)" in ptype or bool(re.search(r"_AO$", meta.name, re.IGNORECASE)) or _has(text, "给定", "指令")
    is_valve_fb = bool(re.search(r"_FB$", meta.name, re.IGNORECASE)) and _has(text, "阀")

    # ---------- 控制输出（给定）
    if is_op and unit in ("Hz",):
        return Profile("analog", "变频给定", "Hz", 30, 48, 1, rule="OP：变频器频率给定")
    if is_op:
        return Profile("analog", "调节阀给定", unit or "%", 20, 80, 1, rule="OP：调节阀开度给定")

    # ---------- 无单位时由描述/位号推断出单位
    if not unit:
        unit = _infer_unit(text, meta.name)

    # ---------- 按单位分派
    if unit == "℃":
        return _temperature(text)
    if unit == "MPa":
        return _pressure_mpa(text)
    if unit == "kPa":
        if _has(text, "真空", "蒸发", "减压"):
            return Profile("analog", "绝压", "kPa", 4, 15, 1, rule="kPa + 真空/蒸发：绝压 4~15 kPa")
        return Profile("analog", "压力", "kPa", 10, 60, 1, rule="kPa：10~60")
    if unit == "%":
        if is_valve_fb or _has(text, "开度", "阀位"):
            return Profile("analog", "阀位反馈", "%", 20, 80, 1, is_feedback=True,
                           rule="阀位反馈：跟随同一阀门给定，滞后约 30 s")
        if _has(text, "液位"):
            return Profile("analog", "液位", "%", 25, 80, 1, rule="液位 %：25~80")
        if _has(text, "浓度") and _has(text, "硫酸", "盐酸", "碱", "氨"):
            return Profile("analog", "浓度", "%", 8, 25, 2, rule="酸碱浓度：8~25 %")
        if _has(text, "浓度"):
            return Profile("analog", "浓度", "%", 20, 60, 2, rule="浓度：20~60 %")
        if _has(text, "湿度"):
            return Profile("analog", "湿度", "%", 40, 75, 1, rule="湿度：40~75 %")
        if _has(text, "反馈", "阀"):
            return Profile("analog", "阀位反馈", "%", 20, 80, 1, is_feedback=True, rule="阀位反馈：20~80 %")
        return Profile("analog", "百分量", "%", 20, 80, 1, rule="百分量：20~80 %")
    if unit == "m3/h":
        if _has(text, "总管"):
            return Profile("analog", "流量", "m3/h", 20, 60, 2, rule="总管流量：20~60 m3/h")
        if _has(text, "蒸汽"):
            return Profile("analog", "蒸汽流量", "m3/h", 2, 10, 2, rule="蒸汽流量：2~10 m3/h")
        return Profile("analog", "流量", "m3/h", 1.5, 25, 2, rule="流量：1.5~25 m3/h")
    if unit == "t/h":
        return Profile("analog", "质量流量", "t/h", 1, 6, 2, rule="t/h：1~6")
    if unit == "L/h":
        return Profile("analog", "小流量", "L/h", 50, 400, 1, rule="L/h：50~400")
    if unit == "L/min":
        return Profile("analog", "小流量", "L/min", 5, 30, 2, rule="L/min：5~30")
    if unit == "m3":
        return Profile("analog", "液位(体积)", "m3", 2, 18, 2, rule="罐容积液位：2~18 m3")
    if unit == "m":
        return Profile("analog", "液位", "m", 0.4, 3.2, 3, rule="液位 m：0.4~3.2")
    if unit == "mm":
        return Profile("analog", "液位", "mm", 300, 1600, 0, rule="液位 mm：300~1600")
    if unit == "L":
        return Profile("analog", "计量罐液位", "L", 20, 160, 1, rule="计量罐 L：20~160")
    if unit == "A":
        if _has(text, "离心机"):
            return Profile("analog", "电流", "A", 30, 90, 1, follows_run=True, rule="离心机电流：30~90 A，停机为 0")
        return Profile("analog", "电流", "A", 8, 45, 1, follows_run=True, rule="电机电流：8~45 A，停机为 0")
    if unit == "Hz":
        return Profile("analog", "频率", "Hz", 30, 50, 1, follows_run=True, rule="变频器频率：30~50 Hz，停机为 0")
    if unit == "rpm":
        if _has(text, "离心机"):
            return Profile("analog", "转速", "rpm", 1350, 1550, 0, follows_run=True, rule="离心机转速：1350~1550 rpm")
        return Profile("analog", "转速", "rpm", 900, 1450, 0, follows_run=True, rule="转速：900~1450 rpm")
    if unit == "pH":
        return _ph(text)
    if unit == "kg/m3":
        if _has(text, "丁酯", "丁醇", "有机", "轻相"):
            return Profile("analog", "密度", "kg/m3", 860, 890, 1, rule="有机相密度：860~890")
        if _has(text, "酸水", "废酸", "重相"):
            return Profile("analog", "密度", "kg/m3", 1010, 1040, 1, rule="水相密度：1010~1040")
        return Profile("analog", "密度", "kg/m3", 980, 1030, 1, rule="密度：980~1030")
    if unit == "μS/cm":
        return Profile("analog", "电导/澄清度", "μS/cm", 5, 40, 1, rule="μS/cm：5~40")
    if unit == "mg/L":
        return Profile("analog", "浓度", "mg/L", 5, 25, 2, rule="mg/L：5~25")

    return Profile("analog", "模拟量", unit, 0, 100, 2, rule="未识别量纲：按 0~100 通用模拟量")


def _infer_unit(text: str, name: str) -> str:
    upper = name.upper()
    last = re.split(r"[.:]", upper)[-1]
    if _has(text, "温度") or re.match(r"^(TI|TT|TE|TIC)", upper):
        return "℃"
    if _has(text, "压力", "真空") or re.match(r"^(PI|PT|PIC)", upper):
        return "MPa"
    if _has(text, "ph") or re.match(r"^AT", upper):
        return "pH"
    if _has(text, "液位") or re.match(r"^(LI|LT|LIC|LE)", upper):
        return "%"
    if _has(text, "流量") or re.match(r"^(FI|FT|FIC)", upper):
        return "m3/h"
    if _has(text, "电流") or re.search(r"_IB$", upper) or re.match(r"^II", upper):
        return "A"
    if _has(text, "频率"):
        return "Hz"
    if _has(text, "转速"):
        return "rpm"
    if _has(text, "密度"):
        return "kg/m3"
    if _has(text, "开度", "阀位", "反馈"):
        return "%"
    if re.match(r"^AI\d*$", last):
        return ""
    return ""


def _temperature(text: str) -> Profile:
    if _has(text, "冷盐水", "冷冻", "盐水"):
        return Profile("analog", "温度", "℃", -12, -2, 1, rule="冷盐水/冷冻：-12~-2 ℃")
    if _has(text, "结晶"):
        return Profile("analog", "温度", "℃", 2, 12, 1, rule="结晶：2~12 ℃（低温结晶）")
    if _has(text, "水解"):
        return Profile("analog", "温度", "℃", 34, 38, 1, rule="酶法水解：34~38 ℃")
    if _has(text, "蒸汽", "蒸发", "精馏", "塔底", "塔釜", "再沸", "加热"):
        return Profile("analog", "温度", "℃", 85, 118, 1, rule="蒸汽/蒸发/精馏：85~118 ℃")
    if _has(text, "冷却水", "循环水"):
        return Profile("analog", "温度", "℃", 25, 34, 1, rule="循环冷却水：25~34 ℃")
    if _has(text, "一冷", "二冷", "冷却", "降温"):
        return Profile("analog", "温度", "℃", 5, 20, 1, rule="冷却/降温段：5~20 ℃")
    return Profile("analog", "温度", "℃", 18, 42, 1, rule="一般工艺温度：18~42 ℃")


def _pressure_mpa(text: str) -> Profile:
    if _has(text, "真空"):
        return Profile("analog", "真空度", "MPa", -0.095, -0.080, 3, rule="真空：-0.095~-0.080 MPa")
    if _has(text, "蒸汽"):
        return Profile("analog", "压力", "MPa", 0.35, 0.65, 3, rule="蒸汽压力：0.35~0.65 MPa")
    if _has(text, "压缩空气", "氮气", "仪表气", "压缩机"):
        return Profile("analog", "压力", "MPa", 0.5, 0.7, 3, rule="气源/压缩机：0.5~0.7 MPa")
    if _has(text, "泵后", "泵出口", "出口", "输送泵", "泵压"):
        return Profile("analog", "压力", "MPa", 0.25, 0.55, 3, rule="泵出口压力：0.25~0.55 MPa")
    return Profile("analog", "压力", "MPa", 0.05, 0.35, 3, rule="一般压力：0.05~0.35 MPa")


def _ph(text: str) -> Profile:
    if _has(text, "水解"):
        return Profile("analog", "pH", "pH", 7.7, 8.1, 2, rule="酶法水解 pH：7.7~8.1")
    if _has(text, "结晶"):
        return Profile("analog", "pH", "pH", 3.9, 4.4, 2, rule="6-APA 等电点结晶 pH：3.9~4.4")
    if _has(text, "萃取", "酸"):
        return Profile("analog", "pH", "pH", 1.8, 2.6, 2, rule="酸化/萃取 pH：1.8~2.6")
    if _has(text, "碱"):
        return Profile("analog", "pH", "pH", 9.0, 11.0, 2, rule="碱液 pH：9~11")
    return Profile("analog", "pH", "pH", 6.5, 7.5, 2, rule="一般 pH：6.5~7.5")
