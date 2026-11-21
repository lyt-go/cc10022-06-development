"""质量统计领域服务：完备率、重复率、一致率与匹配精度计算。

质量检查同时产出补值返工明细：每条缺失字段都追到来源记录和采集分区，
同一轮按来源记录 + 字段去重，已关闭的返工项不会被旧报告重新打开。
"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.services import rework as rework_rules
from app.store import store


class MdmQualityService(BaseModuleService):
    MODULE = "mdm_quality"
    ENTITY = "质量统计"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["统计编号", "实体模型", "完备率", "重复率", "一致率", "匹配精度", "统计时间", "统计区间"]
    REQUIRED_FIELDS = ["统计编号", "实体模型", "完备率"]
    STATUS_ORDER = ["草稿", "计算中", "已完成", "已归档"]
    ACTION_RULES = {"发起统计": "计算中", "确认完成": "已完成", "归档统计": "已归档"}
    NEGATIVE_ACTIONS = []

    def compute_quality_metrics(self, entity_model: str,
                                  records: list[dict[str, Any]],
                                  required_fields: list[str],
                                  *,
                                  source_system: str = "",
                                  partition_status: Any = None,
                                  owners: Any = None,
                                  report_id: str = "",
                                  round_no: int | None = None,
                                  stat_id: str | None = None) -> dict[str, Any]:
        """计算主数据质量指标：完备率、重复率、一致率和匹配精度。

        按实体模型计算质量统计数据，包括字段完备率检测、
        重复记录统计、一致性校验和匹配精度评估。
        同时把校验识别出的缺失字段整理成补值返工明细。
        """
        total = len(records)
        # 计算完备率：校验每条记录必填字段的填充情况
        complete = sum(1 for r in records if all(
            str(r.get(f, "")).strip() for f in required_fields
        ))
        completeness = round(complete / max(total, 1) * 100, 2)

        # 计算重复率：检查实体模型的重复簇数据
        clusters = store.rows("dup_cluster")
        model_clusters = [c for c in clusters if c.get("实体模型") == entity_model]
        dup_count = sum(int(c.get("簇大小", "0")) for c in model_clusters)
        duplication = round(dup_count / max(total, 1) * 100, 2)

        # 计算一致率：检查字段值的一致性和标准化程度
        consistency = self._compute_consistency(records, required_fields)

        # 计算匹配精度：基于匹配任务输出
        match_jobs = store.rows("auto_match_job")
        model_jobs = [j for j in match_jobs if j.get("实体模型") == entity_model]
        total_clusters = sum(int(j.get("输出簇数", "0")) for j in model_jobs)
        match_precision = round(
            max(100 - total_clusters / max(total, 1) * 100, 0), 2
        )

        # 生成质量统计：按实体模型计算多维数据质量指标
        quality_stats = {
            "entity_model": entity_model,
            "total_records": total,
            "complete_records": complete,
            "completeness_pct": completeness,
            "duplication_pct": duplication,
            "consistency_pct": consistency,
            "match_precision_pct": match_precision,
            "computed_at": datetime.datetime.utcnow().isoformat(),
        }

        resolved_round = self._resolve_round(entity_model, report_id, round_no)
        quality_stats["round"] = resolved_round
        quality_stats["report_id"] = report_id

        if stat_id is None and report_id:
            # 重算同一份历史报告时沿用首次统计编号，质量统计行原地更新。
            stat_id = self._existing_stat_id(entity_model, report_id)
        if stat_id is None:
            stat_id = f"QLTY-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

        # 把缺字段证据整理成补值返工明细：来源记录 + 字段 是唯一键
        rework_result = self._generate_rework(
            entity_model=entity_model,
            records=records,
            required_fields=required_fields,
            source_system=source_system,
            partition_status=partition_status,
            owners=owners,
            round_no=resolved_round,
            report_id=report_id,
            stat_id=stat_id,
        )
        quality_stats["rework"] = rework_result

        self._store_quality_stats(entity_model, quality_stats, stat_id=stat_id)
        self._log_report(entity_model, report_id, resolved_round, stat_id, len(records))
        return quality_stats

    def submit_quality_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """接收一份质量检查报告：计算指标并生成补值返工明细。

        报告可携带来源系统、分区采集状态和负责人映射。报告编号用于
        识别“同一轮”：重送旧报告只更新证据，不会重开已完成的返工项。
        """
        entity_model = str(
            report.get("实体模型") or report.get("entity_model") or ""
        ).strip()
        records = report.get("记录") or report.get("records") or report.get("rows") or []
        required_fields = (
            report.get("必需字段")
            or report.get("required_fields")
            or report.get("校验字段")
            or []
        )
        if isinstance(required_fields, str):
            required_fields = [f.strip() for f in required_fields.split(",") if f.strip()]
        if not entity_model:
            return {"ok": False, "reason": "缺少实体模型"}
        if not required_fields:
            return {"ok": False, "reason": "缺少必需字段"}
        stats = self.compute_quality_metrics(
            entity_model,
            list(records),
            list(required_fields),
            source_system=str(report.get("来源系统") or report.get("source_system") or ""),
            partition_status=report.get("分区状态") or report.get("partition_status"),
            owners=report.get("负责人") or report.get("owners"),
            report_id=str(report.get("报告编号") or report.get("report_id") or ""),
            round_no=report.get("轮次") or report.get("round_no"),
            stat_id=report.get("统计编号") or report.get("stat_id"),
        )
        return {"ok": True, **stats}

    def recompute_quality_check(self, entity_model: str,
                                 required_fields: list[str] | None = None,
                                 *, report_id: str = "",
                                 use_source_records: bool = True,
                                 source_system: str = "",
                                 partition_status: Any = None,
                                 owners: Any = None,
                                 stat_id: str | None = None) -> dict[str, Any]:
        """重算历史检查数据：从当前原始行重新计算指标并刷新返工视图。

        默认读取 source_record 中的最新原始行，因此补记的号码会反映到
        完备率上；同一报告编号沿用原轮次，已关闭的返工项不会被重开。
        """
        if not required_fields:
            required_fields = rework_rules.required_fields_for(entity_model)
        if use_source_records:
            records = [
                dict(row) for row in store.rows("source_record")
                if str(row.get("实体模型", entity_model)) == entity_model
            ]
        else:
            records = []
        if not records:
            return {"ok": False, "reason": "没有可重算的原始行"}
        stats = self.compute_quality_metrics(
            entity_model,
            records,
            list(required_fields),
            source_system=source_system,
            partition_status=partition_status,
            owners=owners,
            report_id=report_id,
            stat_id=stat_id,
        )
        view = rework_rules.partition_rows(entity_model)
        return {
            "ok": True,
            **stats,
            "partitions": sorted(view),
            "rework_items": [rework_rules.public_item(r) for r in rework_rules.rework_rows(entity_model)],
        }

    def _generate_rework(self, *, entity_model: str,
                          records: list[dict[str, Any]],
                          required_fields: list[str],
                          source_system: str,
                          partition_status: Any,
                          owners: Any,
                          round_no: int,
                          report_id: str,
                          stat_id: str) -> dict[str, Any]:
        """逐条把缺失字段落到来源记录上，按来源记录 + 字段去重。"""
        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        skipped_closed: list[dict[str, Any]] = []
        skipped_stale: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for index, record in enumerate(records):
            source_record = rework_rules.source_record_id(record, index, entity_model)
            partition = rework_rules.record_partition(record)
            part_status = rework_rules.resolve_partition_status(
                record, partition, partition_status)
            owner = rework_rules.record_owner(record, partition, owners)
            record_source_system = str(
                record.get("来源系统") or source_system or "").strip()
            for field in required_fields:
                if not rework_rules.field_missing(record, field):
                    continue
                key = (source_record, field)
                if key in seen:
                    # 同一轮里重复产出的明细：按来源记录 + 字段去重
                    duplicates.append({"来源记录": source_record, "字段": field})
                    continue
                seen.add(key)
                existing = rework_rules.find_rework_item(entity_model, source_record, field)
                if existing is not None:
                    if rework_rules.is_closed(existing):
                        # 已补齐的字段不能因旧报告迟到又进入待办
                        skipped_closed.append(existing)
                        continue
                    if int(existing.get("最近轮次") or 0) > round_no:
                        # 迟到的旧报告不能把事项退回更早的轮次
                        skipped_stale.append(existing)
                        continue
                    rework_rules.refresh_item(
                        existing,
                        partition=partition,
                        partition_status=part_status,
                        owner=owner,
                        round_no=round_no,
                        stat_id=stat_id,
                        record=record,
                    )
                    updated.append(existing)
                    continue
                created.append(rework_rules.create_rework_item(
                    entity_model=entity_model,
                    source_system=record_source_system,
                    source_record=source_record,
                    field=field,
                    partition=partition,
                    partition_status=part_status,
                    owner=owner,
                    round_no=round_no,
                    stat_id=stat_id,
                    record=record,
                    extra={"报告编号": report_id} if report_id else None,
                ))

        open_items = [
            row for row in rework_rules.rework_rows(entity_model)
            if not rework_rules.is_closed(row)
        ]
        dispatchable = [row for row in open_items if rework_rules.is_dispatchable(row)]
        return {
            "统计编号": stat_id,
            "轮次": round_no,
            "报告编号": report_id,
            "新增明细": len(created),
            "更新明细": len(updated),
            "同轮去重": len(duplicates),
            "跳过已关闭": len(skipped_closed),
            "跳过旧报告": len(skipped_stale),
            "待办明细": len(open_items),
            "可派发明细": len(dispatchable),
            "created_ids": [row.get("id") for row in created],
            "updated_ids": [row.get("id") for row in updated],
            "skipped_closed_ids": [row.get("id") for row in skipped_closed],
            "skipped_stale_ids": [row.get("id") for row in skipped_stale],
        }

    def _existing_stat_id(self, entity_model: str, report_id: str) -> str | None:
        """按报告编号找回首次统计编号，重算时复用同一条统计记录。"""
        for report in store.rows("quality_report"):
            if (
                str(report.get("报告编号", "")) == str(report_id)
                and str(report.get("实体模型", "")) == entity_model
            ):
                return str(report.get("首次统计编号") or "") or None
        # 服务重启后报告登记还在内存里重建；历史报告可能先有统计行。
        for row in store.rows(self.MODULE):
            if (
                str(row.get("报告编号", "")) == str(report_id)
                and str(row.get("实体模型", "")) == entity_model
            ):
                return str(row.get("统计编号") or "") or None
        return None

    def _resolve_round(self, entity_model: str, report_id: str,
                       round_no: int | None) -> int:
        """报告编号决定轮次：旧报告重送沿用原轮次，新报告分配下一轮。"""
        if report_id:
            for report in store.rows("quality_report"):
                if (
                    str(report.get("报告编号", "")) == str(report_id)
                    and str(report.get("实体模型", "")) == entity_model
                ):
                    return int(report.get("轮次") or 0)
            for row in store.rows(self.MODULE):
                if (
                    str(row.get("报告编号", "")) == str(report_id)
                    and str(row.get("实体模型", "")) == entity_model
                ):
                    return int(row.get("轮次") or 0)
        if round_no:
            return int(round_no)
        return rework_rules.next_round(entity_model)

    def _log_report(self, entity_model: str, report_id: str,
                    round_no: int, stat_id: str, record_count: int) -> None:
        if not report_id:
            return
        reports = store.rows("quality_report")
        for report in reports:
            if (
                str(report.get("报告编号", "")) == str(report_id)
                and str(report.get("实体模型", "")) == entity_model
            ):
                report["最近统计编号"] = stat_id
                report["重送次数"] = int(report.get("重送次数", 0)) + 1
                return
        reports.append({
            "id": max((int(r.get("id", 0)) for r in reports), default=0) + 1,
            "报告编号": report_id,
            "实体模型": entity_model,
            "轮次": round_no,
            "首次统计编号": stat_id,
            "最近统计编号": stat_id,
            "记录数": record_count,
            "重送次数": 0,
        })


    def _compute_consistency(self, records: list[dict[str, Any]],
                               fields: list[str]) -> float:
        """计算字段一致性：检查同类记录同字段值的分布集中度。"""
        if not records or len(records) < 2:
            return 100.0
        total_checks = 0
        consistent = 0
        for field in fields:
            values = [str(r.get(field, "")) for r in records if str(r.get(field, "")).strip()]
            if len(values) < 2:
                continue
            most_common = max(set(values), key=values.count)
            total_checks += len(values)
            consistent += values.count(most_common)
        return round(consistent / max(total_checks, 1) * 100, 2)

    def _store_quality_stats(self, entity_model: str, stats: dict[str, Any],
                             *, stat_id: str | None = None) -> None:
        """存储质量统计结果到mdm_quality存储。"""
        rows = store.rows(self.MODULE)
        if stat_id is None:
            stat_id = f"QLTY-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        entry = None
        for existing in rows:
            if str(existing.get("统计编号", "")) == str(stat_id):
                # 同一统计编号重算时原地更新，避免重复产出统计行。
                entry = existing
                break
        if entry is None:
            entry = {
                "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
                "统计编号": stat_id,
            }
            rows.append(entry)
        entry.update({
            "实体模型": entity_model,
            "完备率": f"{stats['completeness_pct']:.2f}%",
            "重复率": f"{stats['duplication_pct']:.2f}%",
            "一致率": f"{stats['consistency_pct']:.2f}%",
            "匹配精度": f"{stats['match_precision_pct']:.2f}%",
            "统计时间": stats["computed_at"],
            "统计区间": "全量",
            "status": "已完成",
            "pending": False,
            "abnormal": False,
        })
        if stats.get("round"):
            entry["轮次"] = stats["round"]
        if stats.get("report_id"):
            entry["报告编号"] = stats["report_id"]
        if stats.get("rework"):
            entry["返工明细数"] = stats["rework"].get("待办明细", 0)
            entry["可派发数"] = stats["rework"].get("可派发明细", 0)

    def query_quality_trend(self, entity_model: str, limit: int = 10) -> list[dict[str, Any]]:
        """查询质量趋势：获取指定实体模型的近期质量统计历史。

        查询质量统计存储，按时间倒序获取最近N次质量统计结果，
        分析完备率、重复率和一致率的变化趋势。
        """
        rows = store.rows(self.MODULE)
        stats = [
            row for row in rows
            if row.get("实体模型") == entity_model and row.get("status") == "已完成"
        ]
        # 查询质量统计趋势：按时间倒序获取质量指标历史变化
        stats.sort(key=lambda r: r.get("统计时间", ""), reverse=True)
        return stats[:limit]

    def aggregate_global_quality(self) -> dict[str, Any]:
        """聚合全局质量指标：汇总所有实体模型的质量统计。

        读取质量统计存储，计算所有实体模型的平均完备率、
        重复率、一致率和匹配精度，输出全局质量概览。
        """
        rows = store.rows(self.MODULE)
        completed = [r for r in rows if r.get("status") == "已完成"]
        if not completed:
            return {"total_stats": 0, "models": []}
        models: dict[str, dict[str, Any]] = {}
        for stat in completed:
            model = stat.get("实体模型", "")
            if model not in models:
                models[model] = {
                    "entity_model": model,
                    "latest": None,
                    "stat_count": 0,
                }
            models[model]["stat_count"] += 1
            if not models[model]["latest"] or stat.get("统计时间", "") > models[model]["latest"].get("统计时间", ""):
                models[model]["latest"] = stat
        return {
            "total_quality_stats": len(completed),
            "models": list(models.values()),
        }

    def archive_old_stats(self, before_date: str) -> int:
        """归档指定日期之前的旧质量统计记录。"""
        rows = store.rows(self.MODULE)
        archived = 0
        for row in rows:
            if row.get("status") == "已完成" and row.get("统计时间", "") < before_date:
                row["status"] = "已归档"
                archived += 1
        return archived