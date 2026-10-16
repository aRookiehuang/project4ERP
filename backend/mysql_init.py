"""Interactive MySQL provisioning; administrator credentials are never persisted."""

from __future__ import annotations

import getpass
import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import set_key
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from .app import models
from .app.config import ROOT, settings
from .seed import seed_business, seed_users


def ask(label, default):
    return input(f"{label} [{default}]：").strip() or str(default)


def database_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", value):
        raise ValueError("数据库名称只能包含英文字母、数字、下划线，长度为 1～64。")
    if value.lower() in {"mysql", "sys", "information_schema", "performance_schema"}:
        raise ValueError("不能使用 MySQL 系统数据库。")
    return value


def connection_url(host, port, username, password, database=None):
    # URL.create escapes @, :, /, %, quotes and other characters in passwords.
    return URL.create(
        "mysql+pymysql",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
        query={"charset": "utf8mb4"},
    )


def connect(url):
    # Large initialization transactions need a longer timeout than web queries.
    return create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 8,
            "read_timeout": 300,
            "write_timeout": 300,
        },
    )


def business_exists(engine):
    """Accept readable existing ERP tables, but refuse partial or unrelated schemas."""
    inspector = inspect(engine)
    actual = set(inspector.get_table_names())
    expected = set(models.business_meta.tables)
    if not actual:
        return False
    if actual != expected:
        raise ValueError("业务库不是完整的项目六表结构，请指定一个新的空数据库。现有表未修改。")
    for name, table in models.business_meta.tables.items():
        columns = {column["name"] for column in inspector.get_columns(name)}
        if not set(table.c.keys()) <= columns:
            raise ValueError(f"业务表 {name} 缺少项目所需字段，请使用新的空数据库。")
    with engine.connect() as conn:
        if conn.scalar(select(func.count()).select_from(models.orders)):
            return True
        for table in models.business_meta.tables.values():
            if conn.execute(select(table).limit(1)).first() is not None:
                raise ValueError("业务库存在部分数据，停止生成以避免混入演示数据。请使用新的空库。")
    return False


def save_environment(path: Path, values: dict[str, str]):
    """Back up secrets outside git, preserve unrelated settings, and replace atomically."""
    backup = None
    if path.exists():
        directory = ROOT / "artifacts" / "config-backups"
        directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="env-", suffix=".bak", dir=directory)
        os.close(fd)
        backup = Path(name)
        shutil.copyfile(path, backup)
    fd, name = tempfile.mkstemp(prefix=".mysql-init-", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        if path.exists():
            shutil.copyfile(path, temporary)
        for key, value in values.items():
            set_key(str(temporary), key, value, quote_mode="always")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def initialize(host, port, username, password, business_name, app_name, orders, login_password):
    admin_url = connection_url(host, port, username, password)
    admin = connect(admin_url)
    business = connect(admin_url.set(database=business_name))
    app = connect(admin_url.set(database=app_name))
    try:
        print("连接 MySQL 并创建数据库……", flush=True)
        with admin.begin() as conn:
            for name in (business_name, app_name):
                conn.exec_driver_sql(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name(name)}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        exists = business_exists(business)
        print("保留已有业务数据。" if exists else f"生成 {orders} 张订单及关联数据……", flush=True)
        if not exists:
            print(seed_business(business, orders, 42), flush=True)
        seed_users(app, login_password)

        # Unique names avoid changing passwords/permissions of pre-existing accounts.
        suffix = secrets.token_hex(5)
        reader, writer = f"erp_read_{suffix}", f"erp_app_{suffix}"
        reader_password, writer_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        print("创建业务只读账号和应用库账号……", flush=True)
        with admin.begin() as conn:
            for user, secret in ((reader, reader_password), (writer, writer_password)):
                conn.exec_driver_sql("CREATE USER %s@'%%' IDENTIFIED BY %s", (user, secret))
            for table in models.business_meta.tables:
                conn.exec_driver_sql(f"GRANT SELECT ON `{business_name}`.`{table}` TO %s@'%%'", (reader,))
            conn.exec_driver_sql(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES "
                f"ON `{app_name}`.* TO %s@'%%'",
                (writer,),
            )
        urls = {
            "APP_DATABASE_URL": connection_url(host, port, writer, writer_password, app_name),
            "BUSINESS_DATABASE_URL": connection_url(host, port, reader, reader_password, business_name),
        }
        for key, url in urls.items():
            engine = connect(url)
            try:
                with engine.connect() as conn:
                    table = models.orders if key == "BUSINESS_DATABASE_URL" else models.users
                    conn.execute(select(table).limit(1)).first()
            finally:
                engine.dispose()
        backup = save_environment(
            ROOT / ".env", {key: url.render_as_string(hide_password=False) for key, url in urls.items()}
        )
        print("完成：已创建/保留数据，运行账号连接成功，连接配置已写入 .env。")
        if backup:
            print(f"原配置备份：{backup}")
        print("网页登录账号：admin / demo / analyst；新账号使用本次输入的网页登录密码。")
        print("已有账号密码保持不变；原应用库的数据不会自动迁移。")
        print("请重启应用：python3 manage.py run（Windows：py manage.py run）。")
        print("打开 http://127.0.0.1:8000，使用默认业务库开始新会话即可。")
    finally:
        business.dispose()
        app.dispose()
        admin.dispose()


def main():
    print("MySQL 一键初始化（MySQL 服务需已安装并启动）")
    print("提供能创建数据库、创建用户及授权的 MySQL 账号；密码输入时不显示。")
    print("连接账号仅用于初始化，不保存；程序会自动生成独立的运行账号。")
    try:
        if any(os.environ.get(key) for key in ("APP_DATABASE_URL", "BUSINESS_DATABASE_URL")):
            raise ValueError(
                "请先清除终端中的 APP_DATABASE_URL / BUSINESS_DATABASE_URL 环境变量，避免覆盖 .env。"
            )
        host = ask("MySQL 主机（WSL 连接 Windows MySQL 时填写 Windows 可达地址）", "127.0.0.1")
        port = int(ask("端口", 3306))
        if not 1 <= port <= 65535:
            raise ValueError("端口须为 1～65535。")
        username = ask("MySQL 初始化账号", "root")
        password = getpass.getpass("MySQL 密码：")
        business_name = database_name(ask("业务数据库名", "erp_demo"))
        app_name = database_name(ask("应用数据库名（存账号和会话）", "nlq_app"))
        if business_name.lower() == app_name.lower():
            raise ValueError("应用库与业务库必须使用不同名称。")
        orders = int(ask("生成订单数量（标准规模填 100000）", 3000))
        if not 1 <= orders <= 1_000_000:
            raise ValueError("订单数量须为 1～1000000。")
        login_password = getpass.getpass(
            "新建网页账号密码（回车使用当前 DEMO_PASSWORD 配置，默认 erp-demo-2026）："
        )
        initialize(
            host,
            port,
            username,
            password,
            business_name,
            app_name,
            orders,
            login_password or settings.demo_password,
        )
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1
    except ValueError as exc:
        print(f"初始化停止：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        original = getattr(exc, "orig", None)
        code = getattr(original, "args", ["未知"])[0]
        print(
            f"MySQL 操作失败（错误码 {code}）。请检查主机、端口、密码及建库/创建用户/授权权限。"
            "连接配置尚未更新；已创建的库、表和数据会保留，可修正问题后重试。",
            file=sys.stderr,
        )
        return 1
    except OSError:
        print("配置文件写入失败，请检查项目目录权限和磁盘空间；数据库中已生成的数据会保留。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
