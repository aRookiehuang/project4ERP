"""Deterministic request constraints; model output is not user confirmation.

These checks supplement (not replace) the SQL AST allowlist and read-only account.
No case IDs, fixture dates, amounts or expected results are used here.
"""

import re
import unicodedata

from .errors import DomainError


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


def reject_unsafe_request(question):
    text = unicodedata.normalize("NFKC", question)
    # Keep SQL token boundaries. Strip comments to also detect obfuscated functions.
    sql = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    danger = (
        r"\b(?:delete\s+from|drop\s+(?:table|database)|truncate\s+table|"
        r"update\s+\w+\s+set|insert\s+into|alter\s+table|grant\s+|revoke\s+)|"
        r"\b(?:sleep|benchmark|load_file|pg_sleep)\s*\(|"
        r"\binto\s+(?:outfile|dumpfile)\b|\bunion\s+(?:all\s+)?select\b|"
        r"information_schema\s*\.|/etc/(?:passwd|shadow)|"
        r"(?:删除|清空|修改|更新|覆盖|写入).{0,25}(?:订单|数据库|数据表|记录)|"
        r"(?:读取|获取|返回|显示|查询|导出).{0,40}(?:密码|密钥|身份证|工资)|"
        r"忽略.{0,20}(?:系统|安全|限制|规则)"
    )
    if re.search(danger, sql, re.IGNORECASE | re.DOTALL):
        raise DomainError(
            "OUT_OF_SCOPE",
            "请求包含危险操作或敏感信息访问，已整体拒绝；请单独提交授权销售数据的只读分析问题。",
        )


def explicit_amount_scope(question):
    q = normalize(question)
    # A later clarification is the user's current choice, not an earlier alternative.
    q = q.rsplit("用户补充:", 1)[-1]
    q = re.sub(r"(?:不是|不要|不按|不统计|不计算|而非|并非)[^,，。；;]{0,20}", "", q)
    item = bool(
        re.search(
            r"明细(?:销售额|成交额|金额)|(?:按|统计|计算)(?:商品|该商品|这个商品)?明细|只(?:算|统计|计算)(?:该|这个)?商品",
            q,
        )
    )
    order = bool(re.search(r"整(?:张)?(?:订单|单)(?:的)?(?:金额|销售额)?|订单总(?:金额|额)", q))
    return "item" if item and not order else "order" if order and not item else None


def clarify_known_ambiguity(question, history=()):
    """Reject a known undefined grain before spending a model request.

    This mirrors QueryPlan.validated's product/category order-amount restriction.
    A clarification reply may replace the original metric, so inspect that reply.
    """
    full = normalize(question)
    q = full.rsplit("用户补充:", 1)[-1]
    grouped_items = re.search(r"(?:按|各|每个|每种)(?:商品类别|商品|产品|类别)", q)
    order_metric = re.search(r"客单价|平均订单金额|最高订单金额|最低订单金额", q)
    if grouped_items and order_metric:
        raise DomainError(
            "NEEDS_CLARIFICATION",
            "商品/类别分组下客单价及订单金额口径不明确，请改查销售额、销量或成交订单数，或明确订单级统计。",
        )
    continuation = bool(history) and bool(
        re.match(r"^(只看|改成|改为|换成|换为|再看|那|其中|按|本月|本年|全部历史|20\d{2}年)", q)
    )
    # Do not invent a dashboard's default metrics for a vague question.
    # Unknown/out-of-catalog metrics remain for the unsupported classifier.
    metric = re.search(
        r"销售额|成交额|实付|消费金额|订单数|下单数量|销量|销售量|销售数量|客户数|客单价|订单金额|销售占比|销售趋势",
        full,
    )
    listing = re.search(r"订单明细|订单列表|逐笔|逐条|列出.{0,20}订单", full)
    unsupported = re.search(r"库存|利润|成本|工资|同比|环比|预测|退款|净收入", full)
    generic = re.search(r"数据|情况|怎么样|如何|分析|统计|查询", full)
    if not continuation and not unsupported and (metric or listing or generic):
        if not metric and not listing:
            raise DomainError("NEEDS_CLARIFICATION", "请明确要分析的指标，例如销售额、成交订单数或销量。")
        has_time = re.search(
            r"20\d{2}(?:年|[-/])|本月|上月|今年|本年|去年|本周|上周|今天|昨天|最近\d+天|全部历史|全部数据",
            full,
        )
        if not has_time:
            if re.search(r"(?:\d{1,2}|[一二三四五六七八九十]+)月", full):
                raise DomainError("NEEDS_CLARIFICATION", "请补充年份，以确定查询的完整时间范围。")
            raise DomainError("NEEDS_CLARIFICATION", "请指定时间范围，例如本月、本年或全部历史。")


def enforce_request_semantics(question, plan, history):
    """Check user evidence independently of model-supplied amount_scope/intent."""
    if plan.action != "query":
        return plan
    q = normalize(question)
    item_filter = any(c.field.startswith(("product_", "category_")) for c in plan.filters.leaves())
    scope = explicit_amount_scope(question)
    # Only an explicit continuation may reuse an already checked scope.
    continuation = bool(re.match(r"^(只看|改成|改为|换成|换为|再看|那|其中)", q))
    if scope is None and continuation and history:
        prior = history[-1]["plan"]
        scope = explicit_amount_scope(history[-1].get("question", ""))
        if prior.get("amount_scope") != scope:
            scope = None
    wants_amount = bool(re.search(r"销售额|成交额|(?:明细|整单|整张订单)金额", q))
    wants_list = bool(re.search(r"列出|逐笔|逐条|订单列表|订单明细|明细列表", q))
    if (
        item_filter
        and not set(plan.dimensions) & {"product", "category"}
        and ("sales_amount" in plan.metrics or wants_amount and not wants_list)
    ):
        if scope is None:
            raise DomainError(
                "NEEDS_CLARIFICATION", "请确认统计该商品/类别的明细金额，还是包含它的整张订单金额。"
            )
        updates = {"amount_scope": scope}
        if plan.intent == "detail" and wants_amount and not wants_list:
            # A monetary aggregate is not a list of orders. Discard detail-only sorting.
            updates.update(
                intent="aggregate",
                metrics=["sales_amount"],
                sort=[s for s in plan.sort if s.field == "sales_amount"],
            )
        plan = plan.model_copy(update=updates)
    if plan.intent != "detail" and not re.search(r"图|表格|列表", q) and not continuation:
        plan = plan.model_copy(update={"visualization": "auto"})
    return plan
