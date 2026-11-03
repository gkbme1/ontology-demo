"""生成能力登记表 data/source/6APA_能力.xlsx（预填版）。

    python3 -m backend.tools.build_capability_table          # 生成（已存在时不覆盖）
    python3 -m backend.tools.build_capability_table --force  # 覆盖为预填版，人工修改会丢失

预填内容只登记本体服务实际在用的外部接口：实时库、历史库，标「已登记」；
启停、调节、规则诊断、模型预测只写能力描述与参数，提供方接口未知，标「待登记」，不虚构端点。
Agent 的分析工具 / 计算模块是本体的使用方，不是能力提供方，不登记在这里。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.services import capability_loader as cl  # noqa: E402

OUT_FILE = ROOT / "data" / "source" / cl.CAPABILITY_FILE_NAME

ALL = "设备、设备组、工段、工艺对象"

CAPABILITIES = [
    {
        "能力ID": "CAP-001", "能力名称": "实时值查询", "能力类型": "数据·时序",
        "能力描述": "读取对象相关测点的当前值、质量码与时间戳",
        "适用对象": ALL, "适用设备类型": "",
        "提供方": "实时数据库 HSM（当前由模拟 DCS 服务代替）", "调用方式": "REST · POST",
        "端点": "{RTDB_BASE_URL}/api/hsm-db-rtserver/v1/rtdata/node/read",
        "本体代调入口": "GET /api/ontology/{id}/realtime",
        "输出": "data[]：nodeId、v（值）、q（质量，1 好 / 0 坏）、t（毫秒时间戳）",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "单次最多 500 个 nodeId，超出由调用方分批；本体代调入口会自动解析对象的位号并分批",
    },
    {
        "能力ID": "CAP-002", "能力名称": "历史值查询", "能力类型": "数据·时序",
        "能力描述": "读取对象相关测点在时间窗内的历史曲线（插值 / 原始 / 统计）",
        "适用对象": ALL, "适用设备类型": "",
        "提供方": "历史数据库 timing-svc（当前由模拟 DCS 服务代替）", "调用方式": "REST · POST",
        "端点": "{HISTORIAN_BASE_URL}/api/timing-svc/v1/history/findAll",
        "本体代调入口": "GET /api/ontology/{id}/history?startTime=…&endTime=…",
        "输出": "data[]：nodeId、values[]（时间、值）、hasMore",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "时间为毫秒时间戳；本体代调入口另接受 yyyy-MM-dd HH:mm:ss",
    },
    {
        "能力ID": "CAP-007", "能力名称": "罐批次查询", "能力类型": "数据·批次",
        "能力描述": "查询设备的罐批次：批号、换酶后批次数、批次与反应起止、各阶段起止",
        "适用对象": "设备", "适用设备类型": "固定化酶反应罐",
        "提供方": "电子批记录 EBR（当前由模拟服务代替）", "调用方式": "REST · GET",
        "端点": "{EBR_BASE_URL}/api/ebr/v1/batches",
        "本体代调入口": "GET /api/ontology/{id}/batches?startTime=…&endTime=…",
        "输出": "items[]：batchNo、enzymeBatchCount、enzymeLot、status、startTime、reactionStart、reactionEnd、phases[]",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "调查时间窗以罐批次的反应起止为准；EBR 分批上线，未就绪时按工序与阶段表的 DCS 条件推断",
    },
    {
        "能力ID": "CAP-008", "能力名称": "班次查询", "能力类型": "数据·排班",
        "能力描述": "查询时间段内的班次与班组（MOM worktrans）",
        "适用对象": "设备、设备组、工段", "适用设备类型": "",
        "提供方": "MOM 排班 worktrans（当前由模拟服务代替）", "调用方式": "REST · GET",
        "端点": "{MOM_BASE_URL}/api/mom/v1/worktrans",
        "本体代调入口": "GET /api/ontology/shifts?startTime=…&endTime=…",
        "输出": "items[]：date、shift、team、startTime、endTime",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "异常调查精确到班次，结合操作记录定位人为原因",
    },
    {
        "能力ID": "CAP-009", "能力名称": "化验结果查询", "能力类型": "数据·化验",
        "能力描述": "查询设备的化验结果（LIMS 与人工录入）：项目、取样时间、报告时间、结果、对应批次",
        "适用对象": "设备", "适用设备类型": "固定化酶反应罐",
        "提供方": "LIMS（当前由模拟服务代替）", "调用方式": "REST · GET",
        "端点": "{LIMS_BASE_URL}/api/lims/v1/results",
        "本体代调入口": "GET /api/ontology/{id}/lab-results?startTime=…&endTime=…&item=…",
        "输出": "items[]：sampleNo、itemCode、itemName、value、sampleTime、reportTime、batchNo、source、property",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "化验与 DCS 存在时间差，按取样时间对齐；化验项目与工艺属性的对应见 6APA_调查知识.xlsx「化验项目」",
    },
    {
        "能力ID": "CAP-010", "能力名称": "化验结果录入", "能力类型": "数据·录入",
        "能力描述": "人工录入化验结果并写入 LIMS，化验员只录一遍，调查与台账共用",
        "适用对象": "设备", "适用设备类型": "固定化酶反应罐",
        "提供方": "LIMS（当前由模拟服务代替）", "调用方式": "REST · POST",
        "端点": "{LIMS_BASE_URL}/api/lims/v1/results",
        "本体代调入口": "POST /api/ontology/{id}/lab-results",
        "输出": "created：录入的化验记录（含所属批次）",
        "前置条件": "化验项目须在本体登记", "登记状态": cl.STATUS_REGISTERED,
        "说明": "录入人必填；取样时间不填按当前时间",
    },
    {
        "能力ID": "CAP-011", "能力名称": "操作记录查询", "能力类型": "数据·事件",
        "能力描述": "查询设备的操作记录：设定值修改、手自动切换，前后值、时间、操作站、班次",
        "适用对象": "设备", "适用设备类型": "固定化酶反应罐",
        "提供方": "DCS 操作日志（当前由模拟服务代替）", "调用方式": "REST · GET",
        "端点": "{OPLOG_BASE_URL}/api/dcs/v1/oplog",
        "本体代调入口": "GET /api/ontology/{id}/operations?startTime=…&endTime=…",
        "输出": "items[]：time、kind、tag、param、oldValue、newValue、station、shift、properties",
        "前置条件": "", "登记状态": cl.STATUS_REGISTERED,
        "说明": "用于「人」这一类候选原因：人为修改设定值与参数偏离的时序关系",
    },
    {
        "能力ID": "CAP-003", "能力名称": "启停 / 开关", "能力类型": "动作",
        "能力描述": "对设备下发启动 / 停止或阀门开 / 关指令",
        "适用对象": "设备", "适用设备类型": "",
        "提供方": "OPAS 动作程序（接口待登记）", "调用方式": "待定", "端点": "", "本体代调入口": "",
        "输出": "指令执行结果与回读状态",
        "前置条件": "需人工确认；设备处于远控；不违反报警联锁约束", "登记状态": cl.STATUS_PENDING,
        "说明": "本体只登记能力与参数绑定，不直接下发控制指令",
    },
    {
        "能力ID": "CAP-004", "能力名称": "调节", "能力类型": "动作",
        "能力描述": "设定调节阀开度、变频频率等控制输出",
        "适用对象": "设备", "适用设备类型": "",
        "提供方": "OPAS 动作程序（接口待登记）", "调用方式": "待定", "端点": "", "本体代调入口": "",
        "输出": "设定结果与反馈值",
        "前置条件": "需人工确认；设定值在工艺限值范围内", "登记状态": cl.STATUS_PENDING,
        "说明": "本体只登记能力与参数绑定，不直接下发控制指令",
    },
    {
        "能力ID": "CAP-005", "能力名称": "规则诊断", "能力类型": "诊断",
        "能力描述": "对对象执行适用的推理规则，给出诊断结论",
        "适用对象": "设备、设备组、工段", "适用设备类型": "",
        "提供方": "推理引擎（接口待登记）", "调用方式": "待定", "端点": "", "本体代调入口": "",
        "输出": "命中的规则、结论与严重程度",
        "前置条件": "", "登记状态": cl.STATUS_PENDING,
        "说明": "规则本身来自 6APA_规则.xlsx",
    },
    {
        "能力ID": "CAP-006", "能力名称": "机理 / 时序模型预测", "能力类型": "模型",
        "能力描述": "用注册的机理或时序模型预测对象的关键工艺量",
        "适用对象": "设备、设备组", "适用设备类型": "",
        "提供方": "模型平台（接口待登记）", "调用方式": "待定", "端点": "", "本体代调入口": "",
        "输出": "预测值及置信区间",
        "前置条件": "", "登记状态": cl.STATUS_PENDING,
        "说明": "模型注册表尚无数据源",
    },
]

PARAMETERS = [
    ("CAP-001", "nodeIds", "string[]", "是", "实时库节点 ID", "本对象位号→nodeId"),
    ("CAP-002", "nodeIds", "string[]", "是", "历史库节点 ID", "本对象位号→nodeId"),
    ("CAP-002", "startTime", "integer", "是", "开始时间，毫秒时间戳", "调用方提供"),
    ("CAP-002", "endTime", "integer", "是", "结束时间，毫秒时间戳", "调用方提供"),
    ("CAP-002", "sampleMode", "string", "否", "interpolated / raw / avg / max / min", "常量:interpolated"),
    ("CAP-002", "interval", "integer", "否", "采样间隔，毫秒", "调用方提供"),
    ("CAP-002", "limit", "integer", "否", "最多返回点数", "调用方提供"),
    ("CAP-007", "unit", "string", "是", "设备名称", "本对象名称"),
    ("CAP-007", "startTime", "integer", "否", "开始时间，毫秒时间戳；默认 3 天前", "调用方提供"),
    ("CAP-007", "endTime", "integer", "否", "结束时间，毫秒时间戳；默认当前", "调用方提供"),
    ("CAP-008", "startTime", "integer", "否", "开始时间", "调用方提供"),
    ("CAP-008", "endTime", "integer", "否", "结束时间", "调用方提供"),
    ("CAP-009", "unit", "string", "是", "设备名称", "本对象名称"),
    ("CAP-009", "startTime", "integer", "否", "开始时间（按取样时间）", "调用方提供"),
    ("CAP-009", "endTime", "integer", "否", "结束时间", "调用方提供"),
    ("CAP-009", "item", "string", "否", "化验项目编码，如 PH", "调用方提供"),
    ("CAP-010", "unit", "string", "是", "设备名称", "本对象名称"),
    ("CAP-010", "itemCode", "string", "是", "化验项目编码", "调用方提供"),
    ("CAP-010", "value", "number", "是", "化验结果", "调用方提供"),
    ("CAP-010", "sampleTime", "string", "否", "取样时间", "调用方提供"),
    ("CAP-010", "enteredBy", "string", "是", "录入人", "调用方提供"),
    ("CAP-011", "unit", "string", "是", "设备名称", "本对象名称"),
    ("CAP-011", "startTime", "integer", "否", "开始时间", "调用方提供"),
    ("CAP-011", "endTime", "integer", "否", "结束时间", "调用方提供"),
    ("CAP-003", "target", "string", "是", "启停 / 开关指令点位号", "本对象位号[启停]→位号"),
    ("CAP-003", "command", "string", "是", "启动 / 停止，或 开 / 关", "调用方提供"),
    ("CAP-004", "target", "string", "是", "调节输出点位号", "本对象位号[调节]→位号"),
    ("CAP-004", "value", "number", "是", "设定值（开度 % 或频率 Hz）", "调用方提供"),
    ("CAP-005", "objectId", "string", "是", "诊断对象", "本对象ID"),
    ("CAP-005", "ruleIds", "string[]", "是", "要执行的规则", "本对象适用规则"),
    ("CAP-006", "inputs", "string[]", "是", "模型输入测点", "本对象位号[过程测量]→nodeId"),
    ("CAP-006", "horizon", "integer", "否", "预测时长，分钟", "调用方提供"),
]

NOTES = [
    ("定位", "本体挂载的能力 = 能力描述 + 调用契约 + 本对象参数绑定。能力由外部系统实现，本体不实现、不代为下发控制指令。"),
    ("能力", "一行一个能力。适用对象可填 设备 / 设备组 / 工段 / 工艺对象（顿号分隔）；适用设备类型留空表示不限。"),
    ("端点", "可写 {RTDB_BASE_URL} / {HISTORIAN_BASE_URL} / {EBR_BASE_URL} / {MOM_BASE_URL}，按本体服务配置展开。本体代调入口里的 {id} 换成对象 ID。"),
    ("登记状态", "已登记：提供方接口已知、可调用；待登记：只声明能力与参数，提供方接口待补。"),
    ("能力参数", "一行一个参数。绑定写法：本对象位号、本对象位号[过程测量|状态|启停|调节]、后缀 →nodeId 或 →位号、本对象ID、本对象名称、本对象适用规则、调用方提供、常量:xxx。"),
    ("适用判断", "必填参数的绑定在对象上取不到值（如对象没有启停指令点）时，该能力不适用于这个对象，档案里不显示。"),
    ("不登记", "Agent 的分析工具与计算模块是本体的使用方，不是能力提供方，不登记在本表。越限判断属于本体的运行约束校验，见档案的「约束」部分。"),
]


def _style(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "C2"


def main() -> int:
    if OUT_FILE.exists() and "--force" not in sys.argv:
        print(f"{OUT_FILE.name} 已存在，未覆盖（覆盖为预填版请加 --force）")
        return 0
    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        pd.DataFrame(CAPABILITIES, columns=cl.CAP_COLUMNS).to_excel(writer, sheet_name=cl.SHEET_CAPS, index=False)
        pd.DataFrame(PARAMETERS, columns=cl.PARAM_COLUMNS).to_excel(writer, sheet_name=cl.SHEET_PARAMS, index=False)
        pd.DataFrame(NOTES, columns=["项目", "说明"]).to_excel(writer, sheet_name="说明", index=False)
        _style(writer.sheets[cl.SHEET_CAPS], [9, 16, 10, 36, 24, 14, 34, 12, 56, 40, 44, 34, 9, 44])
        _style(writer.sheets[cl.SHEET_PARAMS], [9, 12, 10, 6, 30, 28])
        notes = writer.sheets["说明"]
        notes.column_dimensions["A"].width = 12
        notes.column_dimensions["B"].width = 120
    registered = sum(1 for c in CAPABILITIES if c["登记状态"] == cl.STATUS_REGISTERED)
    print(f"已生成 {OUT_FILE.relative_to(ROOT)}：{len(CAPABILITIES)} 项能力（已登记 {registered}，"
          f"待登记 {len(CAPABILITIES) - registered}），{len(PARAMETERS)} 个参数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
