import pytest

from backend.app.analysis import analyze, chart_spec
from backend.app.compiler import compile_query
from backend.app.errors import DomainError
from backend.app.planner import QueryPlan


def test_aggregates_never_silently_truncate():
    plan = QueryPlan(
        metrics=["sales_amount"], dimensions=["sales_region"], time_range={"kind": "all"}
    ).validated(("2024-01-01", "2027-01-01"))
    compiled = compile_query(plan)
    with pytest.raises(DomainError) as error:
        analyze([{"sales_region": str(n), "sales_amount": "1.00"} for n in range(501)], compiled)
    assert error.value.code == "RESULT_TOO_LARGE"


def test_details_truncate_and_charts_reject_more_than_50_points():
    plan = QueryPlan(intent="detail", time_range={"kind": "all"}).validated(("2024-01-01", "2027-01-01"))
    data = analyze([{"id": n, "paid_amount": "1.00"} for n in range(1001)], compile_query(plan))
    assert data["truncated"] and len(data["rows"]) == 1000
    plan = QueryPlan(metrics=["sales_amount"], dimensions=["customer"])
    spec = chart_spec([{"customer": str(n), "sales_amount": "1.00"} for n in range(51)], plan)
    assert spec["type"] == "table"


def test_more_than_four_tables_rejected():
    plan = QueryPlan(
        metrics=["quantity"], dimensions=["category", "customer"], time_range={"kind": "all"}
    ).validated(("2024-01-01", "2027-01-01"))
    with pytest.raises(DomainError):
        compile_query(plan)
