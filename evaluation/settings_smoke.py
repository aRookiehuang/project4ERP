"""Verify settings UI using an isolated application DB; never calls a remote model."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.db import engine_for
from backend.app.preferences import Preferences
from backend.browser import browser_launch_options
from backend.processes import process_group_options, stop_child
from backend.seed import seed_users
from manage import child_environment


def main():
    # Keep evidence, including the isolated settings DB, beneath artifacts.
    output = ROOT / "artifacts/settings"
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    config = Settings(
        _env_file=None,
        app_database_url="sqlite:///" + (directory / "app.db").as_posix(),
        config_key_path=directory / "config.key",
        model_mode="demo",
    )
    engine = engine_for(config.app_database_url)
    seed_users(engine, config.demo_password)
    Preferences(engine, config).put(
        "db:ui-check",
        {
            "name": "界面验证数据源",
            "url": config.business_database_url,
            "data_start": config.data_start,
            "data_end": config.data_end,
        },
    )
    engine.dispose()
    env = dict(
        child_environment(),
        APP_DATABASE_URL=config.app_database_url,
        BUSINESS_DATABASE_URL=config.business_database_url,
        CONFIG_KEY_PATH=str(config.config_key_path),
        MODEL_MODE="demo",
        MODEL_API_KEY="",
        ALLOWED_ORIGINS="http://127.0.0.1:18767",
    )
    child = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "18767"],
        cwd=ROOT,
        env=env,
        **process_group_options(),
    )
    try:
        with httpx.Client(trust_env=False, timeout=1) as client:
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError("Settings verification server exited")
                try:
                    if client.get("http://127.0.0.1:18767/api/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Settings verification server did not become ready")
        # Chromium system dependencies may be supplied through the project's launcher.
        os.environ.update({key: value for key, value in env.items() if key == "LD_LIBRARY_PATH"})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_launch_options())
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto("http://127.0.0.1:18767")
            page.get_by_label("用户名").fill("admin")
            page.get_by_label("密码", exact=True).fill(config.demo_password)
            page.get_by_role("button", name="进入工作台").click()
            page.get_by_role("button", name="数据库与模型设置", exact=True).click()
            expect(page.get_by_role("heading", name="添加共享 MySQL 数据库")).to_be_visible()
            page.get_by_label("模型模式").select_option("api")
            page.get_by_label("API 地址（Base URL）").fill("https://model.example/v1")
            page.get_by_label("模型名称", exact=True).fill("ui-test-model")
            page.get_by_label("API Key", exact=True).fill("ui-test-secret")
            page.get_by_role("button", name="保存模型设置").click()
            expect(page.get_by_role("status")).to_contain_text("模型设置已保存")
            expect(page.get_by_label("API Key", exact=True)).to_have_value("")
            page.screenshot(path=str(output / "settings-desktop.png"))
            page.get_by_role("button", name="关闭设置").click()
            expect(page.locator(".mode-badge")).to_contain_text("模型 API 模式")
            page.get_by_role("button", name="数据库与模型设置", exact=True).click()
            expect(page.get_by_label("模型名称", exact=True)).to_have_value("ui-test-model")
            expect(page.get_by_label("API Key", exact=True)).to_have_value("")
            page.get_by_label("模型模式").select_option("demo")
            page.get_by_role("button", name="保存模型设置").click()
            expect(page.get_by_role("status")).to_contain_text("模型设置已保存")
            page.get_by_role("button", name="关闭设置").click()
            page.get_by_label("查询数据库").select_option("ui-check")
            page.get_by_role("textbox", name="输入分析问题").fill("2026 年 9 月销售额是多少？")
            page.get_by_role("button", name="开始分析").click()
            expect(page.locator(".result-card")).to_have_count(1, timeout=15000)
            expect(page.get_by_label("查询数据库")).to_be_disabled()
            page.reload()
            page.locator(".conversation-link").first.click()
            expect(page.get_by_label("查询数据库")).to_have_value("ui-check")
            page.get_by_role("button", name="数据库与模型设置", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "settings-mobile.png"))
            assert page.locator("dialog").evaluate("node => node.scrollWidth <= node.clientWidth")
            assert not failures, failures
            browser.close()
    finally:
        stop_child(child)
    print(
        "Settings UI passed: encrypted key save/reload, model mode, database selection and conversation binding."
    )


if __name__ == "__main__":
    main()
