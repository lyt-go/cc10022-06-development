"""补值返工共享领域规则。

质量检查、字段复验和返工视图都围绕同一份“缺字段证据”工作：
来源记录 + 字段是唯一键，同一轮重复产出会合并，已经补齐/关闭的
事项不会被旧报告重新打开。把规则集中在这里，避免两个服务各写一套
去重和状态判断。
"""
from __future__ import annotations

import datetime
from typing import Any, Iterable

from app.store import store

REWORK_MODULE = "quality_rework"

VERIFIED_PARTITION = "已核分区"
UNVERIFIED_PARTITION = "未核分区"

# 质量检查默认校验字段：真实项目由实体模型定义提供，这里按实体模型兜底。
DEFAULT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "customer": ["姓名", "电话", "邮箱"],
}


def required_fields_for(entity_model: str) -> list[str]:
    return list(DEFAULT_REQUIRED_FIELDS.get(entity_model, ["姓名", "电话", "邮箱"]))

OPEN_STATUSES = {"待派发", "已派发"}
CLOSED_STATUSES = {"已关闭", "已补齐", "已完成", "已复验", "作废"}

SOURCE_RECORD_KEYS = (
    "来源记录",
    "源记录",
    "来源记录ID",
    "source_record",
    "source_record_id",
    "record_id",
    "记录编号",
    "客户编号",
    "id",
)
PARTITION_KEYS = ("采集分区", "数据分区", "来源分区", "分区", "partition", "_partition")
PARTITION_STATUS_KEYS = (
    "分区状态",
    "核验状态",
    "采集状态",
    "partition_status",
    "verified",
    "_verified",
)
OWNER_KEYS = ("负责人", "处理人", "owner", "assignee")

_VERIFIED_TOKENS = {
    "已核",
    "已核验",
    "已核对",
    "核验通过",
    "成功",
    "采集成功",
    "已采集",
    "verified",
    "true",
    "complete",
    "completed",
    "已核分区",
}
_UNVERIFIED_TOKENS = {
    "未核",
    "未核验",
    "未核对",
    "失败",
    "采集失败",
    "部分失败",
    "partial",
    "partial_failed",
    "failed",
    "unverified",
    "false",
    "未核分区",
}


def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


def normalize_partition_status(value: Any) -> str | None:
    """把各种采集/核验状态收敛成“已核分区 / 未核分区”。"""
    if isinstance(value, bool):
        return VERIFIED_PARTITION if value else UNVERIFIED_PARTITION
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text in {token.casefold() for token in _VERIFIED_TOKENS}:
        return VERIFIED_PARTITION
    if text in {token.casefold() for token in _UNVERIFIED_TOKENS}:
        return UNVERIFIED_PARTITION
    if "未核" in text or "失败" in text or "fail" in text:
        return UNVERIFIED_PARTITION
    if "已核" in text or "成功" in text or "verified" in text:
        return VERIFIED_PARTITION
    return None


def source_record_id(record: dict[str, Any], index: int = 0,
                     entity_model: str = "") -> str:
    """解析来源记录标识；没有显式标识时使用稳定行号兜底。"""
    for key in SOURCE_RECORD_KEYS:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    prefix = entity_model or "ROW"
    return f"{prefix}-ROW-{index + 1}"


def record_partition(record: dict[str, Any]) -> str:
    for key in PARTITION_KEYS:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "默认分区"


def resolve_partition_status(record: dict[str, Any], partition: str,
                             partition_status: Any = None) -> str:
    """优先取分区级状态，其次取记录状态，最后根据分区名推断。"""
    if isinstance(partition_status, dict) and partition in partition_status:
        normalized = normalize_partition_status(partition_status[partition])
        if normalized:
            return normalized
    if isinstance(partition_status, list):
        for entry in partition_status:
            if not isinstance(entry, dict):
                continue
            name = next(
                (entry.get(key) for key in ("分区", "partition") if entry.get(key)),
                None,
            )
            if name == partition:
                normalized = normalize_partition_status(
                    entry.get("分区状态")
                    or entry.get("状态")
                    or entry.get("partition_status")
                    or entry.get("status")
                )
                if normalized:
                    return normalized
    for key in PARTITION_STATUS_KEYS:
        if key not in record:
            continue
        normalized = normalize_partition_status(record.get(key))
        if normalized:
            return normalized
    if "未核" in partition or "失败" in partition:
        return UNVERIFIED_PARTITION
    return VERIFIED_PARTITION


def record_owner(record: dict[str, Any], partition: str,
                 owners: Any = None) -> str:
    for key in OWNER_KEYS:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    if isinstance(owners, dict):
        for key in (partition, "default", "默认", "*"):
            value = owners.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def field_missing(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, "")
    if value is None:
        return True
    return not str(value).strip()


def field_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    return "" if value is None else str(value)


def raw_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    """保留原始行的可回查快照，剔除不可序列化的私有运行态。"""
    snapshot: dict[str, Any] = {}
    for key, value in record.items():
        if str(key).startswith("_"):
            snapshot[key] = value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            snapshot[key] = value
        elif isinstance(value, (list, dict)):
            snapshot[key] = value
        else:
            snapshot[key] = str(value)
    return snapshot


def rework_rows(entity_model: str | None = None) -> list[dict[str, Any]]:
    rows = store.rows(REWORK_MODULE)
    if entity_model:
        rows = [row for row in rows if str(row.get("实体模型", "")) == str(entity_model)]
    return rows


def find_rework_item(entity_model: str, source_record: str,
                     field: str) -> dict[str, Any] | None:
    """按来源记录 + 字段查找事项，包含已关闭事项（用于防止旧报告重开）。"""
    for row in rework_rows(entity_model):
        if (
            str(row.get("来源记录") or row.get("源记录") or "") == str(source_record)
            and str(row.get("字段") or row.get("待补字段") or row.get("缺失字段") or "")
            == str(field)
        ):
            return row
    return None


def is_closed(row: dict[str, Any]) -> bool:
    status = row.get("状态") or row.get("status") or ""
    return bool(row.get("closed")) or status in CLOSED_STATUSES


def is_verified(row: dict[str, Any]) -> bool:
    return (row.get("分区状态") or VERIFIED_PARTITION) == VERIFIED_PARTITION


def is_dispatchable(row: dict[str, Any]) -> bool:
    status = row.get("状态") or row.get("status") or ""
    return (
        not is_closed(row)
        and status in OPEN_STATUSES
        and status == "待派发"
        and is_verified(row)
    )


def _next_id() -> int:
    rows = store.rows(REWORK_MODULE)
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def next_round(entity_model: str) -> int:
    rows = rework_rows(entity_model)
    rounds = []
    for row in rows:
        for key in ("轮次", "最近轮次", "首次轮次"):
            try:
                rounds.append(int(row.get(key) or 0))
            except (TypeError, ValueError):
                continue
    return max(rounds, default=0) + 1


def create_rework_item(
    *,
    entity_model: str,
    source_system: str,
    source_record: str,
    field: str,
    partition: str,
    partition_status: str,
    owner: str,
    round_no: int,
    stat_id: str,
    record: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item_id = _next_id()
    snapshot = raw_snapshot(record)
    status = "待派发"
    item: dict[str, Any] = {
        "id": item_id,
        "返工编号": f"RW-{item_id:05d}",
        "统计编号": stat_id,
        "实体模型": entity_model,
        "来源系统": source_system,
        "来源记录": source_record,
        "源记录": source_record,
        "字段": field,
        "待补字段": field,
        "缺失字段": field,
        "原始值": field_value(record, field),
        "原始数据": snapshot,
        "原始记录": snapshot,
        "分区": partition,
        "分区状态": partition_status,
        "负责人": owner,
        "状态": status,
        "status": status,
        "pending": True,
        "abnormal": partition_status == UNVERIFIED_PARTITION,
        "轮次": round_no,
        "首次轮次": round_no,
        "最近轮次": round_no,
        "发现时间": now_iso(),
        "更新时间": now_iso(),
        "派发时间": "",
        "关闭时间": "",
        "关闭方式": "",
        "关闭原因": "",
        "补齐状态": "",
        "复验值": "",
    }
    if extra:
        item.update(extra)
    item["可派发"] = is_dispatchable(item)
    store.rows(REWORK_MODULE).append(item)
    return item


def refresh_item(
    item: dict[str, Any],
    *,
    partition: str,
    partition_status: str,
    owner: str,
    round_no: int,
    stat_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """同一来源记录 + 字段再次出现时只更新证据，不新增明细。"""
    if is_closed(item):
        # 已补齐的字段不再被新一轮或迟到的旧报告重新派发。
        return item
    field_name = str(item.get("字段") or item.get("待补字段") or "")
    item["统计编号"] = stat_id
    item["分区"] = partition
    item["分区状态"] = partition_status
    item["原始值"] = field_value(record, field_name) if field_name else ""
    snapshot = raw_snapshot(record)
    item["原始数据"] = snapshot
    item["原始记录"] = snapshot
    item["最近轮次"] = round_no
    item["轮次"] = max(int(item.get("轮次") or 0), round_no)
    item["更新时间"] = now_iso()
    if not item.get("负责人") and owner:
        item["负责人"] = owner
    item["abnormal"] = partition_status == UNVERIFIED_PARTITION
    item["可派发"] = is_dispatchable(item)
    return item


def close_rework_item(
    item: dict[str, Any],
    *,
    verified_value: Any = "",
    reason: str = "字段标准化清洗复验通过，字段已补齐",
    verifier: str = "字段标准化清洗",
) -> dict[str, Any]:
    item["状态"] = "已关闭"
    item["status"] = "已关闭"
    item["pending"] = False
    item["closed"] = True
    item["可派发"] = False
    item["补齐状态"] = "已补齐"
    item["关闭方式"] = "字段复验"
    item["关闭原因"] = reason
    item["关闭时间"] = now_iso()
    item["复验时间"] = item["关闭时间"]
    item["复验人"] = verifier
    item["复验值"] = "" if verified_value is None else str(verified_value)
    return item


def public_item(row: dict[str, Any]) -> dict[str, Any]:
    """输出视图行：补上稳定的别名字段和实时可派发判断。"""
    item = dict(row)
    item["原始记录"] = row.get("原始记录") or row.get("原始数据") or {}
    item["待补字段"] = row.get("字段") or row.get("待补字段") or ""
    item["缺失字段"] = item["待补字段"]
    item["源记录"] = row.get("来源记录") or row.get("源记录") or ""
    item["状态"] = row.get("状态") or row.get("status") or ""
    item["status"] = item["状态"]
    item["可派发"] = is_dispatchable(row)
    item["已关闭"] = is_closed(row)
    item["分区状态"] = row.get("分区状态") or VERIFIED_PARTITION
    return item


def partition_rows(entity_model: str | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rework_rows(entity_model):
        partition = str(row.get("分区") or "默认分区")
        grouped.setdefault(partition, []).append(row)
    return grouped


def field_summary(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        field = str(item.get("字段") or item.get("待补字段") or "")
        grouped.setdefault(field, []).append(item)
    summary = []
    for field, rows in grouped.items():
        summary.append({
            "字段": field,
            "事项数": len(rows),
            "来源记录": sorted({str(r.get("来源记录") or "") for r in rows}),
            "负责人": sorted({str(r.get("负责人") or "") for r in rows if r.get("负责人")}),
            "事项编号": [r.get("id") for r in rows],
        })
    summary.sort(key=lambda item: (-int(item["事项数"]), item["字段"]))
    return summary
