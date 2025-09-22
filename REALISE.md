# SmartSpider — 详细技术方案（按“核心目标”逐条展开）

下面把你之前列出的**核心目标**逐项拆成：目标说明 → 关键需求 → 设计思路 & 技术选型 → 详细实现要点（接口/数据模型/算法/异常与监控）→ 可交付产物（示例代码/schema/JSON）。内容尽量具体，可直接用于开发与分阶段实现。

---

# 1. 接口驱动（任务通过 JSON / REST 下发）

**目标说明**
所有爬虫任务由外部接口下发（REST 或 gRPC），任务描述为 JSON 配置，爬虫根据此配置执行，便于无代码控制与自动化。

**关键需求**

- 支持完整任务描述（入口 URL、分页规则、并发、解析规则、是否使用 Cookie、调度时间等）
- 任务可查询/暂停/终止/重试
- 任务版本化与审计

**设计思路 & 技术选型**

- 后端：`FastAPI`（轻量、异步、自动生成 OpenAPI）
- 校验：`pydantic`（验证任务 JSON）
- 队列：`Redis`（任务队列 + 进度缓存）或 `Celery`（若需要分布式成熟生态）
- 存储：Postgres/MySQL 存储任务元数据

**实现要点**

- 定义 `TaskConfig` 的 pydantic 模型（下面有示例）
- API：`POST /tasks` (创建)，`GET /tasks/{id}`，`POST /tasks/{id}/start|stop|pause`，`GET /tasks/{id}/status`
- 将任务放入队列（Redis list 或 Celery broker），worker 从队列弹出执行
- 支持“dry-run”验证任务 JSON

**示例 TaskConfig（简化）**

<pre class="overflow-visible!" data-start="766" data-end="1210"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>&#34;name&#34;</span><span>:</span><span> </span><span>&#34;zhihu_comments&#34;</span><span>,</span><span>
  </span><span>&#34;entry_urls&#34;</span><span>:</span><span> </span><span>[</span><span>&#34;https://www.zhihu.com/question/12345&#34;</span><span>]</span><span>,</span><span>
  </span><span>&#34;pagination&#34;</span><span>:</span><span> </span><span>{</span><span>&#34;type&#34;</span><span>:</span><span>&#34;next_link&#34;</span><span>,</span><span>&#34;selector&#34;</span><span>:</span><span>&#34;a.next&#34;</span><span>}</span><span>,</span><span>
  </span><span>&#34;selectors&#34;</span><span>:</span><span> </span><span>{</span><span>
    </span><span>&#34;items&#34;</span><span>:</span><span> </span><span>{</span><span>&#34;type&#34;</span><span>:</span><span>&#34;css&#34;</span><span>,</span><span>&#34;expr&#34;</span><span>:</span><span>&#34;.comment-item&#34;</span><span>}</span><span>,</span><span>
    </span><span>&#34;fields&#34;</span><span>:</span><span> </span><span>{</span><span>
      </span><span>&#34;author&#34;</span><span>:</span><span>{</span><span>&#34;type&#34;</span><span>:</span><span>&#34;css&#34;</span><span>,</span><span>&#34;expr&#34;</span><span>:</span><span>&#34;.author::text&#34;</span><span>}</span><span>,</span><span>
      </span><span>&#34;content&#34;</span><span>:</span><span>{</span><span>&#34;type&#34;</span><span>:</span><span>&#34;css&#34;</span><span>,</span><span>&#34;expr&#34;</span><span>:</span><span>&#34;.content::text&#34;</span><span>}</span><span>
    </span><span>}</span><span>
  </span><span>}</span><span>,</span><span>
  </span><span>&#34;concurrency&#34;</span><span>:</span><span> </span><span>10</span><span>,</span><span>
  </span><span>&#34;use_cookie&#34;</span><span>:</span><span> </span><span>true</span><span></span><span>,</span><span>
  </span><span>&#34;cookie_id&#34;</span><span>:</span><span> </span><span>3</span><span>,</span><span>
  </span><span>&#34;schedule&#34;</span><span>:</span><span> </span><span>null</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

---

# 2. 高并发 & 异步处理

**目标说明**
高吞吐的 HTTP 请求处理，支持成千上万页面的抓取，同时避免阻塞与资源争用。

**关键需求**

- 每个 Worker 支持高并发 IO（数百并发）
- 全局/每任务速率限制（防封禁）
- 代理池、UA 轮换

**设计思路 & 技术选型**

- 异步 HTTP 客户端：`httpx` (async) 或 `aiohttp`。`httpx` 更现代、API 友好；`aiohttp` 在性能/成熟度上也可靠。
- 并发控制：`asyncio.Semaphore` + per-task queue；全局速率使用 `aiolimiter` 或自实现 leaky-bucket。
- 分布式扩展：单机用 asyncio；横向扩展用多 Worker + Redis 队列（比如 Celery、RQ、Dramatiq）或 Kubernetes 自动伸缩。

**实现要点**

- Worker 采用异步主循环，内部根据 `concurrency` 使用 Semaphore 限制并发连接。
- 每个请求有重试策略（指数退避 + 随机抖动）。
- 实现“per-domain”速率限制，避免同域请求过快。
- 使用连接池（httpx.AsyncClient）复用连接。
- 若分布式：使用 Redis 队列作为任务分发，并且对任务做幂等唯一 id。

**伪代码（Worker 核心）**

<pre class="overflow-visible!" data-start="1835" data-end="2357"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>async</span><span> </span><span>with</span><span> httpx.AsyncClient(timeout=</span><span>10</span><span>) </span><span>as</span><span> client:
    sem = asyncio.Semaphore(concurrency)
    </span><span>async</span><span> </span><span>def</span><span> </span><span>fetch</span><span>(</span><span>url</span><span>):
        </span><span>async</span><span> </span><span>with</span><span> sem:
            </span><span>for</span><span> attempt </span><span>in</span><span> </span><span>range</span><span>(retry):
                </span><span>try</span><span>:
                    r = </span><span>await</span><span> client.get(url, headers=headers, proxies=pick_proxy())
                    r.raise_for_status()
                    </span><span>return</span><span> r.text
                </span><span>except</span><span> Exception:
                    </span><span>await</span><span> asyncio.sleep(backoff(attempt))
    </span><span>await</span><span> asyncio.gather(*[fetch(u) </span><span>for</span><span> u </span><span>in</span><span> urls])
</span></span></code></div></div></pre>

---

# 3. 稳定性（重试、断点续爬、异常处理）

**目标说明**
长时运行不崩溃，节点崩溃后能恢复任务进度。

**关键需求**

- 请求/解析错误分类（可重试 vs 不可重试）
- 任务断点续爬（记录已抓取 URL）
- 任务失败率报警与自动重试

**设计思路**

- 使用 Redis / DB 存储任务进度（已爬 URL 集合、待爬队列、错误计数）
- 对可重试错误（网络超时、代理失败）进行 N 次重试；永久错误记录并跳过
- 定期 checkpoint（每隔 N 个 item 保存到 DB）
- Worker 采用“任务 lease”模式：从队列获取任务时设置 lease（锁），超时自动返回队列，避免死锁

**实现要点**

- 已抓取 URL 存 Redis set（`SADD`），查重快速
- 待抓队列使用 Redis list 或 Stream（Redis Streams 更可靠）
- 断点续爬：任务中断后，队列和已抓集合可继续使用
- 异常监控：设置错误阈值（例如连续 5 次失败则暂停任务并报警）

---

# 4. 进度追踪 & 监控

**目标说明**
提供实时进度（已完成/总数/成功率/错误详情），并能远程查看。

**关键需求**

- 实时数字指标（success_count, fail_count, total, running_workers）
- 任务级别日志（结构化）
- WebSocket 或 SSE 支持界面实时更新

**设计思路 & 技术选型**

- 使用 Redis 或 Postgres 存储进度摘要；Redis 用于高频更新（fast），DB 用于持久化审计
- API 提供 `GET /tasks/{id}/metrics` 和 `GET /tasks/{id}/logs`；也提供 `ws /tasks/{id}/ws` 以实时推送
- 指标导出：Prometheus 格式（`/metrics`），供 Grafana 可视化

**实现要点**

- Worker 每 N 条更新一次 Redis 进度键（避免过度写入）
- 日志使用 JSON 格式，写到文件并发送到日志存储（ELK/Loki）
- 实现 WebSocket 订阅，后端从 Redis pub/sub 发布进度

---

# 5. 日志收集（结构化日志 + 可查询）

**目标说明**
统一结构化日志、方便检索与告警。

**关键需求**

- 任务级别日志（info/warn/error）
- 日志持久化（文件 + 集中式）
- 可按任务/时间/错误类型查询

**设计思路 & 技术选型**

- Python 日志：`structlog` 或 `python-json-logger`，输出 JSON
- 集中存储：Loki + Grafana 或 ELK（Elasticsearch + Logstash + Kibana）
- 日志分层：worker 本地落盘 + 通过 HTTP/UDP/agent 推送到集中存储

**实现要点**

- 在 logger 中携带 task_id、worker_id、url 等上下文
- 错误日志触发告警（例如 Sentry 集成或 Prometheus Alertmanager）

---

# 6. 数据清洗 Pipeline（自动清洗、验证、去重）

**目标说明**
数据入库前经过标准化和校验，保证质量。

**关键需求**

- 规则化（trim、统一时间格式、数字化）
- 字段校验（必填、类型、正则）
- 去重（基于哈希或唯一字段）
- 可插拔清洗步骤（像 Scrapy pipeline）

**设计思路**

- 采用 Pipeline 设计：parse -> item -> pipeline processors（validators, normalizer, deduper, enrichers）
- 使用 `pydantic` model 对 item 验证与转换
- 去重策略：如果数据有唯一 id，使用 DB 唯一索引；没有则使用内容 hash (SHA256) 存 Redis set

**实现要点**

- 每个 pipeline 组件单元测试
- 可以配置 pipeline 优先级与开关（比如启用/禁用 NLP 清洗）
- 提供“清洗日志”记录变更

**示例 pipeline**

<pre class="overflow-visible!" data-start="4226" data-end="4402"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>class</span><span> </span><span>NormalizeWhitespace</span><span>:
    </span><span>def</span><span> </span><span>process</span><span>(</span><span>self, item</span><span>): ...
</span><span>class</span><span> </span><span>PhoneExtractor</span><span>:
    </span><span>def</span><span> </span><span>process</span><span>(</span><span>self, item</span><span>): ...
</span><span>class</span><span> </span><span>Deduper</span><span>:
    </span><span>def</span><span> </span><span>process</span><span>(</span><span>self, item</span><span>): ...
</span></span></code></div></div></pre>

---

# 7. Cookie 管理（读取本地浏览器 cookie 并上传/切换）

**目标说明**
读取本地浏览器 cookie（如 Chrome），上传到服务器集中管理；爬虫执行时可切换 cookie 使用。

**关键需求**

- 从客户端机器读取 cookie（`browser_cookie3`）
- 上传 cookie 到后端，后端存储（加密）
- cookie 状态管理（valid/invalid/last_used/usage_count）
- cookie 分配/租用（避免同一 cookie 同时被多个请求滥用）

**设计思路 & 技术选型**

- 客户端脚本调用 `browser_cookie3.chrome()` 读取 cookie，转换成统一格式 JSON 并上传 `POST /cookies/upload`
- 后端存储：MySQL/Postgres 存元数据 + 加密的 cookie blob（使用 `cryptography.Fernet` 或数据库透明加密）
- Cookie 分配：Worker 请求 cookie 时向 `/cookies/lease?domain=...` 获取一个可用 cookie，并在使用后释放或标记失效

**实现要点**

- Cookie schema（见下）
- Cookie 授权：上传 API 需认证（token）
- Cookie 租约（lease）机制：当 Worker 获取 cookie，后端返回 lease_id 和 TTL；Worker 在释放时提交 lease_id；若超时 lease 自动恢复
- 定期校验 cookie（自动登录检测），失效则标记并通知管理员

**数据库表（cookie）示例**

<pre class="overflow-visible!" data-start="5158" data-end="5495"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-sql"><span><span>CREATE</span><span> </span><span>TABLE</span><span> cookies (
  id SERIAL </span><span>PRIMARY</span><span> KEY,
  name TEXT,
  domain TEXT,
  cookie_json JSONB,
  owner </span><span>VARCHAR</span><span>,
  status </span><span>VARCHAR</span><span>, </span><span>-- active, invalid, locked</span><span>
  last_used </span><span>TIMESTAMP</span><span>,
  usage_count </span><span>INT</span><span> </span><span>DEFAULT</span><span> </span><span>0</span><span>,
  encrypted_blob BYTEA,
  created_at </span><span>TIMESTAMP</span><span> </span><span>DEFAULT</span><span> now()
);
</span><span>CREATE</span><span> INDEX idx_cookies_domain </span><span>ON</span><span> cookies(domain);
</span></span></code></div></div></pre>

**客户端上传示例（Python + browser_cookie3）**

<pre class="overflow-visible!" data-start="5535" data-end="5906"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>import</span><span> browser_cookie3, requests, json
cj = browser_cookie3.chrome()
cookies_for_domain = [ {</span><span>&#34;name&#34;</span><span>:c.name,</span><span>&#34;value&#34;</span><span>:c.value,</span><span>&#34;domain&#34;</span><span>:c.domain,</span><span>&#34;path&#34;</span><span>:c.path} </span><span>for</span><span> c </span><span>in</span><span> cj </span><span>if</span><span> </span><span>&#34;zhihu.com&#34;</span><span> </span><span>in</span><span> c.domain ]
requests.post(</span><span>&#34;https://spider.example.com/api/cookies/upload&#34;</span><span>, json={</span><span>&#34;domain&#34;</span><span>:</span><span>&#34;zhihu.com&#34;</span><span>,</span><span>&#34;cookies&#34;</span><span>:cookies_for_domain}, headers={</span><span>&#34;Authorization&#34;</span><span>:</span><span>&#34;Bearer ...&#34;</span><span>})
</span></span></code></div></div></pre>

---

# 8. 数据存储（结果持久化与检索）

**目标说明**
抓取结果可靠存储，可快速查询、分析和导出。

**关键需求**

- 支持结构化与非结构化存储（MySQL/Mongo/Elasticsearch）
- 支持批量写入与去重
- 支持按任务导出 CSV/Excel & API 下载

**设计思路**

- 关系型 DB（Postgres/MySQL）用于任务元数据与小量结构化结果
- 文档型 DB（MongoDB）或 Elasticsearch 用于大规模全文检索与分析
- 写入策略：先写入本地 WAL（或 Redis 队列）异步批写到 DB，提升吞吐并避免丢失

**实现要点**

- 设计结果表/集合 schema 包含 task_id、url、data(json)、hash、created_at
- 批量写入：每隔 N 条合并提交
- 建立唯一索引（task_id + fingerprint）防重复写入
- 提供 `GET /results?task_id=...` 和导出接口

**示例 SQL schema（results）**

<pre class="overflow-visible!" data-start="6393" data-end="6646"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-sql"><span><span>CREATE</span><span> </span><span>TABLE</span><span> results (
  id BIGSERIAL </span><span>PRIMARY</span><span> KEY,
  task_id </span><span>INT</span><span> </span><span>NOT</span><span> </span><span>NULL</span><span>,
  url TEXT,
  data JSONB,
  fingerprint </span><span>VARCHAR</span><span>(</span><span>64</span><span>),
  created_at </span><span>TIMESTAMP</span><span> </span><span>DEFAULT</span><span> now()
);
</span><span>CREATE</span><span> </span><span>UNIQUE</span><span> INDEX idx_results_task_fp </span><span>ON</span><span> results (task_id, fingerprint);
</span></span></code></div></div></pre>

---

# 9. 任务调度（定时/周期任务）

**目标说明**
任务可按 Cron 或固定周期执行。

**关键需求**

- 支持 Cron 表达式
- 支持手动触发与定时触发共存
- 支持调度历史与重试策略

**设计思路 & 技术选型**

- 使用 `APScheduler`（单机轻量）或 `Celery Beat`（分布式）管理调度规则
- 调度元数据保存在 DB（可审计）
- Scheduler 将生成的“执行实例”下发到队列，Worker 执行

**实现要点**

- 提供 API `POST /schedules`，字段：task_id, cron, enabled
- Scheduler 负责把调度触发转化为具体任务提交到任务队列
- 切换调度实现（开发初期用 APScheduler，后期迁移至 Celery Beat）

---

# 10. 可扩展性（插件化、代理、验证码识别）

**目标说明**
系统支持插件扩展，比如验证码识别、代理管理、反爬策略、AI 解析模块。

**关键需求**

- 插件可注册 hook（请求前/响应后/parse）
- 动态加载插件
- 插件隔离（错误不影响主流程）

**设计思路**

- 定义插件接口（Python abstract base classes），插件以包形式安装或放入 `plugins/` 目录动态加载
- 插件通过配置开启或关闭
- 捕获插件异常并降级（记录错误）

**实现要点**

- 插件示例：`ProxyProvider`, `CaptchaSolver`, `NLPProcessor`
- 插件优先级与依赖管理
- 测试时可 mock 插件

---

# 其它重要点（安全 / 运维 / 测试 / 部署）

**安全**

- 所有敏感数据（cookie, api keys）在 DB 中加密（`cryptography.Fernet`）
- API 通过 JWT / OAuth 认证
- HTTPS 强制

**运维 & 部署**

- 推荐使用 Docker + docker-compose（开发）与 Kubernetes（生产）
- 提供 `docker-compose` 栈：`redis`, `postgres`, `rabbitmq/celery`(可选), `minio`(存储), `kibana/loki`(日志)
- 提供健康检查和 `/metrics`（Prometheus）

**测试**

- 单元测试：`pytest` + `pytest-asyncio`
- 集成测试：docker-compose 环境下测试 worker 与 queue 协作
- 合约测试：API 的 OpenAPI + 自动化测试脚本

**监控**

- Metrics: Prometheus 指标（请求数、成功率、队列长度、任务耗时）
- 日志: Loki/ELK
- Tracing: OpenTelemetry (可选)

---

# 接口 & 数据模型一览（快速参考）

## 主要 REST 接口（示例）

- `POST /api/tasks` — 创建任务（body: TaskConfig）
- `GET /api/tasks/{id}` — 获取任务详情
- `POST /api/tasks/{id}/start` — 启动任务
- `POST /api/tasks/{id}/stop` — 停止任务
- `GET /api/tasks/{id}/metrics` — 获取进度/指标
- `POST /api/cookies/upload` — 上传 cookie（客户端脚本调用）
- `GET /api/cookies/lease?domain=...` — 租用 cookie
- `POST /api/results/export?task_id=...` — 导出结果

## 关键 DB 表（简化）

- `tasks` (id, name, config JSON, owner, status, created_at)
- `task_runs` (id, task_id, started_at, finished_at, metrics JSON)
- `cookies` (id, domain, name, encrypted_blob, status, owner, last_used)
- `results` (id, task_id, url, data JSON, fingerprint, created_at)
- `logs` (id, task_id, level, message JSON, created_at)

---

# MVP 开发路线（建议分阶段）

**阶段 0 — 基础骨架**

- FastAPI + 简单 DB (sqlite/postgres) + Redis
- 异步 Worker（httpx） + 简单任务 JSON 驱动
- 本地读取 cookie 并上传（browser_cookie3）
- 日志本地化

**阶段 1 — 可用系统**

- 任务队列 (Redis), 任务 lease & progress 存 Redis
- Data pipeline 基本组件（validator/normalizer/deduper）
- Results 存 Postgres/Mongo
- 单机部署 docker-compose

**阶段 2 — 稳定 & 扩展**

- 分布式（Celery/Worker autoscale）
- 日志集中（Loki/ELK）
- Prometheus + Grafana
- Cookie lease 改进、自动检测失效

**阶段 3 — 平台化**

- Web 控制台（Vue3）+ 实时 WebSocket
- 插件生态（captcha, proxy）
- 作业审计 & 用户权限

---

# 示例：FastAPI 的 Task 创建（简短示例）

<pre class="overflow-visible!" data-start="9201" data-end="9793"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>from</span><span> fastapi </span><span>import</span><span> FastAPI, HTTPException
</span><span>from</span><span> pydantic </span><span>import</span><span> BaseModel, HttpUrl
</span><span>from</span><span> uuid </span><span>import</span><span> uuid4

</span><span>class</span><span> </span><span>SelectorSpec</span><span>(</span><span>BaseModel</span><span>):
    </span><span>type</span><span>: </span><span>str</span><span>
    expr: </span><span>str</span><span>

</span><span>class</span><span> </span><span>TaskConfig</span><span>(</span><span>BaseModel</span><span>):
    name: </span><span>str</span><span>
    entry_urls: </span><span>list</span><span>[HttpUrl]
    selectors: </span><span>dict</span><span>
    concurrency: </span><span>int</span><span> = </span><span>5</span><span>
    use_cookie: </span><span>bool</span><span> = </span><span>False</span><span>
    cookie_id: </span><span>int</span><span> | </span><span>None</span><span> = </span><span>None</span><span>

app = FastAPI()

</span><span>@app.post(&#34;/api/tasks&#34;</span><span>)
</span><span>async</span><span> </span><span>def</span><span> </span><span>create_task</span><span>(</span><span>cfg: TaskConfig</span><span>):
    task_id = </span><span>str</span><span>(uuid4())
    </span><span># persist to DB, enqueue</span><span>
    </span><span># redis.lpush(&#34;task_queue&#34;, task_id)</span><span>
    </span><span>return</span><span> {</span><span>&#34;task_id&#34;</span><span>: task_id, </span><span>&#34;status&#34;</span><span>: </span><span>&#34;created&#34;</span><span>}
</span></span></code></div></div></pre>

---

# 常见风险与应对

- ​**被目标网站封禁**​：使用代理池、UA 轮换、速率限制；多 cookie 轮换；合理退避。
- ​**Cookie 泄露风险**​：加密存储、最小权限、审计。
- ​**分布式一致性**​：任务幂等性设计、lease/锁机制、幂等写入（fingerprint + unique index）。
- ​**性能瓶颈（DB）**​：采用批写、缓存（Redis）、分库分表或使用更适合检索的存储（Elasticsearch）。
