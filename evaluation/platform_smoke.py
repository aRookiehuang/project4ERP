"""Launch the shared supervisor, run the browser/export flow, then verify shutdown."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.processes import process_group_options, stop_child
from manage import child_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18765)
    port = parser.parse_args().port
    url = f"http://127.0.0.1:{port}"
    child = subprocess.Popen(
        [sys.executable, str(ROOT / "manage.py"), "run", "--port", str(port)],
        cwd=ROOT,
        env=child_environment(),
        **process_group_options(),
    )
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError("Supervisor exited during startup")
                try:
                    if client.get(url + "/api/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("API did not become ready")
        subprocess.run(
            [sys.executable, str(ROOT / "evaluation/browser_smoke.py"), "--url", url, "--exports"],
            cwd=ROOT,
            env=child_environment(),
            check=True,
            timeout=240,
        )
    finally:
        stop_child(child)
    with httpx.Client(timeout=1, trust_env=False) as client:
        try:
            client.get(url + "/api/health/ready")
        except httpx.HTTPError:
            pass
        else:
            raise AssertionError("API remained running after supervisor shutdown")
    path = ROOT / "artifacts/browser/platform.json"
    path.write_text(
        json.dumps(
            {
                "platform": platform.platform(),
                "python": sys.version,
                "native_windows": os.name == "nt",
                "browser_and_exports": "passed",
                "supervisor_shutdown": "passed",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Platform browser/export/start-stop verification passed.")


if __name__ == "__main__":
    main()
