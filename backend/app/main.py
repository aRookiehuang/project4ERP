import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from . import auth, models as m
from .analysis import chart_spec
from .config import ROOT, Settings, settings
from .db import Database
from .errors import DomainError
from .llm import PlannerAdapter
from .planner import ChartInput, ExportInput, LoginInput, QueryInput, QueryPlan, StrictModel
from .query import QueryService, owned, page_payload, snapshot
from .semantic import catalog


class ConversationInput(StrictModel):
    title: str = "新对话"


def create_app(config: Settings = settings):
    @asynccontextmanager
    async def lifespan(app):
        config.export_dir.mkdir(parents=True, exist_ok=True)
        app.state.db = Database(config)
        app.state.adapter = PlannerAdapter(config)
        app.state.query = QueryService(app.state.db, app.state.adapter, config)
        # A single API process owns query execution. Interrupted runs cannot stay running forever.
        with app.state.db.app.begin() as conn:
            conn.execute(
                update(m.query_runs)
                .where(m.query_runs.c.status == "running")
                .values(
                    status="failed",
                    response={
                        "status": "failed",
                        "code": "SERVER_RESTARTED",
                        "answer": "服务重启中断了查询，请重新发送。",
                    },
                )
            )
        yield
        await app.state.adapter.close()
        app.state.db.close()

    app = FastAPI(title="ERP 智能销售查询", version="0.1.0", lifespan=lifespan)
    login_attempts = defaultdict(deque)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in config.allowed_origins.split(","):
                return JSONResponse(
                    status_code=403,
                    content={"status": "failed", "code": "FORBIDDEN", "answer": "请求来源未获允许。"},
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "failed",
                "code": exc.code,
                "answer": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def input_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "status": "failed",
                "code": "INVALID_INPUT",
                "answer": "请求参数不合法，请检查输入。",
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "code": "INTERNAL_ERROR",
                "answer": "服务处理失败，请联系管理员并提供追溯 ID。",
                "request_id": request.state.request_id,
            },
        )

    @app.get("/api/health/ready")
    def ready(request: Request):
        try:
            with request.app.state.db.app.connect() as conn:
                conn.execute(select(m.users.c.id).limit(1))
            with request.app.state.db.business.connect() as conn:
                conn.execute(select(m.orders.c.id).limit(1))
        except Exception as exc:
            raise DomainError("NOT_READY", "数据库未就绪，请先执行初始化。", 503) from exc
        return {
            "status": "ready",
            "model_mode": config.model_mode,
            "model_configured": config.model_mode == "demo" or bool(config.model_api_key),
            "data_coverage": [config.data_start, config.data_end],
            "data_version": config.data_version,
            "database": request.app.state.db.business.dialect.name,
        }

    @app.get("/api/assets/chinese-font")
    def chinese_font():
        if not config.font_path.is_file():
            raise DomainError("NOT_FOUND", "中文字体尚未安装。", 404)
        return FileResponse(config.font_path, media_type="font/otf")

    @app.post("/api/auth/login")
    def login(body: LoginInput, request: Request, response: Response):
        key = request.client.host if request.client else "local"
        now = time.monotonic()
        attempts = login_attempts[key]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            raise DomainError("RATE_LIMITED", "登录尝试过多，请一分钟后再试。", 429)
        attempts.append(now)
        with request.app.state.db.app.connect() as conn:
            user = conn.execute(select(m.users).where(m.users.c.username == body.username)).mappings().first()
        # Always perform a password hash, even if the user is unknown.
        encoded = user["password_hash"] if user else auth.hash_password("dummy")
        if not auth.verify_password(body.password, encoded) or not user:
            raise DomainError("UNAUTHORIZED", "用户名或密码错误。", 401)
        auth.logout(request)
        token, csrf = auth.create_session(request.app.state.db.app, user["id"], config.session_hours)
        response.set_cookie(
            "erp_session",
            token,
            httponly=True,
            samesite="strict",
            secure=config.cookie_secure,
            max_age=config.session_hours * 3600,
            path="/",
        )
        return {"username": user["username"], "role": user["role"], "csrf_token": csrf}

    @app.get("/api/auth/me")
    def me(user=Depends(auth.current_user)):
        return {"username": user["username"], "role": user["role"], "csrf_token": user["csrf"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(auth.current_user)):
        auth.logout(request)
        response.delete_cookie("erp_session", path="/")
        return {"status": "success"}

    @app.get("/api/conversations")
    def list_conversations(request: Request, user=Depends(auth.current_user)):
        with request.app.state.db.app.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(m.conversations.c.id, m.conversations.c.title, m.conversations.c.created_at)
                    .where(m.conversations.c.user_id == user["id"])
                    .order_by(m.conversations.c.created_at.desc())
                    .limit(100)
                ).mappings()
            ]

    @app.post("/api/conversations", status_code=201)
    def new_conversation(body: ConversationInput, request: Request, user=Depends(auth.current_user)):
        identifier = str(uuid.uuid4())
        with request.app.state.db.app.begin() as conn:
            conn.execute(
                m.conversations.insert().values(
                    id=identifier, user_id=user["id"], title=body.title[:120], state=[]
                )
            )
        return {"id": identifier, "title": body.title[:120]}

    @app.get("/api/conversations/{identifier}")
    def get_conversation(identifier: str, request: Request, user=Depends(auth.current_user)):
        with request.app.state.db.app.connect() as conn:
            conversation = owned(conn, m.conversations, identifier, user["id"])
            runs = (
                conn.execute(
                    select(
                        m.query_runs.c.id,
                        m.query_runs.c.question,
                        m.query_runs.c.status,
                        m.query_runs.c.response,
                    )
                    .where(m.query_runs.c.conversation_id == identifier)
                    .order_by(m.query_runs.c.created_at, m.query_runs.c.id)
                )
                .mappings()
                .all()
            )
        messages = []
        for run in runs:
            message = dict(run)
            if message["response"] and message["response"].get("result_id"):
                try:
                    message["response"] = page_payload(
                        snapshot(request.app.state.db.app, message["response"]["result_id"], user["id"])
                    )
                except DomainError as exc:
                    message["response"] = {"status": "failed", "code": exc.code, "answer": exc.message}
            messages.append(message)
        return {"id": identifier, "title": conversation["title"], "messages": messages}

    @app.post("/api/conversations/{identifier}/queries")
    async def query(identifier: str, body: QueryInput, request: Request, user=Depends(auth.current_user)):
        return await request.app.state.query.run(identifier, user["id"], body, request)

    @app.get("/api/results/{identifier}")
    def get_result(
        identifier: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        user=Depends(auth.current_user),
    ):
        return page_payload(snapshot(request.app.state.db.app, identifier, user["id"]), page, page_size)

    @app.post("/api/results/{identifier}/chart")
    def change_chart(identifier: str, body: ChartInput, request: Request, user=Depends(auth.current_user)):
        payload = snapshot(request.app.state.db.app, identifier, user["id"])
        payload["chart_spec"] = chart_spec(
            payload["rows"], QueryPlan.model_validate(payload["plan"]), body.type
        )
        with request.app.state.db.app.begin() as conn:
            conn.execute(
                update(m.result_snapshots)
                .where(m.result_snapshots.c.id == identifier)
                .values(payload=payload)
            )
        return {"chart_spec": payload["chart_spec"]}

    @app.post("/api/results/{identifier}/exports", status_code=202)
    def create_export(identifier: str, body: ExportInput, request: Request, user=Depends(auth.current_user)):
        payload = snapshot(request.app.state.db.app, identifier, user["id"])
        export_id = str(uuid.uuid4())
        with request.app.state.db.app.begin() as conn:
            pending = conn.execute(
                select(m.export_jobs.c.id).where(
                    m.export_jobs.c.user_id == user["id"], m.export_jobs.c.status.in_(["pending", "running"])
                )
            ).all()
            if len(pending) >= 3:
                raise DomainError("OVERLOADED", "已有三个导出任务等待处理，请稍后再试。", 429)
            conn.execute(
                m.export_jobs.insert().values(
                    id=export_id,
                    user_id=user["id"],
                    result_id=identifier,
                    format=body.format,
                    include_sql=int(body.include_sql),
                    status="pending",
                    report=payload,
                    created_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(hours=config.export_hours),
                )
            )
        return {"id": export_id, "status": "pending"}

    def get_job(identifier, request, user):
        with request.app.state.db.app.connect() as conn:
            job = owned(conn, m.export_jobs, identifier, user["id"])
        if job["expires_at"] <= datetime.utcnow():
            job["status"] = "expired"
        return job

    @app.get("/api/exports/{identifier}")
    def export_status(identifier: str, request: Request, user=Depends(auth.current_user)):
        job = get_job(identifier, request, user)
        return {k: job[k] for k in ["id", "status", "format", "error", "checksum", "expires_at"]}

    @app.get("/api/exports/{identifier}/download")
    def download(identifier: str, request: Request, user=Depends(auth.current_user)):
        job = get_job(identifier, request, user)
        if job["status"] == "expired":
            raise DomainError("EXPORT_EXPIRED", "导出文件已过期，请重新导出。", 410)
        path = config.export_dir / f"{job['id']}.{job['format']}"
        if job["status"] != "succeeded" or not path.is_file():
            raise DomainError("EXPORT_NOT_READY", "导出文件尚未生成或生成失败。", 409)
        return FileResponse(path, filename=f"ERP销售报告-{identifier[:8]}.{job['format']}")

    @app.get("/api/admin/semantic-catalog")
    def semantic_catalog(user=Depends(auth.current_user)):
        if user["role"] != "admin":
            raise DomainError("FORBIDDEN", "仅管理员可查看。", 403)
        return catalog()

    @app.get("/api/admin/audit")
    def audit(request: Request, user=Depends(auth.current_user)):
        if user["role"] != "admin":
            raise DomainError("FORBIDDEN", "仅管理员可查看。", 403)
        with request.app.state.db.app.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(
                        m.query_runs.c.id,
                        m.query_runs.c.status,
                        m.query_runs.c.sql_fingerprint,
                        m.query_runs.c.timing,
                        m.query_runs.c.created_at,
                    )
                    .order_by(m.query_runs.c.created_at.desc())
                    .limit(100)
                ).mappings()
            ]

    frontend = ROOT / "frontend/dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
