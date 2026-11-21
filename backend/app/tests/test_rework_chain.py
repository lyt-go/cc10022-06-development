"""补值返工链路测试：质量检查 → 返工视图 → 补记重算 → 复验关闭 → 旧报告回查。"""
from __future__ import annotations

import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.seed import SEED_ROWS
from app.services.field_cleanse import FieldCleanseService
from app.services.mdm_quality import MdmQualityService
from app.services.quality_rework import QualityReworkService
from app.store import store


def reset_store() -> None:
    """每个用例从种子数据重新起跑，避免跨用例的返工事项互相污染。"""
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}


def customer_rows():
    return [dict(row) for row in store.rows("source_record")
            if row.get("实体模型") == "customer"]


def run_initial_check(report_id: str = "RPT-OLD"):
    quality = MdmQualityService()
    return quality.compute_quality_metrics(
        "customer", customer_rows(), ["姓名", "电话", "邮箱"], report_id=report_id)


def test_view_splits_verified_and_unverified_partitions():
    """返工视图要展示已核分区、未核分区和可派发字段。"""
    reset_store()
    run_initial_check()
    view = QualityReworkService().rework_view("customer")

    status_by_partition = {p["分区"]: p["分区状态"] for p in view["partitions"]}
    assert status_by_partition["CRM分区"] == "已核分区"
    assert status_by_partition["ERP分区"] == "已核分区"
    # CRM 样本返回后客服源部分采集失败，这些分区只能作为证据，不能派发
    assert status_by_partition["客服分区"] == "未核分区"

    verified_records = {r for group in view["dispatchable_fields"] for r in group["来源记录"]}
    assert "CRM-41" in verified_records
    assert "CS-11" not in verified_records and "CS-12" not in verified_records

    dispatchable_fields = {group["字段"] for group in view["dispatchable_fields"]}
    assert dispatchable_fields == {"电话", "邮箱"}
    assert view["summary"]["可派发"] == 3
    assert view["summary"]["未核分区待办"] == 2


def test_same_round_dedup_by_source_record_and_field():
    """同一轮重复产出的明细按来源记录 + 字段去重。"""
    reset_store()
    quality = MdmQualityService()
    records = customer_rows()
    first = quality.compute_quality_metrics(
        "customer", records, ["姓名", "电话", "邮箱"], report_id="RPT-DUP")
    assert first["rework"]["新增明细"] == 5

    second = quality.compute_quality_metrics(
        "customer", records + records, ["姓名", "电话", "邮箱"], report_id="RPT-DUP")
    assert second["rework"]["新增明细"] == 0
    assert second["rework"]["同轮去重"] == 5
    assert len(store.rows("quality_rework")) == 5
    assert second["round"] == first["round"] == 1


def test_closed_item_not_reopened_by_late_old_report():
    """已补齐的电话不能因旧报告迟到又进入待办。"""
    reset_store()
    quality = MdmQualityService()
    cleanse = FieldCleanseService()
    stale_records = customer_rows()

    run_initial_check("RPT-OLD")
    rework_service = QualityReworkService()
    assert rework_service.update_source_record("CRM-41", "电话", "13800000041")["ok"]

    closed = cleanse.revalidate_rework_items("customer")
    assert closed["closed"] == 1
    assert closed["closed_ids"] == [1]

    # 重送一份在补值之前生成的旧报告
    resent = quality.compute_quality_metrics(
        "customer", stale_records, ["姓名", "电话", "邮箱"], report_id="RPT-OLD")
    assert resent["round"] == 1
    assert resent["rework"]["跳过已关闭"] == 1
    crm41 = [row for row in store.rows("quality_rework") if row["来源记录"] == "CRM-41"][0]
    assert crm41["状态"] == "已关闭"
    assert crm41["可派发"] is False
    assert "CRM-41" not in {
        item["来源记录"] for item in rework_service.rework_view("customer")["items"]
        if item["可派发"]
    }


def test_supplement_recompute_trace_matches():
    """从 CRM-41 的电话进入返工名单，到补记号码再重算，原始数据和待补字段相符。"""
    reset_store()
    quality = MdmQualityService()
    rework_service = QualityReworkService()
    cleanse = FieldCleanseService()

    run_initial_check("RPT-OLD")
    item = [row for row in store.rows("quality_rework")
            if row["来源记录"] == "CRM-41" and row["字段"] == "电话"][0]
    traced = rework_service.trace_item(item["id"])
    assert traced["待补字段"] == "电话"
    assert traced["原始值"] == ""
    assert traced["原始数据"]["姓名"] == "张三"
    assert traced["原始数据"]["来源记录"] == "CRM-41"
    assert traced["原始数据"]["采集分区"] == "CRM分区"

    rework_service.update_source_record("CRM-41", "电话", "13800000041")
    cleanse.revalidate_rework_items("customer")
    quality.recompute_quality_check(
        "customer", ["姓名", "电话", "邮箱"], report_id="RPT-OLD")

    after = rework_service.trace_item(item["id"])
    assert after["原始值"] == ""             # 原始快照保留发现时的证据
    assert after["当前字段值"] == "13800000041"
    assert after["状态"] == "已关闭"
    assert after["可派发"] is False


def test_dispatch_rejects_unverified_and_closed():
    """派发只接受已核分区、待派发且未关闭的事项。"""
    reset_store()
    run_initial_check()
    rework_service = QualityReworkService()
    items = {row["来源记录"]: row for row in store.rows("quality_rework")}

    blocked = rework_service.dispatch_items([items["CS-11"]["id"]], "客服组")
    assert blocked["dispatched_count"] == 0
    assert "未核验" in blocked["rejected"][0]["reason"]

    ok = rework_service.dispatch_items([items["CRM-43"]["id"]], "数据组-王敏")
    assert ok["dispatched_count"] == 1
    assert ok["dispatched"][0]["负责人"] == "数据组-王敏"

    again = rework_service.dispatch_items([items["CRM-43"]["id"]], "数据组-王敏")
    assert again["dispatched_count"] == 0


def test_report_lookup_keeps_completed_items():
    """已完成事项在重送旧报告后可回查。"""
    reset_store()
    quality = MdmQualityService()
    cleanse = FieldCleanseService()
    rework_service = QualityReworkService()
    stale_records = customer_rows()

    run_initial_check("RPT-OLD")
    rework_service.update_source_record("CRM-41", "电话", "13800000041")
    cleanse.revalidate_rework_items("customer")
    quality.compute_quality_metrics(
        "customer", stale_records, ["姓名", "电话", "邮箱"], report_id="RPT-OLD")

    report = rework_service.report_rework("RPT-OLD")
    closed_ids = {item["返工编号"] for item in report["closed_items"]}
    assert closed_ids == {"RW-00001"}
    assert report["reports"][0]["重送次数"] == 1
    assert report["items"]


def test_field_cleanse_revalidate_only_closes_filled_fields():
    """字段标准化清洗复验改过的原始行，只关闭真的补齐的字段。"""
    reset_store()
    run_initial_check()
    cleanse = FieldCleanseService()
    result = cleanse.revalidate_rework_items(
        "customer",
        records=[{"来源记录": "CRM-41", "电话": ""}],
    )
    assert result["closed"] == 0
    assert result["still_open"] == 5

    result = cleanse.revalidate_rework_items(
        "customer",
        records=[{"来源记录": "CRM-41", "电话": "13800000041"}],
    )
    assert result["closed"] == 1
    assert result["closed_ids"] == [1]
    item = store.find("quality_rework", 1)
    assert item["复验值"] == "13800000041"
    assert item["关闭方式"] == "字段复验"


def test_stale_report_does_not_roll_back_round():
    """迟到的旧报告不会把事项退回更早的轮次。"""
    reset_store()
    quality = MdmQualityService()
    fresh = quality.compute_quality_metrics(
        "customer", customer_rows(), ["姓名", "电话", "邮箱"],
        round_no=2, report_id="RPT-NEW")
    assert fresh["round"] == 2
    item = [row for row in store.rows("quality_rework") if row["来源记录"] == "CRM-41"][0]
    assert item["最近轮次"] == 2

    stale = quality.compute_quality_metrics(
        "customer", customer_rows(), ["姓名", "电话", "邮箱"],
        round_no=1, report_id="RPT-OLDER")
    assert stale["round"] == 1
    assert stale["rework"]["跳过旧报告"] == 5
    assert item["最近轮次"] == 2
    assert item["首次轮次"] == 1 or item["首次轮次"] == 2


if __name__ == "__main__":
    tests = [
        ("返工视图分区拆分", test_view_splits_verified_and_unverified_partitions),
        ("同轮按来源记录+字段去重", test_same_round_dedup_by_source_record_and_field),
        ("旧报告不重开已补齐", test_closed_item_not_reopened_by_late_old_report),
        ("补记重算追溯相符", test_supplement_recompute_trace_matches),
        ("派发拒绝未核与已关闭", test_dispatch_rejects_unverified_and_closed),
        ("旧报告可回查已完成", test_report_lookup_keeps_completed_items),
        ("复验只关闭已补齐字段", test_field_cleanse_revalidate_only_closes_filled_fields),
        ("迟到旧报告不回退轮次", test_stale_report_does_not_roll_back_round),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001 - 测试入口需要打印全部失败
            print(f"  FAIL: {name} -> {exc}")
            failed += 1
    print(f"\n结果: {passed}/{len(tests)} 通过, {failed} 失败")
    assert failed == 0, f"{failed} 条返工链路测试失败！"
