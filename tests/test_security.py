import pytest
from pydantic import ValidationError

from backend.app.errors import DomainError
from backend.app.planner import QueryPlan
from backend.app.sql_guard import validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT orders.id FROM orders LIMIT 1; DROP TABLE orders",
        "SELECT SLEEP(10) FROM orders LIMIT 1",
        "SELECT BENCHMARK(10000,1) FROM orders LIMIT 1",
        "SELECT LOAD_FILE('/etc/passwd') FROM orders LIMIT 1",
        "SELECT @@version FROM orders LIMIT 1",
        "SELECT @secret FROM orders LIMIT 1",
        "SELECT orders.id INTO OUTFILE '/tmp/x' FROM orders LIMIT 1",
        "SELECT user FROM mysql.user LIMIT 1",
        "SELECT orders.id FROM erp_demo.orders LIMIT 1",
        "SELECT orders.id FROM orders FOR UPDATE LIMIT 1",
        "SELECT orders.id FROM orders LOCK IN SHARE MODE LIMIT 1",
        "SELECT /* bypass */ orders.id FROM orders LIMIT 1",
        "SELECT /*!50000 SLEEP(5) */ orders.id FROM orders LIMIT 1",
        "SELECT orders.id FROM orders CROSS JOIN customers LIMIT 1",
        "SELECT orders.id FROM orders JOIN customers ON 1=1 LIMIT 1",
        "SELECT orders.id FROM orders JOIN customers ON orders.id=customers.id LIMIT 1",
        "SELECT * FROM orders LIMIT 1",
        "SELECT orders.unknown FROM orders LIMIT 1",
        "SELECT orders.id FROM orders",
        "WITH x AS (SELECT 1) SELECT orders.id FROM orders LIMIT 1",
        "SELECT my_udf(orders.id) FROM orders LIMIT 1",
        "SELECT orders.id FROM orders UNION SELECT customers.id FROM customers LIMIT 1",
    ],
)
def test_ast_rejects_dangerous_sql(sql):
    with pytest.raises(DomainError):
        validate_sql(sql)


def test_plan_identifier_injection():
    with pytest.raises(ValidationError):
        QueryPlan(metrics=["SUM(orders.paid_amount)"])
    with pytest.raises(ValidationError):
        QueryPlan(filters={"conditions": [{"field": "orders.id OR 1=1", "value": 1}]})


def test_readonly_connection(config, database):
    from backend.app.db import Database
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    db = Database(config)
    with db.business.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("DELETE FROM orders"))
    db.close()
