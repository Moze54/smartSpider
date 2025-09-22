# SmartSpider

一个高效的数据提取和处理的智能网络爬虫项目。

## 特性

- 高效的网页抓取
- HTML 解析和数据提取
- 可配置的爬取规则
- 数据存储和处理

## 安装

### 要求

- Python 3.9 或更高版本

### 安装依赖

```bash
pip install -r requirements.txt
# 开发环境依赖
pip install -r requirements-dev.txt
```

## 使用方法

```bash
python -m smart_spider
```

# 🕷 SmartSpider 设计方案

## 🎯 核心目标

1. ​**接口驱动**​：所有任务通过接口配置（JSON / REST API）下发，不用改代码即可控制抓取。
2. ​**高并发 & 异步**​：支持 `asyncio + aiohttp` 或 `httpx` 实现异步请求，结合任务队列（Celery/Redis/Kafka）支撑大规模并发。
3. ​**稳定性**​：支持重试、异常捕获、断点续爬，保证长时间运行不崩溃。
4. ​**进度追踪**​：每个任务可追踪进度（已抓取 / 总数 / 成功率 / 错误日志）。
5. ​**日志收集**​：统一日志系统（结构化日志 JSON + Elasticsearch / Loki + Grafana 可视化）。
6. ​**数据清洗**​：内置数据清洗规则（正则 / XPath / CSS Selector / AI 解析），保证数据准确性。
7. ​**Cookie 管理**​：支持本地浏览器 cookie 读取，上传到服务器集中存储，支持多 cookie 轮换使用，避免账号封禁。
8. ​**数据存储**​：支持 MySQL / MongoDB / Elasticsearch / CSV/Excel 导出。
9. ​**任务调度**​：可定时运行（APScheduler / Celery Beat），支持周期任务。
10. ​**扩展性**​：支持自定义插件（比如验证码识别、代理池、反爬策略）。

---

## 🏗 系统架构设计

<pre class="overflow-visible!" data-start="793" data-end="1345"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>SmartSpider
│
├── API 层（FastAPI / Flask）
│   ├── 接口下发任务（启动、停止、查询任务状态）
│   ├── Cookie 管理（上传、切换、分配）
│   └── 数据导出接口
│
├── </span><span>Scheduler</span><span> 调度层
│   ├── 任务调度（定时、周期）
│   ├── 分发到 Worker 节点
│
├── Worker 执行层
│   ├── 异步爬虫引擎（asyncio + httpx/aiohttp）
│   ├── 任务队列（Celery / Redis）
│   ├── Cookie 轮换机制
│   ├── 异常重试 &amp; 超时处理
│   └── 数据清洗 Pipeline
│
├── 存储层
│   ├── 任务状态（Redis/MySQL）
│   ├── Cookie 存储（MySQL/Redis）
│   ├── 数据存储（MongoDB/MySQL/Elasticsearch）
│   └── 日志存储（文件 / ELK / Loki）
│
└── Web 控制台（可选，后续迭代）
    ├── 任务管理界面
    ├── 日志查询
    ├── Cookie 管理
    └── 数据可视化
</span></span></code></div></div></pre>

---

## 📋 功能清单

### 1. 任务管理

- [ ] 通过 API 提交爬虫任务（传入 JSON 配置）
- [ ] 支持任务启动、暂停、终止
- [ ] 任务进度实时查询（已完成/总数/错误数）
- [ ] 支持定时任务（如每天凌晨爬取一次）

### 2. 爬虫引擎

- [ ] 异步请求（`aiohttp/httpx`）
- [ ] 支持并发控制（最大连接数/速率限制）
- [ ] 自动重试 & 超时处理
- [ ] 请求头/代理池/随机 UA

### 3. Cookie 管理

- [ ] 本地读取浏览器 cookie（`browser_cookie3`）
- [ ] 上传到服务器存储（数据库）
- [ ] 多 cookie 轮换使用
- [ ] Cookie 失效自动检测 & 切换

### 4. 数据处理

- [ ] 支持 XPath / CSS Selector 提取
- [ ] 内置正则清洗器（去空格、提取手机号、邮箱等）
- [ ] 可插入 AI 辅助解析模块（后期扩展）
- [ ] 数据统一格式化（JSON 输出）

### 5. 日志 & 监控

- [ ] 每个任务独立日志（文件存储 + DB 索引）
- [ ] 异常捕获 & 上报
- [ ] 请求失败率统计
- [ ] Web 控制台日志可视化（后期）

### 6. 存储模块

- [ ] 支持 MySQL/MongoDB 存储
- [ ] 支持 CSV/Excel 导出
- [ ] 任务结果通过 API 下载

### 7. 扩展功能（后期迭代）

- [ ] 分布式调度（多 Worker 节点）
- [ ] 代理池管理（自动检测可用性）
- [ ] 验证码识别模块（接第三方打码平台）
- [ ] Web 管理后台（任务管理、日志、数据可视化）

## 许可证

本项目采用 MIT 许可证 - 详见[LICENSE](LICENSE)文件。
