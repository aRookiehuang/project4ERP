from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")
    app_database_url: str = "sqlite:///artifacts/app.db"
    business_database_url: str = "sqlite:///artifacts/business.db"
    model_mode: str = "demo"
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_name: str = "qwen-plus"
    model_api_key: str = ""
    model_timeout_seconds: float = 5.0
    query_timeout_ms: int = Field(default=1500, ge=100, le=10000)
    request_timeout_seconds: float = 8.0
    max_result_bytes: int = 2_000_000
    max_concurrency: int = 5
    session_hours: int = 12
    snapshot_days: int = 7
    export_hours: int = 24
    export_dir: Path = ROOT / "artifacts" / "exports"
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
    )
    cookie_secure: bool = False
    demo_password: str = "erp-demo-2026"
    data_version: str = "demo-v1-seed42"
    data_start: str = "2024-11-01"
    data_end: str = "2026-11-01"
    chart_js_path: Path = ROOT / "frontend/node_modules/echarts/dist/echarts.min.js"
    font_path: Path = ROOT / "artifacts/fonts/NotoSansCJKsc-Regular.otf"
    browser_channel: str = ""
    browser_executable_path: Path | None = None
    config_key_path: Path = ROOT / "artifacts/config.key"

    @field_validator("app_database_url", "business_database_url", mode="after")
    @classmethod
    def absolute_sqlite_path(cls, value: str):
        url = make_url(value)
        if url.get_backend_name() == "sqlite" and url.database not in {None, "", ":memory:"}:
            path = Path(url.database)
            if not path.is_absolute():
                path = ROOT / path
            return url.set(database=path.resolve().as_posix()).render_as_string(hide_password=False)
        return value

    @field_validator(
        "export_dir", "chart_js_path", "font_path", "browser_executable_path", "config_key_path", mode="after"
    )
    @classmethod
    def project_path(cls, value: Path | None):
        if value is None:
            return None
        return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


settings = Settings()
