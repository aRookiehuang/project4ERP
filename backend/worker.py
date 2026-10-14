"""Single durable export consumer. Run with python -m backend.worker."""

import argparse
import hashlib
import multiprocessing
import os
import signal
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from .app import models as m
from .app.config import Settings, settings
from .app.db import engine_for


def render_child(payload, format, include_sql, target, settings_dict):
    if hasattr(os, "setsid"):
        os.setsid()
    from .app.reports import render_report

    render_report(payload, format, include_sql, target, Settings(**settings_dict))


def process_one(config: Settings):
    engine = engine_for(config.app_database_url)
    try:
        with engine.begin() as conn:
            # Recover work interrupted by a worker crash. A render has a hard 60s lifetime.
            conn.execute(
                update(m.export_jobs)
                .where(
                    m.export_jobs.c.status == "running",
                    m.export_jobs.c.started_at < datetime.utcnow() - timedelta(seconds=90),
                )
                .values(status="pending")
            )
            job = (
                conn.execute(
                    select(m.export_jobs)
                    .where(
                        m.export_jobs.c.status == "pending", m.export_jobs.c.expires_at > datetime.utcnow()
                    )
                    .order_by(m.export_jobs.c.created_at)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not job:
                return False
            claimed = conn.execute(
                update(m.export_jobs)
                .where(m.export_jobs.c.id == job["id"], m.export_jobs.c.status == "pending")
                .values(status="running", started_at=datetime.utcnow())
            )
            if claimed.rowcount != 1:
                return False
            job = dict(job)
        config.export_dir.mkdir(parents=True, exist_ok=True)
        path = config.export_dir / f"{job['id']}.{job['format']}"
        temporary = path.with_suffix(path.suffix + ".tmp")
        process = multiprocessing.get_context("spawn").Process(
            target=render_child,
            args=(job["report"], job["format"], bool(job["include_sql"]), temporary, config.model_dump()),
        )
        process.start()
        process.join(timeout=60)
        if process.is_alive():
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.join(timeout=5)
        success = process.exitcode == 0 and temporary.is_file() and temporary.stat().st_size > 100
        checksum = None
        if success:
            temporary.replace(path)
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        elif temporary.is_file():
            temporary.unlink()
        with engine.begin() as conn:
            conn.execute(
                update(m.export_jobs)
                .where(m.export_jobs.c.id == job["id"])
                .values(
                    status="succeeded" if success else "failed",
                    checksum=checksum,
                    error=None
                    if success
                    else "导出失败或超过 60 秒，请检查 Chromium、中文字体及本地 ECharts 资源。",
                )
            )
        return True
    finally:
        engine.dispose()


def cleanup(config):
    engine = engine_for(config.app_database_url)
    try:
        with engine.begin() as conn:
            expired = conn.execute(
                select(m.export_jobs.c.id, m.export_jobs.c.format).where(
                    m.export_jobs.c.expires_at <= datetime.utcnow(), m.export_jobs.c.status != "expired"
                )
            ).all()
            for identifier, format in expired:
                target = config.export_dir / f"{identifier}.{format}"
                if target.is_file() and target.resolve().parent == config.export_dir.resolve():
                    target.unlink()
            conn.execute(
                update(m.export_jobs)
                .where(m.export_jobs.c.expires_at <= datetime.utcnow())
                .values(status="expired", report={})
            )
            conn.execute(delete(m.sessions).where(m.sessions.c.expires_at <= datetime.utcnow()))
            conn.execute(
                update(m.result_snapshots)
                .where(m.result_snapshots.c.expires_at <= datetime.utcnow())
                .values(payload={})
            )
            conn.execute(
                delete(m.query_runs).where(m.query_runs.c.created_at < datetime.utcnow() - timedelta(days=30))
            )
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        cleanup(settings)
        worked = process_one(settings)
        if args.once:
            break
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
