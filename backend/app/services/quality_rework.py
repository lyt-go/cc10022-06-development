"""补值返工领域服务：质量检查缺字段证据的派发视图与原始记录追溯。

视图按采集分区拆成“已核分区 / 未核分区”，只把已核分区里
待补的字段列为可派发事项；未核分区保留证据但不派发。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services import rework as rework_rules
from app.store import store


class QualityReworkService(BaseModuleService):
    MODULE = rework_rules.REWORK_MODULE
    ENTITY = "补值返工明细"
    OPERATION_TERM = "派发"
    LIST_FIELDS = [
        "返工编号", "统计编号", "实体模型", "来源系统", "来源记录",
        "字段", "分区", "分区状态", "负责人", "状态", "轮次",
    ]
    REQUIRED_FIELDS = ["实体模型", "来源记录", "字段"]
    STATUS_ORDER = ["待派发", "已派发", "已补齐", "已关闭", "作废"]
    ACTION_RULES = {
        "派发返工": "已派发",
        "标记补齐": "已补齐",
        "关闭返工": "已关闭",
        "作废返工": "作废",
    }
    NEGATIVE_ACTIONS = ["作废返工"]

    def list_entries(self, *, filters=None, keyword=None, status=None,
                     page: int = 1, size: int = 20):
        items, total = super().list_entries(
            filters=filters, keyword=keyword, status=status, page=page, size=size)
        # 列表也返回可派发判断，避免前端自己重算分区和状态规则。
        return [rework_rules.public_item(item) for item in items], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(self.MODULE, entry_id)
        return rework_rules.public_item(row) if row else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """人工登记返工事项：仍按来源记录 + 字段去重，已关闭的不重开。"""
        entity_model = str(
            values.get("实体模型") or values.get("entity_model") or "").strip()
        source_record = str(
            values.get("来源记录") or values.get("源记录") or "").strip()
        field = str(
            values.get("字段") or values.get("待补字段") or "").strip()
        missing = [
            name for name, value in
            (("实体模型", entity_model), ("来源记录", source_record), ("字段", field))
            if not value
        ]
        if missing:
            return None, missing
        existing = rework_rules.find_rework_item(entity_model, source_record, field)
        if existing is not None:
            return rework_rules.public_item(existing), []
        partition = str(values.get("分区") or "默认分区")
        partition_status = rework_rules.resolve_partition_status(
            values, partition, values.get("分区状态"))
        record = {"来源记录": source_record, field: values.get("原始值", "")}
        item = rework_rules.create_rework_item(
            entity_model=entity_model,
            source_system=str(values.get("来源系统") or ""),
            source_record=source_record,
            field=field,
            partition=partition,
            partition_status=partition_status,
            owner=str(values.get("负责人") or ""),
            round_no=rework_rules.next_round(entity_model),
            stat_id=str(values.get("统计编号") or ""),
            record=record,
            extra={"报告编号": str(values.get("报告编号") or "")},
        )
        return rework_rules.public_item(item), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        row = store.find(self.MODULE, entry_id)
        if row is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if rework_rules.is_closed(row):
            return None, f"返工事项 {row.get('返工编号')} 已关闭，不能重复处理"
        if action == "派发返工":
            if row.get("分区状态") != rework_rules.VERIFIED_PARTITION:
                return None, f"返工事项 {row.get('返工编号')} 所在分区尚未核验，不能派发"
            if not str(row.get("负责人") or "").strip():
                return None, f"返工事项 {row.get('返工编号')} 缺少负责人，无法派发"
        elif action in ("标记补齐", "关闭返工"):
            if row.get("分区状态") != rework_rules.VERIFIED_PARTITION:
                return None, f"返工事项 {row.get('返工编号')} 所在分区尚未核验，不能关闭"
        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
        row["状态"] = target
        row["status"] = target
        row["pending"] = target not in ("已补齐", "已关闭", "作废")
        if action == "派发返工":
            row["派发时间"] = rework_rules.now_iso()
            row["关闭方式"] = "已派发"
        if action in ("标记补齐", "关闭返工", "作废返工"):
            row["closed"] = True
            row["补齐状态"] = "已补齐" if action == "标记补齐" else row.get("补齐状态", "")
            row["关闭时间"] = rework_rules.now_iso()
            row["关闭方式"] = action
            row["关闭原因"] = f"人工{action}"
        row["可派发"] = rework_rules.is_dispatchable(row)
        row["更新时间"] = rework_rules.now_iso()
        return rework_rules.public_item(row), f"{self.ENTITY}已{action}"

    def rework_view(self, entity_model: str = "",
                    partition: str = "") -> dict[str, Any]:
        """返工视图：已核分区、未核分区、可派发字段与值班派发清单。"""
        rows = rework_rules.rework_rows(entity_model or None)
        if partition:
            rows = [row for row in rows if str(row.get("分区") or "") == partition]
        items = [rework_rules.public_item(row) for row in rows]

        partition_map: dict[str, dict[str, Any]] = {}
        for item in items:
            name = str(item.get("分区") or "默认分区")
            bucket = partition_map.setdefault(name, {
                "分区": name,
                "分区状态": item.get("分区状态") or rework_rules.VERIFIED_PARTITION,
                "事项数": 0,
                "待派发": 0,
                "已派发": 0,
                "已关闭": 0,
                "可派发": 0,
                "待补字段": set(),
                "来源记录": set(),
                "负责人": set(),
                "items": [],
            })
            bucket["事项数"] += 1
            status = item.get("状态")
            if status == "待派发":
                bucket["待派发"] += 1
            elif status == "已派发":
                bucket["已派发"] += 1
            if item.get("已关闭"):
                bucket["已关闭"] += 1
            if item.get("可派发"):
                bucket["可派发"] += 1
            if not item.get("已关闭"):
                bucket["待补字段"].add(str(item.get("待补字段") or ""))
                bucket["来源记录"].add(str(item.get("来源记录") or ""))
            if item.get("负责人"):
                bucket["负责人"].add(str(item.get("负责人")))
            bucket["items"].append(item)

        partition_list = []
        for bucket in partition_map.values():
            bucket["待补字段"] = sorted(f for f in bucket["待补字段"] if f)
            bucket["来源记录"] = sorted(s for s in bucket["来源记录"] if s)
            bucket["负责人"] = sorted(bucket["负责人"])
            bucket["items"].sort(key=lambda item: (str(item.get("来源记录")), str(item.get("待补字段"))))
            partition_list.append(bucket)
        partition_list.sort(key=lambda bucket: (bucket["分区状态"] != rework_rules.VERIFIED_PARTITION, bucket["分区"]))

        verified = [b for b in partition_list if b["分区状态"] == rework_rules.VERIFIED_PARTITION]
        unverified = [b for b in partition_list if b["分区状态"] != rework_rules.VERIFIED_PARTITION]
        open_items = [item for item in items if not item.get("已关闭")]
        dispatchable = [item for item in items if item.get("可派发")]
        pending_verified = [
            item for item in open_items
            if item.get("分区状态") == rework_rules.VERIFIED_PARTITION
        ]

        return {
            "entity_model": entity_model,
            "summary": {
                "事项总数": len(items),
                "待办事项": len(open_items),
                "已关闭": sum(1 for item in items if item.get("已关闭")),
                "可派发": len(dispatchable),
                "已核分区待办": len(pending_verified),
                "未核分区待办": sum(
                    1 for item in open_items
                    if item.get("分区状态") != rework_rules.VERIFIED_PARTITION
                ),
                "已核分区数": len(verified),
                "未核分区数": len(unverified),
            },
            "partitions": partition_list,
            "verified_partitions": verified,
            "unverified_partitions": unverified,
            "dispatchable_fields": rework_rules.field_summary(dispatchable),
            "verified_pending_fields": rework_rules.field_summary(pending_verified),
            "items": items,
        }

    def trace_item(self, entry_id: int) -> dict[str, Any] | None:
        """追溯单条返工事项：原始行快照、当前源行和待补字段。"""
        row = store.find(self.MODULE, entry_id)
        if row is None:
            return None
        item = rework_rules.public_item(row)
        source_record = str(row.get("来源记录") or "")
        current = self._find_source_row(row.get("实体模型"), source_record)
        return {
            "item": item,
            "返工编号": item.get("返工编号"),
            "统计编号": row.get("统计编号"),
            "实体模型": row.get("实体模型"),
            "来源记录": source_record,
            "待补字段": item.get("待补字段"),
            "原始值": row.get("原始值", ""),
            "原始数据": row.get("原始记录") or row.get("原始数据") or {},
            "当前原始行": current,
            "当前字段值": "" if current is None else str(current.get(item.get("待补字段") or "") or ""),
            "分区": row.get("分区"),
            "分区状态": row.get("分区状态"),
            "负责人": row.get("负责人"),
            "状态": item.get("状态"),
            "可派发": item.get("可派发"),
            "轮次": row.get("轮次"),
            "首次轮次": row.get("首次轮次"),
            "最近轮次": row.get("最近轮次"),
            "发现时间": row.get("发现时间"),
            "更新时间": row.get("更新时间"),
            "关闭时间": row.get("关闭时间"),
            "关闭方式": row.get("关闭方式"),
            "关闭原因": row.get("关闭原因"),
            "复验值": row.get("复验值", ""),
            "复验人": row.get("复验人", ""),
        }

    def dispatch_items(self, item_ids: list[int], owner: str = "") -> dict[str, Any]:
        """按值班决定派发返工事项：只派发已核分区且待派发的明细。"""
        dispatched: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for item_id in item_ids:
            row = store.find(self.MODULE, int(item_id))
            if row is None:
                rejected.append({"id": item_id, "reason": "事项不存在"})
                continue
            if rework_rules.is_closed(row):
                rejected.append({"id": item_id, "reason": "事项已关闭"})
                continue
            if not rework_rules.is_dispatchable(row):
                reason = "分区尚未核验" if row.get("分区状态") != rework_rules.VERIFIED_PARTITION else "事项不在待派发状态"
                rejected.append({"id": item_id, "reason": reason})
                continue
            if owner.strip():
                row["负责人"] = owner.strip()
            if not str(row.get("负责人") or "").strip():
                rejected.append({"id": item_id, "reason": "缺少负责人"})
                continue
            row["状态"] = "已派发"
            row["status"] = "已派发"
            row["pending"] = True
            row["派发时间"] = rework_rules.now_iso()
            row["更新时间"] = row["派发时间"]
            row["可派发"] = False
            dispatched.append(rework_rules.public_item(row))
        return {
            "ok": bool(dispatched),
            "dispatched": dispatched,
            "rejected": rejected,
            "dispatched_count": len(dispatched),
            "rejected_count": len(rejected),
        }

    def update_source_record(self, record_id: str, field: str,
                             value: Any) -> dict[str, Any]:
        """补记原始行字段：改的是采集原始行，供后续重算和复验使用。"""
        record = self._find_source_row(None, str(record_id))
        if record is None:
            return {"ok": False, "reason": f"来源记录 {record_id} 不存在"}
        if not field:
            return {"ok": False, "reason": "缺少待补字段"}
        before = rework_rules.field_value(record, field)
        record[field] = value
        record["最后修改时间"] = rework_rules.now_iso()
        record["最后修改字段"] = field
        return {
            "ok": True,
            "source_record": record_id,
            "field": field,
            "before": before,
            "after": rework_rules.field_value(record, field),
            "record": dict(record),
        }

    def report_rework(self, report_id: str,
                      entity_model: str = "") -> dict[str, Any]:
        """按报告编号回查返工明细：旧报告重送后仍能看到已完成事项。"""
        items = [
            row for row in rework_rules.rework_rows(entity_model or None)
            if str(row.get("报告编号") or "") == str(report_id)
            or str(row.get("统计编号") or "") == str(report_id)
        ]
        reports = [
            row for row in store.rows("quality_report")
            if str(row.get("报告编号") or "") == str(report_id)
        ]
        return {
            "report_id": report_id,
            "reports": reports,
            "items": [rework_rules.public_item(row) for row in items],
            "closed_items": [
                rework_rules.public_item(row) for row in items
                if rework_rules.is_closed(row)
            ],
        }

    @staticmethod
    def _find_source_row(entity_model: Any, source_record: str) -> dict[str, Any] | None:
        for row in store.rows("source_record"):
            if entity_model and str(row.get("实体模型", "")) != str(entity_model):
                continue
            if str(row.get("来源记录") or "") == source_record:
                return row
        return None
