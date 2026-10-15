"""Cross-platform installation and supervision; no shell activation required."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent


def venv_python():
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def child_environment():
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    if os.name != "nt":
        node = ROOT / ".tools/node-v22.16.0-linux-x64/bin"
        libs = ROOT / ".tools/browser-libs/usr/lib/x86_64-linux-gnu"
        if node.is_dir():
            env["PATH"] = str(node) + os.pathsep + env.get("PATH", "")
        if libs.is_dir():
            env["LD_LIBRARY_PATH"] = str(libs) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


def execute(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, env=child_environment(), check=True)


def npm_command(*args):
    env = child_environment()
    node = shutil.which("node", path=env.get("PATH"))
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm", path=env.get("PATH"))
    if not node or not npm:
        raise RuntimeError("Install Node.js 22+ (including npm) and add it to PATH.")
    if os.name == "nt":
        # Avoid npm.ps1 execution policy and shell quoting of spaces in paths.
        cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not cli.is_file():
            cli = Path(node).parent / "node_modules/npm/bin/npm-cli.js"
        if not cli.is_file():
            raise RuntimeError("Cannot locate npm-cli.js; use the official Node.js installation.")
        return [node, str(cli), *args]
    return [npm, *args]


def setup(args):
    from backend.browser import installed_windows_browser

    python = venv_python()
    if not python.is_file():
        execute([sys.executable, "-m", "venv", ROOT / ".venv"])
    execute([python, "-m", "pip", "install", "-r", ROOT / "requirements.lock"])
    execute([python, "-m", "pip", "install", "-e", ROOT, "--no-deps"])
    execute(npm_command("ci", "--prefix", "frontend"))
    execute(npm_command("run", "build", "--prefix", "frontend"))
    installed = installed_windows_browser()
    if installed:
        print(f"Using existing system browser (no download): {installed}", flush=True)
    elif not args.skip_browser:
        command = [python, "-m", "playwright", "install"]
        if args.with_system_deps and os.name != "nt":
            command.append("--with-deps")
        execute([*command, "chromium", "--only-shell"])
    print("Setup complete. Next: manage.py assets, manage.py seed, manage.py run")


def assets():
    directory = ROOT / "artifacts/fonts"
    directory.mkdir(parents=True, exist_ok=True)
    base = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/"
    for name, url in [
        ("NotoSansCJKsc-Regular.otf", base + "OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"),
        ("LICENSE.txt", base + "LICENSE"),
    ]:
        destination = directory / name
        if destination.is_file():
            print(f"Preserving existing asset: {destination}")
            continue
        temporary = destination.with_suffix(destination.suffix + ".download")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target)
            if name.endswith(".otf"):
                with temporary.open("rb") as font:
                    if font.read(4) != b"OTTO":
                        raise RuntimeError("Downloaded asset is not an OpenType font.")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def run(args):
    from backend.processes import process_group_options, stop_child
    from backend.app.config import settings

    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Frontend is not built. Run manage.py setup first.")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    env = child_environment()
    env["ALLOWED_ORIGINS"] = (
        settings.allowed_origins + f",http://localhost:{args.port},http://127.0.0.1:{args.port}"
    )
    children = []
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    for sig in [signal.SIGINT, signal.SIGTERM] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else []):
        signal.signal(sig, stop)
    try:
        for module_args in [
            ["uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
            ["backend.worker"],
        ]:
            children.append(
                subprocess.Popen(
                    [str(venv_python()), "-m", *module_args], cwd=ROOT, env=env, **process_group_options()
                )
            )
        print(f"ERP: http://127.0.0.1:{args.port} (Ctrl+C stops API and export worker)", flush=True)
        while not stopped:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("An application process exited; see its output above.")
            time.sleep(0.2)
    finally:
        for child in reversed(children):
            stop_child(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup")
    install.add_argument("--with-system-deps", action="store_true")
    install.add_argument("--skip-browser", action="store_true")
    commands.add_parser("assets")
    seed = commands.add_parser("seed")
    seed.add_argument("--orders", type=int, default=3000)
    seed.add_argument("--seed", type=int, default=42)
    seed.add_argument("--app-only", action="store_true")
    serve = commands.add_parser("run")
    serve.add_argument("--port", type=int, default=int(os.environ.get("ERP_PORT", "8000")))
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.command == "setup":
            setup(args)
        elif args.command == "assets":
            assets()
        elif args.command == "seed":
            execute(
                [
                    venv_python(),
                    "-m",
                    "backend.seed",
                    "--orders",
                    str(args.orders),
                    "--seed",
                    str(args.seed),
                    *(["--app-only"] if args.app_only else []),
                ]
            )
        else:
            if not venv_python().is_file():
                raise RuntimeError("Run manage.py setup first.")
            if Path(sys.executable).absolute() != venv_python().absolute():
                from backend.processes import process_group_options, stop_child

                child = subprocess.Popen(
                    [str(venv_python()), str(ROOT / "manage.py"), "run", "--port", str(args.port)],
                    cwd=ROOT,
                    env=child_environment(),
                    **process_group_options(),
                )

                def stop_proxy(signum, frame):
                    raise KeyboardInterrupt

                for sig in [signal.SIGINT, signal.SIGTERM] + (
                    [signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else []
                ):
                    signal.signal(sig, stop_proxy)
                try:
                    return child.wait()
                except KeyboardInterrupt:
                    return 0
                finally:
                    stop_child(child)
            run(args)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERP startup error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
