import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from . import auth
from .errors import DomainError
from .llm import PlannerAdapter
from .preferences import ModelInput, MysqlInput, check_mysql

router = APIRouter(prefix="/api/settings")


def administrator(user=Depends(auth.current_user)):
    if user["role"] != "admin":
        raise DomainError("FORBIDDEN", "仅管理员可管理共享数据库连接。", 403)
    return user


@router.get("")
def preferences(request: Request, user=Depends(auth.current_user)):
    store = request.app.state.preferences
    return {"databases": store.sources(), "model": store.public_model(user["id"])}


@router.post("/databases/discover")
def discover(body: MysqlInput, user=Depends(administrator)):
    return {"databases": check_mysql(body.model_copy(update={"database": ""}), discover=True)}


@router.post("/databases/test")
def test_database(body: MysqlInput, user=Depends(administrator)):
    return check_mysql(body)


@router.post("/databases", status_code=201)
def add_database(body: MysqlInput, request: Request, user=Depends(administrator)):
    check_mysql(body)
    identifier = str(uuid.uuid4())
    request.app.state.preferences.put(
        "db:" + identifier,
        {
            "name": body.name,
            "url": body.url(),
            "data_start": body.data_start.isoformat(),
            "data_end": body.data_end.isoformat(),
        },
    )
    return {"id": identifier, "name": body.name}


@router.put("/model")
def save_model(body: ModelInput, request: Request, user=Depends(auth.current_user)):
    store = request.app.state.preferences
    store.put("model:" + user["id"], store.prepare_model(user["id"], body))
    return store.public_model(user["id"])


@router.post("/model/test")
async def test_model(body: ModelInput, request: Request, user=Depends(auth.current_user)):
    store = request.app.state.preferences
    model = store.prepare_model(user["id"], body)
    config = store.effective_config(model=model)
    if config.model_mode != "api":
        raise DomainError("INVALID_INPUT", "请选择 API 模式或已配置 API 的服务器默认设置。", 422)
    adapter = PlannerAdapter(config)
    try:
        plan, info = await adapter.plan(
            "查询全部历史销售额", [], datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        )
        if plan.action != "query":
            raise DomainError("INVALID_PLAN", "模型已响应，但未生成可执行的查询计划，请检查模型兼容性。", 422)
        plan.validated((config.data_start, config.data_end))
        return {
            "status": "success",
            "message": "模型调用成功，查询计划校验通过。",
            "model": info.get("model"),
        }
    finally:
        await adapter.close()
