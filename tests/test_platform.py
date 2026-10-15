import os
from pathlib import Path
import subprocess
import sys
import time

from sqlalchemy.engine import make_url

from backend.app.config import ROOT, Settings
from backend.processes import process_group_options, stop_child
from backend.browser import browser_launch_options


def test_timezone_without_system_database():
    env = dict(os.environ, PYTHONTZPATH="")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from datetime import datetime; from zoneinfo import ZoneInfo; "
            "assert datetime(2026, 1, 1, tzinfo=ZoneInfo('Asia/Shanghai')).utcoffset().total_seconds() == 28800",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_configuration_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Settings(
        _env_file=None,
        app_database_url="sqlite:///artifacts/app.db",
        export_dir="artifacts/导出 结果",
        font_path="artifacts/fonts/NotoSansCJKsc-Regular.otf",
    )
    assert Path(make_url(config.app_database_url).database) == ROOT / "artifacts/app.db"
    assert config.export_dir == ROOT / "artifacts/导出 结果"
    assert config.font_path == ROOT / "artifacts/fonts/NotoSansCJKsc-Regular.otf"
    assert (
        Settings(_env_file=None, app_database_url="sqlite:///:memory:").app_database_url
        == "sqlite:///:memory:"
    )


def test_absolute_sqlite_path_with_spaces(tmp_path):
    path = tmp_path / "数据库 数据.db"
    config = Settings(_env_file=None, app_database_url="sqlite:///" + path.as_posix())
    assert Path(make_url(config.app_database_url).database) == path


def test_supervisor_stops_child_process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **process_group_options())
    try:
        time.sleep(0.15)
        stop_child(child)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_windows_kill_targets_owned_process_tree(monkeypatch):
    import backend.processes as processes

    calls = []

    # Patch only the platform discriminator; do not change pathlib's platform globally.
    class WindowsOS:
        name = "nt"
        getpid = staticmethod(lambda: 100)

    monkeypatch.setattr(processes, "os", WindowsOS)
    monkeypatch.setattr(processes.subprocess, "run", lambda args, **kwargs: calls.append(args))
    processes.kill_tree(123)
    assert calls == [["taskkill", "/PID", "123", "/T", "/F"]]


def test_existing_windows_browser_selected_without_download(tmp_path, monkeypatch):
    import backend.browser as browser

    executable = tmp_path / "Microsoft/Edge/Application/msedge.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(browser.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    assert browser_launch_options() == {"executable_path": str(executable)}
    assert browser_launch_options(channel="chrome") == {"channel": "chrome"}


def test_custom_browser_path_with_spaces(tmp_path):
    executable = tmp_path / "浏览器 Browser" / "chrome.exe"
    executable.parent.mkdir()
    executable.touch()
    assert browser_launch_options(channel="msedge", executable_path=executable) == {
        "executable_path": str(executable)
    }
