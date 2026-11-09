"""生成北I-2 深冷装置本体梳理 Excel。

    python3 -m backend.tools.build_cryo_ontology            # 输出 data/cryo/北I-2深冷_本体.xlsx（已存在则覆盖）

输入（data/cryo/source/）：DCS 点表 xlsx、操作规程 docx；人工梳理的知识在 cryo_knowledge.py。
依赖 openpyxl、python-docx（只是离线整理工具，Demo 运行时不需要）。
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import cryo_knowledge as K

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "cryo" / "source"
POINTS_XLSX = SRC / "北I-2深冷_DCS点表.xlsx"
SOP_DOCX = SRC / "北I-2装置操作规程_2025.6.13.docx"
OUT = ROOT / "data" / "cryo" / "北I-2深冷_本体.xlsx"

UNIT_OF_CODE = {"101": "U01", "102": "U02", "103": "U03", "104": "U04", "105": "U05",
                "106": "U06", "107": "U03", "108": "U06", "110": "U06", "112": "U06",
                "TEG": "U03", "SGC": "U03", "DRY": "U03", "BLR": "U06", "FLR": "U06", "ENV": "U06"}

# ------------------------------------------------------------------------------------------
# 点表
# ------------------------------------------------------------------------------------------
INCLUDED = {  # 块类型 → 说明
    "AI": "模拟量输入", "AO": "模拟量输出", "PIDA": "PID 回路", "MAN": "手操器", "MOT2": "电动阀 / 电机控制",
    "VAL2": "开关阀控制", "GASCAL": "气体流量计算", "FLOWSUM": "流量累计", "DI": "开关量输入", "DOV": "开关量输出",
    "AM": "中间模拟量（含 APC / RTO）", "DM": "中间开关量（含 APC / RTO）", "REAL": "实数变量（报警限、回路参数、计算量）",
    "REALM": "Modbus 通讯模拟量（压缩机、膨胀机、导热油炉、锅炉、火炬 PLC）", "INTM": "Modbus 通讯整型（火炬、尾气回收撬）",
    "WORDM": "Modbus 通讯字（锅炉、环境监测）", "BYTEM": "Modbus 通讯字节", "LREAL": "长实数（燃料气累计）",
    "BITM": "Modbus 通讯位（ESD 系统、锅炉、火炬）", "BOOL": "布尔变量（信号质量、联锁投切、程序报警）",
    "APCCOM": "APC 通讯", "APC_MAN": "APC 手操", "APC_OUT": "APC 输出", "APC_SP": "APC 设定", "__AT__SFC": "顺控程序",
}
EXCLUDED = {
    "MODULE": "IO 模块清单（硬件组态）", "CHANNEL": "IO 通道（硬件组态）", "MODULE_DA": "数采组（硬件组态）",
    "HSALARMSPARK": "报警闪烁逻辑（画面）", "HSGETHART": "HART 诊断", "HSGETSTATE": "IO 设备诊断", "KBUSCNVT": "K-BUS 状态",
    "MOD_MODULE": "Modbus 模块诊断", "MOD03_MODBUSMTF": "Modbus 内部数据", "DP_TEST": "内部数据", "SYSAM": "控制站 / 操作站健康",
    "DV": "控制站 / 操作站健康（开关量）", "SYSAV": "操作站登录", "SYSDV": "授权状态", "SYSSTRING": "操作站登录",
    "TON": "延时逻辑", "TOF": "延时逻辑", "R_TRIG": "上升沿逻辑", "F_TRIG": "下降沿逻辑", "TIMER_EVENT": "定时逻辑",
    "FILTER": "滤波逻辑", "FSTMEMY8": "内部逻辑", "TIME": "计时逻辑", "MFQLLBC": "内部逻辑", "INT": "内部变量",
    "WORD": "任务心跳", "OVERVIEW": "画面报警汇总", "MOT2_": "",
}


def load_points():
    wb = openpyxl.load_workbook(POINTS_XLSX, data_only=True)
    pts, stats = [], []
    for ws in wb:
        rows = list(ws.iter_rows(values_only=True))
        n = max(len(rows) - 2, 0)
        if ws.title not in INCLUDED:
            stats.append((ws.title, n, 0, EXCLUDED.get(ws.title, "硬件 / 内部"), "不纳入本体"))
            continue
        h = list(rows[1])

        def col(r, *names):
            for nm in names:
                if nm in h and r[h.index(nm)] not in (None, ""):
                    return r[h.index(nm)]
            return None
        kept = 0
        for r in rows[2:]:
            tag = col(r, "点名")
            if not tag:
                continue
            desc = str(col(r, "点描述") or "").strip()
            pts.append(dict(
                tag=str(tag).strip(), desc=desc, block=ws.title,
                hi=col(r, "工程量量程上限", "量程上限", "PV量程上限"), lo=col(r, "工程量量程下限", "量程下限", "PV量程下限"),
                unit=str(col(r, "单位", "测量值单位") or "").strip(), station=col(r, "站号"),
                s0=col(r, "置0说明"), s1=col(r, "置1说明"),
                spare=("备用" in desc) or str(tag).startswith(("BY10_", "BY11_A", "BY11_D", "BY_AI", "BY_DI")) and "备用" in desc,
            ))
            kept += 1
        stats.append((ws.title, n, kept, INCLUDED[ws.title], "纳入位号表"))
    return pts, stats


def tag_unit(tag: str, desc: str) -> str:
    t = tag
    if re.search(r"SGC", t):
        return "SGC"
    if re.match(r"^(DRY_|GV2109|GZ[OC]_2109|TDRYL|H1070)", t):
        return "DRY"
    if re.match(r"^(GL_|RSL_|ZQL|LS101_|HV_10[345]_|PS10\d|Z10\dDC|GIA30\d)", t):
        return "BLR"
    if re.match(r"^(M[DXW]\d|FT1060|FIO_57)", t) or "TT-106" in desc or "PCV10611" in desc:
        return "FLR" if not t.startswith("FIO_57") else "104"
    if t.startswith("HJJC"):
        return "ENV"
    if re.match(r"^(PT|TT|LT|LS)100\d|^ZI_100\d|^XC_1005", t):
        return "TEG"
    if re.match(r"^(SYS|fcssys|taskHeart|FIO)", t):
        return "SYS"
    if re.search(r"APC|RTO|^DM10|^AM10|^REAL10|^BOOL_\w+L$", t) or "APC" in desc:
        return "APC"
    if re.match(r"^(ANNIU|STOP1|RESET|POWER_ALARM)", t):
        return "ESD"
    m = re.search(r"(?<![0-9])(10[1-9]|11[0-4])(?=[_A-Z])", t)
    if m:
        return "ESD" if m.group(1) == "114" else m.group(1)
    if t.startswith("PN11_A"):
        return "108"
    return ""


# ------------------------------------------------------------------------------------------
# 阀门实例
# ------------------------------------------------------------------------------------------
def vnorm(s: str) -> str:
    s = (s or "").replace("（", "(").replace("）", ")").replace("阀门", "阀").replace("收集管", "收集罐")
    s = s.replace("A床层", "1#床层").replace("B床层", "2#床层")
    for _ in range(3):
        s = re.sub(r"(开阀命令|关阀命令|开反馈|关反馈|开状态|关状态|罐反馈|开到位|关到位|控制|反馈|命令)$", "", s)
        s = re.sub(r"(?<=阀)[开关]$", "", s)
    return s.strip()


def valve_id(tag: str, block: str) -> str:
    if tag == "105HIC111":
        return "105-HICV-111"
    if tag == "105HV201SC1":
        return "105-HV-201"
    if block == "AO":
        parts = tag.split("_")
        return "-".join(parts)
    m = re.match(r"^(\d{3})([A-Z]+)(\d+[A-Z]?)$", tag)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^([A-Z]+)(\d+)(?:_(\d))?$", tag)
    if m:
        return f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")
    return tag


def build_valves(pts):
    valves, by_name = [], {}
    for p in pts:
        if p["block"] not in ("VAL2", "MOT2", "AO", "MAN") or p["spare"]:
            continue
        if p["block"] in ("AO", "MAN") and (re.search(r"TRC|LRC|TCA", p["tag"]) or "变频" in p["desc"]):
            continue
        vid = valve_id(p["tag"], p["block"])
        name, extra = K.VALVE_NAME_FIX.get(vid, (vnorm(p["desc"]), ""))
        if "阀" not in name and vid not in K.VALVE_NAME_FIX and "喷嘴" not in name:
            continue  # 点火、引火筒等非阀门命令
        if name in by_name:
            v = by_name[name]
            v["tags"].append(p["tag"])
            if p["block"] in ("AO",) and not v["id"].count("-") > 1:
                v["id"] = vid
            continue
        cls = {"VAL2": "开关阀", "MOT2": "电动阀", "AO": "调节阀", "MAN": "调节阀"}[p["block"]]
        v = dict(id=vid, name=name, cls=cls, kw="|".join(x for x in [name, extra] if x), tags=[p["tag"]],
                 unit_code=tag_unit(p["tag"], p["desc"]), basis=f"点表 {p['block']} {p['tag']}")
        valves.append(v)
        by_name[name] = v
    for vid, name, cls, host, kw, basis in K.EXTRA_VALVES:
        if name in by_name:
            continue
        v = dict(id=vid, name=name, cls=cls, kw=kw, tags=[], unit_code=vid[:3] if vid[:3].isdigit() else "", basis=basis, host=host)
        valves.append(v)
        by_name[name] = v
    hosts = [("中一联返输气", "PL-OUT-1"), ("北I-2联返输气", "PL-OUT-2")] + K.VALVE_HOST
    eq_unit = {e["id"]: e["unit"] for e in K.EQUIPMENT}
    for v in valves:
        if not v.get("host"):
            v["host"] = next((h for k, h in hosts if k in v["name"]), None)
        v["unit"] = UNIT_OF_CODE.get(v["unit_code"]) or eq_unit.get(v["host"])
    return valves


# ------------------------------------------------------------------------------------------
# 位号归属
# ------------------------------------------------------------------------------------------
class Matcher:
    def __init__(self, equipment, valves):
        self.items = []  # (kw, id, units)
        for e in equipment:
            units = set(filter(None, e["tag_units"].split("|")))
            for kw in filter(None, e["kw"].split("|")):
                self.items.append((kw, e["id"], units))
        for v in valves:
            units = {v["unit_code"]} if v["unit_code"] else set()
            for kw in filter(None, v["kw"].split("|")):
                self.items.append((vnorm(kw) or kw, v["id"], units))

    def match(self, desc: str, unit: str = ""):
        text = desc + "｜" + vnorm(desc)
        cands = [(kw, i, u) for kw, i, u in self.items if kw and kw in text]
        if not cands:
            return None, None
        same = [c for c in cands if unit and unit in c[2]]
        pool = same or [c for c in cands if not c[2] or not unit] or cands
        kw, i, _ = max(pool, key=lambda c: (len(c[0]), bool(c[2])))
        return i, kw


AUX_SUFFIX = r"(_(AH|AL|AM|HH|LL|DQ|BP\d?|KP|TI|TD|SP|MODE|AV\d*|ROD|ALML|LSL|FB|SET|JS)|LS\d?|M1|MLJH?|M_LJ1?|M|BC|_FIL|SD|_DZ1|B2)$"
MANUAL_BIND = {
    "101LT101_AH": "D10101/1", "101LT101_AM": "D10101/1", "S104HZC281A": "104-HV-281A", "S104HZO281A": "104-HV-281A",
    "S104HZO281B": "104-HV-281B", "S104HZC281B": "104-HV-281B",
    "104_HZO_102B": "104-HICV-102B", "104_HZC_102B": "104-HICV-102B", "105PT102_DQ": "TA10501/2",
    "102_TV_102A": "102-TV-102A", "102_TV_102B": "102-TV-102B",
    "A102_FIC130M": "C10201", "BHLSD": "C10201", "TIMESD": "C10201", "a102_FIC130": "C10201", "a102_FIC131": "C10201",
    "102PT101": "PL-FEED", "102TT101": "PL-FEED", "102FT101": "PL-FEED",
    "PT101AROD": "D10301/1", "PT101BROD": "D10301/2",
    "FT10601_01": "X10601", "FT10601_02": "X10601", "FT10601_03": "X10601", "FT10601_04": "X10601",
    "GIA2109LS": "SYS-GDS", "BY11_D0_2511": "H10701", "VS101": "SGC", "VS101_ZI": "SGC",
    "FIO_57_4": "C10402", "104_UIC_161": "C10402", "104_UIC_162": "C10402",
    "PDT191A": "X10401/1", "PDT191B": "X10401/2", "PDT190A": "X10401/1", "PDT190B": "X10401/2",
}


REGEX_BIND = [  # 无描述 / 描述不含设备名的程序点：位号正则 → 对象
    (r"^A_(XF|LC|RC|JR|JY|SY|BX)", "D10301/1"), (r"^B_(XF|LC|RC|JR|JY|SY|BX)", "D10301/2"),
    (r"^(AXF_|YMAN_FZS|PAUSE_FZS|FZSKZ)", "G-103-01"), (r"^(BAOWEN|FJ_ZF|PV_SD_|QD_WD|TZ_WD)", "A10301"),
    (r"^(ZDPY|AUTO$|HJDH$)", "G-101-01"), (r"^105LT107H_AUTO", "D10502"), (r"^105LS106_BP", "D10502"),
    (r"^FSTMEMY8_180A", "X10401/1"), (r"^FSTMEMY8_180B", "X10401/2"), (r"^A_10\d_G", "SYS-GDS"),
    (r"^105HV1(0[1-6]|11)A?DZ$|^105HV1(06|11)_LS_1$", None), (r"^HV111_BP$", "105-HV-111"),
]


def regex_bind(tag):
    for pat, eid in REGEX_BIND:
        if re.match(pat, tag):
            if eid is None:
                m = re.match(r"^105HV1(\d\d)", tag)
                return f"105-HV-1{m.group(1)}A"
            return eid
    return None


def role_of(p) -> str:
    b, t, d = p["block"], p["tag"], p["desc"]
    if b == "AI":
        if re.search(r"_[A-Z]?ZT_|_ZI_|ZT_\d", t) or d.endswith(("阀反馈", "开度反馈", "调节反馈")):
            return "阀位反馈"
        if "变频" in d:
            return "变频反馈"
        return "测量"
    if b == "AO":
        return "变频输出" if "变频" in d else "控制输出"
    if b in ("PIDA",):
        return "控制回路"
    if b == "MAN":
        return "手操输出"
    if b in ("MOT2", "VAL2"):
        return "设备控制块"
    if b == "DI":
        if re.search(r"报警|高开关", d) and "LS" in t:
            return "报警开关"
        if re.search(r"[开关](反馈|状态|到位)", d):
            return "阀位开关反馈"
        if re.search(r"按钮|选择|投自动|自动控制", d):
            return "就地操作"
        if "报警" in d or "故障" in d or "停机" in d:
            return "设备报警"
        return "运行状态"
    if b == "DOV":
        return "控制命令"
    if b == "GASCAL":
        return "流量计算"
    if b == "FLOWSUM":
        return "流量累计"
    if b == "REAL":
        m = re.search(r"_(AH|AL|HH|LL)$", t)
        if m:
            return "报警限设定"
        if t.endswith("_AM"):
            return "报警使能"
        if re.search(r"_(KP|TI|TD)$", t):
            return "回路参数"
        if t.endswith("_SP"):
            return "回路设定值"
        if t.endswith("_MODE"):
            return "回路模式"
        if re.search(r"SET|_LSL|_ALML|SD$|_D$", t) or "设定" in d:
            return "程序设定"
        if re.search(r"_JD$|_FB$", t):
            return "程序进度"
        if re.search(r"LJH?$|^ZL|M\d?$|BHLSD|ROD$|_AV", t):
            return "计算量"
        return "中间量"
    if b in ("REALM", "INTM", "WORDM", "BYTEM", "LREAL"):
        if re.search(r"写参数|设定", d):
            return "设定值（通讯）"
        if re.search(r"报警|故障|高$|低$|超高|超低|异常|运行|状态|到位", d) and b == "INTM":
            return "状态 / 报警（通讯）"
        return "测量（通讯）"
    if b == "BITM":
        if re.search(r"旁路", d):
            return "联锁旁路"
        if t.startswith(("HMI_", "LS_")):
            return "ESD 画面操作"
        return "ESD / 通讯开关量"
    if b == "BOOL":
        if t.endswith("_DQ") or d.endswith("信号质量"):
            return "信号质量"
        if "_BP" in t or "投切" in d:
            return "联锁投切"
        if "联锁" in d:
            return "联锁指示"
        if "ALM" in t or "报警" in d:
            return "程序报警"
        return "逻辑量"
    if b in ("AM", "DM", "APCCOM", "APC_MAN", "APC_OUT", "APC_SP"):
        return "APC / RTO" if re.search(r"APC|RTO|IQ", t) else "计算量"
    if b == "__AT__SFC":
        return "顺控程序"
    return "其他"


QTY = [("压差", "压差"), ("差压", "压差"), ("压力", "压力"), ("压降速率", "压力变化率"), ("温度", "温度"), ("温差", "温度"),
       ("油温", "温度"), ("液位", "液位"), ("界面", "界位"), ("流量", "流量"), ("吨位", "质量"), ("露点", "露点"),
       ("转速", "转速"), ("键相", "转速"), ("频率", "频率"), ("振动", "振动"), ("震动", "振动"), ("位移", "位移"),
       ("电流", "电流"), ("纯度", "纯度"), ("浓度", "浓度"), ("湿度", "湿度"), ("风速", "风速"), ("风向", "风向"),
       ("气压", "压力"), ("油压", "压力"), ("开度", "开度"), ("阀位", "开度"), ("进度", "进度"), ("时间", "时间")]


def quantity(desc: str, unit: str) -> str:
    for k, q in QTY:
        if k in desc:
            return q
    return {"MPa": "压力", "kPa": "压力", "℃": "温度", "%": "百分比", "Hz": "频率", "rpm": "转速"}.get(unit, "")


def bind_points(pts, matcher, valves):
    loop_eq = {lp[0]: lp[2] for lp in K.LOOPS}
    by_tag = {p["tag"]: p for p in pts}
    eq_names = {e["id"]: e["name"] for e in K.EQUIPMENT}
    eq_names.update({v["id"]: v["name"] for v in valves})
    primary = {e["id"]: (e["kw"].split("|")[0] if e["kw"] else e["name"]) for e in K.EQUIPMENT}
    primary.update({v["id"]: v["name"] for v in valves})
    kws_of = {e["id"]: [k for k in e["kw"].split("|") if k] for e in K.EQUIPMENT}
    for p in pts:
        p["unit_code"] = tag_unit(p["tag"], p["desc"])
        p["role"] = role_of(p)
    order = sorted(pts, key=lambda p: (p["block"] not in ("AI", "PIDA", "AO", "VAL2", "MOT2", "DI", "REALM"), p["tag"]))
    for p in order:
        t, how, kw = p["tag"], "", None
        eid = MANUAL_BIND.get(t)
        if eid:
            how = "人工指定"
        elif regex_bind(t):
            eid, how = regex_bind(t), "按位号规则（程序点）"
        elif p["block"] == "PIDA" and t in loop_eq:
            eid, how = loop_eq[t], "控制回路表"
        else:
            base = re.sub(AUX_SUFFIX, "", t)
            bp = by_tag.get(base) if base != t else None
            if bp is not None and bp.get("eq"):
                eid, how = bp["eq"], f"随主位号 {base}"
            else:
                desc = p["desc"] if re.search(r"[一-鿿]", p["desc"]) else (bp["desc"] if bp else p["desc"])
                eid, kw = matcher.match(desc, p["unit_code"])
                how = f"描述关键字「{kw}」" if eid else ""
        if not eid:
            fallback = {"SYS": "SYS-DCS", "APC": "SYS-APC", "ESD": "SYS-ESD", "ENV": "ENV", "FLR": "X10601", "SGC": "SGC",
                        "DRY": "H10701", "BLR": "BLR", "TEG": "G-103-03"}.get(p["unit_code"])
            if fallback:
                eid, how = fallback, "按位号前缀归入系统 / 撬"
        p["eq"], p["how"] = eid, how
        p["eq_name"] = eq_names.get(eid, "") if eid else ""
        d = p["desc"]
        param = d
        # 只去掉设备「本名」（第一个匹配关键字或设备名称）；部件类关键字（润滑油冷却器…）保留在参数名里
        head = next((h for h in (primary.get(eid), p["eq_name"]) if h and d.startswith(h)), None) if eid else None
        if head:
            param = d[len(head):]
        param = param.strip(" _-:：")
        if len(param) <= 2 and param != d:
            # 去掉台号后只剩「液位」「转速」时，用去台号的完整描述，保证同组各台参数同名（如 轻烃储罐液位）
            param = re.sub(r"^\d+#", "", d)
        for k in kws_of.get(eid, ()):  # 「1#膨胀端X轴震动」→「膨胀端X轴震动」（台号属于设备本身时去掉）
            m = re.match(r"^\d+#", k)
            if m and param.startswith(k):
                param = param[len(m.group(0)):]
                break
        p["param"] = param
        p["qty"] = quantity(d, p["unit"])
        p["conf"] = "高" if how in ("人工指定", "控制回路表") or how.startswith("随主位号") else ("中" if eid else "")
        if how.startswith("按位号前缀"):
            p["conf"] = "低"
    return pts


# ------------------------------------------------------------------------------------------
# 规程（docx）
# ------------------------------------------------------------------------------------------
def doc_tables():
    import docx
    d = docx.Document(SOP_DOCX)
    out = []
    for t in d.tables:
        rows = []
        for r in t.rows:
            seen, cells = set(), []
            for c in r.cells:
                if id(c._tc) in seen:
                    continue
                seen.add(id(c._tc))
                cells.append(re.sub(r"\s+", " ", c.text).strip())
            rows.append(cells)
        out.append(rows)
    return d, out


NUM = r"-?\d+(?:\.\d+)?"


def parse_range(s):
    s = (s or "").replace("－", "-").replace("~", "～")
    nums = [float(x) for x in re.findall(NUM, s.replace("～-", "～ -"))]
    if not nums:
        return None, None
    if len(nums) >= 2 and "～" in s:
        a, b = nums[0], nums[1]
        return min(a, b), max(a, b)
    if re.search(r"[＜<≤]|小于|不超过|以下", s):
        return None, nums[0]
    if re.search(r"[≥＞>]|大于|以上", s):
        return nums[0], None
    return nums[0], nums[0]


GENERIC = set("温度压力液位流量差出口入进的高低报警指示值器")


def cjk(s):
    return set(re.findall(r"[\u4e00-\u9fff]", s or "")) - GENERIC


def similarity(a, b):
    A, B = cjk(a), cjk(b)
    if not A or not B:
        return 0.5
    return len(A & B) / min(len(A), len(B))


class TagMapper:
    def __init__(self, pts):
        self.pts = pts
        self.rank = {"测量": 0, "测量（通讯）": 0, "计算量": 1, "流量计算": 1, "控制回路": 2}

    def _norm(self, t):
        u = t.upper().replace("_", "").replace("-", "")
        return re.sub(r"^A(?=\d{3})", "", u)

    def candidates(self, sop_tag, any_unit=False):
        t = self._norm(sop_tag)
        m = re.match(r"^(\d{3})([A-Z]+?)(\d{2,3})([A-Z]?)$", t)
        if not m:
            return []
        u, letters, num, suf = m.groups()
        lead = "PD" if letters.upper().startswith("PD") else letters[0]
        out = []
        for sfx in ([suf, ""] if suf else [""]):
            pat = re.compile("^" + (r"\d{3}" if any_unit else u) + lead + "[A-Z]*" + num + sfx + "$")
            out = [p for p in self.pts if pat.match(self._norm(p["tag"]))]
            if out:
                break
        out.sort(key=lambda p: (self.rank.get(p["role"], 5), "阀" in p["desc"], len(p["tag"])))
        return out

    def map(self, sop_tag, name, strict=True):
        """strict=False：设备报警停机表的仪表位号可靠，同单元按位号取，不做名称校验。"""
        if not sop_tag or not re.search(r"\d", sop_tag):
            return None, "", "规程未给位号"
        c = self.candidates(sop_tag)
        if c and not strict:
            return max(c, key=lambda p: similarity(name, p["desc"])), "位号规则", ""
        if c:
            best = max(c, key=lambda p: (similarity(name, p["desc"]), -c.index(p)))
            if similarity(name, best["desc"]) >= 0.34:
                return best, "位号规则", ""
        alt = [p for p in self.candidates(sop_tag, True) if similarity(name, p["desc"]) >= 0.6]
        if alt:
            note = f"同号点 {c[0]['tag']}「{c[0]['desc']}」名称不符" if c else ""
            return alt[0], "位号规则（跨单元，按名称选）", note
        if c:
            return None, "", f"名称不一致：同号点 {c[0]['tag']}「{c[0]['desc']}」"
        return None, "", "点表无对应位号"


SOP_TAG_FIX = {  # 规程位号 → DCS 位号（规则映射不到、或规程位号写错而名称明确的）
    ("102-TISA", "电机冷风温度"): "a102_TISA11", ("102-TISA", "电机热风温度"): "a102_TISA12",
    ("102-PV120", "入口分离器压力"): "a102_PICA120", ("102-FT-180", "增压机入口流量"): "104FT180A",
    ("102-FI-101", "原料气压缩机入口气流量"): "102FT101M",
    ("102-PT171", "压缩机油站出口汇管压力"): "a102_PINSA171", ("102-TE171", "压缩机润滑油冷却后温度"): "a102_TINSA171",
    ("102-LT-103", "重烃收集罐烃液位"): "102LT102", ("105-LT-101", "二次闪蒸罐烃液位"): "105LT106",
    ("105-LT-102", "二次闪蒸罐水液位"): "105LT107", ("102-LT-124", "增压机出口分离器液位"): "102LT105",
    ("104-TE-126A", "1#塔底泵定子温度"): "104TE125", ("104-TE-126B", "2#塔底泵定子温度"): "104TE126",
    ("104-PDR-103", "重沸器和侧沸器压差指示高"): "104PDT103", ("102-LSA-103", "重烃收集罐水室液位指示、高低报警"): "102LT104",
    ("103-LRCA-104", "再生气空冷器出口温度高报警"): "103TT104", ("104-PT-104", "增压机出口压力"): "104PT112",
    ("102-PT-104", "原料气去脱水单元压力"): "102PT104",
    ("104-PT-180", "膨胀机油箱压力"): "104PT185A、104PT185B", ("104-PDT-182", "膨胀机轴承供回油压差"): "104PDT182A、104PDT182B",
    ("104-TE-184", "膨胀机油冷器出口温度"): "104TE184A、104TE184B", ("104-TE-182", "密封气去膨胀机温度"): "104TE182A、104TE182B",
    ("102-PT-135", "三级出口压力"): "a102_PI135", ("102-TI-135", "三级出口温度"): "a102_TI135",
    ("103-PT-101A", "原料气1#干燥器入口压力"): "103PT101A", ("103-PT-101B", "原料气2#干燥器入口压力"): "103PT101B",
    ("104-PdI-182A", "供油压差联锁启油泵"): "104PDT182A", ("104-PdI-182B", "供油压差联锁启油泵"): "104PDT182B",
    ("104-PI-187A", "前后油膜差压"): "104PDT187A", ("104-PI-187B", "前后油膜差压"): "104PDT187B",
    ("104-LS-183A", "油箱液位"): "104LT184A", ("104-LS-183B", "油箱液位"): "104LT184B",
    ("104-TE-182A", "密封气出油箱温度"): "104TE182A",
    ("104-XE-180XA", "膨胀端X振动"): "104XE180AX", ("104-XE-180XB", "膨胀端X振动"): "104XE180BX",
    ("104-XE-180YA", "膨胀端Y振动"): "104XE180AY", ("104-XE-180YB", "膨胀端Y振动"): "104XE180BY",
    ("104-XE-181XA", "膨胀端X振动"): "104XE181AX", ("104-XE-181XB", "膨胀端X振动"): "104XE181BX",
    ("104-XE-181YA", "膨胀端X振动"): "104XE181AY", ("104-XE-181YB", "膨胀端X振动"): "104XE181BY",
    ("104-PDI-184A", "密封气过滤器差压"): "104PDT183A", ("104-PDI-184B", "密封气过滤器差压"): "104PDT183B",
}

STARTUP_TITLES = {1: ("表2-1", "投用压缩单元", 30), 2: ("表2-2", "投用分子筛吸附器", 10), 3: ("表2-3", "投用丙烷机", 10),
                  4: ("表2-4", "投用再生气系统", 20), 5: ("表2-5", "投用膨胀机", 30), 6: ("表2-6", "投用塔底泵", 10),
                  7: ("表2-7", "投用重烃储运单元", 5), 8: ("表2-8", "投用罐区污水泵", 5), 9: ("表2-9", "投用罐区污油泵", 5),
                  10: ("表2-10", "投用轻烃外输泵", 5)}
STARTUP_MAP = {  # 参数名 → (对象, DCS 位号)
    "压缩机一级出口压力": ("C10201", "a102_PI131"), "压缩机二级出口压力": ("C10201", "a102_PI133"),
    "压缩机三级出口压力": ("C10201", "a102_PI135"), "压缩机入口气量": ("C10201", "a102_FIC130"),
    "压缩机一级出口温度": ("C10201", "a102_TI131"), "压缩机二级出口温度": ("C10201", "a102_TI133"),
    "压缩机三级出口温度": ("C10201", "a102_TI135"), "过滤分离器进出口压差": ("F10301", "103PDT107"),
    "干气过滤器进出口压差": ("G-103-02", "103PDT108"), "吸气压力": ("C10402", ""), "排气压力": ("C10402", ""),
    "吸气温度": ("C10402", ""), "排气温度": ("C10402", ""), "油过滤器前后压差": ("C10402", ""),
    "再生气流量": ("PL-REGEN-DP", "103FT101M"), "导热油出炉温度": ("H10701", "DRY_TT_CK"),
    "再生吸附器压力": ("G-103-01", "103PT103"), "三甘醇重沸器温度": ("TEG-RB", "TT1002"),
    "膨胀机转速": ("G-104-03", "104SI180A"), "膨胀机出口压力": ("G-104-03", "104PT115"),
    "轴承供回油压差": ("G-104-03", "104PDT182A"), "增压端流量": ("G-104-03", "104FT180A"),
    "膨胀机入口压力": ("G-104-03", ""), "膨胀机出口温度": ("G-104-03", "104TT124"),
    "塔底泵出口压力": ("G-104-04", "104PT201"), "塔底泵入口温度": ("G-104-04", ""),
    "重烃泵出口流量": ("G-102-03", ""), "重烃泵出口压力": ("G-102-03", ""), "重烃泵入口压力": ("G-102-03", ""),
    "污水泵出口压力": ("G-105-05", "105PT131"), "污油泵出口压力": ("G-105-06", "105PT133"),
    "外输泵入口压力": ("G-105-04", "105PT206"), "外输泵出口压力": ("G-105-04", "105PT207"),
    "电流": ("G-105-04", ""), "定子温度": ("G-105-04", "105TE106A"),
}


def build_limits(tables, pts, matcher):
    by_tag = {p["tag"]: p for p in pts}
    mapper = TagMapper(pts)
    limits, mapping = [], []
    seq = [0]

    def eq_of(dcs, name):
        if dcs and dcs in by_tag and by_tag[dcs].get("eq"):
            return by_tag[dcs]["eq"]
        e, _ = matcher.match(name)
        return e

    def add(src, mode, name, unit, sop_tag, dcs, how, ll=None, l=None, nl=None, nh=None, h=None, hh=None, op=None,
            raw="", note="", eq=None):
        seq[0] += 1
        e = eq or eq_of(dcs, name)
        limits.append(dict(id=f"CL{seq[0]:03d}", src=src, mode=mode, name=name, unit=unit, sop_tag=sop_tag, dcs=dcs or "",
                           how=how, LL=ll, L=l, NL=nl, NH=nh, H=h, HH=hh, op=op, raw=raw, note=note, eq=e or ""))

    def mapped(sop_tag, name, strict=True):
        fix = SOP_TAG_FIX.get((sop_tag, name))
        if fix:
            mapping.append((sop_tag, name, fix, by_tag.get(fix, {}).get("desc", ""), "人工指定",
                            "规程位号与点表编号不一致，按名称人工对应" if re.sub(r"\D", "", sop_tag) != re.sub(r"\D", "", fix) else "按名称人工对应"))
            return fix, "人工指定", ""
        p, how, note = mapper.map(sop_tag, name, strict)
        mapping.append((sop_tag, name, p["tag"] if p else "", p["desc"] if p else "", how, note))
        return (p["tag"] if p else ""), how, note

    # 表 2-1～2-10 投运确认
    for ti, (tno, title, mins) in STARTUP_TITLES.items():
        for r in tables[ti][1:]:
            if len(r) < 3 or not r[1] or not r[0].isdigit():
                continue
            name, rng = r[1], r[2]
            lo, hi = parse_range(rng)
            e, dcs = STARTUP_MAP.get(name, (None, ""))
            um = re.search(r"MPa|kPa|kpa|℃|m³/h|m3/h|r/min|t/h|A$", rng)
            add(f"{K.SOP} {tno}", f"开车·{title}（维持 {mins} min）", name, um.group(0) if um else "",
                "", dcs, "人工指定" if dcs else "", nl=lo, nh=hi, raw=rng, eq=e)
    # 2.3 启机界定
    for r in tables[11][1:]:
        if len(r) < 6:
            continue
        _, name, stag, unit, op, rng = r[:6]
        dcs, how, note = mapped(stag, name)
        lo, hi = parse_range(rng)
        add(f"{K.SOP} 2.3 启机界定表", "开车·启机界定", name, unit, stag, dcs, how, nl=lo, nh=hi,
            op=parse_range(op)[0], raw=rng, note=note)
    # 附录二 主要运行参数
    for ti in (38, 39, 40):
        for r in tables[ti][1:]:
            if len(r) < 6 or not r[0].isdigit():
                continue
            _, name, unit, stag, op, rng = r[:6]
            stag = "" if stag.strip("—- ") == "" else stag
            dcs, how, note = mapped(stag, name) if stag else ("", "", "规程未给位号")
            lo, hi = parse_range(rng)
            add(f"{K.SOP} 附录二", "正常运行", name, unit, stag, dcs, how, nl=lo, nh=hi,
                op=parse_range(op)[0] if re.search(r"\d", op) else None, raw=rng,
                note=(note + ("；流程图位置 " + r[6] if len(r) > 6 and r[6] else "")).strip("；"))
    # 附录四 主要控制参数报警联锁值
    for r in tables[45][2:]:
        if len(r) < 9 or not r[1]:
            continue
        _, stag, name, unit, sp, hh, h, l, ll = r[:9]
        dcs, how, note = mapped(stag, name)
        f = lambda x: parse_range(x)[0] if x else None
        add(f"{K.SOP} 附录四", "报警 / 联锁", name, unit, stag, dcs, how, ll=f(ll), l=f(l), h=f(h), hh=f(hh),
            op=f(sp), raw=" / ".join(x for x in (sp, hh, h, l, ll) if x), note=note)
    # 压缩机报警停机值
    for ti in (46, 47, 48):
        for r in tables[ti][2:]:
            if len(r) < 4 or not r[0].isdigit():
                continue
            r = r + [""] * (9 - len(r))
            _, stag, name, unit, n_, l, h, ll, hh = r[:9]
            dcs, how, note = mapped(stag, name, strict=False)
            f = lambda x: parse_range(x)[0] if x and re.search(r"\d", x) else None
            add(f"{K.SOP} 附录四 压缩机报警停机值", "报警 / 停机", name, unit, stag, dcs, how, ll=f(ll), l=f(l), h=f(h), hh=f(hh),
                op=f(n_), raw=" / ".join(x for x in (n_, l, h, ll, hh) if x), note=note, eq="C10201")
    # 膨胀机报警停机
    for r in tables[49][1:]:
        if len(r) < 5 or not r[0]:
            continue
        name, inst, alarm, trip, normal = r[:5]
        l = h = ll = hh = None
        for part in re.split(r"、", alarm):
            v = parse_range(part)
            if re.search(r"[＜<]|小于", part):
                l = v[1]
            elif v[0] is not None:
                h = v[0]
        for part in re.split(r"、", trip):
            v = parse_range(part)
            if re.search(r"[＜<]|小于", part):
                ll = v[1]
            elif v[0] is not None:
                hh = v[0]
        inst1 = re.split(r"[－]", inst)[0].strip()
        base = re.sub(r"A/B.*$", "", inst1) if "A/B" in inst1 else inst1
        for side in ("A", "B"):
            if "A/B" not in inst1 and side == "B":
                continue
            stag = base + side if "A/B" in inst1 else base
            dcs, how, note = mapped(stag, name, strict=False) if re.search(r"\d", base) else ("", "", "")
            add(f"{K.SOP} 附录四 膨胀机报警停机", "报警 / 停机", f"{name}（{'1#' if side == 'A' else '2#'}）", "", inst, dcs, how,
                ll=ll, l=l, h=h, hh=hh, raw=f"报警 {alarm}；联锁 {trip}；正常 {normal}", note=note,
                eq="X10401/1" if side == "A" else "X10401/2")
    # 丙烷机
    for r in tables[50][1:]:
        if len(r) < 4:
            continue
        r = r + [""] * (5 - len(r))
        name, inst, start, alarm, trip = r[:5]
        if not re.search(r"\d", inst):
            inst, start, alarm, trip = "", inst, start, alarm
        a, t = parse_range(alarm), parse_range(trip)
        low = re.search(r"[＜<]", alarm)
        add(f"{K.SOP} 附录四 丙烷机报警停机值", "报警 / 停机", name, "", inst, "", "画面位号，点表无对应命名点",
            l=a[1] if low else None, h=None if low else a[0], ll=t[1] if low else None, hh=None if low else t[0],
            op=parse_range(start)[0], raw=f"启机 {start}；报警 {alarm}；联锁 {trip}", eq="C10402")
    # 导热油炉
    seen = set()
    for r in tables[51][1:]:
        if len(r) < 5 or r[0] in seen:
            continue
        seen.add(r[0])
        name, la, lt, ha, ht = r[:5]
        f = lambda x: parse_range(x)[0] if x and re.search(r"\d", x) else None
        dcs = {"热油出炉温度高": "DRY_TT_CK", "导热油炉出口温度": "DRY_TT_CK", "烟气温度高": "DRY_TT_PY", "排烟温度℃": "DRY_TT_PY",
               "导热油炉出口压力": "DRY_PT_CK", "高位油槽压力（膨胀罐）": "DRY_PT_GWC", "热油流量": "DRY_FT", "氮气压力": "DRY_PT_N2",
               "膨胀罐液位低": "108LT101", "盘管温度1": "DRY_TT_1PG", "盘管温度2": "DRY_TT_2PG", "盘管温度3": "DRY_TT_3PG",
               "盘管温度4": "DRY_TT_4PG", "盘管温度5": "DRY_TT_1CK", "盘管温度6": "DRY_TT_2CK"}.get(name, "")
        add(f"{K.SOP} 附录四 导热油炉报警停机值", "报警 / 停机", name, "", "", dcs, "人工指定" if dcs else "",
            l=f(la), ll=f(lt), h=f(ha), hh=f(ht), raw=" / ".join((la, lt, ha, ht)), eq="H10701" if "膨胀罐" not in name else "D10901")
    # PID 设定范围
    for lp in K.LOOPS:
        tag, name, eqid, pv, op, sp, rng = lp[:7]
        if not rng:
            continue
        lo, hi = parse_range(re.sub(r"（.*?）", "", rng))
        unit = re.sub(r"[\d.～\-\s]|（.*?）", "", rng)
        add(f"{K.SOP} 4.1.1 表4-1", "自动控制·设定值范围", f"{name}设定", unit, tag, pv, "控制回路表", nl=lo, nh=hi,
            op=parse_range(sp)[0] if sp else None, raw=f"设定 {sp}；范围 {rng}", eq=eqid)
    return limits, mapping


def parse_valve_positions(tables):
    start = [r for t in (41, 42) for r in tables[t]]
    stop = [r for t in (43, 44) for r in tables[t]]

    def rows(rs):
        out = {}
        for r in rs:
            if r and r[0].isdigit() and len(r) >= 6:
                out[int(r[0])] = r
        return out
    a, b = rows(start), rows(stop)
    res = []
    for k in sorted(set(a) | set(b)):
        r = a.get(k) or b.get(k)
        res.append((k, r[1], r[2], r[3], r[4], a.get(k, [""] * 6)[5], b.get(k, [""] * 6)[5]))
    return res


def parse_safety_valves(tables, matcher):
    out = []
    alias = [("天然气除油器", "除油器"), ("压缩机厂房压力排污罐", "压缩单元压力排污罐"), ("火炬压力排污罐", "火炬压力排污罐"),
             ("1#干燥器", "A吸附器"), ("2#干燥器", "B吸附器"), ("1#增压机", "1#膨胀机"), ("2#增压机", "2#膨胀机"),
             ("轻烃储罐北", "轻烃储罐"), ("轻烃储罐南", "轻烃储罐"), ("冷冻单元甲醇罐", "冷冻单元甲醇罐"),
             ("1#锅炉", "1#热水锅炉"), ("2#锅炉", "2#热水锅炉"), ("1#油分离器", "丙烷机油气分离器"),
             ("2#油分离器", "丙烷机油气分离器"), ("1#冷凝器", "丙烷冷凝器"), ("2#冷凝器", "丙烷冷凝器"), ("1#蒸发器", "丙烷蒸发器"),
             ("2#蒸发器", "丙烷蒸发器")]
    for t in range(52, 57):
        for r in tables[t]:
            if not r or not r[0].isdigit() or len(r) < 9:
                continue
            site = r[1]
            q = site
            for a, b in alias:
                q = q.replace(a, b)
            eid, kw = matcher.match(q)
            if "1#膨胀机" in q and "泵" in q or "油箱" in q:
                pass
            out.append((int(r[0]), site, r[2], r[3], r[4], r[5], r[6], r[7], r[8], eid or ""))
    return out


def parse_procedures(d, matcher, eq_by_sop):
    rows = []
    heading, chapter, on = "", "", False
    step = 0
    for p in d.paragraphs:
        s = re.sub(r"\s+", " ", p.text).strip()
        if not s:
            continue
        if re.match(r"^第[二三四]章", s):
            on, chapter, heading = True, s, s
            continue
        if s.startswith("附录") and on and len(s) < 20:
            break
        if not on:
            continue
        m = re.match(r"^(\d+(?:\.\d+){1,3})\s*(.*)$", s)
        if m and len(s) < 40 and not re.search(r"[，。；：,;]", s):
            heading, step = s, 0
            continue
        if re.match(r"^(表\d|注意：)", s) and len(s) < 40:
            continue
        m = re.match(r"^[（(](\d+)[）)]\s*(.*)$", s)
        text = m.group(2) if m else s
        if m:
            step = int(m.group(1))
        else:
            m2 = re.match(r"^(\d+(?:\.\d+){2,4})\s*(.*)$", s)
            if m2:
                text, heading2 = m2.group(2), m2.group(1)
                step = heading2
            else:
                step = step + 1 if isinstance(step, int) else 1
        tags = sorted(set(re.findall(r"\b\d{3}[-_]?[A-Z]{1,5}[-_]?\d{2,3}[A-Z]?\b", text)))
        eqs = sorted({eq_by_sop[x] for x in re.findall(r"[A-Z]{1,2}-?\d{4,5}(?:/\d)?", text) if x in eq_by_sop})
        if not eqs:
            e, _ = matcher.match(text)
            eqs = [e] if e else []
        post = "中控" if re.search(r"主控室|控制系统|画面|ME系统|设定", text) else ("现场" if re.search(r"现场|手轮|打开|关闭", text) else "")
        act = next((a for a in ("确认", "检查", "设定", "调整", "打开", "关闭", "启", "停", "汇报", "记录", "排液", "加注", "切换", "投用")
                    if a in text), "")
        rows.append((chapter, heading, step, post, act, text, "、".join(eqs), "、".join(tags)))
    return rows


# ------------------------------------------------------------------------------------------
# 写 Excel
# ------------------------------------------------------------------------------------------
HEAD = PatternFill("solid", fgColor="1F4E78")
HFONT = Font(bold=True, color="FFFFFF")


def sheet(wb, title, header, rows, widths=None, note=None):
    ws = wb.create_sheet(title)
    r0 = 1
    if note:
        ws.cell(1, 1, note).font = Font(italic=True, color="555555")
        r0 = 2
    for j, h in enumerate(header, 1):
        c = ws.cell(r0, j, h)
        c.fill, c.font = HEAD, HFONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(rows, r0 + 1):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, v)
    ws.freeze_panes = ws.cell(r0 + 1, 1)
    ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(header))}{r0 + len(rows)}"
    for j, h in enumerate(header, 1):
        w = (widths or {}).get(h)
        if w is None:
            sample = [len(str(h))] + [len(str(r[j - 1])) for r in rows[:300] if j - 1 < len(r) and r[j - 1] is not None]
            w = min(max(sample) + 2, 60)
        ws.column_dimensions[get_column_letter(j)].width = max(w, 6)
    return ws


def main():
    pts, stats = load_points()
    valves = build_valves(pts)
    matcher = Matcher(K.EQUIPMENT, valves)
    bind_points(pts, matcher, valves)
    d, tables = doc_tables()
    limits, mapping = build_limits(tables, pts, matcher)
    eq_by_sop = {}
    for e in K.EQUIPMENT:
        for s in re.findall(r"[A-Z]{1,2}-?\d{4,5}(?:/\d)?", e["sop_id"] + " " + e["id"]):
            eq_by_sop.setdefault(s, e["id"])
            eq_by_sop.setdefault(s.replace("-", ""), e["id"])
    procs = parse_procedures(d, matcher, eq_by_sop)
    vpos = parse_valve_positions(tables)
    svs = parse_safety_valves(tables, matcher)

    eq_all = {e["id"]: e for e in K.EQUIPMENT}
    names = {e["id"]: e["name"] for e in K.EQUIPMENT}
    names.update({v["id"]: v["name"] for v in valves})
    names.update({g[0]: g[1] for g in K.GROUPS})
    names.update({m[0]: m[1] for m in K.MATERIALS})
    names[K.PLANT["id"]] = K.PLANT["name"]
    unit_name = {u[0]: u[1] for u in K.UNITS}
    screen_name = {s[0]: s[2] for s in K.SCREENS}
    nm = lambda i: f"{i} {names.get(i, '')}".strip() if i else ""
    count = Counter(p["eq"] for p in pts if p["eq"] and not p["spare"])

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # 0 说明
    proc_pts = [p for p in pts if not p["spare"]]
    bound = [p for p in proc_pts if p["eq"]]
    summary = [
        ("名称", "北I-2 深冷装置本体梳理（第一步：只梳理本体，不含前后端代码）"),
        ("装置", f"{K.PLANT['name']}（{K.PLANT['org']}）：{K.PLANT['desc']}"),
        ("数据源", "① DCS 点表（和利时 MACS 导出，控制站 10 / 11）：data/cryo/source/北I-2深冷_DCS点表.xlsx"),
        ("", "② 操作规程 WJ/TRQ/03-09-04（2025.6.13）：data/cryo/source/北I-2装置操作规程_2025.6.13.docx"),
        ("", "③ DCS 流程画面截图：仓库根目录 深冷装置工艺流程图/（44 张）"),
        ("生成", "python3 -m backend.tools.build_cryo_ontology（人工梳理部分在 backend/tools/cryo_knowledge.py，改那里再重新生成）"),
        ("层级口径", "厂 → 装置（= v2 的车间）→ 工艺单元（6 个，= 工艺段）→ DCS 流程画面（= 工序）→ 设备组 / 设备 / 阀门"),
        ("口径", K.AUTHORITY + "；设备编号、台数、位号含义冲突时取画面 / 点表，规程编号只作别名（处理记录见「待确认」）"),
        ("状态口径", "规程 / 点表原文 = 「原文」；按画面、位号或机理推断 = 「草案·待工艺确认」，依据列写明推断方式"),
        ("统计", f"单元 {len(K.UNITS)}；画面 {len(K.SCREENS)}；设备类 {len(K.CLASSES)}；设备组 {len(K.GROUPS)}；"
                 f"设备 / 管线 {len(K.EQUIPMENT)}；阀门 {len(valves)}；物料 {len(K.MATERIALS)}"),
        ("", f"位号 {len(proc_pts)}（另有备用 {len(pts) - len(proc_pts)}），已归属对象 {len(bound)}（{len(bound) * 100 // max(len(proc_pts), 1)}%）；"
             f"控制回路 {len(K.LOOPS)}；工艺限值 {len(limits)}；联锁 {len(K.INTERLOCKS)}；拓扑关系 {len(K.FLOWS)}；"
             f"工艺影响 {len(K.INFLUENCES)}；现象 {len(K.PHENOMENA)}；根因关系 {len(K.CAUSAL)}；规程步骤 {len(procs)}；安全阀 {len(svs)}"),
        ("Sheet 导航", "空间层级 / 画面 / 设备类 / 设备组 / 设备实例 / 阀门 / 部件与结构 / 位号表 / 设备参数 / 控制回路 / 工艺限值 / "
                       "规程位号映射 / 报警点 / 联锁与ESD / 物料与介质 / 物理拓扑 / 工艺影响关系 / 运行工况 / 分子筛程序 / 甲醇加注点 / "
                       "启停车阀位 / 安全阀 / 规程步骤 / 现象(候选) / 根因影响关系 / 能力 / 点表块类型 / 待确认"),
    ]
    sheet(wb, "说明", ["项", "内容"], summary, {"项": 12, "内容": 140})

    # 1 空间层级
    rows = [("装置", K.PLANT["id"], K.PLANT["name"], "", 0, "", K.PLANT["desc"], K.PLANT["basis"])]
    for u in K.UNITS:
        rows.append(("工艺单元", u[0], u[1], K.PLANT["id"], u[2], u[3], u[4], K.SOP + " 1.2"))
    for s in K.SCREENS:
        rows.append(("流程画面", s[0], s[2], s[1] or K.PLANT["id"], "", "", s[4], "截图：" + s[3]))
    for g in K.GLOBAL_SCREENS:
        rows.append(("全局画面", "", g, K.PLANT["id"], "", "", "DCS 顶部导航栏画面（非工艺单元）", "画面导航栏"))
    sheet(wb, "空间层级", ["层级", "编号", "名称", "上级", "顺序", "位号前缀", "说明", "依据"], rows, {"说明": 80})

    # 2 设备类
    sheet(wb, "设备类", ["类名", "上级类", "说明", "设计参数模板"], K.CLASSES, {"说明": 50, "设计参数模板": 60})

    # 3 设备组
    rows = [(g[0], g[1], g[2], g[3] and unit_name.get(g[3]), g[4], g[5],
             sum(1 for e in K.EQUIPMENT if e["group"] == g[0] and e["id"] != g[0])) for g in K.GROUPS]
    sheet(wb, "设备组", ["组编号", "组名称", "设备类", "工艺单元", "画面", "成员说明", "成员数"], rows)

    # 4 设备实例
    rows = []
    for e in K.EQUIPMENT:
        basis = "画面" if e["screen"] else ("点表" if count.get(e["id"]) else "规程（旧版）")
        rows.append((e["id"], e["name"], e["cls"], nm(e["group"]) if e["group"] else "", unit_name.get(e["unit"], ""),
                     ", ".join(screen_name.get(x, x) for x in (e["screen"] or "").split("/") if x), e["sop_id"], e["spec"],
                     count.get(e["id"], 0), e["kw"], e["note"], basis,
                     K.DRAFT if ("推断" in e["note"] or basis.startswith("规程")) else "画面 / 点表"))
    sheet(wb, "设备实例", ["编号", "名称", "设备类", "设备组", "工艺单元", "画面", "规程编号（旧版，别名）", "型号 / 规格（规程）", "关联位号数",
                       "位号匹配关键字", "备注", "依据", "状态"], rows, {"型号 / 规格（规程）": 50, "位号匹配关键字": 40, "备注": 50})

    # 5 阀门
    rows = [(v["id"], v["name"], v["cls"], nm(v["host"]) if v["host"] else "", unit_name.get(v["unit"], ""),
             "、".join(v["tags"]), count.get(v["id"], 0), v["basis"]) for v in valves]
    sheet(wb, "阀门", ["阀门编号", "名称", "阀门类", "作用对象", "工艺单元", "控制块位号", "关联位号数", "依据"], rows)

    # 6 部件与结构
    sheet(wb, "部件与结构", ["主体", "谓词", "客体", "依据"], [(nm(a), b, c, d_) for a, b, c, d_ in K.STRUCTURE], {"客体": 80})

    # 7 位号表
    rows = []
    for p in sorted(pts, key=lambda p: (p["unit_code"] or "~", p["eq"] or "~", p["tag"])):
        rows.append((p["tag"], p["desc"], p["block"], INCLUDED.get(p["block"], ""), p["role"], p["qty"], p["unit"],
                     p["lo"], p["hi"], p["station"], p["unit_code"], unit_name.get(UNIT_OF_CODE.get(p["unit_code"], ""), ""),
                     p["eq"] or "", p["eq_name"], p["param"], p["how"], p["conf"],
                     "备用" if p["spare"] else ("" if p["eq"] else "未归属，待人工确认")))
    sheet(wb, "位号表", ["位号", "点描述", "块类型", "块说明", "变量类别", "物理量", "单位", "量程下限", "量程上限", "控制站",
                      "位号单元", "工艺单元", "所属对象", "对象名称", "参数语义名称", "归属依据", "置信度", "备注"], rows,
          {"块说明": 18, "点描述": 34, "归属依据": 26})

    # 8 设备参数（按对象 + 参数汇总）
    agg = defaultdict(list)
    for p in proc_pts:
        if p["eq"] and p["role"] in ("测量", "测量（通讯）", "阀位反馈", "变频反馈", "计算量", "流量计算", "设定值（通讯）",
                                     "报警开关", "运行状态", "阀位开关反馈", "设备报警", "控制输出", "变频输出", "控制命令",
                                     "回路设定值", "状态 / 报警（通讯）", "ESD / 通讯开关量", "控制回路"):
            agg[(p["eq"], p["param"])].append(p)
    cat = lambda r: ("测量" if r.startswith("测量") or r in ("计算量", "流量计算") else
                     "状态" if r in ("报警开关", "运行状态", "阀位开关反馈", "设备报警", "状态 / 报警（通讯）", "ESD / 通讯开关量", "阀位反馈", "变频反馈") else "控制")
    rows = []
    for (eid, param), ps in sorted(agg.items()):
        roles = sorted({p["role"] for p in ps})
        rows.append((eid, names.get(eid, ""), param, cat(ps[0]["role"]), ps[0]["qty"],
                     next((p["unit"] for p in ps if p["unit"]), ""), "、".join(p["tag"] for p in ps), "、".join(roles), len(ps)))
    sheet(wb, "设备参数", ["对象编号", "对象名称", "参数语义名称", "分类", "物理量", "单位", "DCS 位号", "变量类别", "测点数"], rows,
          {"DCS 位号": 40})

    # 9 控制回路
    rows = [(lp[0], lp[1], nm(lp[2]), lp[3], lp[4], lp[5], lp[6], lp[7], lp[8], lp[9], lp[10], lp[11],
             "规程表 4-1" if lp[7] is not None else "点表 PIDA") for lp in K.LOOPS]
    sheet(wb, "控制回路", ["回路位号", "名称", "被控对象", "测量位号 PV", "输出 / 执行器", "设定值", "设定范围", "比例 P", "积分 I",
                       "微分 D", "作用 / 说明", "现场后备操作", "依据"], rows, {"作用 / 说明": 50})

    # 10 工艺限值
    rows = [(x["id"], nm(x["eq"]), unit_name.get(eq_all.get(x["eq"], {}).get("unit"), ""), x["mode"], x["name"], x["unit"],
             x["sop_tag"], x["dcs"], x["how"], x["LL"], x["L"], x["NL"], x["NH"], x["H"], x["HH"], x["op"], x["raw"], x["src"],
             x["note"], "规程旧版参考·待现场确认") for x in limits]
    sheet(wb, "工艺限值", ["限值编号", "适用对象", "工艺单元", "适用工况", "参数含义", "单位", "规程位号", "DCS 位号", "位号映射方式",
                       "低低限 LL", "低限 L", "正常下限", "正常上限", "高限 H", "高高限 HH", "操作点 / 设定值", "原文", "依据", "备注", "状态"],
          rows, {"原文": 36, "依据": 36, "备注": 40})

    # 11 规程位号映射
    seen = set()
    rows = []
    for m in mapping:
        if (m[0], m[1]) in seen:
            continue
        seen.add((m[0], m[1]))
        rows.append(m + ("待确认" if m[5] or not m[2] else "规则映射",))
    sheet(wb, "规程位号映射", ["规程位号", "规程参数名", "DCS 位号", "DCS 点描述", "映射方式", "说明", "状态"], rows, {"说明": 50})

    # 12 报警点
    lim_by_dcs = defaultdict(list)
    for x in limits:
        if x["dcs"]:
            lim_by_dcs[x["dcs"]].append(x)
    by_tag = {p["tag"]: p for p in pts}
    rows = []
    for p in proc_pts:
        m = re.search(r"_(AH|AL|HH|LL)$", p["tag"])
        if p["block"] == "REAL" and m:
            base = p["tag"][: -3]
            bp = by_tag.get(base, {})
            fld = {"AH": "H", "AL": "L", "HH": "HH", "LL": "LL"}[m.group(1)]
            sop = next((x[fld] for x in lim_by_dcs.get(base, []) if x[fld] is not None), None)
            rows.append((base, bp.get("desc", p["desc"]), nm(p["eq"]), {"AH": "高报", "AL": "低报", "HH": "高高报", "LL": "低低报"}[m.group(1)],
                         p["tag"], sop, "规程附录" if sop is not None else "点表已组态，设定值待 DCS 在线导出"))
        elif p["role"] == "报警开关":
            rows.append((p["tag"], p["desc"], nm(p["eq"]), "开关量报警", p["tag"], None, "现场液位开关等"))
        elif p["role"] == "设备报警":
            rows.append((p["tag"], p["desc"], nm(p["eq"]), "设备综合报警", p["tag"], None, "设备自带控制系统"))
    sheet(wb, "报警点", ["测点位号", "描述", "所属对象", "报警类型", "报警组态点", "设定值（规程）", "来源 / 说明"], rows)

    # 13 联锁与ESD
    sheet(wb, "联锁与ESD", ["编号", "名称", "触发条件", "触发位号", "设定值", "动作", "被控对象", "旁路 / 投切点", "依据"],
          [(i[0], i[1], i[2], i[3], i[4], i[5], nm(i[6]), i[7], i[8]) for i in K.INTERLOCKS], {"动作": 50, "触发位号": 36})

    # 14 物料与介质
    sheet(wb, "物料与介质", ["编号", "名称", "类别", "来源", "去向", "典型工况", "依据"], K.MATERIALS, {"来源": 40, "去向": 50, "典型工况": 50})

    # 15 物理拓扑
    rows = [(nm(a), b, nm(c), m, basis, "草案·待工艺确认" if "推断" in basis else "原文") for a, b, c, m, basis in K.FLOWS]
    sheet(wb, "物理拓扑", ["主体", "谓词", "客体", "介质", "依据", "状态"], rows, {"依据": 50})

    # 16 工艺影响关系
    sheet(wb, "工艺影响关系", ["起始对象 / 参数", "关系", "目标对象 / 参数", "机理说明", "依据", "置信度"], K.INFLUENCES, {"机理说明": 70})

    # 17 运行工况
    sheet(wb, "运行工况", ["编号", "名称", "类别", "适用对象", "进入条件 / 识别", "关键参数", "依据"],
          [(m[0], m[1], m[2], nm(m[3]), m[4], m[5], m[6]) for m in K.MODES], {"进入条件 / 识别": 70, "关键参数": 50})

    # 18 分子筛程序
    ws = sheet(wb, "分子筛程序", ["阶段", "顺序", "时长 (s)", "说明"], [s for s in K.SIEVE_STEPS], {"说明": 70},
               note="程序 FZSKZ（分子筛顺控）；一塔吸附、一塔再生；规程 4.1.3 表 4-2 / 4-3")
    r0 = len(K.SIEVE_STEPS) + 4
    hdr = ["程控阀", "名称", "降压", "热吹", "冷吹", "升压", "并行运行"]
    ws.cell(r0 - 1, 1, "表 4-3：D10301/1 吸附（103-KV101A、102A 开）时 D10301/2 再生的阀位；D10301/2 吸附时 A/B 互换").font = Font(italic=True)
    for j, h in enumerate(hdr, 1):
        c = ws.cell(r0, j, h)
        c.fill, c.font = HEAD, HFONT
    for i, row in enumerate(K.SIEVE_VALVES, r0 + 1):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, v)

    # 19 甲醇加注点
    sheet(wb, "甲醇加注点", ["序号", "加注点", "压差表（DCS 位号）", "正常范围", "阀门位号", "操作点"], K.METHANOL_POINTS,
          note=K.SOP + " 4.2.4.3 表 4-4：压差超过操作点时启甲醇泵、开相应加注阀；甲醇罐 < 10% 或压差明显降低时停")

    # 20 启停车阀位
    sheet(wb, "启停车阀位", ["序号", "介质或用途", "阀门位置或位号", "规格", "数量", "启车状态", "停车状态"], vpos,
          {"阀门位置或位号": 60}, note=K.SOP + " 附录三")

    # 21 安全阀
    sheet(wb, "安全阀", ["序号", "安装部位", "规格型号", "工艺介质", "入口 DN", "出口 DN", "定压值 MPa", "最大操作压力 MPa",
                      "最大工作温度 ℃", "所属对象（按名称匹配）"], svs, note=K.SOP + " 附录五")

    # 22 规程步骤
    sheet(wb, "规程步骤", ["章", "节", "步骤", "岗位（推断）", "动作", "步骤描述", "关联对象", "关联位号"], procs,
          {"节": 36, "步骤描述": 90, "关联对象": 20}, note=K.SOP + " 第二～四章正文（表格内容见控制回路、工艺限值等 sheet）")

    # 23 现象 / 根因
    sheet(wb, "现象(候选)", ["编号", "名称", "挂载对象", "类别", "严重度", "判定规则（文字，待转成规则树）", "关联位号", "依据", "状态"],
          [(p[0], p[1], nm(p[2]), p[3], p[4], p[5], p[6], p[7], K.DRAFT) for p in K.PHENOMENA], {"判定规则（文字，待转成规则树）": 60})
    pn = {p[0]: p[1] for p in K.PHENOMENA}
    sheet(wb, "根因影响关系", ["原因现象", "谓词", "结果现象", "机理说明", "依据", "置信度", "状态"],
          [(f"{a} {pn[a]}", "导致", f"{b} {pn[b]}", m, s, c, K.DRAFT) for a, b, m, s, c in K.CAUSAL], {"机理说明": 60})

    # 24 能力
    sheet(wb, "能力", ["能力ID", "能力名称", "类型", "提供方", "适用对象", "说明", "状态"], K.CAPABILITIES, {"说明": 60})

    # 25 点表块类型
    sheet(wb, "点表块类型", ["块类型（sheet）", "点数", "纳入数", "说明", "处理"], stats)

    # 26 待确认
    issues = list(K.OPEN_ISSUES)
    for m in mapping:
        if m[5] and "名称" in m[5]:
            issues.append(("位号映射", f"规程 {m[0]}「{m[1]}」：{m[5]}", m[0], "限值不挂到该位号", "已按点表"))
    unb = [p for p in proc_pts if not p["eq"] and p["role"] not in ("信号质量", "逻辑量")]
    if unb:
        issues.append(("位号归属", f"{len(unb)} 个位号未归属对象：" + "、".join(p["tag"] for p in unb[:40]) + ("…" if len(unb) > 40 else ""),
                       "位号表", "暂不归属（多为无描述的通讯点）", "待补录点表描述"))
    sheet(wb, "待确认", ["类别", "内容", "涉及对象", "处理（按画面 / 点表口径）", "状态"], issues,
          {"内容": 90, "处理（按画面 / 点表口径）": 50}, note="口径：" + K.AUTHORITY)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"写出 {OUT.relative_to(ROOT)}")
    for s in summary[-3:-1]:
        print(" ", s[1])
    print(f"  未归属位号 {len(unb)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
