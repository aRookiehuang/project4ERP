from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

from .config import Settings


def engine_for(url: str, *, readonly: bool = False, timeout_ms: int = 1500):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            if readonly:
                connection.execute("PRAGMA query_only=ON")
    else:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=0,
            pool_timeout=2,
            connect_args={"connect_timeout": 3, "read_timeout": 4, "write_timeout": 4},
        )
        if readonly:

            @event.listens_for(engine, "connect")
            def configure_mysql(connection, _):
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION TRANSACTION READ ONLY")
                    cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={int(timeout_ms)}")
                    cursor.execute("SET SESSION time_zone='+08:00'")

    return engine


class Database:
    def __init__(self, config: Settings, app_engine=None):
        self.owns_app = app_engine is None
        self.app = app_engine if app_engine is not None else engine_for(config.app_database_url)
        self.business = engine_for(
            config.business_database_url, readonly=True, timeout_ms=config.query_timeout_ms
        )
        self.cancel = None
        if self.business.dialect.name == "mysql":
            self.cancel = create_engine(
                config.business_database_url,
                poolclass=NullPool,
                connect_args={"connect_timeout": 1, "read_timeout": 1, "write_timeout": 1},
            )

    def interrupt_mysql(self, connection_id: int):
        # MySQL permits a user to kill its own connections without PROCESS/SUPER.
        if self.cancel:
            with self.cancel.connect() as conn:
                conn.exec_driver_sql(f"KILL QUERY {int(connection_id)}")

    def close(self):
        if self.owns_app:
            self.app.dispose()
        self.business.dispose()
        if self.cancel:
            self.cancel.dispose()
