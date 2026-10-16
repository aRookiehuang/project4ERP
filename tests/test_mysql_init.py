import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from backend import mysql_init
from backend.app import models
from backend.seed import seed_business


def test_password_url_roundtrip():
    password = "a@b:/%#'\"\\${SECRET}中文"
    url = mysql_init.connection_url("127.0.0.1", 3306, "root", password, "erp_demo")
    assert make_url(url.render_as_string(hide_password=False)).password == password


@pytest.mark.parametrize("value", ["mysql", "SYS", "bad-name", "a`; DROP DATABASE x", "x" * 65, ""])
def test_reject_unsafe_database_names(value):
    with pytest.raises(ValueError):
        mysql_init.database_name(value)


def test_env_preserves_other_settings_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(mysql_init, "ROOT", tmp_path)
    path = tmp_path / ".env"
    original = "# user settings\nMODEL_NAME=my-model\nAPP_DATABASE_URL=sqlite:///old.db\n"
    path.write_text(original)
    secret = "a@b:/%#'\"\\${SECRET}中文"
    url = mysql_init.connection_url("localhost", 3306, "writer", secret, "app")
    value = url.render_as_string(hide_password=False)
    backup = mysql_init.save_environment(path, {"APP_DATABASE_URL": value})
    assert backup.read_text() == original
    config = dotenv_values(path)
    assert config["MODEL_NAME"] == "my-model"
    assert make_url(config["APP_DATABASE_URL"]).password == secret
    assert "# user settings" in path.read_text()
    assert not list(tmp_path.glob(".mysql-init-*"))


def test_env_failure_leaves_original(tmp_path, monkeypatch):
    monkeypatch.setattr(mysql_init, "ROOT", tmp_path)
    path = tmp_path / ".env"
    path.write_text("MODEL_NAME=original\n")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mysql_init, "set_key", fail)
    with pytest.raises(OSError):
        mysql_init.save_environment(path, {"APP_DATABASE_URL": "secret"})
    assert path.read_text() == "MODEL_NAME=original\n"
    assert not list(tmp_path.glob(".mysql-init-*"))


def test_empty_and_populated_business_database():
    engine = create_engine("sqlite://")
    assert not mysql_init.business_exists(engine)
    models.business_meta.create_all(engine)
    assert not mysql_init.business_exists(engine)
    seed_business(engine, 3)
    assert mysql_init.business_exists(engine)
    engine.dispose()


def test_partial_business_data_is_rejected():
    engine = create_engine("sqlite://")
    models.business_meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(models.categories.insert().values(id=1, name="existing"))
    with pytest.raises(ValueError, match="部分数据"):
        mysql_init.business_exists(engine)
    engine.dispose()


def test_unrelated_database_is_rejected():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError, match="六表结构"):
        mysql_init.business_exists(engine)
    engine.dispose()


def test_mysql_failure_does_not_print_credentials(monkeypatch, capsys):
    from sqlalchemy.exc import OperationalError

    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.delenv("BUSINESS_DATABASE_URL", raising=False)
    answers = iter(["", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(mysql_init.getpass, "getpass", lambda _: "sensitive-password")

    def fail(*args):
        raise OperationalError("sensitive statement", {}, Exception(1045, "sensitive-password"))

    monkeypatch.setattr(mysql_init, "initialize", fail)
    assert mysql_init.main() == 1
    captured = capsys.readouterr()
    assert "1045" in captured.err
    assert "sensitive-password" not in captured.out + captured.err
    assert "sensitive statement" not in captured.out + captured.err
