# API 文档

本文档描述了 SmartSpider 项目的 API 端点和功能。

## 概述

SmartSpider 提供了一组用于管理和控制网络爬虫以及访问抓取数据的 API。

## 端点

### GET /api/crawlers

列出所有可用的爬虫。

**响应：**
```json
{
  "crawlers": [
    {
      "id": "1",
      "name": "基础爬虫",
      "status": "空闲"
    },
    ...
  ]
}
```

### POST /api/crawlers

创建一个新的爬虫。

**请求体：**
```json
{
  "name": "新爬虫",
  "config": {
    "start_urls": ["https://example.com"],
    "rules": {
      "extract": {
        "title": "h1"
      }
    }
  }
}
```

**响应：**
```json
{
  "id": "2",
  "name": "新爬虫",
  "status": "空闲",
  "created_at": "2023-07-15T10:00:00Z"
}
```

### GET /api/data

获取抓取的数据。

**查询参数：**
- `crawler_id`: 爬虫 ID（可选）
- `limit`: 结果的最大数量（默认值：100）
- `offset`: 分页偏移量（默认值：0）

**响应：**
```json
{
  "data": [
    {
      "id": "1",
      "crawler_id": "1",
      "url": "https://example.com/page1",
      "content": {
        "title": "示例页面标题"
      },
      "scraped_at": "2023-07-15T10:05:00Z"
    },
    ...
  ],
  "total": 42,
  "limit": 100,
  "offset": 0
}
```