# 观数 · ERP 智能销售查询

基于当前目录项目文档实现的 Vue 3 + TypeScript + FastAPI 查询应用。业务数据库使用 MySQL 8.4；另提供 SQLite 本机演示/自动化测试模式。模型输出受限 QueryPlan，由服务端编译参数化 SQL，经 AST 校验后只读执行。

## 已实现

- 中文对话界面、历史会话、预置账号登录、CSRF 与资源归属校验。
- 单表及最多四表关联；销售额、订单数、销量、客户数、客单价、最高/最低订单金额；分组、Top N、HAVING、布尔筛选、日/月趋势、销售占比。
- 支付时间和下单时间区分、订单地区快照、同名实体消歧、商品明细金额与整单金额区分。
- 最近五轮已确认计划、澄清引用、幂等请求、查询取消、查询时限、结果行数/字节限制。
- 确定性摘要、ECharts 图表、快照分页、无需重新查库的图表切换、SQL 追溯。
- 独立持久化导出任务、Word/PDF、中文字体、本地图表资源、超时与过期清理。
- 前端选择 MySQL 数据库、管理员读取数据库列表与检查表结构；每个会话固定绑定数据库。
- 当前用户独立配置 OpenAI 兼容模型 API，支持连接测试、服务端加密保存与即时生效。
- 六表模拟数据生成器、10 万订单/30 万明细规模选项、固定种子与金额一致性校验。
- 口径/SQL 安全/API 隔离测试，HTTP 评测工具和浏览器完整响应计时。

真实模型准确率、MySQL 性能和文档要求的正式盲测尚需部署后验证；不声明已经满足 91% 或 3 秒指标。开发验证情况及限制见 [实施记录](docs/07-实现与验证记录.md)。

## 1. 本机快速启动

支持原生 Windows 和 Linux，不要求 Windows 安装 WSL。建议使用 Python 3.11（兼容 3.10）、Node.js 22+；浏览器导出使用 Playwright 支持的系统版本。两种系统共用源码和依赖锁文件，分别安装各自的虚拟环境与 Node 依赖。

**Windows（PowerShell / CMD）**，从项目根目录执行：

```powershell
py -3.11 manage.py setup --skip-browser
py -3.11 manage.py assets
py -3.11 manage.py seed --orders 3000
.venv\Scripts\python.exe manage.py run
```

**Linux（Bash）**，从项目根目录执行：

```bash
python3 manage.py setup --with-system-deps
python3 manage.py assets
python3 manage.py seed --orders 3000
.venv/bin/python manage.py run
```

`setup` 安装 Python/前端依赖并构建页面。Windows 自动使用已安装的 Edge 或 Chrome，以上命令跳过浏览器下载；非标准安装位置可在 `.env` 中设置 `BROWSER_EXECUTABLE_PATH`。Linux 默认使用 Playwright Chromium，`--with-system-deps` 会调用系统包管理器，可能需要 sudo；浏览器与系统依赖已齐备时可使用 `setup --skip-browser`。Linux 缺少 venv 时先安装发行版的 `python3-venv`。`assets` 下载项目内中文字体与许可证，不修改系统字体；可以手动放置相同文件。`seed` 只初始化新库，已有数据不要重复执行。

再次启动可用 Windows `scripts\dev.cmd` 或 PowerShell `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`；Linux 用 `./scripts/dev.sh`。两者都启动 API 与导出 worker，Ctrl+C 一起停止。可追加 `--port 8080` 改端口。直接使用 `.venv` 内 Python 无需激活环境，也无需修改系统 PowerShell 执行策略。

打开 **http://127.0.0.1:8000**。账号 `demo`、`analyst` 为普通用户，`admin` 为管理员；初始密码为 `erp-demo-2026`。可以在初始化前通过 `DEMO_PASSWORD` 设置。初始化不会覆盖已有数据或密码。

默认不需要 `.env`：运行 SQLite + 明确标注的规则演示模式。需要调整配置时将 `.env.example` 复制为 `.env`，再编辑。演示解析器仅覆盖页面示例与有限追问；它不是大模型，不是 API 故障时的自动降级，也不用于证明模型准确率。

开发前端：另开终端运行 `npm run dev --prefix frontend`，访问 http://127.0.0.1:5173；Vite 将 `/api` 代理到 8000。生产构建由 FastAPI 同源提供，避免浏览器跨域凭据问题。

服务使用**单个 API 工作进程**，同时最多五个查询；请勿添加 `--workers`。会话并发控制与登录限流目前在进程内。

跨系统迁移时仅复制源码、配置和所需数据，不要复制 `.venv`、`frontend/node_modules` 或 `.tools`，应在目标系统重新运行 `setup`。统一启动器对被占用端口先报错，不自动终止已有服务。详细配置及验证范围见 [Windows/Linux 部署说明](docs/09-Windows与Linux部署.md)。

## 2. 模型 API

推荐直接登录页面，打开侧栏的“数据库与模型设置”，将“模型模式”设为“使用我的模型 API”，填写 Base URL、模型名称和 API Key。Base URL 包含供应商的接口前缀（通常为 `/v1`），不用填写 `/chat/completions`。点击“测试模型连接”会真实调用一次模型并检查返回的查询计划；测试成功后点击“保存模型设置”，下一次查询立即生效，无需重启。测试可能产生供应商费用。

每个用户只使用自己的配置；密钥保存后不会回显，留空保留已有密钥，更换 API 地址必须重新填写密钥。“使用服务器默认配置”恢复到 `.env` 指定的模式。“规则演示模式”可用于本机联调。

也可以在 `.env` 中设置所有未自定义用户的默认模型，然后重启服务：

```dotenv
MODEL_MODE=api
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=你的模型ID
MODEL_API_KEY=在本机填写密钥
```

适配器使用兼容的 `/chat/completions` HTTP 协议和 JSON object 输出。供应商需要支持该协议、`response_format` 和对应参数；实际模型 ID/地域由你的账号确定。每次查询只调用一次模型；结构错误和超时明确失败，不自动重试收费。提示词提供业务目录、当前日期与最近五轮计划，不提供数据库连接凭据或查询结果明细。

服务器对日期、字段、指标、关联和 SQL 独立校验，但不能保证模型理解每个中文问题都正确。未知指标、缺年份、缺时间、商品筛选金额口径、重名实体等需澄清。

## 3. MySQL 8.4 部署

### 推荐：交互式一键初始化

MySQL 服务已经安装并启动、项目已执行过 `manage.py setup` 时，在项目根目录运行：

```bash
# WSL / Linux 终端
python3 manage.py mysql-init
```

Windows PowerShell 使用 `py manage.py mysql-init`。从文件资源管理器打开的终端如果提示符以 `PS` 开头，当前仍是 PowerShell；使用 WSL 项目时，先输入 `wsl`，再执行 `cd /home/hcy/projects/erp` 和上面的 Linux 命令。无需手动选择 `.venv` 内的 Python。

按提示填写 MySQL 主机、端口、用户名、密码、业务库名、应用库名和订单数量。初始化账号须有建库、创建用户及授权权限，通常使用自己的 MySQL `root` 账号。密码隐藏输入，支持 `@` 等特殊字符，不需要自己拼接连接串。WSL 中连接 Windows 上的 MySQL 时，主机需要填写从 WSL 可访问的 Windows 地址。

脚本自动创建两个数据库、六张业务表、模拟数据和网页登录账号，并生成业务只读账号与应用库账号，将连接信息写入 `.env`。初始化管理员密码不保存；原 `.env` 备份在 `artifacts/config-backups/`，其他模型等设置保留。默认生成 3000 张订单和 9000 条明细，标准规模填 100000。数据日期沿用当前 `DATA_START` / `DATA_END` 配置，默认是 `[2024-11-01, 2026-11-01)`。

完整六表且已有订单时保留业务数据，部分数据或不兼容的业务库会停止初始化；不删除旧数据。已有网页登录账号的密码保持不变，原 SQLite 应用库中的会话等数据不会迁移。MySQL 建库和授权不会随报错自动撤销；失败后保留已生成的数据，修正连接/权限问题后可以重新运行。每次成功执行会生成新的独立运行账号。

完成后运行 `python3 manage.py run`（Windows 用 `py manage.py run`），或重启已运行的服务，打开 http://127.0.0.1:8000 登录。默认业务库已经连接 MySQL，直接开始新会话即可，无需在页面重复添加。

### 手动部署（需要自行管理账号时）

推荐正式部署将应用库和业务库都放在 MySQL，使用 [.env.mysql.example](.env.mysql.example) 作为配置模板。应用库保存账号、会话、连接配置和导出任务；前端选择的是**业务数据库**，不会切换账号库。现有 SQLite 演示数据不会自动迁移到 MySQL。

页面操作：管理员 `admin` 登录 → “数据库与模型设置” → 填写 MySQL 主机、端口、只读账号和密码 → “读取可选数据库” → 选择或输入库名 → 填写实际数据覆盖日期 → “检查并添加数据库”。保存前检查六张业务表及字段是否可读取；新连接对所有登录用户可见。主机地址以运行后端的机器为准。

用户在侧栏“查询数据库”选择连接后开始新会话。会话固定绑定该连接，历史追问不会随新会话选库改变；切换数据库需新建会话。已有会话继续使用服务器默认业务库。当前支持具有项目 ERP 六表结构的数据库，暂不自动理解任意业务表或跨库关联。

可使用已有的专用 MySQL 实例，或启动提供的本机容器：

```bash
docker compose up -d mysql
```

容器仅将 3306 绑定到本机。`database/bootstrap.sql` 在全新数据卷首次启动时创建业务库、应用库及三个账号；请修改其中开发密码。已有数据库可由管理员审阅后执行该文件。

`.env` 设置为：

```dotenv
APP_DATABASE_URL=mysql+pymysql://app_writer:local-writer-change-me@127.0.0.1:3306/nlq_app?charset=utf8mb4
BUSINESS_DATABASE_URL=mysql+pymysql://query_reader:local-reader-change-me@127.0.0.1:3306/erp_demo?charset=utf8mb4
```

仅初始化阶段设置写入业务库的环境变量，然后生成数据：

```bash
export ERP_SEED_DATABASE_URL='mysql+pymysql://demo_seed:local-seed-change-me@127.0.0.1:3306/erp_demo?charset=utf8mb4'
.venv/bin/python manage.py seed --orders 100000 --seed 42
unset ERP_SEED_DATABASE_URL
```

Windows PowerShell 对应写法：

```powershell
$env:ERP_SEED_DATABASE_URL='mysql+pymysql://demo_seed:local-seed-change-me@127.0.0.1:3306/erp_demo?charset=utf8mb4'
.venv\Scripts\python.exe manage.py seed --orders 100000 --seed 42
Remove-Item Env:ERP_SEED_DATABASE_URL
```

随后由管理员执行 `database/grant-reader.sql`，仅给查询账号六张表的 SELECT 权限。运行服务时不需要初始化账号。应用库账号仅在 `nlq_app` 有权限；业务查询使用独立连接池和只读事务，服务器设置 `MAX_EXECUTION_TIME`。不要将管理员连接串填入 `BUSINESS_DATABASE_URL`。

已有业务库只需按项目表结构准备数据，并用 `manage.py seed --app-only` 初始化新的应用库及账号；不要对已有业务数据执行演示数据生成。启动 API 时自动补建 `runtime_settings` 和 `conversation_sources` 两张应用表，不修改原业务表。升级前备份应用库，并确保应用账号拥有建表权限。

数据库密码和用户 API Key 使用 Fernet 加密保存在应用库中，加密密钥默认存于 `artifacts/config.key`，可通过 `CONFIG_KEY_PATH` 指定位置。备份与迁移时同时保留应用数据库和该密钥文件；Linux 文件以仅当前用户可读写权限创建，Windows 部署目录应限制到运行服务的账号。密钥文件丢失时系统明确报错，不会生成新密钥覆盖旧配置。

模拟数据时间区间默认 `[2024-11-01, 2026-11-01)`，标准规模为 10 万订单、30 万明细、1 万客户、1000 商品、20 类别、50 销售人员。换数据种子时使用新库并更新 `DATA_VERSION`，不要混用旧快照。原始 schema 定义见 `backend/app/models.py`。

## 4. Word / PDF 导出

完成快速启动中的 `setup` 和 `assets` 后即可导出，无需重复安装。下面手工命令中的 `python` 均指项目虚拟环境：Windows 为 `.venv\Scripts\python.exe`，Linux 为 `.venv/bin/python`。

Windows 默认自动查找已有 Edge / Chrome；也可设置 `BROWSER_CHANNEL=msedge`、`BROWSER_CHANNEL=chrome` 或 `BROWSER_EXECUTABLE_PATH`。测试脚本和导出 worker 使用同一配置。选择方式见 [Playwright 官方说明](https://playwright.dev/python/docs/browsers)。

仅在没有可用浏览器时安装 Chromium 及其系统依赖（Linux 的系统依赖安装可能需要管理员权限）：

```bash
python -m playwright install --with-deps chromium
```

下载 [Noto Sans CJK SC Regular](https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese) 到 `artifacts/fonts/NotoSansCJKsc-Regular.otf`，保留其 [SIL Open Font License](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)。也可使用 `FONT_PATH` 指向同类中文 OTF 字体。PDF 嵌入中文字体；Word 使用该字体名称，查看 Word 的设备应安装该字体或兼容的中文字体。

使用 `manage.py run` / `dev.cmd` / `dev.sh` 时已经启动导出 worker，**不要再重复启动**。仅在手工单独运行 Uvicorn 时，另开终端、使用同一环境配置启动工作进程：

```bash
python -m backend.worker
```

页面点击 Word/PDF 后自动轮询并下载。导出工作进程应只有一个；它从应用库领取任务，独立子进程渲染、60 秒截止、崩溃后回收陈旧任务。导出保留 24 小时，结果快照 7 天，审计 30 天；工作进程负责到期清理。图表使用 `frontend/node_modules/echarts/dist/echarts.min.js` 本地资源（可用 `CHART_JS_PATH` 修改），浏览器禁用外部网络请求。

导出内容在点击时冻结，包括当前图表、全部已保存行、口径、时间、追溯 ID。前端分页不会改变报告；SQL 附录可选且不展示绑定值。超过 1000 条明细明确标记截断；聚合查询不展示超过上限的部分结果。

## 5. 验证

以下 `python` 同样使用项目虚拟环境解释器；无须激活环境，可直接替换成上述完整路径。

```bash
python -m pytest -q
npm run build --prefix frontend
# API、导出 worker 均已启动时：
python evaluation/browser_smoke.py --exports
# 五种快照场景 × 两种报告格式，检查完整 Word 表格：
python evaluation/report_smoke.py
# 独立检查统一启动器、浏览器、导出与停止（使用 18765 端口）：
python evaluation/platform_smoke.py
# 独立应用库中的设置页、密钥不回显、选库与会话绑定检查：
python evaluation/settings_smoke.py
```

浏览器脚本保存桌面/移动端截图、Word/PDF 下载及完整渲染耗时到 `artifacts/browser/`。这是规则演示链路验证，不替代真实模型验收。详细评测协议见 [evaluation/README.md](evaluation/README.md) 和原始 [评测方案](docs/04-评测与验收方案.md)。

接口文档：http://127.0.0.1:8000/docs 。通过登录接口获得 Cookie 和 `csrf_token` 后，修改接口需要 `X-CSRF-Token` 请求头；登录是例外。

## 6. 运维与故障定位

- `NOT_READY` / 启动报缺表：先初始化应用库和业务库，再运行服务；只重建应用对象用 `python -m backend.seed --app-only`。
- `MODEL_UNAVAILABLE`：检查模型 ID、地址、API Key 与超时；密钥不会返回页面。
- `INVALID_PLAN` / `NEEDS_CLARIFICATION`：检查问题时间、指标、实体及可支持范围。
- `RESULT_TOO_LARGE`：缩短时间范围、减少分组或明确 Top N。图表超过 50 点时只展示表格。
- 导出一直等待：确认 `python -m backend.worker` 在运行且使用相同应用库。
- 导出失败：检查 Chromium、系统库、中文字体和本地 ECharts 文件；失败可重新导出。
- 停止服务和 worker：各终端 Ctrl+C。容器停止用 `docker compose stop`，不删除数据卷。
- SQLite 备份：先停止 API/worker，复制 `artifacts/app.db`、`artifacts/business.db` 和导出目录；MySQL 使用账号权限范围内的 `mysqldump`，恢复到独立库验证后切换配置。

本项目尚未提供任意表结构适配、注册/密码找回、跨库分析和企业级行级权限。共享数据库连接目前支持添加；变更连接信息时请添加新连接并开启新会话。对外部署需 HTTPS、`COOKIE_SECURE=true`、设置允许来源及修改演示账号密码。
