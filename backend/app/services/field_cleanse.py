"""字段清洗领域服务：标准化函数执行、修正字典匹配与字段完整性校验。

清洗规则也承担补值返工的复验职责：原始行被修改后，先复验字段是否
真的补齐，再关闭对应的返工事项；复验不通过的事项保持打开。
"""
from __future__ import annotations

import re
from typing import Any

from app.services.base import BaseModuleService
from app.services import rework as rework_rules
from app.store import store


class FieldCleanseService(BaseModuleService):
    MODULE = "field_cleanse"
    ENTITY = "清洗规则"
    OPERATION_TERM = "清洗"
    LIST_FIELDS = ["规则编号", "实体模型", "目标字段", "标准化函数", "修正字典", "异常处理", "先后顺序", "规则版本"]
    REQUIRED_FIELDS = ["规则编号", "实体模型", "目标字段"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    STANDARD_FUNCTIONS: dict[str, Any] = {
        "trim": lambda v: v.strip() if isinstance(v, str) else v,
        "lower": lambda v: v.lower() if isinstance(v, str) else v,
        "upper": lambda v: v.upper() if isinstance(v, str) else v,
        "remove_spaces": lambda v: re.sub(r"\s+", "", v) if isinstance(v, str) else v,
        "format_phone": lambda v: re.sub(r"[^\d+]", "", v) if isinstance(v, str) else v,
        "format_id": lambda v: v.replace("-", "").replace(" ", "").upper() if isinstance(v, str) else v,
    }

    def cleanse_field_value(self, rule_id: int, raw_value: str) -> dict[str, Any]:
        """清洗字段值：按清洗规则执行标准化函数和修正字典映射。

        读取字段清洗规则，对原始字段值依次应用标准化函数和修正字典，
        校验清洗结果并返回清洗前值、清洗后值和采用的标准化函数。
        """
        rule = self.get_entry(rule_id)
        if not rule or rule.get("status") != "已生效":
            return {"ok": False, "reason": "清洗规则不可用", "raw": raw_value, "cleansed": raw_value}
        value = raw_value
        applied = []
        func_names = [f.strip() for f in rule.get("标准化函数", "").split(",") if f.strip()]
        for func_name in func_names:
            if func_name in self.STANDARD_FUNCTIONS:
                value = self.STANDARD_FUNCTIONS[func_name](value)
                applied.append(func_name)
        # 清洗字段值：应用标准化函数和修正字典完成字段转换
        dict_entries = [d.strip() for d in rule.get("修正字典", "").split(",") if ":" in d]
        for entry in dict_entries:
            wrong, correct = entry.split(":", 1)
            if isinstance(value, str) and wrong.strip() in value:
                value = value.replace(wrong.strip(), correct.strip())
                applied.append(f"dict:{wrong.strip()}->{correct.strip()}")
        return {"ok": True, "raw": raw_value, "cleansed": value, "applied_functions": applied}

    def batch_cleanse_records(self, rule_id: int, records: list[dict[str, Any]],
                               target_field: str) -> list[dict[str, Any]]:
        """批量清洗记录指定字段：遍历记录列表对目标字段执行清洗规则。

        读取清洗规则，对传入记录列表逐条清洗目标字段值，
        校验字段完整性并标准化字段内容，返回清洗后的记录列表。
        """
        rule = self.get_entry(rule_id)
        if not rule:
            return records
        for record in records:
            if target_field in record:
                result = self.cleanse_field_value(rule_id, str(record[target_field]))
                if result["ok"]:
                    # 清洗目标字段：标准化字段值并更新记录
                    record[target_field] = result["cleansed"]
                    record["_cleansed_fields"] = record.get("_cleansed_fields", [])
                    record["_cleansed_fields"].append(target_field)
        return records

    def validate_field_completeness(self, entity_model: str, records: list[dict[str, Any]],
                                     required_fields: list[str]) -> dict[str, Any]:
        """验证字段完整性：检查清洗后每条记录的必填字段是否均已填充。

        遍历清洗后的记录列表，逐一验证必填字段完整性，
        统计完备率、缺失字段分布和异常记录列表。
        """
        total = len(records)
        complete = 0
        field_missing: dict[str, int] = {}
        incomplete_records: list[dict[str, Any]] = []
        for i, record in enumerate(records):
            missing = [f for f in required_fields if not str(record.get(f, "")).strip()]
            if missing:
                incomplete_records.append({"index": i, "missing_fields": missing})
                for f in missing:
                    field_missing[f] = field_missing.get(f, 0) + 1
            else:
                complete += 1
        # 验证字段完整性：统计完备率和缺失字段分布
        completeness = round(complete / max(total, 1) * 100, 2)
        return {
            "entity_model": entity_model,
            "total_records": total,
            "complete_records": complete,
            "completeness_pct": completeness,
            "field_missing_distribution": field_missing,
            "incomplete_detail": incomplete_records,
        }

    def query_cleanse_rules_for_model(self, entity_model: str) -> list[dict[str, Any]]:
        """查询指定实体模型的所有已生效清洗规则，按先后顺序排列。

        遍历清洗规则存储，筛选已生效且匹配实体模型的规则，
        按先后顺序字段排序返回清洗规则执行序列。
        """
        rows = store.rows(self.MODULE)
        rules = [
            row for row in rows
            if row.get("实体模型") == entity_model and row.get("status") == "已生效"
        ]
        # 查询清洗规则并按先后顺序排序
        rules.sort(key=lambda r: int(r.get("先后顺序", "0") or "0"))
        return rules

    def standardize_field_values(self, records: list[dict[str, Any]],
                                  entity_model: str) -> list[dict[str, Any]]:
        """标准化字段值：对实体模型的所有记录执行完整清洗流水线。

        查询该实体模型的所有清洗规则，按先后顺序依次对每条记录的
        各目标字段执行标准化函数和修正字典转换，完成全链路清洗。
        """
        rules = self.query_cleanse_rules_for_model(entity_model)
        for rule in rules:
            target_field = rule.get("目标字段", "")
            if not target_field:
                continue
            for record in records:
                if target_field in record:
                    result = self.cleanse_field_value(rule["id"], str(record[target_field]))
                    if result["ok"]:
                        # 标准化字段值：执行完整清洗流水线并更新记录
                        record[target_field] = result["cleansed"]
        return records

    # ── 补值返工复验 ──

    def revalidate_rework_items(self, entity_model: str,
                                 records: list[dict[str, Any]] | None = None,
                                 *, source_records: list[dict[str, Any]] | None = None,
                                 verifier: str = "字段标准化清洗") -> dict[str, Any]:
        """复验改过的原始行：字段补齐后关闭对应返工项。

        原始行默认按“来源记录”唯一键合并：先取 source_record 中已修改的
        原始行，再用传入 records 覆盖同键行。复验只关闭本轮确实能取到
        非空值的返工项，未补齐的事项保持打开并回写复验结果。
        """
        merged = self._merge_source_rows(entity_model, records, source_records)
        closed: list[dict[str, Any]] = []
        still_open: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        for item in rework_rules.rework_rows(entity_model):
            if rework_rules.is_closed(item):
                continue
            source_record = str(item.get("来源记录") or item.get("源记录") or "")
            field = str(item.get("字段") or item.get("待补字段") or "")
            record = merged.get(source_record)
            if record is None:
                unmatched.append(item)
                continue
            value = rework_rules.field_value(record, field)
            if value.strip():
                rework_rules.close_rework_item(
                    item, verified_value=value, verifier=verifier)
                closed.append(item)
            else:
                item["复验时间"] = rework_rules.now_iso()
                item["复验值"] = value
                item["复验人"] = verifier
                item["补齐状态"] = "未补齐"
                item["可派发"] = rework_rules.is_dispatchable(item)
                still_open.append(item)
        return {
            "entity_model": entity_model,
            "closed": len(closed),
            "still_open": len(still_open),
            "unmatched": len(unmatched),
            "closed_ids": [row.get("id") for row in closed],
            "still_open_ids": [row.get("id") for row in still_open],
            "unmatched_ids": [row.get("id") for row in unmatched],
        }

    def revalidate_and_close_rework(self, entity_model: str,
                                     records: list[dict[str, Any]] | None = None,
                                     *, source_records: list[dict[str, Any]] | None = None,
                                     verifier: str = "字段标准化清洗") -> dict[str, Any]:
        """复验并关闭返工项：与 revalidate_rework_items 同一套复验规则。"""
        return self.revalidate_rework_items(
            entity_model, records, source_records=source_records, verifier=verifier)

    @staticmethod
    def _merge_source_rows(entity_model: str,
                            records: list[dict[str, Any]] | None,
                            source_records: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
        """按来源记录合并原始行，后传入的同键行覆盖先前的行。"""
        merged: dict[str, dict[str, Any]] = {}
        rows = source_records
        if rows is None:
            rows = [
                row for row in store.rows("source_record")
                if str(row.get("实体模型", entity_model)) == entity_model
            ]
        for index, row in enumerate(rows):
            key = rework_rules.source_record_id(row, index, entity_model)
            merged[key] = dict(row)
        for index, row in enumerate(records or []):
            key = rework_rules.source_record_id(row, index, entity_model)
            base = merged.get(key, {})
            combined = dict(base)
            combined.update(row)
            merged[key] = combined
        return merged