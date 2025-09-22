"""
SmartSpider 的 API 路由
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, HttpUrl, Field, UUID4
from typing import List, Dict, Any, Optional, Union
import uuid
from datetime import datetime
from smart_spider.core.service import CrawlerService
from smart_spider.settings import settings
from smart_spider.utils.logger import get_logger

# 初始化日志记录器
logger = get_logger(__name__)

# 创建API路由器
router = APIRouter()

# 初始化爬虫服务
crawler_service = CrawlerService(settings)

# 任务状态枚举
TASK_STATUS = {
    "CREATED": "created",
    "STARTED": "started",
    "PAUSED": "paused",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "STOPPED": "stopped"
}

# 数据模型定义
class SelectorSpec(BaseModel):
    """选择器规范模型"""
    type: str = Field(..., example="css", description="选择器类型，如css, xpath")
    expr: str = Field(..., example=".title", description="选择器表达式")

class PaginationSpec(BaseModel):
    """分页规范模型"""
    type: str = Field(..., example="next_link", description="分页类型")
    selector: str = Field(..., example="a.next-page", description="分页选择器")

class TaskConfig(BaseModel):
    """爬虫任务配置模型"""
    name: str = Field(..., example="example_task", description="任务名称")
    entry_urls: List[HttpUrl] = Field(..., example=["https://example.com"], description="入口URL列表")
    pagination: Optional[PaginationSpec] = Field(None, description="分页配置")
    selectors: Dict[str, Any] = Field(..., example={"items": {"type": "css", "expr": ".item"}}, description="数据选择器配置")
    concurrency: int = Field(default=5, ge=1, le=100, example=5, description="并发请求数")
    use_cookie: bool = Field(default=False, example=False, description="是否使用Cookie")
    cookie_id: Optional[int] = Field(None, example=1, description="Cookie ID")
    schedule: Optional[str] = Field(None, example="0 0 * * *", description="定时任务表达式，Cron格式")

class Task(BaseModel):
    """任务模型"""
    id: UUID4 = Field(..., example="123e4567-e89b-12d3-a456-426614174000", description="任务ID")
    config: TaskConfig = Field(..., description="任务配置")
    status: str = Field(..., example="created", description="任务状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

class TaskMetrics(BaseModel):
    """任务指标模型"""
    task_id: UUID4 = Field(..., description="任务ID")
    success_count: int = Field(default=0, description="成功请求数")
    fail_count: int = Field(default=0, description="失败请求数")
    total_count: int = Field(default=0, description="总请求数")
    progress_percent: float = Field(default=0.0, description="完成进度百分比")
    running_workers: int = Field(default=0, description="运行中的工作线程数")
    last_updated: datetime = Field(default_factory=datetime.now, description="最后更新时间")

class CookieItem(BaseModel):
    """Cookie项模型"""
    name: str = Field(..., example="session_id", description="Cookie名称")
    value: str = Field(..., example="abc123", description="Cookie值")
    domain: str = Field(..., example="example.com", description="Cookie域名")
    path: str = Field(..., example="/", description="Cookie路径")

class CookieUploadRequest(BaseModel):
    """Cookie上传请求模型"""
    domain: str = Field(..., example="example.com", description="Cookie域名")
    cookies: List[CookieItem] = Field(..., description="Cookie列表")

class CookieLeaseRequest(BaseModel):
    """Cookie租用请求模型"""
    domain: str = Field(..., example="example.com", description="Cookie域名")
    lease_time: int = Field(default=300, ge=60, le=3600, example=300, description="租用时间（秒）")

# 模拟数据库存储
_tasks_db: Dict[UUID4, Dict[str, Any]] = {}
_cookies_db: Dict[int, Dict[str, Any]] = {}
_task_metrics: Dict[UUID4, Dict[str, Any]] = {}

@router.post("/tasks", response_model=Task, tags=["任务管理"])
async def create_task(task_config: TaskConfig):
    """创建新的爬虫任务"""
    logger.info(f"Creating new task: {task_config.name}")
    
    # 生成任务ID
    task_id = uuid.uuid4()
    now = datetime.now()
    
    # 创建任务
    task = {
        "id": task_id,
        "config": task_config.dict(),
        "status": TASK_STATUS["CREATED"],
        "created_at": now,
        "updated_at": now
    }
    
    # 存储任务
    _tasks_db[task_id] = task
    
    # 初始化任务指标
    _task_metrics[task_id] = TaskMetrics(task_id=task_id).dict()
    
    logger.info(f"Task created successfully: {task_id}")
    return task

@router.get("/tasks", response_model=List[Task], tags=["任务管理"])
async def list_tasks(
    status: Optional[str] = Query(None, description="按状态过滤任务")
):
    """列出所有爬虫任务"""
    tasks = list(_tasks_db.values())
    
    # 按状态过滤
    if status:
        tasks = [task for task in tasks if task["status"] == status]
    
    return tasks

@router.get("/tasks/{task_id}", response_model=Task, tags=["任务管理"])
async def get_task(task_id: UUID4):
    """获取指定任务的详细信息"""
    if task_id not in _tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return _tasks_db[task_id]

@router.post("/tasks/{task_id}/start", response_model=Dict[str, str], tags=["任务管理"])
async def start_task(task_id: UUID4, background_tasks: BackgroundTasks):
    """启动指定的爬虫任务"""
    if task_id not in _tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = _tasks_db[task_id]
    
    # 检查任务状态
    if task["status"] == TASK_STATUS["STARTED"]:
        raise HTTPException(status_code=400, detail="Task is already started")
    
    # 更新任务状态
    task["status"] = TASK_STATUS["STARTED"]
    task["updated_at"] = datetime.now()
    
    logger.info(f"Starting task: {task_id}")
    
    # 这里应该在后台启动实际的爬虫任务
    # background_tasks.add_task(run_crawler_task, task_id)
    
    return {"status": "success", "message": "Task started successfully"}

@router.post("/tasks/{task_id}/stop", response_model=Dict[str, str], tags=["任务管理"])
async def stop_task(task_id: UUID4):
    """停止指定的爬虫任务"""
    if task_id not in _tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = _tasks_db[task_id]
    
    # 检查任务状态
    if task["status"] != TASK_STATUS["STARTED"] and task["status"] != TASK_STATUS["PAUSED"]:
        raise HTTPException(status_code=400, detail="Task is not running")
    
    # 更新任务状态
    task["status"] = TASK_STATUS["STOPPED"]
    task["updated_at"] = datetime.now()
    
    logger.info(f"Stopping task: {task_id}")
    
    # 这里应该实现停止实际爬虫任务的逻辑
    
    return {"status": "success", "message": "Task stopped successfully"}

@router.post("/tasks/{task_id}/pause", response_model=Dict[str, str], tags=["任务管理"])
async def pause_task(task_id: UUID4):
    """暂停指定的爬虫任务"""
    if task_id not in _tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = _tasks_db[task_id]
    
    # 检查任务状态
    if task["status"] != TASK_STATUS["STARTED"]:
        raise HTTPException(status_code=400, detail="Task is not running")
    
    # 更新任务状态
    task["status"] = TASK_STATUS["PAUSED"]
    task["updated_at"] = datetime.now()
    
    logger.info(f"Pausing task: {task_id}")
    
    return {"status": "success", "message": "Task paused successfully"}

@router.get("/tasks/{task_id}/metrics", response_model=TaskMetrics, tags=["任务管理"])
async def get_task_metrics(task_id: UUID4):
    """获取指定任务的指标"""
    if task_id not in _task_metrics:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return _task_metrics[task_id]

@router.post("/cookies/upload", response_model=Dict[str, str], tags=["Cookie管理"])
async def upload_cookies(cookie_request: CookieUploadRequest):
    """上传Cookie到服务器"""
    logger.info(f"Uploading cookies for domain: {cookie_request.domain}")
    
    # 生成Cookie ID
    cookie_id = max(_cookies_db.keys(), default=0) + 1
    
    # 创建Cookie记录
    cookie_record = {
        "id": cookie_id,
        "domain": cookie_request.domain,
        "cookies": [cookie.dict() for cookie in cookie_request.cookies],
        "status": "active",
        "last_used": None,
        "usage_count": 0,
        "created_at": datetime.now()
    }
    
    # 存储Cookie
    _cookies_db[cookie_id] = cookie_record
    
    logger.info(f"Cookies uploaded successfully: ID {cookie_id}")
    return {"status": "success", "message": "Cookies uploaded successfully", "cookie_id": cookie_id}

@router.get("/cookies/lease", response_model=Dict[str, Any], tags=["Cookie管理"])
async def lease_cookie(
    domain: str = Query(..., example="example.com", description="Cookie域名"),
    lease_time: int = Query(default=300, ge=60, le=3600, description="租用时间（秒）")
):
    """租用Cookie用于爬虫任务"""
    logger.info(f"Leasing cookie for domain: {domain}")
    
    # 查找可用的Cookie
    available_cookies = [
        cookie for cookie in _cookies_db.values()
        if cookie["domain"] == domain and cookie["status"] == "active"
    ]
    
    if not available_cookies:
        raise HTTPException(status_code=404, detail=f"No available cookies for domain: {domain}")
    
    # 选择一个Cookie（这里简单选择第一个）
    cookie = available_cookies[0]
    
    # 更新Cookie信息
    cookie["last_used"] = datetime.now()
    cookie["usage_count"] += 1
    
    logger.info(f"Cookie leased successfully: ID {cookie['id']}")
    
    # 返回Cookie信息和租用ID
    return {
        "cookie_id": cookie["id"],
        "lease_id": str(uuid.uuid4()),  # 生成租用ID
        "lease_time": lease_time,
        "cookies": cookie["cookies"]
    }

@router.get("/cookies", response_model=List[Dict[str, Any]], tags=["Cookie管理"])
async def list_cookies():
    """列出所有存储的Cookie"""
    return list(_cookies_db.values())

@router.get("/results", response_model=List[Dict[str, Any]], tags=["数据管理"])
async def get_results(
    task_id: Optional[UUID4] = Query(None, description="按任务ID过滤结果")
):
    """获取抓取的结果数据"""
    # 这是一个占位实现
    # 在实际实现中，应该从数据库中查询结果数据
    logger.info(f"Fetching results for task: {task_id}")
    
    # 模拟结果数据
    results = [
        {"id": 1, "task_id": task_id, "url": "https://example.com/page1", "data": {"title": "Page 1"}},
        {"id": 2, "task_id": task_id, "url": "https://example.com/page2", "data": {"title": "Page 2"}}
    ]
    
    return results

@router.post("/results/export", response_model=Dict[str, str], tags=["数据管理"])
async def export_results(
    task_id: UUID4 = Query(..., description="要导出的任务ID"),
    format: str = Query(default="json", regex="^(json|csv|excel)$", description="导出格式")
):
    """导出抓取的结果数据"""
    # 这是一个占位实现
    # 在实际实现中，应该从数据库中查询结果并生成导出文件
    logger.info(f"Exporting results for task: {task_id}, format: {format}")
    
    # 模拟导出文件URL
    export_url = f"/exports/{task_id}.{format}"
    
    return {"status": "success", "message": "Results exported successfully", "export_url": export_url}

# 模拟运行爬虫任务的函数
def run_crawler_task(task_id: UUID4):
    """在后台运行爬虫任务"""
    logger.info(f"Running crawler task in background: {task_id}")
    
    # 这里应该实现实际的爬虫逻辑
    # 由于这是一个示例，我们只是模拟进度更新
    
    import time
    import asyncio
    
    # 更新任务指标
    if task_id in _task_metrics:
        metrics = _task_metrics[task_id]
        metrics["running_workers"] = 1
        
        # 模拟进度更新
        for i in range(1, 11):
            metrics["success_count"] = i
            metrics["total_count"] = 10
            metrics["progress_percent"] = i * 10
            metrics["last_updated"] = datetime.now()
            time.sleep(1)  # 模拟工作
        
        # 完成任务
        metrics["running_workers"] = 0
        
        # 更新任务状态
        if task_id in _tasks_db:
            _tasks_db[task_id]["status"] = TASK_STATUS["COMPLETED"]
            _tasks_db[task_id]["updated_at"] = datetime.now()

# 使用示例
if __name__ == '__main__':
    import uvicorn
    uvicorn.run("smart_spider.api.routes:router", host="0.0.0.0", port=8000, reload=True)