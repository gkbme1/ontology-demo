"""数据一致性检查（需求文档第二十三章）。

导入 Excel 时自动校验，生成数据质量报告供前端查看。
检查只报告问题，不修改原始数据。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.services.dcs_loader import DcsDataset
from backend.services.mapping_loader import MappingDataset
from backend.services.relation_excel_loader import RelationDataset
from backend.services.rule_loader import RuleDataset

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def build_quality_report(
    dcs: DcsDataset,
    relations: RelationDataset,
    mapping: MappingDataset,
    rules: RuleDataset,
    matches: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def record(check: str, group: str, description: str, found: list[dict[str, Any]], severity="warning"):
        checks.append(
            {
                "check": check,
                "group": group,
                "description": description,
                "issueCount": len(found),
                "passed": not found,
                "severity": severity,
            }
        )
        for item in found:
            issues.append({"check": check, "group": group, "severity": severity, **item})

    # ------------------------------------------------------- DCS 数据检查

    mismatched = []
    for equip in dcs.equipment.values():
        s1 = equip.get("statsFromSheet1")
        if not s1 or s1.get("totalPoints") is None:
            continue
        if s1["totalPoints"] != equip["stats"]["total"]:
            mismatched.append(
                {
                    "detail": (
                        f"设备「{equip['name']}」Sheet1 声明 {s1['totalPoints']} 点，"
                        f"Sheet2 实际 {equip['stats']['total']} 点"
                    ),
                    "objectId": equip["id"],
                    "objectName": equip["name"],
                    "source": equip.get("statsSource"),
                }
            )
    record("Sheet1 与 Sheet2 点位数量一致性", "DCS 点表", "设备统计声明点数与点位明细实际点数是否一致", mismatched)

    unlinked = [
        {
            "detail": f"Sheet1 第 {r['source']['row']} 行设备「{r['equipmentName']}」未能回指到点位明细中的设备实例",
            "objectName": r["equipmentName"],
            "source": r["source"],
        }
        for r in dcs.stats_rows
        if "equipmentId" not in r
    ]
    record("Sheet1 设备回指点位明细", "DCS 点表", "设备统计中的每台设备是否能在点位明细中找到唯一实例", unlinked, "info")

    empty_equipment = [
        {"detail": f"DCS 点「{t['name']}」生产设备/装置为空", "objectId": t["id"], "source": t["source"]}
        for t in dcs.tags.values()
        if not t["equipmentName"]
    ]
    record("空设备", "DCS 点表", "生产设备/装置字段为空", empty_equipment, "error")

    empty_param = [
        {"detail": f"DCS 点「{t['name']}」参数语义名称为空", "objectId": t["id"], "source": t["source"]}
        for t in dcs.tags.values()
        if not t["parameterName"]
    ]
    record("空参数语义", "DCS 点表", "参数语义名称字段为空", empty_param, "error")

    empty_owl = [
        {"detail": f"DCS 点「{t['name']}」OWL Subject URI 为空", "objectId": t["id"], "source": t["source"]}
        for t in dcs.tags.values()
        if not t["owlSubject"]
    ]
    record("空 OWL Subject", "DCS 点表", "本体三元组主体字段为空", empty_owl, "error")

    dup_tags = [
        {
            "detail": f"DCS 点名「{t['name']}」在点位明细中出现 {1 + len(t['duplicates'])} 次",
            "objectId": t["id"],
            "source": t["source"],
            "extraSources": t["duplicates"],
        }
        for t in dcs.tags.values()
        if t.get("duplicates")
    ]
    record("重复 DCS 点", "DCS 点表", "DCS 点名是否重复", dup_tags, "error")

    by_equipment_name: dict[str, set[str]] = defaultdict(set)
    for equip in dcs.equipment.values():
        by_equipment_name[equip["name"]].add(equip["owlSubject"])
    name_collisions = [
        {
            "detail": f"设备名称「{name}」对应 {len(uris)} 个不同的 OWL Subject：" + "、".join(sorted(uris)[:4]),
            "objectName": name,
        }
        for name, uris in by_equipment_name.items()
        if len(uris) > 1
    ]
    record("同名设备跨工段重复", "DCS 点表", "同一设备名称是否对应多个 OWL Subject（不同工段/控制站）", name_collisions, "info")

    multi_tag_params = [
        {
            "detail": (
                f"设备「{p['equipmentName']}」的参数语义「{p['name']}」绑定了 {p['tagCount']} 个 DCS 点："
                + "、".join(dcs.tags[t]["name"] for t in p["tagIds"] if t in dcs.tags)
            ),
            "objectId": p["id"],
            "objectName": p["name"],
            "source": p["source"],
        }
        for p in dcs.parameters.values()
        if p["tagCount"] > 1
    ]
    record("一个参数语义对应多个 DCS 点", "DCS 点表", "同一设备下参数语义名称重复绑定多个位号", multi_tag_params, "warning")

    # ------------------------------------------------------- 关系 Excel 检查

    for issue in relations.issues:
        issues.append({"group": "工业关系 Excel", **issue})
    for check_name, sev in (("关系 Excel 必填字段为空", "error"), ("权重格式错误", "warning"), ("重复关系", "warning")):
        found = [i for i in relations.issues if i["check"] == check_name]
        checks.append(
            {
                "check": check_name,
                "group": "工业关系 Excel",
                "description": {
                    "关系 Excel 必填字段为空": "工段/关系大类/起止对象/谓词等必填字段是否为空",
                    "权重格式错误": "权重是否为空或非数字",
                    "重复关系": "同工段+同起始对象+同谓词+同目标对象+同子场景是否重复",
                }[check_name],
                "issueCount": len(found),
                "passed": not found,
                "severity": sev,
            }
        )

    direction_ok = all(r["subject"]["entity"] and r["object"]["entity"] for r in relations.relations)
    checks.append(
        {
            "check": "关系方向保持",
            "group": "工业关系 Excel",
            "description": "严格保留 Excel 中的 Subject → Predicate → Object 方向，不因展示需要反转",
            "issueCount": 0 if direction_ok else 1,
            "passed": direction_ok,
            "severity": "error",
        }
    )

    declared = {}
    for row in relations.overview_rows:
        try:
            declared[(row["category"], (row["predicate"] or "").split(" ")[0])] = int(row["declaredCount"])
        except (TypeError, ValueError):
            continue
    actual: dict[tuple[str, str], int] = defaultdict(int)
    for r in relations.relations:
        actual[(r["category"], r["predicate"])] += 1
    overview_mismatch = [
        {
            "detail": f"Overview 声明「{cat} / {pred}」{n} 条，关系明细实际 {actual.get((cat, pred), 0)} 条",
            "objectName": f"{cat}/{pred}",
        }
        for (cat, pred), n in declared.items()
        if actual.get((cat, pred), 0) != n
    ]
    record("关系分类统计一致性", "工业关系 Excel", "Overview Sheet 声明的关系数量与关系明细实际数量是否一致",
           overview_mismatch, "info")

    # ------------------------------------------------------- 对象匹配检查

    unmatched = [
        {
            "detail": f"关系对象「{m['entityName']}」（{m['entityType']}）未匹配到任何 DCS 本体实例，保留为外部关系对象",
            "objectId": m["entityId"],
            "objectName": m["entityName"],
        }
        for m in matches.values()
        if m["matchStatus"] == "UNMATCHED"
    ]
    record("关系对象匹配", "对象匹配", "关系 Excel 中的对象能否匹配到 DCS 设备/参数或人工映射目标", unmatched, "info")

    no_anchor = [
        {
            "detail": f"关系对象「{m['entityName']}」已加载但当前暂无对应 DCS 测点",
            "objectId": m["entityId"],
            "objectName": m["entityName"],
        }
        for m in matches.values()
        if m["tagCount"] == 0
    ]
    record("测量锚点覆盖", "对象匹配", "关系对象是否可建立到 DCS 点的测量锚点", no_anchor, "info")

    pending = [
        {
            "detail": f"关系对象「{m['entityName']}」的映射为人工编制，确认状态为“待现场确认”",
            "objectId": m["entityId"],
            "objectName": m["entityName"],
        }
        for m in matches.values()
        if m["pendingConfirmation"]
    ]
    record("人工映射确认状态", "对象匹配", "人工映射条目是否已由现场确认", pending, "warning")

    for issue in mapping.issues:
        issues.append({"group": "对象映射 Excel", **issue})

    # ------------------------------------------------------- 规则数据源

    checks.append(
        {
            "check": "规则数据源",
            "group": "规则文件",
            "description": "规则必须来自独立规则 Excel / 规则文件",
            "issueCount": 0 if rules.available else 1,
            "passed": rules.available,
            "severity": "info",
        }
    )
    if not rules.available:
        issues.append(
            {
                "check": "规则数据源",
                "group": "规则文件",
                "severity": "info",
                "detail": "未提供规则数据源，规则页显示空状态；系统不会从参数名称自动生成规则。",
            }
        )

    # ------------------------------------------- v2 口径切换带来的新检查

    # 1) DCS 加载过程中自己发现的问题（缺列、编号未登记、设备统计缺编号等）
    for issue in dcs.issues:
        issues.append({"group": "DCS 点表", **issue})
    checks.append({
        "check": "点表工段编号完整性",
        "group": "DCS 点表",
        "description": "点位与设备统计的「工段编号(流程图口径)」是否都能落到工段划分表登记的工段上",
        "issueCount": len(dcs.issues),
        "passed": not dcs.issues,
        "severity": "warning",
    })

    # 2) 同一设备的点位落在多个工段：真实情况，不是错误，但要让使用者知道
    multi_area = [
        {
            "detail": (
                f"设备「{e['name']}」的点位分布在 {len(e['areaIds'])} 个工段："
                + "、".join(f"{c}" for c in e.get("areaCodes", []))
                + f"；主工段取自设备统计表的声明（{e.get('areaCode')}）"
            ),
            "objectId": e["id"],
            "objectName": e["name"],
            "source": e.get("statsSource") or e.get("source"),
        }
        for e in dcs.equipment.values()
        if e.get("areaSpan", 1) > 1
    ]
    record(
        "设备跨工段",
        "DCS 点表",
        "v2 工段按流程图口径划分，一台设备的点位可能落在多个工段（控制站口径下不会出现）",
        multi_area,
        severity="info",
    )

    # 3) 工段编号 S99 的含义在两套文件里不一致
    conflict = []
    spare = dcs.area_by_code.get("S99")
    if spare and dcs.areas.get(spare, {}).get("name") == "备用/未定义点":
        conflict.append({
            "detail": (
                "DCS 点表「工段划分」把 S99 定义为「备用/未定义点」，"
                "而工艺限值与规则文件的「工段取值(参考)」把 S99 写成「跨工段协同」。"
                "同一编号两个含义，建议现场统一（例如给跨工段协同另编一个号）。"
                "在统一之前，本体按各自文件的口径分别解析，不做合并。"
            ),
            "objectId": spare,
            "objectName": "S99",
            "source": dcs.areas[spare].get("source"),
        })
    record("工段编号含义冲突", "工段口径", "同一工段编号在不同数据源里是否指同一件事", conflict, severity="warning")

    # 4) 关系表自带位号解析情况
    unresolved = []
    for rel in relations.relations:
        missing = rel.get("unresolvedTagNames") or []
        if missing:
            unresolved.append({
                "detail": (
                    f"关系 {rel.get('relationCode') or rel['id']}（{rel['subjectEntity']} "
                    f"{rel['predicate']} {rel['objectEntity']}）引用的位号在点表中不存在："
                    + "、".join(missing)
                ),
                "objectId": rel["id"],
                "objectName": rel.get("relationCode"),
                "source": rel["source"],
            })
    record(
        "关系引用的位号可解析",
        "工业关系 Excel",
        "关系明细的「关联DCS位号」与「绑定测点」客体是否都能在 DCS 点表中找到",
        unresolved,
        severity="warning",
    )

    # 5) 关系加载器自己发现的问题（位号被截断等）
    relation_issue_count = 0
    for issue in relations.issues:
        if issue.get("check") == "关联DCS位号被截断":
            issues.append({"group": "工业关系 Excel", **issue})
            relation_issue_count += 1
    checks.append({
        "check": "关联DCS位号完整性",
        "group": "工业关系 Excel",
        "description": "「关联DCS位号」单元格是否被写截断（值以省略号结尾）",
        "issueCount": relation_issue_count,
        "passed": relation_issue_count == 0,
        "severity": "warning",
    })

    # 6) 点表里的标准设备组名称 vs 设备主数据登记的设备组
    known_groups = {g["name"] for g in dcs.equipment_groups.values()}
    stray: dict[str, int] = {}
    for tag in dcs.tags.values():
        label = tag.get("equipmentGroup")
        if label and label not in known_groups:
            stray[label] = stray.get(label, 0) + 1
    record(
        "标准设备组已登记",
        "DCS 点表",
        "点位明细的「标准设备组(本体)」是否都能在「设备主数据」中找到对应设备组",
        [
            {
                "detail": f"点位明细的设备组「{label}」（{count} 个点）未登记在「设备主数据」中，"
                          "按未登记处理，只保留文字标签",
                "objectName": label,
            }
            for label, count in sorted(stray.items(), key=lambda kv: -kv[1])
        ],
        severity="info",
    )

    empty_groups = [
        {
            "detail": f"设备组「{g['name']}」在点位明细中没有对应点位（声明 {g['tagCountDeclared']} 点）",
            "objectId": g["id"],
            "objectName": g["name"],
            "source": g["source"],
        }
        for g in dcs.equipment_groups.values()
        if not g["tagIds"]
    ]
    record("设备组已落到点位", "DCS 点表", "「设备主数据」登记的设备组是否都能在点位明细中找到点位", empty_groups, severity="info")

    # 7) 画面与点表差异：现场待确认清单，原样透出
    record(
        "流程画面与点表差异",
        "DCS 点表",
        "「画面与点表差异」Sheet 中现场尚未确认的不一致项",
        [
            {
                "detail": f"{row.get('tag')}（{row.get('screen')}）：{row.get('impact') or '需现场确认'}",
                "objectName": row.get("tag"),
                "source": row.get("source"),
            }
            for row in dcs.screen_diff_rows
            if not row.get("confirmed")
        ],
        severity="info",
    )

    record(
        "画面可见但点表未收录",
        "DCS 点表",
        "「画面补充测点」Sheet 中建议补录的位号",
        [
            {
                "detail": f"{row.get('tag')}（{row.get('screen')}）：{row.get('meaning') or ''}，状态 {row.get('status') or '待补录'}",
                "objectName": row.get("tag"),
                "source": row.get("source"),
            }
            for row in dcs.screen_extra_rows
        ],
        severity="info",
    )

    issues.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity", "info"), 3))
    summary = {
        "checkCount": len(checks),
        "passedCount": len([c for c in checks if c["passed"]]),
        "issueCount": len(issues),
        "errorCount": len([i for i in issues if i.get("severity") == "error"]),
        "warningCount": len([i for i in issues if i.get("severity") == "warning"]),
        "infoCount": len([i for i in issues if i.get("severity") == "info"]),
    }
    return {"summary": summary, "checks": checks, "issues": issues}
