"""生成报警处置规程：空模板 + 由本体推导的处置卡骨架（草案）。

    python3 -m backend.tools.build_procedure_skeleton          # 生成（已存在时不覆盖）
    python3 -m backend.tools.build_procedure_skeleton --force  # 覆盖骨架，人工补充的内容会丢失

- data/source/6APA_处置规程.模板.xlsx：四个工作表的表头、字段说明与填写示例
  （示例为用户提供的其他项目报警响应卡 ARP-001，只示意格式，不加载）。
- data/source/6APA_处置规程.xlsx：6-APA 的处置卡骨架，只用本体里已有的事实推导：
  报警点 = 带数值的工艺限值（高 / 低两侧各一张）+ 工业关系里的报警事件；
  可能原因 = 指向该工艺量的影响 / 质量关系（按正负向区分偏高、偏低的原因）、控制回路、测点本身；
  后果 = 该工艺量的下游影响 + 引用该限值的规则结论；解除条件 = 回到限值的正常区间；
  处置步骤只生成「确认判断」阶段能由数据完成的步骤，真实处置步骤、禁止操作留给工艺人员补充。
  全部标「草案·待工艺确认」。
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.ontology.indexes import OntologyStore  # noqa: E402
from backend.ontology.models import CAUSAL_CATEGORIES  # noqa: E402
from backend.services import procedure_model as pm  # noqa: E402
from backend.services import process_limits  # noqa: E402

SOURCE_DIR = ROOT / "data" / "source"
OUT_FILE = SOURCE_DIR / pm.PROCEDURE_FILE_NAME
TEMPLATE_FILE = SOURCE_DIR / "6APA_处置规程.模板.xlsx"
STATUS = "草案·待工艺确认"
MAX_TAGS = 12

CATEGORY_OF_TYPE = {
    "工艺属性": "工艺", "物料流股": "工艺", "质量指标": "工艺", "业务指标": "工艺",
    "生产设备": "设备", "设备实例": "设备", "设备部件": "设备", "执行机构": "设备",
    "控制仪表": "仪表", "控制系统": "仪表", "公用介质": "公用工程",
}


class Ctx:
    def __init__(self, store: OntologyStore) -> None:
        self.store = store
        self.entity_by_name = {}
        for e in store.relations.entities.values():
            self.entity_by_name.setdefault(e["name"], e)
        self.upstream: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.downstream: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.control_in: dict[str, list[dict[str, Any]]] = defaultdict(list)   # 执行机构 —影响→ X
        self.control_out: dict[str, list[dict[str, Any]]] = defaultdict(list)  # X —反馈给→ 控制器
        self.alarms: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rel in store.relations.relations:
            s, o, cat = rel.get("subjectEntity"), rel.get("objectEntity"), rel.get("category")
            if cat in CAUSAL_CATEGORIES:
                self.upstream[o].append(rel)
                self.downstream[s].append(rel)
            elif cat == "控制关系" and rel.get("predicate") == "反馈给":
                self.control_out[s].append(rel)
            elif cat == "控制关系" and rel.get("predicate") in ("影响", "控制"):
                self.control_in[o].append(rel)
            elif cat == "报警联锁关系":
                self.alarms[s].append(rel)
        self.rules = [store._rule_view(r) for r in store.rules.rules]

    def tags_of(self, name: str) -> list[str]:
        entity = self.entity_by_name.get(name)
        if not entity:
            return []
        dcs = self.store.dcs
        out = []
        for m in entity["match"]["matches"]:
            if m["objectType"] == "parameter":
                out += [dcs.tags[t]["name"] for t in (dcs.parameters.get(m["id"]) or {}).get("tagIds", []) if t in dcs.tags]
            elif m["objectType"] == "tag" and m["id"] in dcs.tags:
                out.append(dcs.tags[m["id"]]["name"])
        return list(dict.fromkeys(out))


# 只有「正向影响」可以可靠地推方向。关系表里「负向影响」有时指反向变化，有时指不利影响
# （如 R1222「超温加速6-APA母环开环降解」标的是负向影响），所以负向 / 一般影响不推方向，只引用机理原文。
def _direction_text(pred: str, side: str) -> str:
    """上游量 A —pred→ X：X 偏高（side=高）时，A 应当怎样。"""
    if pred == "正向影响":
        return "偏高" if side == "高" else "偏低"
    return "异常"


def _effect_text(pred: str, side: str) -> str:
    """X —pred→ Y：X 偏高（side=高）时 Y 怎样。"""
    if pred == "正向影响":
        return "升高" if side == "高" else "降低"
    return "受影响"


def _join(names: list[str], limit: int = MAX_TAGS) -> str:
    return "、".join(names[:limit])


def build_card(ctx: Ctx, cid: str, *, x: str, side: str, area: str, tags: list[str], limit: dict[str, Any] | None,
               alarm_rels: list[dict[str, Any]]) -> tuple[dict, list, list]:
    unit = (limit or {}).get("unit") or ""
    if limit and side == "高":
        level = "/".join(k for k, v in (("H", limit.get("high")), ("HH", limit.get("highHigh"))) if v is not None)
        setpoint = " / ".join(f"{k} {v}" for k, v in (("H", limit.get("high")), ("HH", limit.get("highHigh"))) if v is not None)
    elif limit:
        level = "/".join(k for k, v in (("L", limit.get("low")), ("LL", limit.get("lowLow"))) if v is not None)
        setpoint = " / ".join(f"{k} {v}" for k, v in (("L", limit.get("low")), ("LL", limit.get("lowLow"))) if v is not None)
    else:
        level, setpoint = side, ""
    alarm_names = [r.get("objectEntity") for r in alarm_rels]
    alarm_name = alarm_names[0] if alarm_names else f"{x}{side}"

    # ---- 可能原因
    causes = [{
        "原因类别": "仪表", "原因描述": f"{x} 测点故障或信号异常（假报警）", "关联对象": x,
        "验证方法": "看信号质量码、数值是否冻结或突变，与同一工艺量的其他测点对比",
        "验证位号": _join(tags), "判据": "质量码为坏 / 长时间不变 / 与其他测点偏差明显",
        "依据": "通用测点核查",
    }]
    seen = {x}
    for rel in ctx.upstream.get(x, []):
        a = rel.get("subjectEntity")
        if not a or a in seen:
            continue
        seen.add(a)
        want = _direction_text(rel.get("predicate") or "", side)
        a_tags = ctx.tags_of(a)
        causes.append({
            "原因类别": CATEGORY_OF_TYPE.get(rel.get("subjectType") or "", "工艺"),
            "原因描述": f"{a}{want}（{rel.get('domainDescription') or rel.get('predicate')}）",
            "关联对象": a,
            "验证方法": f"查看「{a}」实时值与报警前趋势" if a_tags else f"核对「{a}」状况（本体中无现场测点，需人工确认）",
            "验证位号": _join(a_tags, 6),
            "判据": (f"{a}{want}，且变化早于或同步于 {x}" if want != "异常" else f"{a} 偏离正常并早于或同步于 {x} 变化")
            if a_tags else "",
            "依据": f"工业关系 {rel.get('relationCode') or ''} {rel.get('subjectEntity')} {rel.get('predicate')} {x}",
        })
    for rel in ctx.control_in.get(x, []):
        act = rel.get("subjectEntity")
        if not act or act in seen:
            continue
        seen.add(act)
        causes.append({
            "原因类别": "设备" if rel.get("subjectType") == "执行机构" else "仪表",
            "原因描述": f"{act} 调节异常（{rel.get('domainDescription') or '控制回路'}）",
            "关联对象": act,
            "验证方法": f"对比「{act}」的开度 / 频率指令与反馈",
            "验证位号": _join(rel.get("tagNames") or [], 6),
            "判据": "指令与反馈不一致，或已到限位仍无法拉回",
            "依据": f"工业关系 {rel.get('relationCode') or ''} 控制关系",
        })
    for rel in ctx.control_out.get(x, []):
        ctl = rel.get("objectEntity")
        if not ctl or ctl in seen:
            continue
        seen.add(ctl)
        causes.append({
            "原因类别": "仪表", "原因描述": f"控制器 {ctl} 未投自动或参数不当",
            "关联对象": ctl, "验证方法": f"核对 {ctl} 的手自动状态与设定值", "验证位号": "",
            "判据": "", "依据": f"工业关系 {rel.get('relationCode') or ''} {x} 反馈给 {ctl}",
        })
    for i, c in enumerate(causes, 1):
        c.update({"卡片编号": cid, "序号": i})

    # ---- 后果
    effects, effect_objects = [], []
    for rel in ctx.downstream.get(x, [])[:6]:
        y = rel.get("objectEntity")
        mech = rel.get("domainDescription") or ""
        effects.append(f"{y}{_effect_text(rel.get('predicate') or '', side)}" + (f"（{mech}）" if mech else ""))
        effect_objects.append(y)
    if limit:
        for r in ctx.rules:
            if limit["id"] in (r.get("limitRefs") or []):
                cond = r.get("condition") or ""
                is_high = bool(re.search(r">|高|超", cond))
                is_low = bool(re.search(r"<|低|不足", cond))
                if (side == "高" and is_high) or (side == "低" and is_low) or not (is_high or is_low):
                    effects.append(f"{r.get('conclusion')}（规则 {r.get('ruleId') or r.get('id')}）")
    effects += [f"触发「{n}」" for n in alarm_names]

    # ---- 处置步骤：只生成确认判断阶段能由数据完成的
    steps = [{"阶段": "确认判断", "岗位": "中控主操", "动作类型": "确认",
              "步骤描述": f"确认报警信息，查看「{x}」当前值与报警前趋势", "关联对象": x, "关联位号": _join(tags),
              "前置条件": "", "依据": "通用报警确认"}]
    if len(tags) > 1:
        steps.append({"阶段": "确认判断", "岗位": "中控主操", "动作类型": "对比",
                      "步骤描述": f"对比「{x}」的 {len(tags)} 个测点，区分单点假报警与真实{side}",
                      "关联对象": x, "关联位号": _join(tags), "前置条件": "", "依据": "同一工艺量多测点"})
    checkable = [c for c in causes[1:] if c["验证位号"]]
    if checkable:
        steps.append({"阶段": "确认判断", "岗位": "中控主操", "动作类型": "查询",
                      "步骤描述": "逐项核对可能原因中的相关参数：" + "、".join(c["关联对象"] for c in checkable[:6]),
                      "关联对象": "、".join(c["关联对象"] for c in checkable[:6]),
                      "关联位号": _join([t for c in checkable[:6] for t in c["验证位号"].split("、")][:MAX_TAGS]),
                      "前置条件": "", "依据": "由可能原因推导"})
    for i, s in enumerate(steps, 1):
        s.update({"卡片编号": cid, "序号": i})

    normal = ""
    if limit and limit.get("normalLow") is not None and limit.get("normalHigh") is not None:
        normal = f"{x} 恢复至正常区间 {limit['normalLow']}～{limit['normalHigh']} {unit}，报警自动复位"
    card = {
        "卡片编号": cid, "卡片名称": f"{x}{'高' if side == '高' else '低'}", "报警名称": alarm_name,
        "触发对象": x, "触发位号": _join(tags, 40), "报警级别": level, "设定值": setpoint, "单位": unit,
        "关联限值": (limit or {}).get("id") or "", "所属工段": area,
        "关联设备": "", "关联联锁": "、".join(alarm_names), "优先级": "", "允许响应时间": "",
        "报警现象·DCS": f"{_join(tags, 6)} {setpoint} 报警" if setpoint else "",
        "报警现象·现场": "", "未及时处置后果": "；".join(effects), "后果关联对象": "、".join(dict.fromkeys(effect_objects)),
        "解除条件": normal, "汇报要点": f"位号 {_join(tags, 6)}，{x} 实时读数与趋势；"
        + ("、".join(effect_objects[:3]) + " 状态" if effect_objects else "相关设备状态"),
        "记录要求": "记入操作记录及报警台账", "状态": STATUS,
        "依据": (f"工艺限值 {limit['id']}（{limit.get('status')}）" if limit else "")
        + ("；" if limit and alarm_rels else "") + ("、".join(f"报警事件「{n}」" for n in alarm_names)),
    }
    return card, causes, steps


def build_skeleton(store: OntologyStore) -> tuple[list, list, list]:
    ctx = Ctx(store)
    cards, causes, steps = [], [], []
    counter: dict[str, int] = defaultdict(int)
    used_alarm: set[str] = set()

    def next_id(area: str) -> str:
        counter[area] += 1
        return f"ARP-{area or 'XX'}-{counter[area]:02d}"

    for limit in process_limits._load():
        if not limit.get("hasValues"):
            continue
        x = limit["appliesTo"]
        targets, _ = process_limits.resolve_targets(store, limit)
        tags = [t["name"] for t in targets]
        if not tags:
            continue
        area = limit.get("areaCode") or (targets[0].get("areaCode") if targets else "") or ""
        if x.endswith("*"):  # 位号族限值（如 TI_1407*）：触发对象用测点所属设备组
            x = targets[0].get("equipmentGroup") or x
        alarm_rels = ctx.alarms.get(limit["appliesTo"], [])
        for side, keys in (("高", ("high", "highHigh")), ("低", ("low", "lowLow"))):
            if all(limit.get(k) is None for k in keys):
                continue
            side_alarms = [r for r in alarm_rels if ("低" in (r.get("objectEntity") or "")) == (side == "低")]
            used_alarm.update(r["id"] for r in side_alarms)
            c, cs, ss = build_card(ctx, next_id(area), x=x, side=side, area=area, tags=tags, limit=limit, alarm_rels=side_alarms)
            cards.append(c)
            causes += cs
            steps += ss

    for name, rels in ctx.alarms.items():
        for rel in rels:
            if rel["id"] in used_alarm:
                continue
            tags = rel.get("tagNames") or ctx.tags_of(name)
            if not tags:
                continue
            side = "低" if "低" in (rel.get("objectEntity") or "") else "高"
            area = rel.get("areaCode") or ""
            c, cs, ss = build_card(ctx, next_id(area), x=name, side=side, area=area, tags=tags, limit=None, alarm_rels=[rel])
            c["卡片名称"] = rel.get("objectEntity") or c["卡片名称"]
            cards.append(c)
            causes += cs
            steps += ss
    return cards, causes, steps


# ------------------------------------------------------------------ 模板与示例

FIELD_NOTES = [
    ("处置卡", "卡片编号", "必填", "唯一编号，例如 ARP-S11-01"),
    ("处置卡", "触发位号", "必填", "DCS 位号，多个用顿号分隔；可写 TI_1407* 表示位号族"),
    ("处置卡", "触发对象", "选填", "工艺量 / 设备名称，需与本体中的名称一致，对应不上时标「待确认」"),
    ("处置卡", "报警级别 / 设定值", "选填", "如 L/LL、7.5 / 7.0；与工艺限值表重复时可只填「关联限值」编号"),
    ("处置卡", "关联联锁", "选填", "联锁或报警事件名称，需与本体中的名称一致"),
    ("处置卡", "优先级 / 允许响应时间", "选填", "如 一般报警（重要报警）；15min 以上（5～15min）"),
    ("可能原因", "原因类别", "必填", "仪表 / 工艺 / 设备 / 操作 / 公用工程"),
    ("可能原因", "验证方法 / 验证位号 / 判据", "选填", "怎样确认这个原因；验证位号对应上本体时，该原因可由程序自动验证"),
    ("处置步骤", "阶段", "必填", "确认判断 / 假报警处置 / 真实处置 / 升级上报 / 恢复确认"),
    ("处置步骤", "岗位", "必填", "中控主操 / 中控副操 / 外操 / 班长 / 调度 / 仪表 / 车间"),
    ("处置步骤", "动作类型", "必填", "确认 / 查询 / 对比 / 联系 / 现场检查 / 操作 / 联锁 / 上报 / 记录；"
     "确认、查询、对比且关联位号已对应时可由程序自动完成，其余为人工步骤"),
    ("禁止操作", "禁止内容", "必填", "如 严禁屏蔽该报警；联锁触发后不得强制解除"),
]

EXAMPLE_CARD = {
    "卡片编号": "ARP-001", "卡片名称": "次高压锅炉给水压力低", "报警名称": "次高压锅炉给水压力（LL）",
    "触发对象": "次高压锅炉给水压力", "触发位号": "PI_039006", "报警级别": "L/LL", "设定值": "7.5 / 7.0", "单位": "MPa",
    "关联限值": "", "所属工段": "气化区域", "关联设备": "次高压锅炉给水泵", "关联联锁": "无",
    "优先级": "一般报警（重要报警）", "允许响应时间": "15min 以上（5～15min）",
    "报警现象·DCS": "PI_039006 位号框变蓝（黄）、框线闪烁、声光报警",
    "报警现象·现场": "次高压锅炉给水中断，换热器温度降低；破渣机、锁斗循环水泵、黑水循环泵机封水流量指示为 0",
    "未及时处置后果": "机泵机封水中断，机封损坏泄漏，引发安全事故，造成系统停车",
    "后果关联对象": "破渣机、锁斗循环水泵、黑水循环泵",
    "解除条件": "次高压锅炉给水压力恢复至 7.5MPa，报警自动复位，禁止手动清报警",
    "汇报要点": "位号 PI_039006 LL，锅炉给水压力实时读数；现场关注破渣机、锁斗循环泵、黑水循环泵运行状态",
    "记录要求": "记入操作记录及报警台账", "状态": "示例", "依据": "其他项目报警响应卡（用户提供），仅示意填写格式",
}
EXAMPLE_CAUSES = [
    ("仪表", "远传压力表故障，压力表电缆松动", "PI_039006", "对比就地压力表、流量计、出口压力", "PI_039006", "远传与就地读数不一致"),
    ("工艺", "次高压锅炉界区阀关闭，系统管线泄漏", "界区阀", "查看界区阀状态与给水流量", "", "流量与压力同时下降"),
    ("设备", "次高压锅炉给水泵故障或不打量", "次高压锅炉给水泵", "查看泵运行状态、电流、出口压力", "", "泵停或电流异常"),
    ("操作", "误操作界区阀关闭，现场导淋卡涩", "界区阀", "核对操作记录、现场检查", "", ""),
]
EXAMPLE_STEPS = [
    ("确认判断", "中控主操", "对比", "对比就地压力表、流量计、出口压力多参数综合判断，区分假报警与真实压力低，同步通知现场巡检，禁止盲目操作", "PI_039006"),
    ("假报警处置", "中控主操", "联系", "通知仪表检查，中控及现场监控其他参数，班长知情，严禁屏蔽报警", ""),
    ("真实处置", "中控主操", "联系", "确认报警信息、查看相关参数，联系调度确认锅炉水泵运行状态及恢复供水时间；及时解除有高压仪表冲洗水的仪表联锁，防止联锁误跳车；联系调度可否减气化炉负荷，后系统降低系统压力", ""),
    ("真实处置", "外操", "现场检查", "赶赴现场检查界区阀与机泵运行情况；若因锅炉给水泵原因，密切注意机泵机封温度和泄漏情况；黑水循环泵可停泵处理，锁斗循环泵、破渣机可间歇启动防止锥底积渣；气化炉补水可切换至事故激冷水补水，注意气化炉液位", ""),
    ("真实处置", "中控主操", "联锁", "次高压锅炉给水压力低低，联锁自动触发，禁止旁路联锁", ""),
    ("升级上报", "班长", "上报", "事态恶化上报调度和车间", ""),
    ("恢复确认", "外操", "现场检查", "给水恢复后逐个恢复各锅炉给水用户点，确认设备无异常，汇报中控", ""),
]


def _style(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "C2"


def write_book(path: Path, cards, causes, steps, forbidden, extra: list[tuple[str, pd.DataFrame]] = ()) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(cards, columns=pm.CARD_COLUMNS).to_excel(writer, sheet_name=pm.SHEET_CARDS, index=False)
        pd.DataFrame(causes, columns=pm.CAUSE_COLUMNS).to_excel(writer, sheet_name=pm.SHEET_CAUSES, index=False)
        pd.DataFrame(steps, columns=pm.STEP_COLUMNS).to_excel(writer, sheet_name=pm.SHEET_STEPS, index=False)
        pd.DataFrame(forbidden, columns=pm.FORBIDDEN_COLUMNS).to_excel(writer, sheet_name=pm.SHEET_FORBIDDEN, index=False)
        for name, df in extra:
            df.to_excel(writer, sheet_name=name, index=False)
        _style(writer.sheets[pm.SHEET_CARDS], [12, 18, 22, 18, 30] + [12] * 18)
        _style(writer.sheets[pm.SHEET_CAUSES], [12, 6, 9, 40, 18, 36, 26, 30, 40])
        _style(writer.sheets[pm.SHEET_STEPS], [12, 6, 10, 10, 9, 60, 18, 26, 14, 20])
        _style(writer.sheets[pm.SHEET_FORBIDDEN], [12, 6, 50, 18, 20])


def main() -> int:
    force = "--force" in sys.argv
    if not TEMPLATE_FILE.exists() or force:
        ex_causes = [{"卡片编号": "ARP-001", "序号": i, "原因类别": c, "原因描述": d, "关联对象": o, "验证方法": m,
                      "验证位号": t, "判据": j, "依据": "示例"} for i, (c, d, o, m, t, j) in enumerate(EXAMPLE_CAUSES, 1)]
        ex_steps = [{"卡片编号": "ARP-001", "序号": i, "阶段": p, "岗位": r, "动作类型": a, "步骤描述": d,
                     "关联对象": "", "关联位号": t, "前置条件": "", "依据": "示例"} for i, (p, r, a, d, t) in enumerate(EXAMPLE_STEPS, 1)]
        ex_forbidden = [{"卡片编号": "ARP-001", "序号": 1, "禁止内容": "严禁屏蔽次高压锅炉压力低低报警", "关联对象": "", "依据": "示例"},
                        {"卡片编号": "ARP-001", "序号": 2, "禁止内容": "联锁触发不得强制解除联锁", "关联对象": "", "依据": "示例"}]
        write_book(TEMPLATE_FILE, [EXAMPLE_CARD], ex_causes, ex_steps, ex_forbidden,
                   [("字段说明", pd.DataFrame(FIELD_NOTES, columns=["工作表", "字段", "必填", "说明"]))])
        print(f"已生成 {TEMPLATE_FILE.relative_to(ROOT)}（含填写示例 ARP-001，来自其他项目，仅示意格式）")
    if OUT_FILE.exists() and not force:
        print(f"{OUT_FILE.name} 已存在，未覆盖（按本体重建骨架请加 --force）")
        return 0
    store = OntologyStore()
    cards, causes, steps = build_skeleton(store)
    # 已有规程的工段用规程卡替换推导骨架：S11 酶法水解（docs/SOP-S11-ALARM-001.md）
    from backend.tools.sop_s11_cards import build as build_s11

    s11_cards, s11_causes, s11_steps, s11_forbidden = build_s11(store)
    keep = {c["卡片编号"] for c in cards if c["所属工段"] != "S11"}
    cards = [c for c in cards if c["卡片编号"] in keep] + s11_cards
    causes = [c for c in causes if c["卡片编号"] in keep] + s11_causes
    steps = [s for s in steps if s["卡片编号"] in keep] + s11_steps
    write_book(OUT_FILE, cards, causes, steps, s11_forbidden)
    print(f"已生成 {OUT_FILE.relative_to(ROOT)}：{len(cards)} 张处置卡（S11 {len(s11_cards)} 张取自 SOP-S11-ALARM-001，"
          f"其余为推导骨架），{len(causes)} 条可能原因，{len(steps)} 个步骤，{len(s11_forbidden)} 条禁止操作")
    return 0


if __name__ == "__main__":
    sys.exit(main())
