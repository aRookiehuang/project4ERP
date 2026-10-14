import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from . import models as m
from .analysis import analyze
from .cancellation import QueryCancellation
from .compiler import compile_query
from .errors import DomainError
from .planner import Condition, FilterGroup, QueryInput
from .semantic import METRICS, VERSION


def owned(conn, table, identifier, user_id):
    row = (
        conn.execute(select(table).where(table.c.id == identifier, table.c.user_id == user_id))
        .mappings()
        .first()
    )
    if not row:
        raise DomainError("NOT_FOUND", "记录不存在或无权访问。", 404)
    return dict(row)


def snapshot(db, result_id, user_id):
    with db.connect() as conn:
        row = owned(conn, m.result_snapshots, result_id, user_id)
    if row["expires_at"] <= datetime.utcnow():
        raise DomainError("RESULT_EXPIRED", "结果已过期，请重新查询。", 410)
    return row["payload"]


def page_payload(payload, page=1, page_size=20):
    result = dict(payload)
    result["total_rows"] = len(payload["rows"])
    result["page"] = page
    result["page_size"] = page_size
    result["rows"] = payload["rows"][(page - 1) * page_size : page * page_size]
    return result


class QueryService:
    def __init__(self, db, adapter, config):
        self.db, self.adapter, self.config = db, adapter, config
        self.active = set()
        self.slots = asyncio.Semaphore(config.max_concurrency)

    def resolve_entities(self, plan, cancelled):
        entities = {
            "customer_name": (m.customers, "customer_id"),
            "product_name": (m.products, "product_id"),
            "category_name": (m.categories, "category_id"),
            "salesperson_name": (m.salespeople, "salesperson_id"),
        }
        replacements = {}
        with self.db.business.connect() as conn:
            for condition in plan.filters.leaves():
                if cancelled.is_set():
                    raise DomainError("QUERY_CANCELLED", "查询已取消。", 499)
                if condition.field not in entities:
                    continue
                if condition.op != "eq":
                    raise DomainError(
                        "NEEDS_CLARIFICATION", "实体名称需要明确等值选择；可用 ID 区分同名实体。"
                    )
                table, id_field = entities[condition.field]
                ids = (
                    conn.execute(select(table.c.id).where(table.c.name == condition.value).limit(3))
                    .scalars()
                    .all()
                )
                if not ids:
                    raise DomainError("NEEDS_CLARIFICATION", f"未找到实体“{condition.value}”，请核对名称。")
                if len(ids) > 1:
                    raise DomainError(
                        "NEEDS_CLARIFICATION",
                        f"实体“{condition.value}”重名，请指定 ID：{'、'.join(map(str, ids))}。",
                    )
                replacements[id(condition)] = Condition(field=id_field, value=ids[0])

        def replace(group):
            return FilterGroup(
                logic=group.logic,
                conditions=[
                    replace(c) if isinstance(c, FilterGroup) else replacements.get(id(c), c)
                    for c in group.conditions
                ],
            )

        return plan.model_copy(update={"filters": replace(plan.filters)})

    def execute(self, plan, cancelled):
        plan = self.resolve_entities(plan, cancelled)
        started = time.perf_counter()
        dialect = self.db.business.dialect.name
        compiled = compile_query(plan, dialect)
        validation_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        with self.db.business.connect() as conn:
            raw = conn.connection.driver_connection
            deadline = time.monotonic() + self.config.query_timeout_ms / 1000
            if dialect == "sqlite":
                raw.set_progress_handler(lambda: int(cancelled.is_set() or time.monotonic() > deadline), 500)
                if isinstance(cancelled, QueryCancellation):
                    cancelled.attach(raw.interrupt)
            elif isinstance(cancelled, QueryCancellation):
                connection_id = raw.thread_id()
                cancelled.attach(lambda: self.db.interrupt_mysql(connection_id))
            try:
                if cancelled.is_set():
                    raise DomainError("QUERY_CANCELLED", "查询已取消。", 499)
                rows = conn.execute(compiled.statement).mappings().fetchall()
                if cancelled.is_set() or time.monotonic() > deadline:
                    raise DomainError("QUERY_TIMEOUT", "数据库查询超时或已取消，请缩小范围后重试。", 504)
                data = analyze(rows, compiled)
                if len(json.dumps(data, ensure_ascii=False).encode()) > self.config.max_result_bytes:
                    raise DomainError("RESULT_TOO_LARGE", "结果字节数超限，请缩小范围。", 422)
            except DBAPIError as exc:
                conn.invalidate()
                code = getattr(exc.orig, "args", [None])[0]
                if (
                    code in (3024, 1317)
                    or "interrupt" in str(exc.orig).lower()
                    or time.monotonic() >= deadline
                ):
                    raise DomainError("QUERY_TIMEOUT", "数据库执行已超时，请缩小查询范围。", 504) from exc
                raise DomainError(
                    "QUERY_FAILED", "数据库执行失败，请检查数据库状态或联系管理员。", 503
                ) from exc
            finally:
                if isinstance(cancelled, QueryCancellation):
                    cancelled.detach()
                if dialect == "sqlite":
                    try:
                        raw.set_progress_handler(None, 0)
                    except Exception:
                        pass
                if cancelled.is_set():
                    conn.invalidate()
        return (
            data,
            compiled,
            {
                "validate_ms": round(validation_ms, 2),
                "db_analysis_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )

    async def run(self, conversation_id: str, user_id: str, body: QueryInput, request):
        started = time.perf_counter()
        with self.db.app.connect() as conn:
            conversation = owned(conn, m.conversations, conversation_id, user_id)
            existing = (
                conn.execute(
                    select(m.query_runs).where(
                        m.query_runs.c.conversation_id == conversation_id,
                        m.query_runs.c.idempotency_key == body.idempotency_key,
                    )
                )
                .mappings()
                .first()
            )
        if existing:
            if existing["question"] != body.question:
                raise DomainError("IDEMPOTENCY_CONFLICT", "相同幂等键不能用于不同问题。", 409)
            if existing["response"]:
                response = existing["response"]
                if response.get("result_id"):
                    return page_payload(snapshot(self.db.app, response["result_id"], user_id))
                return response
            raise DomainError("QUERY_IN_PROGRESS", "该问题仍在处理中，请稍后查看会话。", 409)
        if conversation_id in self.active:
            raise DomainError("QUERY_IN_PROGRESS", "本会话已有查询正在执行，请稍候。", 409)
        if len(self.active) >= self.config.max_concurrency:
            raise DomainError("OVERLOADED", "当前查询较多，请稍后重试。", 429)
        self.active.add(conversation_id)
        query_id = str(uuid.uuid4())
        cancelled = QueryCancellation()
        task = None
        try:
            with self.db.app.begin() as conn:
                conn.execute(
                    m.query_runs.insert().values(
                        id=query_id,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        idempotency_key=body.idempotency_key,
                        question=body.question,
                        status="running",
                    )
                )

            async def pipeline():
                question = body.question
                state = conversation["state"]
                if body.clarification_ref:
                    with self.db.app.connect() as conn:
                        prior = owned(conn, m.query_runs, body.clarification_ref, user_id)
                    if (
                        prior["conversation_id"] != conversation_id
                        or prior["status"] != "needs_clarification"
                    ):
                        raise DomainError("INVALID_PLAN", "澄清引用不属于当前会话的待澄清问题。", 422)
                    question = prior["question"] + "；用户补充：" + question
                llm_start = time.perf_counter()
                plan, model_info = await self.adapter.plan(
                    question, state[-5:], datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
                )
                timing = {"llm_ms": round((time.perf_counter() - llm_start) * 1000, 2)}
                if plan.action != "query":
                    return {
                        "status": "needs_clarification" if plan.action == "clarify" else "unsupported",
                        "query_id": query_id,
                        "question": body.question,
                        "answer": plan.clarification or "请补充查询条件。",
                    }, None
                plan = plan.validated((self.config.data_start, self.config.data_end))
                data, compiled, db_timing = await asyncio.to_thread(self.execute, plan, cancelled)
                timing.update(db_timing)
                timing["server_ms"] = round((time.perf_counter() - started) * 1000, 2)
                payload = {
                    "status": "success",
                    "query_id": query_id,
                    "result_id": str(uuid.uuid4()),
                    "question": question,
                    "interpreted_question": question,
                    "assumptions": [
                        "人民币；Asia/Shanghai；时间区间左闭右开。",
                        "按下单时间统计全部状态。"
                        if plan.time_field == "created_at"
                        else "按支付时间统计 PAID / SHIPPED / COMPLETED。",
                    ],
                    "time_range": plan.time_range.model_dump(mode="json"),
                    "metric_definitions": {metric: METRICS[metric] for metric in plan.metrics},
                    "sql_display": compiled.sql,
                    "snapshot_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "data_coverage": [self.config.data_start, self.config.data_end],
                    "versions": {
                        "semantic": VERSION,
                        "data": self.config.data_version,
                        "prompt": "v1",
                        **model_info,
                    },
                    "timing": timing,
                    "plan": plan.model_dump(mode="json"),
                    **data,
                }
                return payload, plan

            task = asyncio.create_task(pipeline())
            deadline = time.monotonic() + self.config.request_timeout_seconds
            while not task.done():
                if await request.is_disconnected():
                    cancelled.set()
                    raise DomainError("QUERY_CANCELLED", "客户端已取消查询。", 499)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    cancelled.set()
                    raise DomainError("QUERY_TIMEOUT", "查询超过请求截止时间，请稍后重试。", 504)
                await asyncio.wait({task}, timeout=min(0.05, remaining))
            payload, plan = await task
            with self.db.app.begin() as conn:
                if plan:
                    conn.execute(
                        m.result_snapshots.insert().values(
                            id=payload["result_id"],
                            user_id=user_id,
                            conversation_id=conversation_id,
                            payload=payload,
                            expires_at=datetime.utcnow() + timedelta(days=self.config.snapshot_days),
                        )
                    )
                    state = (
                        conversation["state"]
                        + [{"question": body.question, "plan": plan.model_dump(mode="json")}]
                    )[-5:]
                    conn.execute(
                        update(m.conversations)
                        .where(m.conversations.c.id == conversation_id)
                        .values(state=state)
                    )
                conn.execute(
                    update(m.query_runs)
                    .where(m.query_runs.c.id == query_id)
                    .values(
                        status=payload["status"],
                        response=page_payload(payload) if plan else payload,
                        plan=plan.model_dump(mode="json") if plan else None,
                        timing=payload.get("timing"),
                        sql_fingerprint=hashlib.sha256(payload.get("sql_display", "").encode()).hexdigest(),
                    )
                )
            return page_payload(payload) if plan else payload
        except DomainError as exc:
            status = {"NEEDS_CLARIFICATION": "needs_clarification", "OUT_OF_SCOPE": "unsupported"}.get(
                exc.code, "failed"
            )
            response = {
                "status": status,
                "query_id": query_id,
                "question": body.question,
                "code": exc.code,
                "answer": exc.message,
                "timing": {"server_ms": round((time.perf_counter() - started) * 1000, 2)},
            }
            with self.db.app.begin() as conn:
                conn.execute(
                    update(m.query_runs)
                    .where(m.query_runs.c.id == query_id)
                    .values(status=status, response=response)
                )
            if status == "failed":
                raise
            return response
        except asyncio.CancelledError:
            cancelled.set()
            with self.db.app.begin() as conn:
                conn.execute(
                    update(m.query_runs)
                    .where(m.query_runs.c.id == query_id)
                    .values(
                        status="failed",
                        response={
                            "status": "failed",
                            "query_id": query_id,
                            "question": body.question,
                            "answer": "请求已取消。",
                            "code": "QUERY_CANCELLED",
                        },
                    )
                )
            raise
        except Exception as exc:
            with self.db.app.begin() as conn:
                conn.execute(
                    update(m.query_runs)
                    .where(m.query_runs.c.id == query_id)
                    .values(
                        status="failed",
                        response={
                            "status": "failed",
                            "query_id": query_id,
                            "question": body.question,
                            "answer": "查询处理失败。",
                            "code": "QUERY_FAILED",
                        },
                    )
                )
            raise DomainError("QUERY_FAILED", "查询处理失败，请稍后重试。", 503) from exc
        finally:
            if task and not task.done():
                cancelled.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.active.discard(conversation_id)
