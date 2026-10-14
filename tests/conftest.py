from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import models as m
from backend.app.config import Settings
from backend.app.db import engine_for
from backend.app.main import create_app
from backend.seed import seed_users


@pytest.fixture
def config(tmp_path):
    return Settings(
        _env_file=None,
        app_database_url=f"sqlite:///{tmp_path}/app.db",
        business_database_url=f"sqlite:///{tmp_path}/business.db",
        export_dir=tmp_path / "exports",
        model_mode="demo",
        demo_password="test-password",
        data_start="2024-11-01",
        data_end="2026-11-01",
    )


@pytest.fixture
def database(config):
    engine = engine_for(config.business_database_url)
    m.business_meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            m.customers.insert(),
            [
                {"id": 1, "customer_code": "C1", "name": "同名", "region": "华南"},
                {"id": 2, "customer_code": "C2", "name": "同名", "region": "华东"},
                {"id": 3, "customer_code": "C3", "name": "第三客户", "region": "华北"},
            ],
        )
        conn.execute(m.salespeople.insert(), [{"id": 1, "name": "销售甲", "department": "销售部"}])
        conn.execute(m.categories.insert(), [{"id": 1, "name": "类别甲"}, {"id": 2, "name": "类别乙"}])
        conn.execute(
            m.products.insert(),
            [
                {"id": 1, "sku": "P1", "name": "商品甲", "category_id": 1},
                {"id": 2, "sku": "P2", "name": "商品乙", "category_id": 2},
                {"id": 3, "sku": "P3", "name": "商品丙", "category_id": 1},
            ],
        )
        cases = [
            (1, 1, "COMPLETED", "2026-09-01", "华东", [(1, 2, 100), (2, 1, 200)]),
            (2, 2, "PAID", "2026-09-30", "华东", [(1, 1, 100)]),
            (3, 1, "CANCELLED", "2026-09-10", "华东", [(1, 1, 999)]),
            (4, 1, "PAID", "2026-10-01", "华东", [(1, 1, 50)]),
            (5, 1, "COMPLETED", "2026-09-10", "华东", [(1, 1, 0)]),
            (6, 1, "PENDING", "2026-09-10", "华东", [(1, 1, 125)]),
            (7, 3, "SHIPPED", "2026-09-20", "华北", [(3, 2, 200)]),
        ]
        item_id = 0
        for identifier, customer, status, date, region, items in cases:
            conn.execute(
                m.orders.insert().values(
                    id=identifier,
                    order_no=f"SO{identifier}",
                    customer_id=customer,
                    salesperson_id=1,
                    status=status,
                    created_at=datetime.fromisoformat(date),
                    paid_at=datetime.fromisoformat(date)
                    if status in ["PAID", "SHIPPED", "COMPLETED"]
                    else None,
                    sales_region=region,
                    paid_amount=sum(Decimal(str(x[2])) for x in items),
                )
            )
            for product, quantity, amount in items:
                item_id += 1
                conn.execute(
                    m.order_items.insert().values(
                        id=item_id,
                        order_id=identifier,
                        product_id=product,
                        quantity=quantity,
                        unit_price=Decimal(str(amount)) / quantity,
                        line_paid_amount=Decimal(str(amount)),
                    )
                )
    app = engine_for(config.app_database_url)
    seed_users(app, config.demo_password)
    app.dispose()
    yield engine
    engine.dispose()


@pytest.fixture
def client(config, database):
    with TestClient(create_app(config)) as client:
        result = client.post("/api/auth/login", json={"username": "demo", "password": config.demo_password})
        assert result.status_code == 200
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        yield client
