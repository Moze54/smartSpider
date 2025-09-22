"""
SmartSpider 基本功能测试
"""

import asyncio
import pytest
import os
from pathlib import Path

from smart_spider.core.task_manager import TaskManager
from smart_spider.core.cookie_manager import CookieManager
from smart_spider.core.proxy_manager import ProxyManager
from smart_spider.settings import settings
from smart_spider.utils.logger import get_logger

logger = get_logger(__name__)


class TestSmartSpiderBasic:
    """测试SmartSpider的基本功能"""

    def setup_method(self):
        """测试前的设置"""
        logger.info("Starting tests for SmartSpider")
        # 创建管理器实例
        self.task_manager = TaskManager()
        self.cookie_manager = CookieManager()
        self.proxy_manager = ProxyManager()
        # 确保测试不会影响实际数据
        self.test_task_id = "test_task_001"
        self.test_cookie_id = "test_cookie_001"
        self.test_proxy_id = "test_proxy_001"
        self.test_pool_id = "test_pool_001"

    def teardown_method(self):
        """测试后的清理"""
        logger.info("Cleaning up after tests")
        # 清理测试数据
        asyncio.run(self._cleanup_test_data())

    async def _cleanup_test_data(self):
        """异步清理测试数据"""
        try:
            # 删除测试任务
            if hasattr(self.task_manager, 'tasks') and self.test_task_id in self.task_manager.tasks:
                await self.task_manager.delete_task(self.test_task_id)
            
            # 删除测试Cookie
            if hasattr(self.cookie_manager, 'cookie_pools'):
                for pool in self.cookie_manager.cookie_pools.values():
                    cookies_to_remove = [c.id for c in pool.cookies if c.id == self.test_cookie_id]
                    for cookie_id in cookies_to_remove:
                        await self.cookie_manager.remove_cookie(pool.id, cookie_id)
            
            # 删除测试代理池和代理
            if hasattr(self.proxy_manager, 'proxy_pools'):
                if self.test_pool_id in self.proxy_manager.proxy_pools:
                    await self.proxy_manager.delete_proxy_pool(self.test_pool_id)
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    def test_settings_load(self):
        """测试配置加载功能"""
        # 验证配置文件是否正确加载
        app_version = settings.get("app.version")
        assert app_version is not None, "配置未正确加载"
        assert isinstance(app_version, str), "配置项类型错误"
        
        # 验证嵌套配置获取
        crawler_concurrency = settings.get("crawler.concurrent_requests")
        assert crawler_concurrency is not None, "嵌套配置项未正确获取"
        assert isinstance(crawler_concurrency, int), "嵌套配置项类型错误"

    def test_logger(self):
        """测试日志功能"""
        # 测试日志记录
        test_logger = get_logger("test_logger")
        test_logger.info("Test log message")
        test_logger.error("Test error message")
        
        # 验证日志文件是否存在（如果配置了文件日志）
        log_path = settings.get("logging.file.path")
        if log_path and settings.get("logging.file.enabled", True):
            log_file = Path(log_path)
            if log_file.is_absolute():
                assert log_file.exists(), "日志文件不存在"
            else:
                # 如果是相对路径，相对于项目根目录
                project_root = Path(__file__).parent.parent
                log_file_path = project_root / log_path
                assert log_file_path.exists(), "日志文件不存在"

    @pytest.mark.asyncio
    async def test_task_manager(self):
        """测试任务管理器功能"""
        # 创建测试任务
        task_config = {
            "name": "Test Task",
            "description": "A test task",
            "config": {
                "entry_urls": ["https://example.com"],
                "concurrency": 2,
                "timeout": 10
            }
        }
        
        try:
            # 创建任务
            task = await self.task_manager.create_task(task_config)
            assert task is not None, "任务创建失败"
            assert task.id == self.test_task_id, "任务ID不匹配"
            
            # 获取任务
            retrieved_task = await self.task_manager.get_task(self.test_task_id)
            assert retrieved_task is not None, "任务获取失败"
            assert retrieved_task.name == "Test Task", "任务名称不匹配"
            
        except Exception as e:
            pytest.fail(f"任务管理器测试失败: {e}")

    @pytest.mark.asyncio
    async def test_cookie_manager(self):
        """测试Cookie管理器功能"""
        # 创建测试Cookie池
        cookie_pool_config = {
            "name": "Test Cookie Pool",
            "description": "A test cookie pool",
            "type": "session"
        }
        
        try:
            # 创建Cookie池
            pool = await self.cookie_manager.create_cookie_pool(cookie_pool_config)
            assert pool is not None, "Cookie池创建失败"
            
            # 添加测试Cookie
            cookie_data = {
                "domain": "example.com",
                "name": "test_cookie",
                "value": "test_value",
                "path": "/",
                "expires": None,
                "httpOnly": False,
                "secure": False,
                "session": True
            }
            
            cookie = await self.cookie_manager.add_cookie(pool.id, cookie_data)
            assert cookie is not None, "Cookie添加失败"
            
            # 获取Cookie
            retrieved_cookie = next((c for c in pool.cookies if c.id == cookie.id), None)
            assert retrieved_cookie is not None, "Cookie获取失败"
            assert retrieved_cookie.name == "test_cookie", "Cookie名称不匹配"
            
        except Exception as e:
            pytest.fail(f"Cookie管理器测试失败: {e}")

    @pytest.mark.asyncio
    async def test_proxy_manager(self):
        """测试代理管理器功能"""
        # 创建测试代理池
        proxy_pool_config = {
            "name": "Test Proxy Pool",
            "description": "A test proxy pool",
            "type": "public"
        }
        
        try:
            # 创建代理池
            pool = await self.proxy_manager.create_proxy_pool(proxy_pool_config)
            assert pool is not None, "代理池创建失败"
            
            # 添加测试代理
            proxy_data = {
                "ip": "127.0.0.1",
                "port": 8080,
                "protocol": "http",
                "status": "pending"
            }
            
            proxy = await self.proxy_manager.add_proxy(pool.id, proxy_data)
            assert proxy is not None, "代理添加失败"
            
            # 获取代理
            retrieved_proxy = next((p for p in pool.proxies if p.id == proxy.id), None)
            assert retrieved_proxy is not None, "代理获取失败"
            assert retrieved_proxy.ip == "127.0.0.1", "代理IP不匹配"
            
        except Exception as e:
            pytest.fail(f"代理管理器测试失败: {e}")

    def test_directories_exist(self):
        """测试必要的目录是否存在"""
        # 检查必要的目录
        project_root = Path(__file__).parent.parent
        directories = [
            "logs",
            "data",
            "data/crawled",
            "data/tasks",
            "cache/crawler"
        ]
        
        for dir_path in directories:
            full_path = project_root / dir_path
            assert full_path.exists(), f"目录不存在: {full_path}"
            assert full_path.is_dir(), f"路径不是目录: {full_path}"


if __name__ == "__main__":
    # 如果直接运行此文件，执行测试
    pytest.main([__file__])