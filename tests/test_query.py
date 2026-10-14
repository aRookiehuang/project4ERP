from datetime import date
import threading

import pytest

from backend.app.analysis import analyze
from backend.app.compiler import compile_query
from backend.app.db import Database
from backend.app.errors import DomainError
from backend.app.llm import demo_plan
from backend.app.planner import QueryPlan, TimeRange
from backend.app.query import QueryService


def plan(**kwargs):
    return QueryPlan.model_validate(
        {"metrics": ["sales_amount"], "time_range": {"start": "2026-09-01", "end": "2026-10-01"}, **kwargs}
    ).validated(("2024-11-01", "2026-11-01"))


def run(engine, **kwargs):
    compiled = compile_query(plan(**kwargs), "sqlite")
    with engine.connect() as conn:
        rows = conn.execute(compiled.statement).mappings().all()
    return analyze(rows, compiled)


def test_order_totals_decimal_and_boundary(database):
    data = run(database, metrics=["sales_amount", "order_count", "average_order_value"])
    assert data["rows"] == [{"sales_amount": "600.00", "order_count": 4, "average_order_value": "150.00"}]
    assert "600.00" in data["answer"]


def test_four_table_category_no_double_count(database):
    data = run(database, dimensions=["category"], metrics=["sales_amount", "order_count", "quantity"])
    assert data["rows"] == [
        {"category": "类别甲", "category_id": 1, "sales_amount": "400.00", "order_count": 4, "quantity": 6},
        {"category": "类别乙", "category_id": 2, "sales_amount": "200.00", "order_count": 1, "quantity": 1},
    ]


def test_product_filter_exists_order_scope(database):
    data = run(database, amount_scope="order", filters={"conditions": [{"field": "product_id", "value": 1}]})
    assert data["rows"][0]["sales_amount"] == "400.00"
    data = run(database, amount_scope="item", filters={"conditions": [{"field": "product_id", "value": 1}]})
    assert data["rows"][0]["sales_amount"] == "200.00"


def test_multiple_item_conditions_match_same_line(database):
    data = run(
        database,
        amount_scope="order",
        filters={"conditions": [{"field": "product_id", "value": 1}, {"field": "category_id", "value": 2}]},
    )
    assert data["rows"][0]["sales_amount"] is None


def test_ambiguous_product_scope_and_aov():
    with pytest.raises(DomainError, match="请确认"):
        plan(filters={"conditions": [{"field": "product_id", "value": 1}]})
    with pytest.raises(DomainError, match="客单价"):
        plan(metrics=["average_order_value"], dimensions=["category"])


def test_duplicate_names_group_by_id(database):
    data = run(database, dimensions=["customer"], intent="ranking", top_n=2)
    assert [r["customer_id"] for r in data["rows"]] == [1, 3]


def test_ambiguous_entity_rejected(config, database):
    db = Database(config)
    service = QueryService(db, None, config)
    with pytest.raises(DomainError, match="重名"):
        service.resolve_entities(
            plan(filters={"conditions": [{"field": "customer_name", "value": "同名"}]}), threading.Event()
        )
    db.close()


def test_created_vs_paid_count(database):
    data = run(database, metrics=["placed_order_count"])
    assert data["rows"][0]["placed_order_count"] == 6
    with pytest.raises(DomainError):
        plan(metrics=["placed_order_count", "sales_amount"])


def test_unpaid_detail_uses_created_at(database):
    data = run(
        database,
        intent="detail",
        metrics=[],
        time_field="created_at",
        filters={"conditions": [{"field": "status", "value": "PENDING"}]},
    )
    assert len(data["rows"]) == 1 and data["rows"][0]["id"] == 6
    with pytest.raises(DomainError, match="时间字段"):
        plan(time_field="created_at")


def test_combined_amount_quantity_preserves_grain(database):
    data = run(database, metrics=["sales_amount", "quantity", "average_order_value"])
    assert data["rows"] == [{"sales_amount": "600.00", "quantity": 7, "average_order_value": "150.00"}]


def test_regions_use_order_snapshot(database):
    data = run(database, filters={"conditions": [{"field": "sales_region", "value": "华东"}]})
    assert data["rows"][0]["sales_amount"] == "400.00"
    data = run(database, filters={"conditions": [{"field": "customer_region", "value": "华东"}]})
    assert data["rows"][0]["sales_amount"] == "100.00"


def test_share_complete_denominator_with_other(database):
    data = run(database, intent="share", dimensions=["sales_region"], top_n=1, visualization="pie")
    assert data["statistics"]["total_sales_amount"] == "600.00"
    assert data["rows"][0]["sales_share"] == "66.67"
    assert data["rows"][1]["sales_region"] == "其他"
    assert data["rows"][1]["sales_amount"] == "200.00"


def test_empty_zero_and_null_are_different(database):
    data = run(
        database,
        time_range={"start": "2020-01-01", "end": "2020-02-01"},
        metrics=["sales_amount", "average_order_value"],
    )
    assert data["rows"][0] == {"sales_amount": None, "average_order_value": None}
    data = run(
        database,
        time_range={"start": "2026-09-10", "end": "2026-09-11"},
        metrics=["sales_amount", "average_order_value"],
    )
    assert data["rows"][0] == {"sales_amount": "0.00", "average_order_value": "0.00"}


def test_having_and_boolean_filters(database):
    data = run(
        database, dimensions=["sales_region"], having={"metric": "sales_amount", "op": "gt", "value": "300"}
    )
    assert len(data["rows"]) == 1 and data["rows"][0]["sales_region"] == "华东"
    data = run(
        database,
        filters={
            "logic": "or",
            "conditions": [
                {"field": "sales_region", "value": "华东"},
                {"field": "sales_region", "value": "华北"},
            ],
        },
    )
    assert data["rows"][0]["sales_amount"] == "600.00"


def test_time_gap_fill_only_additive(database):
    data = run(
        database,
        intent="trend",
        dimensions=["month"],
        time_range={"start": "2026-08-01", "end": "2026-11-01"},
    )
    assert [r["sales_amount"] for r in data["rows"]] == ["0.00", "600.00", "50.00"]
    data = run(
        database,
        intent="trend",
        dimensions=["month"],
        metrics=["average_order_value"],
        time_range={"start": "2026-08-01", "end": "2026-11-01"},
    )
    assert len(data["rows"]) == 2


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_parameters_not_interpolated(dialect):
    attack = "华东' OR 1=1; DROP TABLE orders; --"
    compiled = compile_query(
        plan(filters={"conditions": [{"field": "sales_region", "value": attack}]}), dialect
    )
    assert attack not in compiled.sql and attack in compiled.params.values()


def test_mysql_four_table_compiles():
    compiled = compile_query(plan(dimensions=["month", "category"], metrics=["sales_amount", "quantity"]))
    assert "date_format" in compiled.sql.lower()
    assert compiled.sql.count("JOIN") == 3


def test_month_rollover_and_leap_year():
    assert TimeRange(kind="last_month").resolve(("2020-01-01", "2030-01-01"), date(2024, 3, 3)).start == date(
        2024, 2, 1
    )
    assert TimeRange(kind="this_month").resolve(("2020-01-01", "2030-01-01"), date(2026, 12, 31)).end == date(
        2027, 1, 1
    )


def test_demo_followup_replaces_region():
    first = demo_plan("2026 年 9 月华东地区销售额最高的 5 个客户", [])
    second = demo_plan("只看华北地区", [{"plan": first.model_dump(mode="json")}])
    assert second.filters.conditions[0].value == "华北"
    assert second.time_range == first.time_range and second.top_n == 5
    assert demo_plan("销售额是多少？", []).action == "clarify"
