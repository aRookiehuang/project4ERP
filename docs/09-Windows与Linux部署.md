# Windows / Linux 部署与兼容性

两种系统运行同一套 Vue、FastAPI、查询编译器和报告模块。Windows 可直接安装运行，不依赖 WSL；Linux 不依赖 Windows、Office 或 LibreOffice。MySQL 可选原生服务或 Docker，SQLite 仅用于开发演示与测试。

## 统一操作入口

| 操作 | Windows | Linux |
|---|---|---|
| 安装依赖与构建 | `py -3.11 manage.py setup --skip-browser` | `python3 manage.py setup --with-system-deps` |
| 下载中文字体 | `py -3.11 manage.py assets` | `python3 manage.py assets` |
| 初始化新演示库 | `py -3.11 manage.py seed` | `python3 manage.py seed` |
| 启动 API + 导出 | `scripts\dev.cmd` | `./scripts/dev.sh` |
| 直接启动 | `.venv\Scripts\python.exe manage.py run` | `.venv/bin/python manage.py run` |
| 测试 | `.venv\Scripts\python.exe -m pytest -q` | `.venv/bin/python -m pytest -q` |

Python 建议 3.11，测试矩阵包含 3.10/3.11；Node.js 使用 22+。执行 `setup` 的 Python 决定虚拟环境版本。没有 `py` 启动器的 Windows 可用已安装的 `python` 替代；不要用指向 Microsoft Store 的空占位命令。

导出系统版本以 [Playwright 官方要求](https://playwright.dev/python/docs/intro) 为准。Windows 自动使用已安装的 Edge，其次是 Chrome，无需额外下载。非标准安装位置在 `.env` 设置 `BROWSER_EXECUTABLE_PATH=C:/浏览器目录/chrome.exe`；也可设置 `BROWSER_CHANNEL=chrome` 或 `BROWSER_CHANNEL=msedge`。显式可执行路径优先于 channel；均未配置时自动发现 Windows 浏览器，Linux 默认使用 Playwright Chromium。测试脚本和报告导出共用此选择逻辑。[Playwright 浏览器通道说明](https://playwright.dev/python/docs/browsers)

Linux 已有 Chrome / Edge 时也可显式选择并使用 `setup --skip-browser`。未安装浏览器时才需要安装目标系统对应的 Chromium，不能跨系统复制二进制文件。Linux 浏览器所需系统库需由系统管理员安装。

## 已处理的平台差异

- Windows 使用 `.venv/Scripts/python.exe`，Linux 使用 `.venv/bin/python`。启动器使用参数列表传递命令，支持安装路径包含空格。
- Windows 直接运行 Node 的 npm CLI，避免 `npm.ps1` 被执行策略阻止；前端构建仍使用同一 `package-lock.json`。
- `.env` 固定从项目根目录以 UTF-8 读取；相对 SQLite、字体、图表与导出路径以项目根目录解析。改变启动目录不会创建另一套数据库。自定义 Windows 路径可写为 `C:/ERP/data/app.db`；相对路径更便于迁移。
- 显式安装 `tzdata`，不依赖 Windows 系统是否提供 IANA 时区数据；`Asia/Shanghai` 日期解析与 Linux 一致。[Python 官方说明](https://docs.python.org/3/library/zoneinfo.html#data-sources)
- 依赖锁文件对 `backports.asyncio.runner` 使用 Python `<3.11` 条件，对 Windows `colorama` 使用平台条件，避免把 Python 3.10 冻结结果错误应用到 3.11。
- 导出采用 `multiprocessing` 的 spawn 模式；Windows 超时清理使用限定子进程 PID 的 `taskkill /T`，Linux 清理专属进程组。统一启动器停止 API 和 worker，worker 停止时回收正在渲染的子进程。
- 字体保存在项目目录，PDF 内嵌中文字体，Word 文本可编辑。阅读 Word 的设备仍需要中文字体；不保证不同 Office 软件版式像素一致。
- `.gitattributes` 固定 Bash 脚本 LF、Windows 脚本 CRLF，避免 Git 自动换行破坏启动脚本。

## 配置与数据迁移

先在目标系统运行 `setup`，不要复制 `.venv`、`node_modules`、浏览器缓存、`.tools`。`.env.example` 可复制为 `.env`，SQLite 相对路径无需更改。复制已有 SQLite 数据前停止 API/worker；MySQL 使用备份恢复或连接目标平台上的批准实例。模型 URL、API Key 与 MySQL 账号配置方式在两种系统相同。

Windows PowerShell 设置临时环境变量用 `$env:NAME='value'`；Linux Bash 用 `export NAME='value'`。MySQL 凭据、API Key 不提交到源码仓库。Windows 原生 MySQL 可通过 MySQL 客户端执行 `database/bootstrap.sql` 和 `database/grant-reader.sql`，无需 Docker。

同一应用数据库仍只运行一个 API 与一个导出 worker；不要同时使用统一启动器和手工 worker。额外的 `--port` 仅改变本机端口，不表示支持多实例部署。

## 验证方式

`.github/workflows/cross-platform.yml` 定义 Windows Server 2022 / Ubuntu 24.04 × Python 3.10 / 3.11 矩阵，安装平台原生依赖、构建前端、运行后端测试、初始化数据，并通过 `evaluation/platform_smoke.py` 执行真实浏览器查询和 Word/PDF 下载及停止检查。工作流只有推送到启用 Actions 的仓库后才会运行，配置文件本身不是通过证明。

2026-10-15 本机实测已完成：

| 环境 | 后端测试 | 浏览器、Word/PDF、启动与停止 |
|---|---|---|
| Windows 11，Python 3.11.9，Node 24.14.1 | 70 项通过，依赖检查通过 | 使用系统已有 Edge，全部通过；原生 Windows Python 运行，项目路径含空格 |
| Ubuntu 22.04.5 / WSL2，Python 3.10.12，Node 22.16.0 | 70 项通过，依赖检查通过 | 使用已有 Linux Chromium，全部通过 |

Windows 和 Linux 均已完成前端生产构建。Windows 验证结束后检查未残留本项目的 API、worker 或统一启动器进程。当前 Linux 验证环境是 WSL2，独立 Linux 主机及其他 Python 版本仍由 CI 矩阵继续覆盖；未声称远端 Actions 已运行。

本机证据保存在 `artifacts/platform/windows/` 与 `artifacts/platform/linux/`，包含 `platform.json`、`smoke.json`、截图与下载的 `report.docx` / `report.pdf`。这些运行产物不纳入 Git。重新验证可执行虚拟环境 Python 加 `evaluation/platform_smoke.py --port 18766`；端口可调整，避免与正在运行的实例冲突。

真实模型 API、MySQL 集成与正式准确率/性能验收继续按原评测方案执行；跨平台验证不能替代这些指标。
