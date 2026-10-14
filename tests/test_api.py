import uuid

from sqlalchemy import select, update

from backend.app import models as m
from backend.app.db import engine_for


def ask(client, conversation, question, **kwargs):
    return client.post(
        f"/api/conversations/{conversation}/queries",
        json={"question": question, "idempotency_key": str(uuid.uuid4()), **kwargs},
    )


def test_full_query_followup_snapshot_and_idempotency(client, config):
    conversation = client.post("/api/conversations", json={"title": "测试"}).json()["id"]
    key = str(uuid.uuid4())
    result = ask(client, conversation, "2026 年 9 月销售额是多少？", idempotency_key=key)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["rows"][0]["sales_amount"] == "600.00"
    again = ask(client, conversation, "2026 年 9 月销售额是多少？", idempotency_key=key)
    assert again.json()["result_id"] == data["result_id"]
    assert ask(client, conversation, "另一个问题", idempotency_key=key).status_code == 409
    followup = ask(client, conversation, "只看华东地区").json()
    assert followup["rows"][0]["sales_amount"] == "400.00"
    writer = engine_for(config.business_database_url)
    with writer.begin() as conn:
        conn.execute(update(m.orders).where(m.orders.c.id == 1).values(paid_amount=99999))
    writer.dispose()
    saved = client.get(f"/api/results/{data['result_id']}").json()
    assert saved["rows"][0]["sales_amount"] == "600.00"
    assert len(client.get(f"/api/conversations/{conversation}").json()["messages"]) == 2


def test_clarification_and_rejection(client):
    conv = client.post("/api/conversations", json={}).json()["id"]
    clarify = ask(client, conv, "销售额是多少？").json()
    assert clarify["status"] == "needs_clarification"
    answer = ask(client, conv, "2026 年 9 月", clarification_ref=clarify["query_id"]).json()
    assert answer["status"] == "success" and answer["rows"][0]["sales_amount"] == "600.00"
    assert ask(client, conv, "预测明年利润").json()["status"] == "unsupported"


def test_user_isolation_csrf_and_admin(client, config):
    conv = client.post("/api/conversations", json={}).json()["id"]
    result = ask(client, conv, "2026 年 9 月销售额").json()["result_id"]
    job = client.post(f"/api/results/{result}/exports", json={"format": "docx"}).json()["id"]
    login = client.post(
        "/api/auth/login", json={"username": "analyst", "password": config.demo_password}
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    assert client.get(f"/api/conversations/{conv}").status_code == 404
    assert client.get(f"/api/results/{result}").status_code == 404
    assert client.post(f"/api/results/{result}/chart", json={"type": "pie"}).status_code == 404
    assert client.post(f"/api/results/{result}/exports", json={"format": "pdf"}).status_code == 404
    assert client.get(f"/api/exports/{job}").status_code == 404
    assert client.get(f"/api/exports/{job}/download").status_code == 404
    assert client.get("/api/admin/semantic-catalog").status_code == 403
    assert client.post("/api/conversations", json={}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "demo", "password": "bad"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )


def test_export_frozen_at_creation(client, config):
    conv = client.post("/api/conversations", json={}).json()["id"]
    result = ask(client, conv, "2026 年 9 月各地区销售额").json()["result_id"]
    job = client.post(f"/api/results/{result}/exports", json={"format": "pdf"}).json()["id"]
    client.post(f"/api/results/{result}/chart", json={"type": "table"})
    engine = engine_for(config.app_database_url)
    with engine.connect() as conn:
        report = conn.scalar(select(m.export_jobs.c.report).where(m.export_jobs.c.id == job))
    assert report["chart_spec"]["type"] == "bar"
    engine.dispose()


def test_snapshot_expiry_and_bounded_pages(client, config):
    from datetime import datetime, timedelta

    conv = client.post("/api/conversations", json={}).json()["id"]
    result = ask(client, conv, "列出 2026 年 9 月的订单明细").json()["result_id"]
    assert client.get(f"/api/results/{result}?page=0").status_code == 422
    assert client.get(f"/api/results/{result}?page_size=1001").status_code == 422
    engine = engine_for(config.app_database_url)
    with engine.begin() as conn:
        conn.execute(
            update(m.result_snapshots)
            .where(m.result_snapshots.c.id == result)
            .values(expires_at=datetime.utcnow() - timedelta(seconds=1))
        )
    assert client.get(f"/api/results/{result}").status_code == 410
    history = client.get(f"/api/conversations/{conv}").json()
    assert history["messages"][0]["response"]["code"] == "RESULT_EXPIRED"
    assert client.post(f"/api/results/{result}/exports", json={"format": "pdf"}).status_code == 410
    engine.dispose()
