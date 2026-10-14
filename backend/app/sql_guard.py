import sqlglot
from sqlglot import exp

from .errors import DomainError
from .semantic import TABLES

# A deliberately small AST language. New compiler operators must be reviewed here.
ALLOWED_NODES = {
    "Select",
    "From",
    "Table",
    "TableAlias",
    "Identifier",
    "Column",
    "Alias",
    "Literal",
    "Placeholder",
    "Where",
    "And",
    "Or",
    "Not",
    "Paren",
    "EQ",
    "NEQ",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "In",
    "Is",
    "Null",
    "Offset",
    "Like",
    "Escape",
    "Join",
    "Group",
    "Order",
    "Ordered",
    "Limit",
    "Distinct",
    "Star",
    "Having",
    "Count",
    "Sum",
    "Avg",
    "Min",
    "Max",
    "Coalesce",
    "Nullif",
    "Div",
    "Cast",
    "DataType",
    "DataTypeParam",
    "TimeToStr",
    "TsOrDsToDate",
    "TsOrDsToTimestamp",
    "StrToTime",
    "Exists",
    "Subquery",
    "Neg",
    "Add",
}
RELATIONS = {
    frozenset(("orders.customer_id", "customers.id")),
    frozenset(("orders.salesperson_id", "salespeople.id")),
    frozenset(("order_items.order_id", "orders.id")),
    frozenset(("order_items.product_id", "products.id")),
    frozenset(("products.category_id", "categories.id")),
}


def validate_sql(sql: str, dialect: str = "mysql"):
    def reject():
        raise DomainError("FORBIDDEN", "查询未通过只读 SQL 安全校验。", 403)

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError:
        reject()
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        reject()
    root = statements[0]
    if not root.args.get("limit"):
        reject()
    tables = list(root.find_all(exp.Table))
    if len({t.name for t in tables}) > 4 or len(tables) != len({t.name for t in tables}):
        reject()
    for table in tables:
        if table.name not in TABLES or table.db or table.catalog or table.alias:
            reject()
    aliases = {a.alias for a in root.find_all(exp.Alias)}
    for node in root.walk():
        if type(node).__name__ not in ALLOWED_NODES or node.comments:
            reject()
        if isinstance(node, exp.Column):
            if node.table:
                if node.table not in TABLES or node.name not in TABLES[node.table]:
                    reject()
            elif node.name not in aliases:
                reject()
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            reject()
        if isinstance(node, exp.Join):
            on = node.args.get("on")
            if not isinstance(on, exp.EQ) or not all(isinstance(c, exp.Column) for c in (on.left, on.right)):
                reject()
            if frozenset((on.left.sql(), on.right.sql())) not in RELATIONS:
                reject()
            if node.args.get("kind") not in (None, "INNER", "OUTER") or node.args.get("side") not in (
                None,
                "LEFT",
            ):
                reject()
    return root
