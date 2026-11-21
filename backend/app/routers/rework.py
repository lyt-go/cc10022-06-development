"""补值返工专用接口：重算质量检查、返工视图、派发、复验与原始行补记。

通用资源路由已经覆盖列表/登记/动作；这里补的是跨模块链路：
质量检查产出返工明细、清洗规则复验关闭返工、原始行改值后重算。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.field_cleanse import FieldCleanseService
from app.services.mdm_quality import MdmQualityService
from app.services.quality_rework import QualityReworkService
from app.store import store

router = APIRouter(prefix="/api", tags=["补值返工"])
quality_service = MdmQualityService()
rework_service = QualityReworkService()
cleanse_service = FieldCleanseService()


class RecomputePayload(BaseModel):
    entity_model: str = Field(default="customer")
    required_fields: list[str] = Field(default_factory=list)
    report_id: str = ""
    source_system: str = ""
    partition_status: dict[str, str] | None = None
    owners: dict[str, str] | None = None
    use_source_records: bool = True
    stat_id: str = ""


class DispatchPayload(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    owner: str = ""


class RevalidatePayload(BaseModel):
    entity_model: str = Field(default="customer")
    records: list[dict[str, Any]] = Field(default_factory=list)
    verifier: str = "字段标准化清洗"


class SourceFieldPayload(BaseModel):
    field: str
    value: Any = ""


@router.get("/source_record")
def list_source_records(entity_model: str | None = Query(default=None),
                        source_system: str | None = Query(default=None),
                        partition: str | None = Query(default=None)) -> dict[str, Any]:
    """列出采集原始行：工作台追溯缺字段证据时使用。"""
    rows = [dict(row) for row in store.rows("source_record")]
    if entity_model:
        rows = [row for row in rows if str(row.get("实体模型", "")) == entity_model]
    if source_system:
        rows = [row for row in rows if str(row.get("来源系统", "")) == source_system]
    if partition:
        rows = [row for row in rows if str(row.get("采集分区", "")) == partition]
    return {"items": rows, "total": len(rows), "page": 1, "size": len(rows)}


@router.post("/source_record/{record_id}/fields")
def update_source_field(record_id: str, payload: SourceFieldPayload) -> dict[str, Any]:
    """补记原始行字段：例如给 CRM-41 补上电话，再触发重算。"""
    result = rework_service.update_source_record(record_id, payload.field, payload.value)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "来源记录不存在"))
    return result


@router.post("/mdm_quality/recompute")
def recompute_quality(payload: RecomputePayload) -> dict[str, Any]:
    """重算历史检查数据：从当前原始行刷新指标和返工视图。"""
    result = quality_service.recompute_quality_check(
        payload.entity_model,
        payload.required_fields or None,
        report_id=payload.report_id,
        use_source_records=payload.use_source_records,
        source_system=payload.source_system,
        partition_status=payload.partition_status,
        owners=payload.owners,
        stat_id=payload.stat_id or None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "重算失败"))
    return result


@router.post("/mdm_quality/reports")
def submit_quality_report(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """接收质量检查报告：同一轮重复明细按来源记录 + 字段去重。"""
    report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
    result = quality_service.submit_quality_report(report)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "报告处理失败"))
    return result


@router.post("/mdm_quality/check")
def run_quality_check(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """质量检查别名：与 /mdm_quality/reports 共用同一套报告处理。"""
    return submit_quality_report(payload)


@router.get("/quality_rework/view")
def rework_view(entity_model: str = Query(default=""),
                partition: str = Query(default="")) -> dict[str, Any]:
    """返工视图：已核分区、未核分区、可派发字段与值班派发清单。"""
    return rework_service.rework_view(entity_model, partition)


@router.get("/quality_rework/reports/{report_id}")
def report_rework(report_id: str, entity_model: str = Query(default="")) -> dict[str, Any]:
    """按报告编号回查返工明细，含已关闭事项。"""
    return rework_service.report_rework(report_id, entity_model)


@router.post("/quality_rework/dispatch")
def dispatch_rework(payload: DispatchPayload) -> dict[str, Any]:
    """按值班决定派发事项：未核分区和已关闭事项会被拒绝。"""
    return rework_service.dispatch_items(payload.item_ids, payload.owner)


@router.post("/quality_rework/revalidate")
def revalidate_rework(payload: RevalidatePayload) -> dict[str, Any]:
    """字段标准化清洗复验改过的原始行，并关闭对应返工项。"""
    return cleanse_service.revalidate_rework_items(
        payload.entity_model,
        payload.records,
        verifier=payload.verifier,
    )


@router.get("/quality_rework/{entry_id}/trace")
def trace_rework(entry_id: int) -> dict[str, Any]:
    """追溯返工事项：原始行快照、当前源行和待补字段。"""
    result = rework_service.trace_item(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"返工事项 {entry_id} 不存在")
    return result
