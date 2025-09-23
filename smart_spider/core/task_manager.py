"""
任务管理器 - 负责创建、启动、暂停、停止和监控爬虫任务
"""

import os
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Union
from concurrent.futures import ThreadPoolExecutor

from smart_spider.models.task import Task, TaskStatus, TaskConfig, TaskMetrics
from smart_spider.core.crawler import SmartCrawler
from smart_spider.core.service import CrawlerService
from smart_spider.core.storage import StorageManager
from smart_spider.core.cache import get_cache
from smart_spider.utils.logger import get_logger
from smart_spider.settings import settings


class TaskManager:
    """任务管理器类"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(TaskManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance
    
    def _init(self):
        """初始化任务管理器"""
        self.tasks: Dict[str, Task] = {}
        self.crawlers: Dict[str, SmartCrawler] = {}
        self.task_lock = asyncio.Lock()
        self.logger = get_logger(__name__)
        self.storage = StorageManager.create_storage(settings.get('storage', {}))
        self.cache = get_cache('task_cache', {'type': 'memory', 'max_size': 100, 'default_ttl': 300})
        self.executor = ThreadPoolExecutor(max_workers=settings.get('max_workers', 10))
        self.task_monitors = {}
        self.loaded_tasks = False
        
        self.logger.info("任务管理器初始化成功")
    
    async def ensure_tasks_loaded(self):
        """确保任务已从存储加载（延迟加载机制）"""
        if not self.loaded_tasks:
            await self._load_tasks_from_storage()
            self.loaded_tasks = True
    
    async def _load_tasks_from_storage(self):
        """从存储加载已保存的任务"""
        try:
            tasks_data = await self.storage.get(filename='tasks.json')
            if tasks_data and isinstance(tasks_data, list):
                for task_dict in tasks_data:
                    try:
                        task = Task.from_dict(task_dict)
                        # 只加载未终止的任务
                        if not task.is_terminated():
                            task.status = TaskStatus.PENDING  # 重启后将所有任务设置为等待状态
                            self.tasks[task.id] = task
                            self.logger.info(f"加载任务: {task.id} - {task.config.name}")
                    except Exception as e:
                        self.logger.error(f"加载任务失败: {str(e)}")
        except Exception as e:
            self.logger.error(f"从存储加载任务失败: {str(e)}")
    
    async def _save_tasks_to_storage(self):
        """将任务保存到存储"""
        try:
            tasks_data = [task.to_dict() for task in self.tasks.values()]
            await self.storage.save(tasks_data, filename='tasks.json', overwrite=True)
            self.logger.debug("任务保存到存储成功")
        except Exception as e:
            self.logger.error(f"将任务保存到存储失败: {str(e)}")
    
    async def create_task(self, config: Union[Dict[str, Any], TaskConfig]) -> Task:
        """创建新任务
        Args:
            config: 任务配置，可以是字典或TaskConfig对象
        Returns:
            Task: 创建的任务对象
        """
        async with self.task_lock:
            try:
                # 转换配置格式
                if isinstance(config, dict):
                    task_config = TaskConfig.from_dict(config)
                else:
                    task_config = config
                
                # 验证配置
                service = CrawlerService(settings)
                validation_result = await service.validate_crawler_config(task_config.to_dict())
                if not validation_result['valid']:
                    raise ValueError(f"任务配置无效: {validation_result['errors']}")
                
                # 创建任务
                task = Task(config=task_config)
                self.tasks[task.id] = task
                
                # 保存任务到存储
                await self._save_tasks_to_storage()
                
                self.logger.info(f"创建任务成功: {task.id} - {task.config.name}")
                return task
            except Exception as e:
                self.logger.error(f"创建任务失败: {str(e)}")
                raise
    
    async def start_task(self, task_id: str) -> bool:
        """启动任务
        Args:
            task_id: 任务ID
        Returns:
            bool: 是否启动成功
        """
        async with self.task_lock:
            if task_id not in self.tasks:
                self.logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            if task.status == TaskStatus.RUNNING:
                self.logger.warning(f"任务已经在运行中: {task_id}")
                return True
            
            try:
                # 创建爬虫实例
                crawler = SmartCrawler(settings)
                self.crawlers[task_id] = crawler
                
                # 更新任务状态
                task.update_status(TaskStatus.RUNNING)
                
                # 保存任务状态
                await self._save_tasks_to_storage()
                
                # 启动爬虫任务
                asyncio.create_task(self._run_crawler(task_id, crawler))
                
                # 启动任务监控
                self._start_task_monitor(task_id)
                
                self.logger.info(f"启动任务成功: {task_id} - {task.config.name}")
                return True
            except Exception as e:
                self.logger.error(f"启动任务失败: {str(e)}")
                task.mark_as_failed(str(e))
                await self._save_tasks_to_storage()
                return False
    
    async def _run_crawler(self, task_id: str, crawler: SmartCrawler):
        """运行爬虫任务
        Args:
            task_id: 任务ID
            crawler: 爬虫实例
        """
        task = self.tasks.get(task_id)
        if not task:
            return
        
        try:
            # 准备爬取参数
            crawl_params = {
                'urls': task.config.entry_urls,
                'concurrency': task.config.concurrency,
                'delay': task.config.delay,
                'timeout': task.config.timeout,
                'retry_count': task.config.retry_count,
                'allowed_domains': task.config.allowed_domains,
                'follow_external_links': task.config.follow_external_links,
                'user_agent': task.config.user_agent,
                'pagination': task.config.pagination,
                'selectors': task.config.selectors,
                'cookie_pool_id': task.config.cookie_pool_id,
                'custom_headers': task.config.custom_headers,
                'task_id': task_id
            }
            
            # 运行爬虫
            results = await crawler.start_crawling(
                crawl_params, 
                self._on_crawl_progress,  # 进度回调
                self._on_crawl_complete    # 完成回调
            )
            
            # 处理结果
            service = CrawlerService(settings)
            processed_data = await service.process_crawled_data(results)
            
            # 保存结果
            save_config = task.config.storage_config or {'format': 'jsonl'}
            await service.save_crawled_data(
                processed_data,
                task_id=task_id,
                **save_config
            )
            
            # 更新任务状态为完成
            task.update_status(TaskStatus.COMPLETED)
            
        except Exception as e:
            self.logger.error(f"任务执行失败: {task_id} - {str(e)}")
            task.mark_as_failed(str(e))
        finally:
            # 清理资源
            if task_id in self.crawlers:
                del self.crawlers[task_id]
            
            # 停止任务监控
            self._stop_task_monitor(task_id)
            
            # 保存任务状态
            await self._save_tasks_to_storage()
    
    def _on_crawl_progress(self, task_id: str, progress: Dict[str, Any]):
        """爬取进度回调
        Args:
            task_id: 任务ID
            progress: 进度信息
        """
        async def update_progress():
            async with self.task_lock:
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    
                    # 更新指标
                    if 'success_count' in progress:
                        task.update_metrics(success_count=progress['success_count'])
                    if 'fail_count' in progress:
                        task.update_metrics(fail_count=progress['fail_count'])
                    if 'total_count' in progress:
                        task.update_metrics(total_count=progress['total_count'])
                    if 'crawled_url' in progress:
                        task.update_metrics(crawled_url=progress['crawled_url'])
                    if 'error_url' in progress:
                        task.update_metrics(error_url=progress['error_url'])
                    
                    # 保存进度
                    await self._save_tasks_to_storage()
        
        # 使用asyncio.create_task来避免阻塞爬虫
        asyncio.create_task(update_progress())
    
    def _on_crawl_complete(self, task_id: str, success: bool, results: Any = None):
        """爬取完成回调
        Args:
            task_id: 任务ID
            success: 是否成功
            results: 爬取结果
        """
        self.logger.info(f"任务爬取完成: {task_id}, 成功: {success}")
    
    async def pause_task(self, task_id: str) -> bool:
        """暂停任务
        Args:
            task_id: 任务ID
        Returns:
            bool: 是否暂停成功
        """
        async with self.task_lock:
            if task_id not in self.tasks:
                self.logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            if task.status != TaskStatus.RUNNING:
                self.logger.warning(f"任务不在运行状态，无法暂停: {task_id} - {task.status}")
                return False
            
            try:
                # 暂停爬虫
                if task_id in self.crawlers:
                    crawler = self.crawlers[task_id]
                    await crawler.pause()
                
                # 更新任务状态
                task.pause()
                
                # 保存任务状态
                await self._save_tasks_to_storage()
                
                self.logger.info(f"暂停任务成功: {task_id} - {task.config.name}")
                return True
            except Exception as e:
                self.logger.error(f"暂停任务失败: {str(e)}")
                return False
    
    async def resume_task(self, task_id: str) -> bool:
        """恢复任务
        Args:
            task_id: 任务ID
        Returns:
            bool: 是否恢复成功
        """
        async with self.task_lock:
            if task_id not in self.tasks:
                self.logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            if task.status != TaskStatus.PAUSED:
                self.logger.warning(f"任务不在暂停状态，无法恢复: {task_id} - {task.status}")
                return False
            
            try:
                # 恢复爬虫
                if task_id in self.crawlers:
                    crawler = self.crawlers[task_id]
                    await crawler.resume()
                else:
                    # 如果爬虫不存在，重新创建并启动
                    await self.start_task(task_id)
                
                # 更新任务状态
                task.resume()
                
                # 保存任务状态
                await self._save_tasks_to_storage()
                
                self.logger.info(f"恢复任务成功: {task_id} - {task.config.name}")
                return True
            except Exception as e:
                self.logger.error(f"恢复任务失败: {str(e)}")
                return False
    
    async def stop_task(self, task_id: str) -> bool:
        """停止任务
        Args:
            task_id: 任务ID
        Returns:
            bool: 是否停止成功
        """
        async with self.task_lock:
            if task_id not in self.tasks:
                self.logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            if task.is_terminated():
                self.logger.warning(f"任务已经终止，无需停止: {task_id} - {task.status}")
                return True
            
            try:
                # 停止爬虫
                if task_id in self.crawlers:
                    crawler = self.crawlers[task_id]
                    await crawler.stop()
                    del self.crawlers[task_id]
                
                # 更新任务状态
                task.stop()
                
                # 停止任务监控
                self._stop_task_monitor(task_id)
                
                # 保存任务状态
                await self._save_tasks_to_storage()
                
                self.logger.info(f"停止任务成功: {task_id} - {task.config.name}")
                return True
            except Exception as e:
                self.logger.error(f"停止任务失败: {str(e)}")
                return False
    
    async def delete_task(self, task_id: str) -> bool:
        """删除任务
        Args:
            task_id: 任务ID
        Returns:
            bool: 是否删除成功
        """
        async with self.task_lock:
            if task_id not in self.tasks:
                self.logger.error(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            if task.status == TaskStatus.RUNNING:
                self.logger.error(f"任务正在运行中，无法删除: {task_id}")
                return False
            
            try:
                # 停止任务（如果还在运行）
                if task.is_active():
                    await self.stop_task(task_id)
                
                # 从内存中删除任务
                del self.tasks[task_id]
                
                # 停止任务监控（如果存在）
                self._stop_task_monitor(task_id)
                
                # 保存任务状态
                await self._save_tasks_to_storage()
                
                # 删除任务数据（移到最后，确保即使文件删除失败也能成功删除内存中的任务）
                await self.storage.delete(filename=f'{task_id}_results.jsonl')
                
                self.logger.info(f"删除任务成功: {task_id} - {task.config.name}")
                return True
            except Exception as e:
                self.logger.error(f"删除任务失败: {str(e)}")
                return False
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息
        Args:
            task_id: 任务ID
        Returns:
            Task: 任务对象或None
        """
        async with self.task_lock:
            return self.tasks.get(task_id)
    
    async def list_tasks(self, status: Optional[str] = None) -> List[Task]:
        """列出所有任务
        Args:
            status: 任务状态过滤
        Returns:
            List[Task]: 任务列表
        """
        async with self.task_lock:
            if status:
                return [task for task in self.tasks.values() if task.status == status]
            else:
                return list(self.tasks.values())
    
    async def get_task_metrics(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务指标
        Args:
            task_id: 任务ID
        Returns:
            Dict[str, Any]: 任务指标或None
        """
        task = await self.get_task(task_id)
        if not task:
            return None
        
        return task.metrics.to_dict()
    
    async def get_task_results(self, task_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """获取任务结果
        Args:
            task_id: 任务ID
            limit: 结果数量限制
            offset: 结果偏移量
        Returns:
            List[Dict[str, Any]]: 任务结果列表
        """
        try:
            # 尝试从缓存获取结果
            cache_key = f"task_results_{task_id}_{limit}_{offset}"
            cached_results = await self.cache.get(cache_key)
            if cached_results:
                return cached_results
            
            # 从存储获取结果
            results = await self.storage.get(filename=f'{task_id}_results.jsonl')
            if results and isinstance(results, list):
                # 应用分页
                paginated_results = results[offset:offset+limit]
                
                # 缓存结果
                await self.cache.set(cache_key, paginated_results, ttl=60)
                
                return paginated_results
            
            return []
        except Exception as e:
            self.logger.error(f"获取任务结果失败: {str(e)}")
            return []
    
    async def export_task_results(self, task_id: str, format: str = 'json', filepath: Optional[str] = None) -> str:
        """导出任务结果
        Args:
            task_id: 任务ID
            format: 导出格式（json, csv, pickle）
            filepath: 导出文件路径
        Returns:
            str: 导出文件路径
        """
        try:
            task = await self.get_task(task_id)
            if not task:
                raise ValueError(f"任务不存在: {task_id}")
            
            # 获取所有结果
            results = await self.storage.get(filename=f'{task_id}_results.jsonl')
            if not results or not isinstance(results, list):
                raise ValueError(f"任务没有结果: {task_id}")
            
            # 生成文件路径
            if not filepath:
                export_dir = settings.get('export.path', 'exports')
                os.makedirs(export_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filepath = os.path.join(export_dir, f'{task_id}_export_{timestamp}.{format}')
            
            # 创建临时存储配置
            export_config = {
                'type': 'file',
                'path': os.path.dirname(filepath),
                'format': format
            }
            
            # 导出结果
            export_storage = StorageManager.create_storage(export_config)
            await export_storage.save(results, filename=os.path.basename(filepath), overwrite=True)
            
            self.logger.info(f"导出任务结果成功: {task_id} -> {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"导出任务结果失败: {str(e)}")
            raise
    
    def _start_task_monitor(self, task_id: str):
        """启动任务监控
        Args:
            task_id: 任务ID
        """
        # 如果已经有监控在运行，先停止
        self._stop_task_monitor(task_id)
        
        # 创建监控任务
        async def monitor_task():
            while task_id in self.tasks:
                task = self.tasks[task_id]
                if task.is_terminated():
                    break
                
                # 记录任务状态
                self.logger.debug(f"任务监控: {task_id} - 状态: {task.status}, 进度: {task.metrics.progress_percent:.2f}%")
                
                # 检查是否需要自动保存
                await self._save_tasks_to_storage()
                
                # 等待一段时间
                await asyncio.sleep(30)  # 每30秒检查一次
        
        # 启动监控任务
        self.task_monitors[task_id] = asyncio.create_task(monitor_task())
    
    def _stop_task_monitor(self, task_id: str):
        """停止任务监控
        Args:
            task_id: 任务ID
        """
        if task_id in self.task_monitors:
            monitor = self.task_monitors[task_id]
            if not monitor.done():
                monitor.cancel()
            del self.task_monitors[task_id]
    
    async def shutdown(self):
        """关闭任务管理器"""
        # 停止所有正在运行的任务
        for task_id in list(self.tasks.keys()):
            await self.stop_task(task_id)
        
        # 停止所有任务监控
        for task_id in list(self.task_monitors.keys()):
            self._stop_task_monitor(task_id)
        
        # 保存任务状态
        await self._save_tasks_to_storage()
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        self.logger.info("任务管理器已关闭")


# 使用示例
if __name__ == '__main__':
    # 只在直接运行该模块时创建实例
    task_manager = TaskManager()
    # 示例任务配置
    task_config = {
        'name': '示例爬虫任务',
        'entry_urls': ['https://example.com'],
        'concurrency': 3,
        'delay': 2,
        'timeout': 30,
        'retry_count': 3,
        'allowed_domains': ['example.com'],
        'follow_external_links': False
    }
    
    # 测试任务管理器的异步函数
    async def test_task_manager():
        print("===== 测试任务管理器 =====")
        
        # 创建任务
        print("创建任务...")
        task = await task_manager.create_task(task_config)
        print(f"任务创建成功: {task.id} - {task.config.name}")
        
        # 列出所有任务
        tasks = await task_manager.list_tasks()
        print(f"当前任务数量: {len(tasks)}")
        
        # 启动任务
        print(f"启动任务: {task.id}...")
        start_success = await task_manager.start_task(task.id)
        print(f"任务启动: {'成功' if start_success else '失败'}")
        
        # 等待一段时间
        print("等待5秒...")
        await asyncio.sleep(5)
        
        # 获取任务指标
        metrics = await task_manager.get_task_metrics(task.id)
        print(f"任务指标: {metrics}")
        
        # 暂停任务
        print(f"暂停任务: {task.id}...")
        pause_success = await task_manager.pause_task(task.id)
        print(f"任务暂停: {'成功' if pause_success else '失败'}")
        
        # 等待一段时间
        print("等待2秒...")
        await asyncio.sleep(2)
        
        # 恢复任务
        print(f"恢复任务: {task.id}...")
        resume_success = await task_manager.resume_task(task.id)
        print(f"任务恢复: {'成功' if resume_success else '失败'}")
        
        # 等待一段时间
        print("等待2秒...")
        await asyncio.sleep(2)
        
        # 停止任务
        print(f"停止任务: {task.id}...")
        stop_success = await task_manager.stop_task(task.id)
        print(f"任务停止: {'成功' if stop_success else '失败'}")
        
        # 获取任务信息
        updated_task = await task_manager.get_task(task.id)
        print(f"任务最终状态: {updated_task.status}")
        
        # 删除任务
        print(f"删除任务: {task.id}...")
        delete_success = await task_manager.delete_task(task.id)
        print(f"任务删除: {'成功' if delete_success else '失败'}")
        
        # 再次列出所有任务
        tasks = await task_manager.list_tasks()
        print(f"删除后任务数量: {len(tasks)}")
        
        # 关闭任务管理器
        print("关闭任务管理器...")
        await task_manager.shutdown()
        print("测试完成")
    
    # 运行异步测试
    import asyncio
    asyncio.run(test_task_manager())