from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)

business_meta = MetaData()
customers = Table(
    "customers",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("customer_code", String(30), unique=True, nullable=False),
    Column("name", String(100), nullable=False),
    Column("region", String(30), nullable=False),
)
salespeople = Table(
    "salespeople",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("department", String(100), nullable=False),
)
categories = Table(
    "categories",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
)
products = Table(
    "products",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("sku", String(30), unique=True, nullable=False),
    Column("name", String(100), nullable=False),
    Column("category_id", ForeignKey("categories.id"), nullable=False, index=True),
)
orders = Table(
    "orders",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("order_no", String(30), unique=True, nullable=False),
    Column("customer_id", ForeignKey("customers.id"), nullable=False),
    Column("salesperson_id", ForeignKey("salespeople.id"), nullable=False, index=True),
    Column("sales_region", String(30), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("paid_at", DateTime),
    Column("paid_amount", Numeric(18, 2), nullable=False),
    CheckConstraint("status IN ('PENDING','CANCELLED','PAID','SHIPPED','COMPLETED')"),
    CheckConstraint("status NOT IN ('PAID','SHIPPED','COMPLETED') OR paid_at IS NOT NULL"),
    CheckConstraint("paid_amount >= 0"),
    Index("ix_orders_paid_status", "paid_at", "status"),
    Index("ix_orders_region_paid", "sales_region", "paid_at"),
    Index("ix_orders_customer_paid", "customer_id", "paid_at"),
)
order_items = Table(
    "order_items",
    business_meta,
    Column("id", Integer, primary_key=True),
    Column("order_id", ForeignKey("orders.id"), nullable=False, index=True),
    Column("product_id", ForeignKey("products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(18, 2), nullable=False),
    Column("line_paid_amount", Numeric(18, 2), nullable=False),
    CheckConstraint("quantity > 0"),
    CheckConstraint("line_paid_amount >= 0"),
    Index("ix_items_product_order", "product_id", "order_id"),
)

app_meta = MetaData()
users = Table(
    "users",
    app_meta,
    Column("id", String(36), primary_key=True),
    Column("username", String(50), unique=True, nullable=False),
    Column("password_hash", String(256), nullable=False),
    Column("role", String(20), nullable=False),
)
sessions = Table(
    "sessions",
    app_meta,
    Column("id", String(64), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("csrf", String(64), nullable=False),
    Column("expires_at", DateTime, nullable=False),
)
conversations = Table(
    "conversations",
    app_meta,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String(120), nullable=False),
    Column("state", JSON, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)
query_runs = Table(
    "query_runs",
    app_meta,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", ForeignKey("conversations.id"), nullable=False),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("idempotency_key", String(100), nullable=False),
    Column("question", Text, nullable=False),
    Column("status", String(30), nullable=False),
    Column("response", JSON),
    Column("plan", JSON),
    Column("sql_fingerprint", String(64)),
    Column("timing", JSON),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
    UniqueConstraint("conversation_id", "idempotency_key"),
)
result_snapshots = Table(
    "result_snapshots",
    app_meta,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("conversation_id", ForeignKey("conversations.id"), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("expires_at", DateTime, nullable=False),
)
export_jobs = Table(
    "export_jobs",
    app_meta,
    Column("id", String(36), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("result_id", ForeignKey("result_snapshots.id"), nullable=False),
    Column("format", String(10), nullable=False),
    Column("include_sql", Integer, nullable=False, default=0),
    Column("report", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("error", String(200)),
    Column("checksum", String(64)),
    Column("created_at", DateTime, nullable=False),
    Column("started_at", DateTime),
    Column("expires_at", DateTime, nullable=False),
)
