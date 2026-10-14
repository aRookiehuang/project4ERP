VERSION = "erp-sales-v1"
METRICS = {
    "sales_amount": {
        "label": "销售额",
        "unit": "元",
        "definition": "有效订单实付金额之和；商品/类别维度使用成交明细金额",
        "type": "decimal",
    },
    "order_count": {
        "label": "成交订单数",
        "unit": "单",
        "definition": "有效订单的不同订单 ID 数量",
        "type": "integer",
    },
    "placed_order_count": {
        "label": "下单数量",
        "unit": "单",
        "definition": "按下单时间统计不同订单，默认含全部状态",
        "type": "integer",
    },
    "quantity": {"label": "销量", "unit": "件", "definition": "有效订单明细数量之和", "type": "integer"},
    "customer_count": {
        "label": "成交客户数",
        "unit": "人",
        "definition": "有效订单的不同客户 ID 数量",
        "type": "integer",
    },
    "average_order_value": {
        "label": "客单价",
        "unit": "元/单",
        "definition": "销售额 / 成交订单数；无订单时为空",
        "type": "decimal",
    },
    "min_order_amount": {
        "label": "最低订单金额",
        "unit": "元",
        "definition": "有效订单最小实付金额",
        "type": "decimal",
    },
    "max_order_amount": {
        "label": "最高订单金额",
        "unit": "元",
        "definition": "有效订单最大实付金额",
        "type": "decimal",
    },
}
DIMENSIONS = {
    "month": "月份",
    "day": "日期",
    "sales_region": "销售地区",
    "customer_region": "客户当前地区",
    "customer": "客户",
    "salesperson": "销售人员",
    "product": "商品",
    "category": "商品类别",
    "status": "订单状态",
}
FILTERS = {
    "sales_region",
    "customer_region",
    "status",
    "customer_id",
    "salesperson_id",
    "product_id",
    "category_id",
    "customer_name",
    "product_name",
    "category_name",
    "salesperson_name",
    "paid_amount",
}
VALID_STATUSES = ["PAID", "SHIPPED", "COMPLETED"]
TABLES = {
    "orders": [
        "id",
        "order_no",
        "customer_id",
        "salesperson_id",
        "sales_region",
        "status",
        "created_at",
        "paid_at",
        "paid_amount",
    ],
    "order_items": ["id", "order_id", "product_id", "quantity", "unit_price", "line_paid_amount"],
    "customers": ["id", "customer_code", "name", "region"],
    "salespeople": ["id", "name", "department"],
    "products": ["id", "sku", "name", "category_id"],
    "categories": ["id", "name"],
}


def catalog():
    return {
        "version": VERSION,
        "metrics": METRICS,
        "dimensions": DIMENSIONS,
        "filters": sorted(FILTERS),
        "tables": TABLES,
        "timezone": "Asia/Shanghai",
        "valid_statuses": VALID_STATUSES,
        "relations": [
            "orders.customer_id = customers.id",
            "orders.salesperson_id = salespeople.id",
            "order_items.order_id = orders.id",
            "order_items.product_id = products.id",
            "products.category_id = categories.id",
        ],
    }
