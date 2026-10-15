"""Persistent encrypted connection profiles and user-owned model settings."""

import json
import os
import threading
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import URL, make_url

from . import models as m
from .errors import DomainError
from .planner import StrictModel
from .db import engine_for


class MysqlInput(StrictModel):
    name: str = Field(default="MySQL 业务库", min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(default="", max_length=2048)
    database: str = Field(default="", max_length=64)
    data_start: date = date(2024, 11, 1)
    data_end: date = date(2026, 11, 1)

    @model_validator(mode="after")
    def dates(self):
        if self.data_end <= self.data_start:
            raise ValueError("结束日期必须晚于开始日期")
        return self

    def url(self):
        return URL.create(
            "mysql+pymysql",
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database or None,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)


class ModelInput(StrictModel):
    mode: Literal["server", "demo", "api"] = "server"
    base_url: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=4096)
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        if value:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("请输入不含凭据、查询参数的 HTTP(S) API 地址")
        return value

    @model_validator(mode="after")
    def api_fields(self):
        if self.mode == "api" and (not self.base_url or not self.model.strip()):
            raise ValueError("API 模式需要地址和模型名称")
        return self


class Preferences:
    def __init__(self, engine, config):
        self.engine, self.config = engine, config
        self.lock = threading.RLock()

    def cipher(self):
        with self.lock:
            return self._cipher()

    def _cipher(self):
        path = self.config.config_key_path
        if not path.exists():
            # Never replace a missing key if encrypted settings already exist.
            with self.engine.connect() as conn:
                if conn.scalar(select(m.runtime_settings.c.id).limit(1)):
                    raise DomainError(
                        "CONFIG_KEY_MISSING", "配置加密密钥丢失，请恢复服务器 config.key。", 503
                    )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as target:
                    target.write(Fernet.generate_key())
        return Fernet(path.read_bytes())

    def get(self, key):
        with self.engine.connect() as conn:
            value = conn.scalar(select(m.runtime_settings.c.value).where(m.runtime_settings.c.id == key))
        if value is None:
            return None
        try:
            return json.loads(self.cipher().decrypt(value.encode()))
        except (InvalidToken, ValueError) as exc:
            raise DomainError("CONFIG_KEY_INVALID", "无法解密连接配置，请检查服务器配置密钥。", 503) from exc

    def put(self, key, value):
        with self.lock:
            self._put(key, value)

    def _put(self, key, value):
        encrypted = self.cipher().encrypt(json.dumps(value).encode()).decode()
        with self.engine.begin() as conn:
            existing = conn.scalar(select(m.runtime_settings.c.id).where(m.runtime_settings.c.id == key))
            if existing:
                conn.execute(
                    update(m.runtime_settings).where(m.runtime_settings.c.id == key).values(value=encrypted)
                )
            else:
                conn.execute(m.runtime_settings.insert().values(id=key, value=encrypted))

    def source(self, identifier):
        if identifier == "default":
            return {
                "name": "服务器默认数据库",
                "url": self.config.business_database_url,
                "data_start": self.config.data_start,
                "data_end": self.config.data_end,
            }
        value = self.get("db:" + identifier)
        if value is None:
            raise DomainError("NOT_FOUND", "数据库连接不存在。", 404)
        return value

    def sources(self):
        with self.engine.connect() as conn:
            keys = conn.scalars(
                select(m.runtime_settings.c.id).where(m.runtime_settings.c.id.like("db:%"))
            ).all()
        rows = []
        for identifier in ["default", *[key[3:] for key in keys]]:
            source = self.source(identifier)
            url = make_url(source["url"])
            rows.append(
                {
                    "id": identifier,
                    "name": source["name"],
                    "kind": url.get_backend_name(),
                    "database": url.database if url.get_backend_name() == "mysql" else "本机演示库",
                    "data_start": source["data_start"],
                    "data_end": source["data_end"],
                }
            )
        return rows

    def model(self, user_id):
        return self.get("model:" + user_id)

    def prepare_model(self, user_id, body):
        value = body.model_dump()
        previous = self.model(user_id)
        if body.mode == "api" and not body.api_key:
            # A saved key must never silently travel to a newly entered provider.
            if previous and previous.get("base_url") == body.base_url:
                value["api_key"] = previous.get("api_key", "")
            if not value["api_key"]:
                raise DomainError("INVALID_INPUT", "首次配置或更换 API 地址时，请填写 API Key。", 422)
        if body.mode != "api":
            value["api_key"] = ""
        return value

    def effective_config(self, source_id="default", model=None):
        source = self.source(source_id)
        values = self.config.model_dump()
        values.update(
            business_database_url=source["url"], data_start=source["data_start"], data_end=source["data_end"]
        )
        if source_id != "default":
            values["data_version"] = "source-" + source_id
        if model and model["mode"] != "server":
            values.update(
                model_mode=model["mode"],
                model_base_url=model["base_url"],
                model_name=model["model"],
                model_api_key=model["api_key"],
                model_timeout_seconds=model["timeout_seconds"],
                request_timeout_seconds=model["timeout_seconds"] + 5,
            )
        return type(self.config)(_env_file=None, **values)

    def public_model(self, user_id):
        value = self.model(user_id)
        effective = self.effective_config(model=value)
        return {
            "mode": value["mode"] if value else "server",
            "effective_mode": effective.model_mode,
            "base_url": value["base_url"] if value else self.config.model_base_url,
            "model": value["model"] if value else self.config.model_name,
            "has_api_key": bool(value and value.get("api_key")),
            "configured": effective.model_mode == "demo" or bool(effective.model_api_key),
            "timeout_seconds": value["timeout_seconds"] if value else 30,
        }


def check_mysql(body: MysqlInput, *, discover=False):
    if not discover and not body.database:
        raise DomainError("INVALID_INPUT", "请选择数据库名称。", 422)
    engine = engine_for(body.url(), readonly=not discover)
    try:
        with engine.connect() as conn:
            if discover:
                return [
                    name
                    for name in conn.exec_driver_sql("SHOW DATABASES").scalars()
                    if name not in {"mysql", "sys", "performance_schema", "information_schema"}
                ]
            for table in m.business_meta.sorted_tables:
                conn.execute(select(table).limit(0))
        return {"status": "success", "message": "MySQL 连接成功，六张 ERP 表及所需字段可读取。"}
    except Exception as exc:
        raise DomainError(
            "DATABASE_UNAVAILABLE", "MySQL 连接或表结构检查失败，请检查地址、账号权限和六张 ERP 表。", 422
        ) from exc
    finally:
        engine.dispose()
