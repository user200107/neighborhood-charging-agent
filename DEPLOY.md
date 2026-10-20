# 部署手册：Netlify + FastAPI

## 0. 本次部署状态

- 前端站点：<https://neighborhood-charging.netlify.app>（在线）。
- Netlify Function：`api-proxy` 已构建发布，`API_BASE_URL` 指向 Vercel FastAPI。
- FastAPI 后端：Vercel 项目 `neighborhood_charging_agent`，公网域名 <https://neighborhoodchargingagent.vercel.app>。
- 数据库：Neon PostgreSQL，已创建表并写入演示数据；`/api/health` 返回 `database: postgresql`。
- LLM：DeepSeek `deepseek-flash` 已接入，Agent 回答带 `llm_polished: true`。
- **本地无需运行**：FastAPI、Docker、MySQL、PostgreSQL、公网隧道均可关闭。
- 注意：`*.vercel.app` 在部分中国大陆网络会被 DNS 污染，浏览器直接打开 Vercel 域名可能失败；请通过 Netlify 站点访问，Netlify Function 在海外可正常回源。

## 1. 先说结论：Netlify 不能直接运行 FastAPI

Netlify 的 Serverless Functions 官方运行时是 **JavaScript / TypeScript / Go**，没有 Python 运行时；静态站点本身也只托管静态文件。因此无法把 FastAPI 直接放到 Netlify Functions 里运行。

- Netlify Functions 总览：<https://docs.netlify.com/build/functions/overview/>
- Functions 入门（语言选项）：<https://docs.netlify.com/build/functions/get-started/>

本项目的生产拓扑：

```text
┌──────────────────────────────┐
│ Netlify                       │
│  ├── 静态前端 dist/           │
│  └── /api/* → Function 代理   │
└──────────────┬───────────────┘
               │ HTTPS + API_BASE_URL
┌──────────────▼───────────────┐
│ Vercel                        │
│  └── FastAPI Function        │
│       └── Neon PostgreSQL    │
└──────────────────────────────┘
```

Netlify Function 只做反向代理，不复制业务逻辑；FastAPI 仍是唯一业务后端。

---

## 2. 部署 FastAPI 后端（Vercel，已采用）

Vercel 官方支持 FastAPI：识别 `app/main.py` 中的 `app` ASGI 实例，零配置构建为 Function。  
参考：<https://vercel.com/docs/frameworks/backend/fastapi>

### 2.1 创建项目

1. 登录 <https://vercel.com>，确保使用 Hobby 免费计划（无需信用卡）。
2. 安装 CLI：`npm i -g vercel`，或使用 `npx vercel`。
3. 在仓库根目录执行：

```bash
vercel link
vercel deploy --prod
```

项目配置：

- Framework：`FastAPI`
- Root Directory：仓库根目录
- Build / Output：保持自动检测

### 2.2 配置环境变量

在 Vercel Project → Settings → Environment Variables 中添加：

```text
APP_ENV=production
DEBUG=false
DEMO_MODE=true
SEED_DEMO_DATA=true
ALLOW_SQLITE_FALLBACK=false
DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require
JWT_SECRET=<32 字节以上随机值>
CORS_ORIGINS=https://neighborhood-charging.netlify.app
LLM_MODEL=deepseek-flash
LLM_API_KEY=<DeepSeek Key>
LLM_BASE_URL=https://api.deepseek.com
```

修改环境变量后需要重新 `vercel deploy --prod`。

### 2.3 验证

```text
GET https://<project>.vercel.app/api/health
→ {"status":"ok","database":"postgresql","database_ok":true}
```

> `*.vercel.app` 在部分中国大陆网络会被 DNS 污染，直接打开 Vercel 域名可能超时；这不影响 Netlify Function 在海外回源，用户始终访问 Netlify 站点。
>
> Render 仍可作为备选：绑定支付方式后使用 `render.yaml` 创建 Docker Web Service；本项目当前未使用 Render，因为其 API 返回 `402 Payment information is required`。

### 2.4 使用任意 Docker 平台

```bash
docker build -t neighborhood-charging-api .
docker run -p 8000:8000 \
  -e APP_ENV=production \
  -e DEBUG=false \
  -e JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  -e DATABASE_URL="postgresql://user:password@host:5432/charging" \
  -e DEMO_MODE=true \
  -e SEED_DEMO_DATA=true \
  neighborhood-charging-api
```

容器内使用 `$PORT`（默认 8000），已内置 `/api/health` 健康检查。

### 2.5 生产环境初始化管理员

关闭种子数据后，空库没有登录账号。首次部署执行：

```bash
python scripts/create_admin.py \
  --username admin \
  --password '请替换为强密码' \
  --tenant-code NEIGHBOR \
  --tenant-name '邻里充电'
```

Vercel 没有常驻 Shell，可在本地对 Neon 执行该脚本；其他平台可在一次性 Job 中执行。脚本会创建租户、管理员并授权租户下全部社区。

### 2.6 生产环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `APP_ENV` | 是 | `production` |
| `DEBUG` | 是 | `false` |
| `JWT_SECRET` | 是 | 32 字节以上随机值，**必须替换默认值** |
| `DATABASE_URL` | 是 | PostgreSQL 连接串，自动转换为 `postgresql+psycopg` |
| `DEMO_MODE` | 否 | 生产建议 `false` |
| `SEED_DEMO_DATA` | 否 | 生产建议 `false` |
| `CORS_ORIGINS` | 否 | 前端域名，例如 `https://your-site.netlify.app`；`*` 仅用于演示 |
| `ACCESS_TOKEN_MINUTES` | 否 | 默认 480 分钟 |
| `REFRESH_TOKEN_DAYS` | 否 | 默认 7 天 |
| `DEVICE_API_KEY` | 否 | 设备网关注入密钥；配置后 `/api/device-events` 支持 `X-Device-Key` |
| `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | 否 | OpenAI 兼容接口，用于润色 Agent 回答；不配置则使用确定性模板 |

> 启用 `CORS_ORIGINS` 具体域名时，浏览器请求会携带 `Authorization`，后端已允许对应头。若前端通过 Netlify Function 同源代理访问，则不会触发跨域。

---

## 3. 部署 Netlify 前端

### 3.1 Git 集成

1. 登录 Netlify → **Add new project** → **Import an existing project**。
2. 选择 GitHub 仓库。
3. 构建设置已被 `netlify.toml` 接管：
   - Build command：`python scripts/build_netlify.py`
   - Publish directory：`dist`
4. 在 **Site configuration → Environment variables** 添加：
   - `API_BASE_URL` = `https://你的后端域名`（不要带 `/api`）
5. 触发 Deploy。

`scripts/build_netlify.py` 会把 `static/` 复制到 `dist/static/`、生成 `dist/index.html`、`_headers` 与运行时配置。无需 npm。

### 3.2 Netlify CLI

```bash
npm install -g netlify-cli
netlify login
netlify init
netlify env:set API_BASE_URL https://你的后端域名
netlify deploy --build --prod
```

查看部署状态：

```bash
netlify status
netlify open:site
```

### 3.3 验证

```bash
curl https://<your-site>.netlify.app/api/health
```

应返回：

```json
{
  "status": "ok",
  "database": "postgresql",
  "database_ok": true,
  "version": "1.0.0"
}
```

然后打开站点，使用演示账号登录。若登录提示「后端未配置」，检查 `API_BASE_URL` 是否设置并重新部署（Function 环境变量在运行时读取，修改后需重新 Deploy 或刷新函数配置）。

---

## 4. Netlify Function 代理说明

文件：`netlify/functions/api-proxy.mjs`

- 通过 `config.path = ["/api/*"]` 接管所有 API 请求。
- 读取运行时环境变量 `API_BASE_URL`，转发方法、路径、查询串、请求体与认证头。
- 移除 hop-by-hop 头，补充 `X-Forwarded-For` / `X-Forwarded-Proto`。
- 未配置 `API_BASE_URL`：返回 `503 API_NOT_CONFIGURED`。
- 后端不可达：返回 `502 UPSTREAM_UNREACHABLE`。
- 响应头附加 `X-Proxied-By: netlify-function`。

如需直连后端（跨域），可在 `dist/static/config.js` 中设置 `apiBaseUrl` 并把后端域名加入 CSP `connect-src`；本仓库默认走同源代理，推荐保持。

---

## 5. 数据库与迁移

- 开发/演示：SQLite `data/charging.db`，启动自动建表与种子。
- 生产：PostgreSQL，`DATABASE_URL` 支持 `postgres://` 与 `postgresql://`，自动使用 psycopg3。
- 参考 DDL：`database/init.sql`（由 ORM 模型生成）。
- 应用启动执行 `Base.metadata.create_all`，适用于首次部署；后续结构变更建议接入 Alembic：
  ```bash
  pip install alembic
  alembic init migrations
  ```
  将 `app.models.Base.metadata` 配置为 target metadata，生成并审查迁移后再发布。

备份建议：每日全量 + 持续增量，异地加密保留；每月恢复演练，核对用户、订单、事件、审批、审计。

---

## 6. 回滚

1. Netlify：Deploys → 选择上一个成功 Deploy → **Rollback**。
2. 后端：容器平台回滚到上一镜像/版本。
3. 数据库：仅使用向后兼容迁移；订单、退款、审批数据不直接删除，采用状态修正与审计补偿。

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| **Docker Desktop 无法启动** | Windows `WSLService` 被禁用，Docker 日志报 `Wsl/0x80070422` | 以管理员身份打开 PowerShell：`Set-Service WSLService -StartupType Automatic; Start-Service WSLService`，再启动 Docker Desktop；若 WSL 功能未启用则执行 `wsl --install` 并重启 |
| Docker 启动后数据库端口未监听 | 容器未启动/健康检查未通过 | `docker compose up -d`，`docker compose ps`，等待 healthy |
| MySQL 连接 1045 | 容器未启动或 `.env` 密码与 compose 不一致 | 使用 `docker compose up -d`；默认 `agent_user/123456` |
| PostgreSQL 连接超时 | 5432 未启动 | `docker compose up -d postgres`；检查 `docker compose logs postgres` |
| `503 API_NOT_CONFIGURED` | Netlify 未设置 `API_BASE_URL` | 设置环境变量并重新部署 |
| `502 UPSTREAM_UNREACHABLE` | 后端休眠/域名错误/证书问题 | 访问后端 `/api/health`，确认 Render 实例已唤醒 |
| 登录 401 | 密码错误或演示数据未初始化 | 检查 `DEMO_MODE` / `SEED_DEMO_DATA`，或执行 `create_admin.py` |
| 首次请求很慢 | Render 免费实例冷启动 | 升级实例或使用保活探针 |
| 数据重启后丢失 | SQLite 容器临时盘 | 使用托管 PostgreSQL |
| 工单无法关闭 | 未完成验收/心跳过期 | 先「维修回填」→「提交验收」→ 再「关闭」 |
| Agent 不执行停机 | 设计如此 | 高风险动作只创建审批，由财务/管理员执行 |

---

## 8. 只部署前端会发生什么？

可以部署成功，页面、登录界面、静态资源均正常；但所有 API 请求会返回 `503 API_NOT_CONFIGURED`，无法登录。若只想做纯静态展示，需要额外实现浏览器端 mock 数据层，本项目未采用该方案——后端保持 FastAPI 单一事实来源。

---

## 9. 上线检查清单

- [ ] 替换 `JWT_SECRET`，关闭 `DEBUG`、`DEMO_MODE`、`SEED_DEMO_DATA`
- [ ] 使用 PostgreSQL，开启自动备份与恢复演练
- [ ] 限制 `CORS_ORIGINS` 为正式域名
- [ ] 配置 HTTPS、WAF/限流、登录失败告警
- [ ] 关闭或限制 `/docs`（生产默认关闭）
- [ ] 配置日志聚合、指标与 P1 告警
- [ ] 依赖漏洞扫描、密钥扫描、越权测试
- [ ] 执行工单验收、审批执行、Agent 高风险拦截回归
