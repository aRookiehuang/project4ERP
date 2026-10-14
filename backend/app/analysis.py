from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from itertools import product

from .errors import DomainError
from .planner import QueryPlan


def serialize_rows(rows, columns):
    result = []
    types = {c["key"]: c["type"] for c in columns}
    for row in rows:
        item = {}
        for key, value in dict(row).items():
            if value is None:
                item[key] = None
            elif types.get(key) == "decimal":
                item[key] = str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            elif isinstance(value, (date, datetime)):
                item[key] = value.isoformat()
            elif isinstance(value, Decimal):
                item[key] = int(value) if types.get(key) == "integer" else str(value)
            else:
                item[key] = value
        result.append(item)
    return result


def fill_time_gaps(rows: list[dict], plan: QueryPlan):
    time_dim = next((d for d in plan.dimensions if d in {"month", "day"}), None)
    additive = {"sales_amount", "quantity", "order_count", "placed_order_count", "customer_count"}
    if not time_dim or not set(plan.metrics) <= additive or not rows:
        return rows
    current, end = plan.time_range.start, plan.time_range.end
    points = []
    while current < end and len(points) <= 500:
        points.append(current.strftime("%Y-%m" if time_dim == "month" else "%Y-%m-%d"))
        current = (
            (current.replace(day=1) + timedelta(days=32)).replace(day=1)
            if time_dim == "month"
            else current + timedelta(days=1)
        )
    other = next((d for d in plan.dimensions if d != time_dim), None)
    entity_key = other + "_id" if other and other + "_id" in rows[0] else other
    entities = {r[entity_key]: r[other] for r in rows} if other else {None: None}
    if len(points) * len(entities) > 500:
        raise DomainError(
            "RESULT_TOO_LARGE", "补齐时间后超过 500 个分组，请缩小时间范围或改为按月统计。", 422
        )
    found = {(r[time_dim], r.get(entity_key)): r for r in rows}
    filled = []
    for point, entity in product(points, entities):
        row = found.get((point, entity))
        if row is None:
            row = {time_dim: point, **{m: "0.00" if m == "sales_amount" else 0 for m in plan.metrics}}
            if other:
                row[other] = entities[entity]
                if entity_key != other:
                    row[entity_key] = entity
        filled.append(row)
    return filled


def chart_spec(rows, plan: QueryPlan, requested: str | None = None):
    kind = requested or plan.visualization
    if kind == "table":
        return {"type": "table", "reason": "已按选择仅展示表格。"}
    if plan.intent == "detail" or not rows:
        return {"type": "table", "reason": "明细或空结果仅展示表格。"}
    if not plan.dimensions:
        return {"type": "card", "metrics": plan.metrics}
    if len(rows) > 50:
        return {"type": "table", "reason": "超过 50 个图表数据点，请缩小范围、修改粒度或明确 Top N。"}
    x = next((d for d in plan.dimensions if d in {"month", "day"}), plan.dimensions[0])
    if kind in {"auto", "card"}:
        kind = "line" if x in {"month", "day"} else "bar"
    if kind == "line" and x not in {"month", "day"}:
        kind = "bar"
    if kind == "pie" and (
        len(plan.dimensions) != 1
        or len(plan.metrics) != 1
        or len(rows) > 6
        or any(r[plan.metrics[0]] is None or Decimal(str(r[plan.metrics[0]])) < 0 for r in rows)
    ):
        return {"type": "table", "reason": "占比图要求一个维度、一个非负指标且不超过 6 项。"}
    if kind == "pie" and plan.intent != "share" and plan.top_n:
        return {"type": "table", "reason": "Top N 的占比需要完整分母，请使用销售占比查询。"}
    return {
        "type": kind,
        "x": x,
        "series": plan.metrics,
        "group": next((d for d in plan.dimensions if d != x), None),
        "data": rows,
    }


def analyze(raw_rows, compiled):
    plan, columns = compiled.plan, compiled.columns
    rows = serialize_rows(raw_rows, columns)
    truncated = plan.intent == "detail" and len(rows) > 1000
    if plan.intent != "detail" and len(rows) > 500:
        raise DomainError("RESULT_TOO_LARGE", "完整结果超过 500 个分组，请缩小查询范围。", 422)
    if plan.intent == "detail":
        rows = rows[:1000]
    if plan.intent == "trend" and not plan.having and not plan.sort and not plan.top_n:
        rows = fill_time_gaps(rows, plan)
    statistics = {"scope": "完整筛选范围", "group_count": len(rows)}
    if plan.intent == "share":
        total = sum((Decimal(r["sales_amount"] or "0") for r in rows), Decimal(0))
        statistics["total_sales_amount"] = str(total.quantize(Decimal("0.01")))
        if plan.top_n and len(rows) > plan.top_n:
            kept, rest = rows[: plan.top_n], rows[plan.top_n :]
            other = {k: None for k in rows[0]}
            other.update(
                {
                    plan.dimensions[0]: "其他",
                    "sales_amount": str(
                        sum((Decimal(r["sales_amount"] or "0") for r in rest), Decimal(0)).quantize(
                            Decimal("0.01")
                        )
                    ),
                }
            )
            rows = kept + [other]
        for row in rows:
            row["sales_share"] = (
                str((Decimal(row["sales_amount"] or "0") / total * 100).quantize(Decimal("0.01")))
                if total
                else None
            )
        columns.append({"key": "sales_share", "label": "销售占比", "unit": "%", "type": "decimal"})
    elif plan.top_n:
        rows = rows[: plan.top_n]
        statistics["scope"] = f"当前范围内前 {plan.top_n} 项；不代表全部分组总额"
    if not rows or (
        not plan.dimensions
        and plan.intent != "detail"
        and all(r.get(metric) is None or r.get(metric) == 0 for r in rows for metric in plan.metrics)
    ):
        answer = "本条件下无有效数据。空集金额为空；无有效订单时客单价不计算。"
    elif plan.intent == "detail":
        answer = f"已保存 {len(rows)} 条订单明细。" + (
            "结果超过上限，仅保留前 1,000 条。" if truncated else ""
        )
    elif not plan.dimensions:
        answer = (
            "；".join(
                f"{c['label']}：{rows[0].get(c['key']) if rows[0].get(c['key']) is not None else '无有效订单'} {c['unit']}"
                for c in columns
                if c["key"] in plan.metrics
            )
            + "。"
        )
    else:
        metric = plan.metrics[0]
        valid = [r for r in rows if r.get(metric) is not None]
        peak = max(valid, key=lambda r: Decimal(str(r[metric]))) if valid else None
        answer = f"返回 {len(rows)} 个分组。"
        if peak:
            label = " / ".join(str(peak[d]) for d in plan.dimensions)
            meta = next(c for c in columns if c["key"] == metric)
            answer += f"当前展示范围内，{label}的{meta['label']}最高，为 {peak[metric]} {meta['unit']}。"
        if plan.top_n:
            answer += statistics["scope"] + "。"
    return {
        "rows": rows,
        "columns": columns,
        "statistics": statistics,
        "answer": answer,
        "truncated": truncated,
        "chart_spec": chart_spec(rows, plan),
    }
