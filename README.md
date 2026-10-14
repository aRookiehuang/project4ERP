# 观数 · ERP 智能销售查询

基于当前目录项目文档实现的 Vue 3 + TypeScript + FastAPI 查询应用。业务数据库使用 MySQL 8.4；另提供 SQLite 本机演示/自动化测试模式。模型输出受限 QueryPlan，由服务端编译参数化 SQL，经 AST 校验后只读执行。

## 已实现

- 中文对话界面、历史会话、预置账号登录、CSRF 与资源归属校验。
- 单表及最多四表关联；销售额、订单数、销量、客户数、客单价、最高/最低订单金额；分组、Top N、HAVING、布尔筛选、日/月趋势、销售占比。
- 支付时间和下单时间区分、订单地区快照、同名实体消歧、商品明细金额与整单金额区分。
- 最近五轮已确认计划、澄清引用、幂等请求、查询取消、查询时限、结果行数/字节限制。
- 确定性摘要、ECharts 图表、快照分页、无需重新查库的图表切换、SQL 追溯。
- 独立持久化导出任务、Word/PDF、中文字体、本地图表资源、超时与过期清理。
- 六表模拟数据生成器、10 万订单/30 万明细规模选项、固定种子与金额一致性校验。
- 口径/SQL 安全/API 隔离测试，HTTP 评测工具和浏览器完整响应计时。

真实模型准确率、MySQL 性能和文档要求的正式盲测尚需部署后验证；不声明已经满足 91% 或 3 秒指标。开发验证情况及限制见 [实施记录](docs/07-实现与验证记录.md)。

## 1. 本机快速启动

需要 Python 3.10+、Node.js 22+。以下命令从仓库根目录执行。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
npm ci --prefix frontend
npm run build --prefix frontend
python -m backend.seed --orders 3000
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell 将前两行改为 `py -m venv .venv`、`.venv\Scripts\Activate.ps1`。Linux 缺少 venv 时先安装发行版的 `python3-venv`。

打开 **http://127.0.0.1:8000**。账号 `demo`、`analyst` 为普通用户，`admin` 为管理员；初始密码为 `erp-demo-2026`。可以在初始化前通过 `DEMO_PASSWORD` 设置。初始化不会覆盖已有数据或密码。

默认不需要 `.env`：运行 SQLite + 明确标注的规则演示模式。需要调整配置时将 `.env.example` 复制为 `.env`，再编辑。演示解析器仅覆盖页面示例与有限追问；它不是大模型，不是 API 故障时的自动降级，也不用于证明模型准确率。

开发前端：另开终端运行 `npm run dev --prefix frontend`，访问 http://127.0.0.1:5173；Vite 将 `/api` 代理到 8000。生产构建由 FastAPI 同源提供，避免浏览器跨域凭据问题。

服务使用**单个 API 工作进程**，同时最多五个查询；请勿添加 `--workers`。会话并发控制与登录限流目前在进程内。

当前工作区已安装依赖并初始化演示数据。Linux/WSL 可直接运行 `./scripts/dev.sh`，同时启动 API 和导出 worker；脚本会识别工作区内的 Node.js 与浏览器系统库。先停止已有 8000 端口服务，避免重复启动。

## 2. 模型 API

在 `.env` 中设置并重启服务：

```dotenv
MODEL_MODE=api
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=你的模型ID
MODEL_API_KEY=在本机填写密钥
```

适配器使用兼容的 `/chat/completions` HTTP 协议和 JSON object 输出。供应商需要支持该协议、`response_format` 和对应参数；实际模型 ID/地域由你的账号确定。每次查询只调用一次模型；结构错误和超时明确失败，不自动重试收费。提示词提供业务目录、当前日期与最近五轮计划，不提供数据库连接凭据或查询结果明细。

服务器对日期、字段、指标、关联和 SQL 独立校验，但不能保证模型理解每个中文问题都正确。未知指标、缺年份、缺时间、商品筛选金额口径、重名实体等需澄清。

## 3. MySQL 8.4 部署

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
python -m backend.seed --orders 100000 --seed 42
unset ERP_SEED_DATABASE_URL
```

随后由管理员执行 `database/grant-reader.sql`，仅给查询账号六张表的 SELECT 权限。运行服务时不需要初始化账号。应用库账号仅在 `nlq_app` 有权限；业务查询使用独立连接池和只读事务，服务器设置 `MAX_EXECUTION_TIME`。不要将管理员连接串填入 `BUSINESS_DATABASE_URL`。

模拟数据时间区间默认 `[2024-11-01, 2026-11-01)`，标准规模为 10 万订单、30 万明细、1 万客户、1000 商品、20 类别、50 销售人员。换数据种子时使用新库并更新 `DATA_VERSION`，不要混用旧快照。原始 schema 定义见 `backend/app/models.py`。

## 4. Word / PDF 导出

安装 Chromium 及其系统依赖（Linux 的系统依赖安装可能需要管理员权限）：

```bash
python -m playwright install --with-deps chromium
```

下载 [Noto Sans CJK SC Regular](https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese) 到 `artifacts/fonts/NotoSansCJKsc-Regular.otf`，保留其 [SIL Open Font License](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)。也可使用 `FONT_PATH` 指向同类中文 OTF 字体。PDF 嵌入中文字体；Word 使用该字体名称，查看 Word 的设备应安装该字体或兼容的中文字体。

另开终端、使用同一环境配置启动工作进程：

```bash
python -m backend.worker
```

页面点击 Word/PDF 后自动轮询并下载。导出工作进程应只有一个；它从应用库领取任务，独立子进程渲染、60 秒截止、崩溃后回收陈旧任务。导出保留 24 小时，结果快照 7 天，审计 30 天；工作进程负责到期清理。图表使用 `frontend/node_modules/echarts/dist/echarts.min.js` 本地资源（可用 `CHART_JS_PATH` 修改），浏览器禁用外部网络请求。

导出内容在点击时冻结，包括当前图表、全部已保存行、口径、时间、追溯 ID。前端分页不会改变报告；SQL 附录可选且不展示绑定值。超过 1000 条明细明确标记截断；聚合查询不展示超过上限的部分结果。

## 5. 验证

```bash
python -m pytest -q
npm run build --prefix frontend
# API、导出 worker 均已启动时：
python evaluation/browser_smoke.py --exports
# 五种快照场景 × 两种报告格式，检查完整 Word 表格：
python evaluation/report_smoke.py
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

本项目尚未提供任意数据源管理、注册/密码找回、跨库分析和企业级行级权限。对外部署需 HTTPS、`COOKIE_SECURE=true`、设置允许来源及修改演示账号密码。
