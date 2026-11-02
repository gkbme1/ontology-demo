"""报警处置规程自测（不需要单独启动服务）。

    python3 -m tests.test_procedures

1. 骨架：每张卡都有触发位号与可能原因，只由本体推导；处置步骤只含确认判断阶段，禁止操作留空待补充；
2. 锚定：卡片里的位号、工艺量、设备都对应到本体对象；对应不上的标「待确认」而不是硬对（用模板里其他项目的示例验证）；
3. 方向：只对「正向影响」推偏高 / 偏低，「负向影响」不推方向（关系表中负向影响有时指不利影响）；
4. 挂接：设备 / 工段档案带出相关处置卡；HTTP 接口可用；数据源清单里有处置规程。
"""
from __future__ import annotations

import sys

from backend.ontology.indexes import OntologyStore
from backend.services import asset_model as am
from backend.services import procedure_model as pm
from backend.tools.build_procedure_skeleton import TEMPLATE_FILE

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    store = OntologyStore()
    ps = store.procedures

    print("[骨架]")
    cards = list(ps.cards.values())
    check(ps.available and len(cards) >= 30 and not ps.issues, f"{pm.PROCEDURE_FILE_NAME} 加载 {len(cards)} 张处置卡，无引用错误")
    check(all(c["trigger"]["tags"] and c["causes"] for c in cards), "每张卡都有触发位号与可能原因")
    check(all(c["status"].startswith("草案") for c in cards), "由本体推导的卡全部标草案，待工艺确认")
    check(all(s["phase"] == "确认判断" for c in cards for s in c["steps"]) and not any(c["forbidden"] for c in cards),
          "只生成确认判断步骤，真实处置步骤与禁止操作不编造")
    card = ps.cards["ARP-S11-01"]
    check(card["trigger"]["limits"][0]["id"] == "PL001" and "TI_1301A" in [t["text"] for t in card["trigger"]["tags"]],
          f"{card['id']} {card['name']}：关联限值 PL001，触发位号含 TI_1301A")
    check(any(c["category"] == "仪表" and "假报警" in c["description"] for c in card["causes"])
          and any(c["category"] == "设备" for c in card["causes"]), "原因含测点本身（假报警）与控制回路执行机构")
    check("R-S11-01" in card["consequence"]["text"] and "33.0～35.0" in card["clearCondition"],
          "后果引用规则 R-S11-01，解除条件取限值正常区间")

    print("\n[方向]")
    texts = [c["description"] for c in cards for c in c["causes"]]
    check(not any("6-APA热降解损失率降低" in c["consequence"]["text"] for c in cards),
          "不把「负向影响」当成反向变化（超温不会写成降解损失率降低）")
    check(any("偏高（" in t for t in texts), "正向影响推出偏高 / 偏低的原因")

    print("\n[锚定]")
    refs = [r for c in cards for r in pm._all_refs(c)]
    check(refs and all(r["status"] == pm.ANCHOR_OK for r in refs), f"骨架里 {len(refs)} 处名称全部对应到本体")
    check(all(c["autoCheck"] == any(t["status"] == pm.ANCHOR_OK for t in c["verifyTags"]) for card in cards for c in card["causes"]),
          "验证位号已对应的原因标为可自动验证")
    foreign = pm.load_procedures(TEMPLATE_FILE, store)
    ex = foreign.cards["ARP-001"]
    pend = [r["text"] for r in pm._all_refs(ex) if r["status"] == pm.ANCHOR_PENDING]
    check("PI_039006" in pend and "次高压锅炉给水泵" in pend and ex["summary"]["autoCauseCount"] == 0,
          f"其他项目的示例卡对应不上 6-APA 本体，标待确认（{len(pend)} 处），不硬对")
    check(len(ex["steps"]) == 7 and len(ex["forbidden"]) == 2 and {s["role"] for s in ex["steps"]} >= {"中控主操", "外操", "班长"},
          "模板示例完整表达了自然语言规程：7 个步骤、岗位、2 条禁止操作")

    print("\n[挂接]")
    tank = store.dcs.equipment_by_owl(":Dev_13_水解罐A")
    p = am.profile(store, tank["id"])
    trig = [c for c in p["procedures"] if c["relation"] == "触发"]
    check(any(c["id"] == "ARP-S11-01" for c in trig), f"水解罐A 档案带出 {len(trig)} 张由它触发的处置卡")
    area = am.profile(store, "area-S11")["procedures"]
    check(area and all(c["area"]["id"] == "area-S11" for c in area if c["relation"] == "本工段"), f"工段 S11 档案列出本工段 {len(area)} 张卡")
    try:
        from fastapi.testclient import TestClient

        from backend import main as app_module
    except Exception as exc:  # pragma: no cover
        check(False, f"无法加载应用：{exc}")
        return 1
    app_module._store = store
    client = TestClient(app_module.app)
    check(client.get("/api/ontology/procedures").json()["total"] == len(cards), "/api/ontology/procedures 列出全部处置卡")
    check(client.get("/api/ontology/procedures/ARP-S11-01").json()["name"] == card["name"]
          and client.get("/api/ontology/procedures/NOPE").status_code == 404, "单张卡接口可用，未知卡 404")
    check(client.get(f"/api/ontology/{tank['id']}/procedures").json()["total"] == len(p["procedures"]), "对象相关处置卡接口可用")
    sources = client.get("/api/ontology/data-sources").json()["sources"]
    check(any(s["file"] == pm.PROCEDURE_FILE_NAME and s["available"] for s in sources), "数据源清单里有处置规程")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
