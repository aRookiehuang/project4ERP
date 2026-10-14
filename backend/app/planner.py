from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import DomainError
from .semantic import DIMENSIONS, FILTERS, METRICS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(StrictModel):
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "is_null", "not_null"] = "eq"
    value: str | int | float | list[str | int] | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.field not in FILTERS:
            raise ValueError("不支持的筛选字段")
        if self.op == "in" and (not isinstance(self.value, list) or not 1 <= len(self.value) <= 50):
            raise ValueError("集合筛选需要 1～50 个值")
        if self.op not in {"in", "is_null", "not_null"} and (
            self.value is None or isinstance(self.value, list)
        ):
            raise ValueError("筛选值类型不合法")
        if self.op == "contains" and not isinstance(self.value, str):
            raise ValueError("包含查询需要文本")
        if self.field.endswith("_id") and self.op not in {"is_null", "not_null"}:
            for value in self.value if isinstance(self.value, list) else [self.value]:
                if not str(value).isdigit() or int(str(value)) < 1:
                    raise ValueError("实体 ID 必须为正整数")
        if self.field == "paid_amount" and self.value is not None:
            for value in self.value if isinstance(self.value, list) else [self.value]:
                if not Decimal(str(value)).is_finite():
                    raise ValueError("金额必须为有限数值")
        return self


class FilterGroup(StrictModel):
    logic: Literal["and", "or"] = "and"
    conditions: list[Condition | FilterGroup] = Field(default_factory=list, max_length=8)

    def leaves(self):
        for condition in self.conditions:
            if isinstance(condition, FilterGroup):
                yield from condition.leaves()
            else:
                yield condition

    def depth(self):
        return 1 + max((c.depth() for c in self.conditions if isinstance(c, FilterGroup)), default=0)


class TimeRange(StrictModel):
    kind: Literal["absolute", "this_month", "last_month", "this_year", "last_30_days", "all"] = "absolute"
    start: date | None = None
    end: date | None = None

    def resolve(self, coverage: tuple[str, str], today: date | None = None):
        today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if self.kind == "all":
            start, end = map(date.fromisoformat, coverage)
        elif self.kind == "this_year":
            start, end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
        elif self.kind in {"this_month", "last_month"}:
            first = today.replace(day=1)
            if self.kind == "last_month":
                start, end = (first - timedelta(days=1)).replace(day=1), first
            else:
                start = first
                end = (first + timedelta(days=32)).replace(day=1)
        elif self.kind == "last_30_days":
            start, end = today - timedelta(days=29), today + timedelta(days=1)
        else:
            start, end = self.start, self.end
        if start is None or end is None:
            raise DomainError("NEEDS_CLARIFICATION", "请提供完整时间范围（含年份），例如 2026 年 9 月。")
        if start >= end:
            raise DomainError("INVALID_PLAN", "开始日期必须早于结束日期。")
        return TimeRange(start=start, end=end)


class Sort(StrictModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class Having(StrictModel):
    metric: str
    op: Literal["gt", "gte", "lt", "lte", "eq"]
    value: Decimal


class QueryPlan(StrictModel):
    action: Literal["query", "clarify", "unsupported"] = "query"
    intent: Literal["aggregate", "detail", "ranking", "trend", "share"] = "aggregate"
    metrics: list[str] = Field(default_factory=list, max_length=3)
    dimensions: list[str] = Field(default_factory=list, max_length=2)
    filters: FilterGroup = Field(default_factory=FilterGroup)
    time_range: TimeRange | None = None
    time_field: Literal["paid_at", "created_at"] | None = None
    sort: list[Sort] = Field(default_factory=list, max_length=3)
    top_n: int | None = Field(default=None, ge=1, le=1000)
    visualization: Literal["auto", "bar", "line", "pie", "table", "card"] = "auto"
    amount_scope: Literal["order", "item"] | None = None
    clarification: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_catalog(self):
        if any(m not in METRICS for m in self.metrics) or any(d not in DIMENSIONS for d in self.dimensions):
            raise ValueError("指标或维度不在目录内")
        if len(set(self.metrics)) != len(self.metrics) or len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("指标、维度不能重复")
        if len(list(self.filters.leaves())) > 8 or self.filters.depth() > 2:
            raise ValueError("筛选条件最多 8 个、2 层")
        return self

    having: Having | None = None

    def validated(self, coverage: tuple[str, str], today: date | None = None):
        if self.action != "query":
            return self
        if not self.time_range:
            raise DomainError("NEEDS_CLARIFICATION", "请指定时间范围：本月、本年或全部历史。")
        if self.intent != "detail" and not self.metrics:
            raise DomainError("NEEDS_CLARIFICATION", "请指定指标，例如销售额、成交订单数或销量。")
        if "placed_order_count" in self.metrics and len(self.metrics) > 1:
            raise DomainError("OUT_OF_SCOPE", "下单数量与成交指标时间及状态口径不同，请分别查询。")
        expected_time = "created_at" if "placed_order_count" in self.metrics else "paid_at"
        if self.intent != "detail" and self.time_field not in {None, expected_time}:
            raise DomainError("INVALID_PLAN", "时间字段与指标口径不一致。")
        item_dims = set(self.dimensions) & {"product", "category"}
        if item_dims and set(self.metrics) & {"average_order_value", "min_order_amount", "max_order_amount"}:
            raise DomainError(
                "NEEDS_CLARIFICATION",
                "商品/类别维度下订单金额与客单价口径不明确，请改查销售额、销量或成交订单数。",
            )
        item_filter = any(c.field.startswith(("product_", "category_")) for c in self.filters.leaves())
        if item_filter and not item_dims and "sales_amount" in self.metrics and self.amount_scope is None:
            raise DomainError(
                "NEEDS_CLARIFICATION", "请确认统计该商品的明细金额，还是包含该商品的整张订单金额。"
            )
        if self.intent == "detail" and (self.dimensions or self.having):
            raise DomainError("INVALID_PLAN", "订单明细不支持分组或聚合筛选。")
        if self.intent == "share" and (
            self.metrics != ["sales_amount"] or len(self.dimensions) != 1 or self.having
        ):
            raise DomainError("OUT_OF_SCOPE", "销售占比需要一个分组维度和销售额指标，暂不支持 HAVING。")
        allowed_sort = set(self.metrics + self.dimensions)
        if self.intent == "detail":
            allowed_sort |= {"paid_amount", "created_at", "paid_at", "id"}
        if any(s.field not in allowed_sort for s in self.sort):
            raise DomainError("INVALID_PLAN", "排序字段必须包含在查询结果中。")
        if self.having and (self.having.metric not in self.metrics or not self.having.value.is_finite()):
            raise DomainError("INVALID_PLAN", "聚合筛选必须使用已选择的指标和有限数值。")
        if "day" in self.dimensions and "month" in self.dimensions:
            raise DomainError("INVALID_PLAN", "请选择日或月中的一种时间粒度。")
        return self.model_copy(
            update={
                "time_range": self.time_range.resolve(coverage, today),
                "time_field": self.time_field or expected_time,
            }
        )


class QueryInput(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=100)
    clarification_ref: str | None = None


class LoginInput(StrictModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class ExportInput(StrictModel):
    format: Literal["docx", "pdf"]
    include_sql: bool = False


class ChartInput(StrictModel):
    type: Literal["bar", "line", "pie", "table", "card"]
