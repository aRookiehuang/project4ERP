"""Explicit, non-destructive initialization. Refuses to overwrite an existing business dataset."""

import argparse
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from .app import models as m
from .app.auth import hash_password
from .app.config import ROOT, settings
from .app.db import engine_for


def seed_business(engine, count=3000, seed=42):
    m.business_meta.create_all(engine)
    with engine.begin() as conn:
        if conn.scalar(select(func.count()).select_from(m.orders)):
            raise RuntimeError("业务数据已存在；初始化不会覆盖。变体数据请使用新的数据库。")
        rng = random.Random(seed)
        standard = count >= 100_000
        customer_count, product_count, category_count, seller_count = (
            (10000, 1000, 20, 50) if standard else (80, 30, 5, 8)
        )
        regions = ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]
        category_names = ["办公设备", "数码配件", "办公耗材", "智能家居", "网络设备"]
        conn.execute(
            m.customers.insert(),
            [
                {
                    "id": n,
                    "customer_code": f"C{n:05}",
                    "name": "同名客户" if n in (1, 2) else f"模拟客户{n:04}",
                    "region": regions[n % len(regions)],
                }
                for n in range(1, customer_count + 1)
            ],
        )
        conn.execute(
            m.salespeople.insert(),
            [
                {"id": n, "name": f"销售员{n:02}", "department": "销售一部" if n % 2 else "销售二部"}
                for n in range(1, seller_count + 1)
            ],
        )
        conn.execute(
            m.categories.insert(),
            [
                {"id": n, "name": category_names[n - 1] if n <= 5 else f"商品类别{n:02}"}
                for n in range(1, category_count + 1)
            ],
        )
        conn.execute(
            m.products.insert(),
            [
                {
                    "id": n,
                    "sku": f"SKU{n:05}",
                    "name": f"模拟商品{n:04}",
                    "category_id": (n - 1) % category_count + 1,
                }
                for n in range(1, product_count + 1)
            ],
        )
        start = datetime.fromisoformat(settings.data_start)
        end = datetime.fromisoformat(settings.data_end)
        seconds = int((end - start).total_seconds()) - 86400
        orders, items = [], []
        item_id = 0
        for n in range(1, count + 1):
            created = start + timedelta(seconds=rng.randrange(seconds))
            status = rng.choices(
                ["PENDING", "CANCELLED", "PAID", "SHIPPED", "COMPLETED"], [8, 7, 15, 20, 50]
            )[0]
            amount = Decimal("0.00")
            for _ in range(3):
                item_id += 1
                quantity = rng.randint(1, 8)
                price = Decimal(rng.randint(100, 100000)) / 100
                paid = (price * quantity * Decimal(rng.choice(["0.8", "0.9", "1"]))).quantize(Decimal("0.01"))
                if n % 101 == 0:
                    paid = Decimal("0.00")
                amount += paid
                items.append(
                    {
                        "id": item_id,
                        "order_id": n,
                        "product_id": rng.randint(1, product_count),
                        "quantity": quantity,
                        "unit_price": price,
                        "line_paid_amount": paid,
                    }
                )
            orders.append(
                {
                    "id": n,
                    "order_no": f"SO{n:09}",
                    "customer_id": rng.randint(1, customer_count),
                    "salesperson_id": rng.randint(1, seller_count),
                    "sales_region": rng.choice(regions),
                    "status": status,
                    "created_at": created,
                    "paid_at": created + timedelta(hours=rng.randint(0, 23))
                    if status in ["PAID", "SHIPPED", "COMPLETED"]
                    else None,
                    "paid_amount": amount,
                }
            )
            if len(orders) == 1000 or n == count:
                conn.execute(m.orders.insert(), orders)
                conn.execute(m.order_items.insert(), items)
                orders, items = [], []
        totals = (
            select(m.order_items.c.order_id, func.sum(m.order_items.c.line_paid_amount).label("total"))
            .group_by(m.order_items.c.order_id)
            .subquery()
        )
        mismatches = conn.scalar(
            select(func.count())
            .select_from(m.orders.join(totals, m.orders.c.id == totals.c.order_id))
            .where(func.abs(m.orders.c.paid_amount - totals.c.total) > Decimal("0.005"))
        )
        if mismatches:
            raise RuntimeError("数据校验失败：订单与明细金额不一致")
    return {"orders": count, "order_items": count * 3, "seed": seed, "amount_mismatches": 0}


def seed_users(engine, password):
    m.app_meta.create_all(engine)
    with engine.begin() as conn:
        for username, role in [("demo", "user"), ("analyst", "user"), ("admin", "admin")]:
            if not conn.scalar(select(m.users.c.id).where(m.users.c.username == username)):
                conn.execute(
                    m.users.insert().values(
                        id=str(uuid.uuid4()),
                        username=username,
                        password_hash=hash_password(password),
                        role=role,
                    )
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--business-admin-url",
        help="仅用于初始化的建表/写入账号 URL；优先使用 ERP_SEED_DATABASE_URL 环境变量",
    )
    parser.add_argument("--app-only", action="store_true")
    args = parser.parse_args()
    import os

    if not 1 <= args.orders <= 1_000_000:
        parser.error("订单数量须为 1～1,000,000")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    business_url = (
        args.business_admin_url or os.environ.get("ERP_SEED_DATABASE_URL") or settings.business_database_url
    )
    if not args.app_only:
        business = engine_for(business_url)
        try:
            print(seed_business(business, args.orders, args.seed))
        finally:
            business.dispose()
    app_engine = engine_for(settings.app_database_url)
    seed_users(app_engine, settings.demo_password)
    app_engine.dispose()
    print("初始化完成。账号 demo / analyst / admin；密码来自 DEMO_PASSWORD（见配置）。")


if __name__ == "__main__":
    main()
