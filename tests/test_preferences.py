import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from backend.app import models as m
from backend.app.db import engine_for
from backend.app.main import create_app
from backend.app.planner import QueryPlan
from backend.app.preferences import Preferences
from backend.app.llm import PlannerAdapter


def login(client, config, username):
    result = client.post("/api/auth/login", json={"username": username, "password": config.demo_password})
    assert result.status_code == 200
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]


def api_model(**changes):
    return {
        "mode": "api",
        "base_url": "https://model.example/v1",
        "model": "test-model",
        "api_key": "secret-test-key",
        "timeout_seconds": 30,
        **changes,
    }


def test_model_encryption_retention_and_user_isolation(client, config):
    response = client.put("/api/settings/model", json=api_model())
    assert response.status_code == 200, response.text
    assert response.json()["has_api_key"]
    assert "secret-test-key" not in response.text
    assert "api_key" not in response.json()
    response = client.put("/api/settings/model", json=api_model(api_key="", model="another-model"))
    assert response.status_code == 200
    assert (
        client.put(
            "/api/settings/model", json=api_model(api_key="", base_url="https://other.example/v1")
        ).status_code
        == 422
    )
    engine = engine_for(config.app_database_url)
    with engine.connect() as conn:
        encrypted = conn.scalar(select(m.runtime_settings.c.value))
        user_id = conn.scalar(select(m.users.c.id).where(m.users.c.username == "demo"))
    assert "secret-test-key" not in encrypted and "model.example" not in encrypted
    assert Preferences(engine, config).model(user_id)["api_key"] == "secret-test-key"
    login(client, config, "analyst")
    own = client.get("/api/settings").json()["model"]
    assert own["mode"] == "server" and not own["has_api_key"]
    assert client.put("/api/settings/model", json=api_model(api_key="")).status_code == 422
    engine.dispose()


def test_settings_permissions_and_invalid_endpoints(client, config, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "backend.app.settings_routes.check_mysql",
        lambda body, **kw: calls.append(body) or {"status": "success"},
    )
    body = {"host": "localhost", "username": "reader", "password": "db-secret", "database": "erp"}
    for endpoint in ("databases", "databases/test", "databases/discover"):
        assert client.post("/api/settings/" + endpoint, json=body).status_code == 403
    assert not calls
    assert (
        client.put("/api/settings/model", json=api_model(base_url="file:///tmp/private")).status_code == 422
    )
    assert (
        client.put(
            "/api/settings/model", json=api_model(base_url="https://user:password@example.com")
        ).status_code
        == 422
    )
    assert (
        client.put("/api/settings/model", json=api_model(), headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    login(client, config, "admin")
    added = client.post("/api/settings/databases", json=body)
    assert added.status_code == 201
    public = client.get("/api/settings")
    assert len(public.json()["databases"]) == 2
    assert "db-secret" not in public.text and "reader" not in public.text
    assert calls


def test_selected_source_query_history_and_persistence(client, config, tmp_path):
    # Independent business DB with a deliberately different result.
    second_url = f"sqlite:///{tmp_path}/second.db"
    first, second = engine_for(config.business_database_url), engine_for(second_url)
    m.business_meta.create_all(second)
    with first.connect() as source, second.begin() as target:
        for table in m.business_meta.sorted_tables:
            rows = [dict(row) for row in source.execute(select(table)).mappings()]
            if rows:
                target.execute(table.insert(), rows)
        target.execute(update(m.orders).where(m.orders.c.id == 1).values(paid_amount=1000))
    app_engine = engine_for(config.app_database_url)
    identifier = str(uuid.uuid4())
    Preferences(app_engine, config).put(
        "db:" + identifier,
        {
            "name": "第二业务库",
            "url": second_url,
            "data_start": config.data_start,
            "data_end": config.data_end,
        },
    )
    assert client.post("/api/conversations", json={"source_id": "unknown"}).status_code == 404
    conversations = [
        client.post("/api/conversations", json={"source_id": source}).json()["id"]
        for source in ("default", identifier)
    ]
    for conversation, expected in zip(conversations, ("600.00", "1300.00")):
        response = client.post(
            f"/api/conversations/{conversation}/queries",
            json={
                "question": "2026 年 9 月销售额",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows"][0]["sales_amount"] == expected
    assert client.get(f"/api/conversations/{conversations[1]}").json()["source_id"] == identifier
    with TestClient(create_app(config)) as restarted:
        login(restarted, config, "demo")
        assert restarted.get(f"/api/conversations/{conversations[1]}").json()["source_id"] == identifier
        assert len(restarted.get("/api/settings").json()["databases"]) == 2
    first.dispose()
    second.dispose()
    app_engine.dispose()


def test_saved_model_is_used_for_real_query_and_connection_test(client, monkeypatch):
    calls = []

    def init(adapter, config):
        adapter.settings = config
        adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        plan = QueryPlan.model_validate(
            {
                "intent": "aggregate",
                "metrics": ["sales_amount"],
                "time_range": {"kind": "absolute", "start": "2026-09-01", "end": "2026-10-01"},
            }
        )
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": plan.model_dump_json()}}]}
        )

    monkeypatch.setattr(PlannerAdapter, "__init__", init)
    assert client.put("/api/settings/model", json=api_model()).status_code == 200
    probe = client.post("/api/settings/model/test", json=api_model(api_key=""))
    assert probe.status_code == 200, probe.text
    conv = client.post("/api/conversations", json={}).json()["id"]
    response = client.post(
        f"/api/conversations/{conv}/queries",
        json={"question": "九月营收如何", "idempotency_key": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    assert response.json()["versions"]["mode"] == "api"
    assert response.json()["versions"]["model"] == "test-model"
    assert response.json()["rows"][0]["sales_amount"] == "600.00"
    assert len(calls) == 2
    assert str(calls[0].url) == "https://model.example/v1/chat/completions"


def test_missing_encryption_key_does_not_replace_saved_secrets(client, config):
    assert client.put("/api/settings/model", json=api_model()).status_code == 200
    original = config.config_key_path.read_bytes()
    config.config_key_path.unlink()
    response = client.get("/api/settings")
    assert response.status_code == 503 and response.json()["code"] == "CONFIG_KEY_MISSING"
    assert not config.config_key_path.exists()
    config.config_key_path.write_bytes(original)
    assert client.get("/api/settings").status_code == 200
