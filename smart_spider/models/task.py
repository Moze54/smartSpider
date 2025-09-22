"""
Task 类 - 任务模型定义
"""

import uuid
from enum import Enum
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 运行中
    PAUSED = "paused"        # 已暂停
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    STOPPED = "stopped"      # 已停止


class TaskPriority(str, Enum):
    """任务优先级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TaskConfig:
    """任务配置数据类"""
    name: str  # 任务名称
    entry_urls: List[str]  # 入口URL列表
    concurrency: int = 5  # 并发数
    delay: int = 1  # 请求延迟（秒）
    timeout: int = 30  # 超时时间（秒）
    retry_count: int = 3  # 重试次数
    allowed_domains: Optional[List[str]] = None  # 允许的域名
    follow_external_links: bool = False  # 是否跟随外部链接
    user_agent: Optional[str] = None  # 用户代理
    pagination: Optional[Dict[str, Any]] = None  # 分页配置
    selectors: Optional[Dict[str, Any]] = None  # 选择器配置
    cookie_pool_id: Optional[str] = None  # Cookie池ID
    storage_config: Optional[Dict[str, Any]] = None  # 存储配置
    custom_headers: Optional[Dict[str, str]] = None  # 自定义请求头

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskConfig':
        """从字典创建实例"""
        return cls(**data)


@dataclass
class TaskMetrics:
    """任务指标数据类"""
    success_count: int = 0  # 成功爬取的URL数量
    fail_count: int = 0  # 失败的URL数量
    total_count: int = 0  # 总URL数量
    progress_percent: float = 0.0  # 完成进度百分比
    start_time: Optional[datetime] = None  # 开始时间
    end_time: Optional[datetime] = None  # 结束时间
    duration: Optional[float] = None  # 持续时间（秒）
    crawled_urls: set = field(default_factory=set)  # 已爬取的URL集合
    error_urls: set = field(default_factory=set)  # 爬取失败的URL集合

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = asdict(self)
        # 转换集合为列表，转换datetime为字符串
        result['crawled_urls'] = list(self.crawled_urls)
        result['error_urls'] = list(self.error_urls)
        if self.start_time:
            result['start_time'] = self.start_time.isoformat()
        if self.end_time:
            result['end_time'] = self.end_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskMetrics':
        """从字典创建实例"""
        # 处理特殊字段
        if 'crawled_urls' in data and isinstance(data['crawled_urls'], list):
            data['crawled_urls'] = set(data['crawled_urls'])
        if 'error_urls' in data and isinstance(data['error_urls'], list):
            data['error_urls'] = set(data['error_urls'])
        if 'start_time' in data and isinstance(data['start_time'], str):
            data['start_time'] = datetime.fromisoformat(data['start_time'])
        if 'end_time' in data and isinstance(data['end_time'], str):
            data['end_time'] = datetime.fromisoformat(data['end_time'])
        return cls(**data)


@dataclass
class Task:
    """爬虫任务数据类"""
    config: TaskConfig  # 任务配置
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 任务ID
    status: TaskStatus = TaskStatus.PENDING  # 任务状态
    priority: TaskPriority = TaskPriority.MEDIUM  # 任务优先级
    metrics: TaskMetrics = field(default_factory=TaskMetrics)  # 任务指标
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 创建时间
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 更新时间
    user_id: Optional[str] = None  # 用户ID（可选）
    error_message: Optional[str] = None  # 错误信息（可选）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'id': self.id,
            'config': self.config.to_dict(),
            'status': self.status.value,
            'priority': self.priority.value,
            'metrics': self.metrics.to_dict(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'user_id': self.user_id,
            'error_message': self.error_message
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """从字典创建实例"""
        # 处理嵌套对象
        if 'config' in data and isinstance(data['config'], dict):
            data['config'] = TaskConfig.from_dict(data['config'])
        if 'metrics' in data and isinstance(data['metrics'], dict):
            data['metrics'] = TaskMetrics.from_dict(data['metrics'])
        # 处理枚举类型
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = TaskStatus(data['status'])
        if 'priority' in data and isinstance(data['priority'], str):
            data['priority'] = TaskPriority(data['priority'])
        # 处理datetime类型
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'updated_at' in data and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)

    def update_status(self, status: TaskStatus) -> None:
        """更新任务状态"""
        self.status = status
        self.updated_at = datetime.now(timezone.utc)
        
        # 如果状态变为运行中，记录开始时间
        if status == TaskStatus.RUNNING and not self.metrics.start_time:
            self.metrics.start_time = datetime.now(timezone.utc)
        
        # 如果状态变为完成，记录结束时间和持续时间
        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED]:
            if not self.metrics.end_time:
                self.metrics.end_time = datetime.now(timezone.utc)
                # 计算持续时间
                if self.metrics.start_time:
                    self.metrics.duration = (
                        self.metrics.end_time - self.metrics.start_time
                    ).total_seconds()

    def update_metrics(self, success_count: int = None, fail_count: int = None, 
                      total_count: int = None, crawled_url: str = None, 
                      error_url: str = None) -> None:
        """更新任务指标"""
        if success_count is not None:
            self.metrics.success_count = success_count
        if fail_count is not None:
            self.metrics.fail_count = fail_count
        if total_count is not None:
            self.metrics.total_count = total_count
        if crawled_url:
            self.metrics.crawled_urls.add(crawled_url)
            self.metrics.success_count += 1
        if error_url:
            self.metrics.error_urls.add(error_url)
            self.metrics.fail_count += 1
        
        # 更新进度百分比
        if self.metrics.total_count > 0:
            self.metrics.progress_percent = (
                (self.metrics.success_count + self.metrics.fail_count) 
                / self.metrics.total_count * 100
            )
        
        # 更新时间
        self.updated_at = datetime.now(timezone.utc)

    def pause(self) -> None:
        """暂停任务"""
        if self.status == TaskStatus.RUNNING:
            self.update_status(TaskStatus.PAUSED)

    def resume(self) -> None:
        """恢复任务"""
        if self.status == TaskStatus.PAUSED:
            self.update_status(TaskStatus.RUNNING)

    def stop(self) -> None:
        """停止任务"""
        if self.status in [TaskStatus.RUNNING, TaskStatus.PAUSED]:
            self.update_status(TaskStatus.STOPPED)

    def mark_as_failed(self, error_message: str) -> None:
        """标记任务为失败"""
        self.error_message = error_message
        self.update_status(TaskStatus.FAILED)

    def is_active(self) -> bool:
        """检查任务是否活跃（运行中或暂停）"""
        return self.status in [TaskStatus.RUNNING, TaskStatus.PAUSED]

    def is_terminated(self) -> bool:
        """检查任务是否已终止（完成、失败或停止）"""
        return self.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED]


# 使用示例
if __name__ == '__main__':
    # 创建任务配置
    config = TaskConfig(
        name="示例爬虫任务",
        entry_urls=["https://example.com"],
        concurrency=3,
        delay=2,
        allowed_domains=["example.com"]
    )
    
    # 创建任务
    task = Task(config=config)
    
    # 打印任务信息
    print(f"任务ID: {task.id}")
    print(f"任务状态: {task.status}")
    print(f"创建时间: {task.created_at}")
    
    # 开始任务
    task.update_status(TaskStatus.RUNNING)
    
    # 更新指标
    task.update_metrics(crawled_url="https://example.com")
    task.update_metrics(crawled_url="https://example.com/about")
    task.update_metrics(error_url="https://example.com/nonexistent")
    
    # 完成任务
    task.update_status(TaskStatus.COMPLETED)
    
    # 转换为字典
    task_dict = task.to_dict()
    print(f"\n任务字典: {task_dict}")
    
    # 从字典重建任务
    new_task = Task.from_dict(task_dict)
    print(f"\n重建的任务状态: {new_task.status}")
    print(f"重建的任务指标: {new_task.metrics.to_dict()}")