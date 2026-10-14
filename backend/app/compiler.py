from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import and_, bindparam, cast, distinct, exists, func, literal_column, Numeric, or_, select
from sqlalchemy.dialects import mysql, sqlite

from . import models as m
from .errors import DomainError
from .planner import Condition, FilterGroup, QueryPlan
from .semantic import DIMENSIONS, METRICS, VALID_STATUSES
from .sql_guard import validate_sql


@dataclass
class CompiledQuery:
    sql: str
    params: dict
    columns: list[dict]
    plan: QueryPlan
    limit: int
    statement: object


def compile_query(plan: QueryPlan, dialect: str = "mysql") -> CompiledQuery:
    o, i, p, c, s, k = m.orders, m.order_items, m.products, m.customers, m.salespeople, m.categories
    fields = {
        "sales_region": o.c.sales_region,
        "customer_region": c.c.region,
        "status": o.c.status,
        "customer_id": o.c.customer_id,
        "salesperson_id": o.c.salesperson_id,
        "product_id": i.c.product_id,
        "category_id": p.c.category_id,
        "customer_name": c.c.name,
        "product_name": p.c.name,
        "category_name": k.c.name,
        "salesperson_name": s.c.name,
        "paid_amount": o.c.paid_amount,
    }
    item_fields = {"product_id", "category_id", "product_name", "category_name"}
    leaf_fields = {x.field for x in plan.filters.leaves()}
    item_dimensions = bool(set(plan.dimensions) & {"product", "category"})
    use_items = plan.intent != "detail" and (
        item_dimensions or "quantity" in plan.metrics or plan.amount_scope == "item"
    )
    if (
        use_items
        and not item_dimensions
        and leaf_fields & item_fields
        and plan.amount_scope != "item"
        and set(plan.metrics) & {"sales_amount", "average_order_value"}
    ):
        raise DomainError(
            "OUT_OF_SCOPE", "销量与订单金额混合统计存在粒度差异，请分开查询或明确使用明细金额。"
        )
    time_field = o.c[plan.time_field or ("created_at" if "placed_order_count" in plan.metrics else "paid_at")]
    required = {o}
    if use_items:
        required.add(i)
    dimension_expr = {
        "sales_region": o.c.sales_region,
        "customer_region": c.c.region,
        "status": o.c.status,
        "customer": c.c.name,
        "salesperson": s.c.name,
        "product": p.c.name,
        "category": k.c.name,
    }
    id_expr = {"customer": c.c.id, "salesperson": s.c.id, "product": p.c.id, "category": k.c.id}
    for d in plan.dimensions:
        if d not in {"month", "day"}:
            required.add(dimension_expr[d].table)
    for f in leaf_fields:
        if f not in item_fields or use_items:
            required.add(fields[f].table)
    if k in required:
        required |= {p, i}
    if p in required:
        required.add(i)

    def join_from(base, tables):
        joins = [
            (i, o.c.id == i.c.order_id),
            (p, i.c.product_id == p.c.id),
            (k, p.c.category_id == k.c.id),
            (c, o.c.customer_id == c.c.id),
            (s, o.c.salesperson_id == s.c.id),
        ]
        result = base
        for table, on in joins:
            if table in tables and table is not base:
                result = result.join(table, on, isouter=table in {c, s})
        return result

    params_counter = 0

    def condition_sql(condition: Condition):
        nonlocal params_counter
        field = fields[condition.field]
        params_counter += 1
        value = condition.value
        if condition.op in {"is_null", "not_null"}:
            return field.is_(None) if condition.op == "is_null" else field.is_not(None)
        if condition.op == "contains":
            value = "%" + str(value).replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        param = bindparam(f"f{params_counter}", value, expanding=condition.op == "in")
        return {
            "eq": lambda: field == param,
            "ne": lambda: field != param,
            "gt": lambda: field > param,
            "gte": lambda: field >= param,
            "lt": lambda: field < param,
            "lte": lambda: field <= param,
            "in": lambda: field.in_(param),
            "contains": lambda: field.like(param, escape="!"),
        }[condition.op]()

    def group_sql(group: FilterGroup):
        expressions = []
        for condition in group.conditions:
            if isinstance(condition, FilterGroup):
                expressions.append(group_sql(condition))
            else:
                expr = condition_sql(condition)
                if condition.field in item_fields and not use_items:
                    tables = {i}
                    if condition.field in {"category_id", "product_name", "category_name"}:
                        tables.add(p)
                    if condition.field == "category_name":
                        tables.add(k)
                    expr = exists(
                        select(literal_column("1"))
                        .select_from(join_from(i, tables))
                        .where(i.c.order_id == o.c.id, expr)
                    )
                expressions.append(expr)
        return (
            (and_ if group.logic == "and" else or_)(*expressions)
            if expressions
            else literal_column("1") == literal_column("1")
        )

    # Multiple item predicates must match the same line; put them in one EXISTS.
    item_conditions = [x for x in plan.filters.leaves() if x.field in item_fields]
    filters = plan.filters
    if not use_items and len(item_conditions) > 1:
        if filters.logic != "and" or any(isinstance(x, FilterGroup) for x in filters.conditions):
            raise DomainError("OUT_OF_SCOPE", "复杂商品条件请使用商品维度分组后查询。")
        outer = FilterGroup(conditions=[x for x in filters.conditions if x.field not in item_fields])
        item_tables = {i}
        if any(x.field != "product_id" for x in item_conditions):
            item_tables.add(p)
        if any(x.field == "category_name" for x in item_conditions):
            item_tables.add(k)
        filter_expr = and_(
            group_sql(outer),
            exists(
                select(literal_column("1"))
                .select_from(join_from(i, item_tables))
                .where(i.c.order_id == o.c.id, *[condition_sql(x) for x in item_conditions])
            ),
        )
    else:
        filter_expr = group_sql(filters)
    amount = func.sum(i.c.line_paid_amount if use_items else o.c.paid_amount)
    expressions = {
        "sales_amount": amount,
        "order_count": func.count(distinct(o.c.id)),
        "placed_order_count": func.count(distinct(o.c.id)),
        "quantity": func.sum(i.c.quantity),
        "customer_count": func.count(distinct(o.c.customer_id)),
        "average_order_value": amount / cast(func.nullif(func.count(distinct(o.c.id)), 0), Numeric(18, 2)),
        "min_order_amount": func.min(o.c.paid_amount),
        "max_order_amount": func.max(o.c.paid_amount),
    }
    columns, projections, groups, stable = [], [], [], []
    sort_fields = {}
    if plan.intent == "detail":
        for key, label, unit in [
            ("id", "订单 ID", ""),
            ("order_no", "订单号", ""),
            ("sales_region", "销售地区", ""),
            ("status", "状态", ""),
            ("created_at", "下单时间", ""),
            ("paid_at", "支付时间", ""),
            ("paid_amount", "订单金额", "元"),
        ]:
            projections.append(o.c[key].label(key))
            columns.append({"key": key, "label": label, "unit": unit, "type": "decimal" if unit else "text"})
            sort_fields[key] = o.c[key]
        stable = [o.c.id]
    else:
        for d in plan.dimensions:
            if d in {"month", "day"}:
                pattern = "%Y-%m" if d == "month" else "%Y-%m-%d"
                expr = (
                    func.strftime(pattern, time_field)
                    if dialect == "sqlite"
                    else func.date_format(time_field, pattern)
                )
            else:
                expr = dimension_expr[d]
            projections.append(expr.label(d))
            groups.append(expr)
            columns.append({"key": d, "label": DIMENSIONS[d], "unit": "", "type": "text"})
            sort_fields[d] = expr
            if d in id_expr:
                projections.append(id_expr[d].label(d + "_id"))
                groups.append(id_expr[d])
                stable.append(id_expr[d])
                columns.append(
                    {"key": d + "_id", "label": DIMENSIONS[d] + " ID", "unit": "", "type": "integer"}
                )
            else:
                stable.append(expr)
        for metric in plan.metrics:
            projections.append(expressions[metric].label(metric))
            columns.append({"key": metric, **METRICS[metric]})
            sort_fields[metric] = expressions[metric]
    if not plan.time_range or not plan.time_range.start or not plan.time_range.end:
        raise DomainError("INVALID_PLAN", "时间范围尚未解析。")
    statement = (
        select(*projections)
        .select_from(join_from(o, required))
        .where(
            time_field >= bindparam("time_start", datetime.combine(plan.time_range.start, time.min)),
            time_field < bindparam("time_end", datetime.combine(plan.time_range.end, time.min)),
            filter_expr,
        )
    )
    if "placed_order_count" not in plan.metrics and not (
        plan.intent == "detail" and plan.time_field == "created_at"
    ):
        statement = statement.where(
            o.c.status.in_(bindparam("valid_statuses", VALID_STATUSES, expanding=True))
        )
    if groups:
        statement = statement.group_by(*groups)
    if plan.having:
        h = plan.having
        field, value = expressions[h.metric], bindparam("having_value", h.value)
        statement = statement.having(
            {
                "gt": field > value,
                "gte": field >= value,
                "lt": field < value,
                "lte": field <= value,
                "eq": field == value,
            }[h.op]
        )
    ordering = [
        sort_fields[s.field].asc() if s.direction == "asc" else sort_fields[s.field].desc() for s in plan.sort
    ]
    if not ordering and plan.intent in {"ranking", "share"}:
        ordering = [expressions[plan.metrics[0]].desc()]
    statement = statement.order_by(*ordering, *[x.asc() for x in stable])
    # Fetch complete grouped results first, then Top N; never derive a share denominator from Top N.
    limit = 1001 if plan.intent == "detail" else 501
    if plan.intent == "detail" and plan.top_n:
        limit = plan.top_n
    if plan.intent not in {"detail", "share"} and plan.top_n:
        if plan.top_n > 500:
            raise DomainError("RESULT_TOO_LARGE", "聚合排名最多返回 500 个完整分组。", 422)
        limit = plan.top_n
    statement = statement.limit(limit)
    sql_dialect = (
        sqlite.dialect(paramstyle="named") if dialect == "sqlite" else mysql.dialect(paramstyle="named")
    )
    compiled = statement.compile(dialect=sql_dialect, compile_kwargs={"render_postcompile": True})
    sql = str(compiled)
    validate_sql(sql, dialect)
    return CompiledQuery(sql, compiled.params, columns, plan, limit, statement)
