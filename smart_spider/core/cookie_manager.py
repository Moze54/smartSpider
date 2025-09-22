"""
Cookie管理器 - 负责Cookie池管理、Cookie租用、健康检查和更新
"""

import os
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union
from urllib.parse import urlparse

from smart_spider.models.cookie import (
    CookieItem, CookieStatus, CookieSource, CookiePool, CookiePoolType,
    CookieLease, LeaseStatus
)
from smart_spider.core.crawler import SmartCrawler
from smart_spider.core.storage import StorageManager
from smart_spider.core.cache import get_cache
from smart_spider.utils.logger import get_logger
from smart_spider.settings import settings


class CookieManager:
    """Cookie管理器类"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(CookieManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance
    
    def _init(self):
        """初始化Cookie管理器"""
        self.cookie_pools: Dict[str, CookiePool] = {}
        self.cookie_leases: Dict[str, CookieLease] = {}
        self.pool_lock = asyncio.Lock()
        self.logger = get_logger(__name__)
        self.storage = StorageManager.create_storage(settings.get('storage', {}))
        self.cache = get_cache('cookie_cache', {'type': 'memory', 'max_size': 1000, 'default_ttl': 600})
        self.health_check_intervals = {
            CookieStatus.VALID: 300,  # 5分钟
            CookieStatus.WARNING: 60,  # 1分钟
            CookieStatus.INVALID: 3600  # 1小时
        }
        self._initialized = False
        
        # 延迟初始化，避免在没有事件循环时创建任务
        if settings.get('delay_init', False):
            self.logger.info("Cookie管理器初始化成功(延迟加载模式)")
        else:
            # 从存储加载Cookie池
            asyncio.create_task(self._load_cookie_pools_from_storage())
            
            # 启动健康检查任务
            asyncio.create_task(self._health_check_loop())
        
        self.logger.info("Cookie管理器初始化成功")
    
    async def _load_cookie_pools_from_storage(self):
        """从存储加载Cookie池"""
        try:
            pools_data = await self.storage.get(filename='cookie_pools.json')
            if pools_data and isinstance(pools_data, list):
                for pool_dict in pools_data:
                    try:
                        cookie_pool = CookiePool.from_dict(pool_dict)
                        self.cookie_pools[cookie_pool.id] = cookie_pool
                        self.logger.info(f"加载Cookie池: {cookie_pool.id} - {cookie_pool.name}")
                    except Exception as e:
                        self.logger.error(f"加载Cookie池失败: {str(e)}")
        except Exception as e:
            self.logger.error(f"从存储加载Cookie池失败: {str(e)}")
    
    async def _save_cookie_pools_to_storage(self):
        """将Cookie池保存到存储"""
        try:
            pools_data = [pool.to_dict() for pool in self.cookie_pools.values()]
            await self.storage.save(pools_data, filename='cookie_pools.json', overwrite=True)
            self.logger.debug("Cookie池保存到存储成功")
        except Exception as e:
            self.logger.error(f"将Cookie池保存到存储失败: {str(e)}")
    
    async def create_cookie_pool(self, config: Union[Dict[str, Any], CookiePool]) -> CookiePool:
        """创建Cookie池
        Args:
            config: Cookie池配置，可以是字典或CookiePool对象
        Returns:
            CookiePool: 创建的Cookie池对象
        """
        async with self.pool_lock:
            try:
                # 转换配置格式
                if isinstance(config, dict):
                    # 如果没有提供id，生成一个
                    if 'id' not in config:
                        config['id'] = f"pool_{int(time.time())}_{random.randint(1000, 9999)}"
                    cookie_pool = CookiePool.from_dict(config)
                else:
                    cookie_pool = config
                
                # 验证Cookie池配置
                self._validate_cookie_pool(cookie_pool)
                
                # 添加到Cookie池集合
                self.cookie_pools[cookie_pool.id] = cookie_pool
                
                # 保存Cookie池到存储
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"创建Cookie池成功: {cookie_pool.id} - {cookie_pool.name}")
                return cookie_pool
            except Exception as e:
                self.logger.error(f"创建Cookie池失败: {str(e)}")
                raise
    
    def _validate_cookie_pool(self, cookie_pool: CookiePool):
        """验证Cookie池配置
        Args:
            cookie_pool: Cookie池对象
        Raises:
            ValueError: 配置无效时抛出
        """
        # 验证名称
        if not cookie_pool.name or len(cookie_pool.name) > 100:
            raise ValueError("Cookie池名称不能为空且长度不能超过100个字符")
        
        # 验证类型
        if not isinstance(cookie_pool.type, CookiePoolType):
            raise ValueError(f"无效的Cookie池类型: {cookie_pool.type}")
        
        # 验证描述
        if cookie_pool.description and len(cookie_pool.description) > 500:
            raise ValueError("Cookie池描述长度不能超过500个字符")
        
        # 验证域名
        if cookie_pool.target_domains and not isinstance(cookie_pool.target_domains, list):
            raise ValueError("目标域名必须是列表格式")
    
    async def get_cookie_pool(self, pool_id: str) -> Optional[CookiePool]:
        """获取Cookie池
        Args:
            pool_id: Cookie池ID
        Returns:
            CookiePool: Cookie池对象或None
        """
        async with self.pool_lock:
            return self.cookie_pools.get(pool_id)
    
    async def list_cookie_pools(self, pool_type: Optional[CookiePoolType] = None) -> List[CookiePool]:
        """列出所有Cookie池
        Args:
            pool_type: Cookie池类型过滤
        Returns:
            List[CookiePool]: Cookie池列表
        """
        async with self.pool_lock:
            if pool_type:
                return [pool for pool in self.cookie_pools.values() if pool.type == pool_type]
            else:
                return list(self.cookie_pools.values())
    
    async def update_cookie_pool(self, pool_id: str, config: Dict[str, Any]) -> Optional[CookiePool]:
        """更新Cookie池配置
        Args:
            pool_id: Cookie池ID
            config: 要更新的配置
        Returns:
            CookiePool: 更新后的Cookie池对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return None
            
            try:
                cookie_pool = self.cookie_pools[pool_id]
                
                # 更新配置
                for key, value in config.items():
                    if hasattr(cookie_pool, key) and key != 'id' and key != 'cookies':
                        setattr(cookie_pool, key, value)
                
                # 验证更新后的配置
                self._validate_cookie_pool(cookie_pool)
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"更新Cookie池成功: {pool_id} - {cookie_pool.name}")
                return cookie_pool
            except Exception as e:
                self.logger.error(f"更新Cookie池失败: {str(e)}")
                return None
    
    async def delete_cookie_pool(self, pool_id: str) -> bool:
        """删除Cookie池
        Args:
            pool_id: Cookie池ID
        Returns:
            bool: 是否删除成功
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return False
            
            try:
                # 检查是否有正在使用的Cookie
                for lease in self.cookie_leases.values():
                    if lease.cookie_pool_id == pool_id and lease.status == LeaseStatus.ACTIVE:
                        self.logger.error(f"Cookie池还有活跃的Cookie租用，无法删除: {pool_id}")
                        return False
                
                # 从内存中删除Cookie池
                del self.cookie_pools[pool_id]
                
                # 保存更新后的Cookie池集合
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"删除Cookie池成功: {pool_id}")
                return True
            except Exception as e:
                self.logger.error(f"删除Cookie池失败: {str(e)}")
                return False
    
    async def add_cookie(self, pool_id: str, cookie_data: Union[Dict[str, Any], CookieItem]) -> Optional[CookieItem]:
        """添加Cookie到Cookie池
        Args:
            pool_id: Cookie池ID
            cookie_data: Cookie数据，可以是字典或CookieItem对象
        Returns:
            CookieItem: 添加的Cookie对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return None
            
            try:
                cookie_pool = self.cookie_pools[pool_id]
                
                # 转换Cookie数据格式
                if isinstance(cookie_data, dict):
                    # 如果没有提供id，生成一个
                    if 'id' not in cookie_data:
                        cookie_data['id'] = f"cookie_{int(time.time())}_{random.randint(1000, 9999)}"
                    # 如果没有提供状态，默认为待验证
                    if 'status' not in cookie_data:
                        cookie_data['status'] = CookieStatus.PENDING
                    cookie_item = CookieItem.from_dict(cookie_data)
                else:
                    cookie_item = cookie_data
                
                # 验证Cookie数据
                self._validate_cookie(cookie_item, cookie_pool)
                
                # 检查是否已存在相同的Cookie
                for existing_cookie in cookie_pool.cookies:
                    if existing_cookie.value == cookie_item.value and existing_cookie.domain == cookie_item.domain:
                        self.logger.warning(f"Cookie已存在于池: {cookie_pool.id}")
                        return existing_cookie
                
                # 添加Cookie到池
                cookie_pool.cookies.append(cookie_item)
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"添加Cookie到池成功: {cookie_item.id} -> {pool_id}")
                
                # 立即进行健康检查
                asyncio.create_task(self._check_cookie_health(cookie_item, cookie_pool))
                
                return cookie_item
            except Exception as e:
                self.logger.error(f"添加Cookie到池失败: {str(e)}")
                return None
    
    def _validate_cookie(self, cookie_item: CookieItem, cookie_pool: CookiePool):
        """验证Cookie数据
        Args:
            cookie_item: Cookie对象
            cookie_pool: Cookie池对象
        Raises:
            ValueError: 数据无效时抛出
        """
        # 验证必要字段
        if not cookie_item.value:
            raise ValueError("Cookie值不能为空")
        
        # 验证域名匹配
        if cookie_pool.target_domains and cookie_item.domain:
            # 检查Cookie域名是否与目标域名匹配
            cookie_domain = cookie_item.domain.lstrip('.')
            domain_matched = False
            for target_domain in cookie_pool.target_domains:
                target_domain = target_domain.lstrip('.')
                # 检查是否是子域名或完全匹配
                if cookie_domain == target_domain or cookie_domain.endswith(f'.{target_domain}'):
                    domain_matched = True
                    break
            
            if not domain_matched:
                raise ValueError(f"Cookie域名 {cookie_item.domain} 与Cookie池的目标域名不匹配")
        
        # 验证来源
        if not isinstance(cookie_item.source, CookieSource):
            raise ValueError(f"无效的Cookie来源: {cookie_item.source}")
        
        # 验证状态
        if not isinstance(cookie_item.status, CookieStatus):
            raise ValueError(f"无效的Cookie状态: {cookie_item.status}")
    
    async def remove_cookie(self, pool_id: str, cookie_id: str) -> bool:
        """从Cookie池移除Cookie
        Args:
            pool_id: Cookie池ID
            cookie_id: CookieID
        Returns:
            bool: 是否移除成功
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return False
            
            cookie_pool = self.cookie_pools[pool_id]
            
            # 检查是否有正在使用的Cookie租用
            for lease in self.cookie_leases.values():
                if lease.cookie_id == cookie_id and lease.status == LeaseStatus.ACTIVE:
                    self.logger.error(f"Cookie还有活跃的租用，无法移除: {cookie_id}")
                    return False
            
            try:
                # 移除Cookie
                original_count = len(cookie_pool.cookies)
                cookie_pool.cookies = [c for c in cookie_pool.cookies if c.id != cookie_id]
                
                if len(cookie_pool.cookies) == original_count:
                    self.logger.warning(f"Cookie不存在于池: {cookie_id} -> {pool_id}")
                    return False
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"从池移除Cookie成功: {cookie_id} -> {pool_id}")
                return True
            except Exception as e:
                self.logger.error(f"从池移除Cookie失败: {str(e)}")
                return False
    
    async def update_cookie(self, pool_id: str, cookie_id: str, updates: Dict[str, Any]) -> Optional[CookieItem]:
        """更新Cookie信息
        Args:
            pool_id: Cookie池ID
            cookie_id: CookieID
            updates: 要更新的字段
        Returns:
            CookieItem: 更新后的Cookie对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return None
            
            cookie_pool = self.cookie_pools[pool_id]
            
            # 查找Cookie
            cookie_item = next((c for c in cookie_pool.cookies if c.id == cookie_id), None)
            if not cookie_item:
                self.logger.error(f"Cookie不存在: {cookie_id} -> {pool_id}")
                return None
            
            try:
                # 保存旧状态，用于比较
                old_status = cookie_item.status
                
                # 更新Cookie信息
                for key, value in updates.items():
                    if hasattr(cookie_item, key) and key != 'id' and key != 'created_at':
                        # 特殊处理状态字段
                        if key == 'status' and isinstance(value, str):
                            value = CookieStatus(value)
                        setattr(cookie_item, key, value)
                
                # 更新最后更新时间
                cookie_item.updated_at = datetime.now(timezone.utc)
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
                
                self.logger.info(f"更新Cookie信息成功: {cookie_id} -> {pool_id}")
                
                # 如果状态发生变化，进行健康检查
                if cookie_item.status != old_status:
                    asyncio.create_task(self._check_cookie_health(cookie_item, cookie_pool))
                
                return cookie_item
            except Exception as e:
                self.logger.error(f"更新Cookie信息失败: {str(e)}")
                return None
    
    async def lease_cookie(self, pool_id: str, task_id: str, ttl: int = 300) -> Optional[CookieLease]:
        """租用Cookie
        Args:
            pool_id: Cookie池ID
            task_id: 任务ID
            ttl: 租用时长（秒）
        Returns:
            CookieLease: Cookie租用对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return None
            
            cookie_pool = self.cookie_pools[pool_id]
            
            try:
                # 查找可用的Cookie（优先级：VALID > WARNING > PENDING）
                available_cookies = []
                
                # 1. 首先查找VALID状态的Cookie
                valid_cookies = [c for c in cookie_pool.cookies if 
                                c.status == CookieStatus.VALID and not self._is_cookie_leased(c.id)]
                available_cookies.extend(valid_cookies)
                
                # 2. 如果没有VALID状态的Cookie，查找WARNING状态的Cookie
                if not available_cookies:
                    warning_cookies = [c for c in cookie_pool.cookies if 
                                     c.status == CookieStatus.WARNING and not self._is_cookie_leased(c.id)]
                    available_cookies.extend(warning_cookies)
                
                # 3. 如果没有WARNING状态的Cookie，查找PENDING状态的Cookie
                if not available_cookies:
                    pending_cookies = [c for c in cookie_pool.cookies if 
                                     c.status == CookieStatus.PENDING and not self._is_cookie_leased(c.id)]
                    available_cookies.extend(pending_cookies)
                
                # 如果没有可用的Cookie，返回None
                if not available_cookies:
                    self.logger.warning(f"Cookie池 {pool_id} 中没有可用的Cookie")
                    return None
                
                # 选择一个Cookie（随机选择）
                selected_cookie = random.choice(available_cookies)
                
                # 创建Cookie租用
                lease = CookieLease(
                    cookie_id=selected_cookie.id,
                    cookie_pool_id=pool_id,
                    task_id=task_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl)
                )
                
                # 添加到租用集合
                self.cookie_leases[lease.id] = lease
                
                self.logger.info(f"租用Cookie成功: {selected_cookie.id} -> {pool_id} (任务: {task_id})")
                
                # 启动租用到期检查
                asyncio.create_task(self._check_lease_expiration(lease.id))
                
                return lease
            except Exception as e:
                self.logger.error(f"租用Cookie失败: {str(e)}")
                return None
    
    def _is_cookie_leased(self, cookie_id: str) -> bool:
        """检查Cookie是否已被租用
        Args:
            cookie_id: CookieID
        Returns:
            bool: 是否已被租用
        """
        for lease in self.cookie_leases.values():
            if lease.cookie_id == cookie_id and lease.status == LeaseStatus.ACTIVE:
                return True
        return False
    
    async def release_cookie(self, lease_id: str) -> bool:
        """释放Cookie租用
        Args:
            lease_id: 租用ID
        Returns:
            bool: 是否释放成功
        """
        async with self.pool_lock:
            if lease_id not in self.cookie_leases:
                self.logger.error(f"Cookie租用不存在: {lease_id}")
                return False
            
            lease = self.cookie_leases[lease_id]
            
            try:
                # 更新租用状态
                lease.release()
                
                self.logger.info(f"释放Cookie租用成功: {lease_id}")
                return True
            except Exception as e:
                self.logger.error(f"释放Cookie租用失败: {str(e)}")
                return False
    
    async def _check_lease_expiration(self, lease_id: str):
        """检查Cookie租用是否到期
        Args:
            lease_id: 租用ID
        """
        while True:
            # 检查租用是否存在
            if lease_id not in self.cookie_leases:
                break
            
            lease = self.cookie_leases[lease_id]
            
            # 检查租用是否已到期
            if lease.status == LeaseStatus.ACTIVE and datetime.now(timezone.utc) > lease.expires_at:
                # 自动释放到期的租用
                await self.release_cookie(lease_id)
                
                self.logger.info(f"Cookie租用已自动释放（到期）: {lease_id}")
                break
            
            # 如果租用已释放，停止检查
            if lease.status == LeaseStatus.RELEASED:
                break
            
            # 等待一段时间后再次检查
            await asyncio.sleep(10)
    
    async def _health_check_loop(self):
        """Cookie健康检查循环"""
        self.logger.info("启动Cookie健康检查循环")
        
        while True:
            try:
                # 对每个Cookie池中的Cookie进行健康检查
                for pool_id, cookie_pool in list(self.cookie_pools.items()):
                    for cookie_item in list(cookie_pool.cookies):
                        # 根据Cookie状态决定检查间隔
                        check_interval = self.health_check_intervals.get(cookie_item.status, 300)
                        
                        # 检查是否需要进行健康检查
                        last_check = cookie_item.last_health_check or cookie_item.created_at
                        time_since_last_check = (datetime.now(timezone.utc) - last_check).total_seconds()
                        
                        if time_since_last_check >= check_interval:
                            # 异步进行健康检查
                            asyncio.create_task(self._check_cookie_health(cookie_item, cookie_pool))
                
                # 清理过期的租用
                self._clean_expired_leases()
                
                # 等待一段时间后再次检查
                await asyncio.sleep(60)  # 每分钟检查一次是否需要进行健康检查
            except Exception as e:
                self.logger.error(f"Cookie健康检查循环异常: {str(e)}")
                # 出错后等待一段时间再继续
                await asyncio.sleep(10)
    
    def _clean_expired_leases(self):
        """清理过期的租用"""
        current_time = datetime.now(timezone.utc)
        expired_lease_ids = []
        
        for lease_id, lease in list(self.cookie_leases.items()):
            # 移除已释放且已过期1小时以上的租用记录
            if lease.status == LeaseStatus.RELEASED and \
               (current_time - lease.released_at).total_seconds() > 3600:
                expired_lease_ids.append(lease_id)
        
        for lease_id in expired_lease_ids:
            if lease_id in self.cookie_leases:
                del self.cookie_leases[lease_id]
                self.logger.debug(f"清理过期的Cookie租用记录: {lease_id}")
    
    async def _check_cookie_health(self, cookie_item: CookieItem, cookie_pool: CookiePool):
        """检查Cookie的健康状态
        Args:
            cookie_item: Cookie对象
            cookie_pool: Cookie池对象
        """
        try:
            # 更新最后健康检查时间
            cookie_item.last_health_check = datetime.now(timezone.utc)
            
            # 如果Cookie池没有目标域名，跳过健康检查
            if not cookie_pool.target_domains:
                self.logger.debug(f"跳过Cookie健康检查（没有目标域名）: {cookie_item.id}")
                return
            
            # 选择一个目标域名进行健康检查
            target_domain = random.choice(cookie_pool.target_domains)
            test_url = f"https://{target_domain}"
            
            self.logger.debug(f"开始Cookie健康检查: {cookie_item.id} -> {test_url}")
            
            # 使用爬虫进行健康检查
            crawler = SmartCrawler(settings)
            
            # 准备Cookie字典
            cookie_dict = {
                cookie_item.name: cookie_item.value,
                'domain': cookie_item.domain,
                'path': cookie_item.path or '/'
            }
            
            # 执行健康检查请求
            result = await crawler._check_url_health(test_url, cookies=[cookie_dict])
            
            # 更新Cookie状态
            if result['status_code'] == 200:
                # 检查响应内容，判断是否需要登录（这里可以根据实际情况调整判断逻辑）
                if '需要登录' in result['content'] or 'login' in result['content'].lower():
                    new_status = CookieStatus.INVALID
                    self.logger.warning(f"Cookie健康检查失败（需要登录）: {cookie_item.id} -> {test_url}")
                else:
                    new_status = CookieStatus.VALID
                    self.logger.debug(f"Cookie健康检查成功: {cookie_item.id} -> {test_url}")
            elif result['status_code'] == 403 or result['status_code'] == 401:
                new_status = CookieStatus.INVALID
                self.logger.warning(f"Cookie健康检查失败（权限错误）: {cookie_item.id} -> {test_url}, 状态码: {result['status_code']}")
            elif result['status_code'] == 429:
                new_status = CookieStatus.WARNING
                self.logger.warning(f"Cookie健康检查警告（频率限制）: {cookie_item.id} -> {test_url}, 状态码: {result['status_code']}")
            else:
                new_status = CookieStatus.WARNING
                self.logger.warning(f"Cookie健康检查警告（其他错误）: {cookie_item.id} -> {test_url}, 状态码: {result['status_code']}")
            
            # 更新Cookie状态
            if new_status != cookie_item.status:
                cookie_item.status = new_status
                cookie_item.updated_at = datetime.now(timezone.utc)
                self.logger.info(f"Cookie状态更新: {cookie_item.id} -> {new_status}")
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
                
            # 记录健康检查结果
            cookie_item.health_check_results.append({
                'timestamp': datetime.now(timezone.utc),
                'status': new_status,
                'url': test_url,
                'response_code': result['status_code'],
                'response_time': result['response_time']
            })
            
            # 保持最近10次健康检查结果
            if len(cookie_item.health_check_results) > 10:
                cookie_item.health_check_results = cookie_item.health_check_results[-10:]
                
        except Exception as e:
            self.logger.error(f"Cookie健康检查失败: {str(e)}")
            
            # 更新Cookie状态为警告
            if cookie_item.status != CookieStatus.INVALID:
                cookie_item.status = CookieStatus.WARNING
                cookie_item.updated_at = datetime.now(timezone.utc)
                
                # 保存更新后的Cookie池
                await self._save_cookie_pools_to_storage()
    
    async def get_leased_cookie(self, lease_id: str) -> Optional[Dict[str, Any]]:
        """获取租用的Cookie信息
        Args:
            lease_id: 租用ID
        Returns:
            Dict[str, Any]: Cookie信息字典或None
        """
        async with self.pool_lock:
            # 检查租用是否存在且有效
            if lease_id not in self.cookie_leases:
                self.logger.error(f"Cookie租用不存在: {lease_id}")
                return None
            
            lease = self.cookie_leases[lease_id]
            
            if lease.status != LeaseStatus.ACTIVE:
                self.logger.error(f"Cookie租用已失效: {lease_id}")
                return None
            
            if datetime.now(timezone.utc) > lease.expires_at:
                self.logger.error(f"Cookie租用已到期: {lease_id}")
                return None
            
            # 查找Cookie池和Cookie
            if lease.cookie_pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {lease.cookie_pool_id}")
                return None
            
            cookie_pool = self.cookie_pools[lease.cookie_pool_id]
            cookie_item = next((c for c in cookie_pool.cookies if c.id == lease.cookie_id), None)
            
            if not cookie_item:
                self.logger.error(f"Cookie不存在: {lease.cookie_id}")
                return None
            
            # 返回Cookie信息
            return {
                'id': cookie_item.id,
                'name': cookie_item.name,
                'value': cookie_item.value,
                'domain': cookie_item.domain,
                'path': cookie_item.path,
                'secure': cookie_item.secure,
                'http_only': cookie_item.http_only,
                'expires': cookie_item.expires,
                'status': cookie_item.status.value
            }
    
    async def batch_add_cookies(self, pool_id: str, cookies_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加Cookie到Cookie池
        Args:
            pool_id: Cookie池ID
            cookies_data: Cookie数据列表
        Returns:
            Dict[str, Any]: 添加结果统计
        """
        stats = {
            'total': len(cookies_data),
            'success': 0,
            'failed': 0,
            'errors': []
        }
        
        for cookie_data in cookies_data:
            try:
                # 添加上传时间和来源
                if 'uploaded_at' not in cookie_data:
                    cookie_data['uploaded_at'] = datetime.now(timezone.utc)
                if 'source' not in cookie_data:
                    cookie_data['source'] = CookieSource.UPLOADED.value
                
                # 添加Cookie
                result = await self.add_cookie(pool_id, cookie_data)
                if result:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"添加Cookie失败: {cookie_data.get('name', 'unknown')}")
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"添加Cookie异常: {str(e)}")
        
        self.logger.info(f"批量添加Cookie完成: {stats['success']} 成功, {stats['failed']} 失败")
        return stats
    
    async def get_cookie_pool_stats(self, pool_id: str) -> Optional[Dict[str, Any]]:
        """获取Cookie池统计信息
        Args:
            pool_id: Cookie池ID
        Returns:
            Dict[str, Any]: 统计信息字典或None
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return None
            
            cookie_pool = self.cookie_pools[pool_id]
            
            # 统计各状态的Cookie数量
            status_counts = {
                status.value: 0 for status in CookieStatus
            }
            
            for cookie in cookie_pool.cookies:
                status_counts[cookie.status.value] += 1
            
            # 统计活跃的租用数量
            active_leases = 0
            for lease in self.cookie_leases.values():
                if lease.cookie_pool_id == pool_id and lease.status == LeaseStatus.ACTIVE:
                    active_leases += 1
            
            # 计算平均健康分数（简化版）
            health_score = 0
            if len(cookie_pool.cookies) > 0:
                # 为不同状态分配分数
                status_scores = {
                    CookieStatus.VALID: 100,
                    CookieStatus.WARNING: 50,
                    CookieStatus.PENDING: 75,
                    CookieStatus.INVALID: 0
                }
                
                total_score = sum(status_scores.get(cookie.status, 0) for cookie in cookie_pool.cookies)
                health_score = total_score / len(cookie_pool.cookies)
            
            return {
                'pool_id': pool_id,
                'pool_name': cookie_pool.name,
                'total_cookies': len(cookie_pool.cookies),
                'status_counts': status_counts,
                'active_leases': active_leases,
                'health_score': round(health_score, 2),
                'target_domains': cookie_pool.target_domains,
                'created_at': cookie_pool.created_at,
                'updated_at': cookie_pool.updated_at
            }
    
    async def refresh_all_cookies(self, pool_id: str) -> Dict[str, Any]:
        """刷新Cookie池中的所有Cookie
        Args:
            pool_id: Cookie池ID
        Returns:
            Dict[str, Any]: 刷新结果统计
        """
        async with self.pool_lock:
            if pool_id not in self.cookie_pools:
                self.logger.error(f"Cookie池不存在: {pool_id}")
                return {'success': False, 'error': 'Cookie池不存在'}
            
            cookie_pool = self.cookie_pools[pool_id]
            
            # 只对非活跃租用的Cookie进行刷新
            refreshable_cookies = []
            for cookie in cookie_pool.cookies:
                if not self._is_cookie_leased(cookie.id):
                    refreshable_cookies.append(cookie)
            
            self.logger.info(f"开始刷新Cookie池中的Cookie: {pool_id}, 共 {len(refreshable_cookies)} 个Cookie可刷新")
            
            # 异步刷新每个Cookie
            tasks = []
            for cookie in refreshable_cookies:
                tasks.append(self._check_cookie_health(cookie, cookie_pool))
            
            # 等待所有刷新任务完成
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # 保存更新后的Cookie池
            await self._save_cookie_pools_to_storage()
            
            # 返回刷新结果
            stats = await self.get_cookie_pool_stats(pool_id)
            
            self.logger.info(f"Cookie池刷新完成: {pool_id}")
            return {
                'success': True,
                'stats': stats
            }
    
    async def shutdown(self):
        """关闭Cookie管理器"""
        # 保存Cookie池
        await self._save_cookie_pools_to_storage()
        
        # 释放所有活跃的Cookie租用
        for lease_id in list(self.cookie_leases.keys()):
            lease = self.cookie_leases[lease_id]
            if lease.status == LeaseStatus.ACTIVE:
                await self.release_cookie(lease_id)
        
        self.logger.info("Cookie管理器已关闭")