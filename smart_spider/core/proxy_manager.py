"""
代理管理器 - 负责代理IP池管理、代理测试、健康检查和动态调度
"""

import os
import asyncio
import random
import time
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union, Tuple
from urllib.parse import urlparse

from smart_spider.core.storage import StorageManager
from smart_spider.core.cache import get_cache
from smart_spider.utils.logger import get_logger
from smart_spider.settings import settings


class ProxyStatus:
    """代理IP状态枚举"""
    VALID = 'valid'         # 有效
    WARNING = 'warning'     # 警告（响应慢等）
    INVALID = 'invalid'     # 无效
    PENDING = 'pending'     # 待验证
    BLACKLISTED = 'blacklisted'  # 黑名单


class ProxyType:
    """代理类型枚举"""
    HTTP = 'http'           # HTTP代理
    HTTPS = 'https'         # HTTPS代理
    SOCKS5 = 'socks5'       # SOCKS5代理
    SOCKS4 = 'socks4'       # SOCKS4代理
    ALL = 'all'             # 所有类型


class ProxyPoolType:
    """代理池类型枚举"""
    PUBLIC = 'public'       # 公共代理
    PRIVATE = 'private'     # 私有代理
    SHARED = 'shared'       # 共享代理池


class ProxyItem:
    """代理IP项"""
    def __init__(self,
                 id: Optional[str] = None,
                 ip: str = '',
                 port: int = 0,
                 protocol: str = ProxyType.HTTP,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 location: Optional[str] = None,
                 isp: Optional[str] = None,
                 status: str = ProxyStatus.PENDING,
                 response_time: float = 0.0,
                 anonymity: Optional[str] = None,
                 created_at: Optional[datetime] = None,
                 updated_at: Optional[datetime] = None,
                 last_health_check: Optional[datetime] = None,
                 health_check_results: Optional[List[Dict[str, Any]]] = None,
                 fail_count: int = 0,
                 success_count: int = 0,
                 score: float = 0.0):
        self.id = id or f"proxy_{int(time.time())}_{random.randint(1000, 9999)}"
        self.ip = ip
        self.port = port
        self.protocol = protocol.lower()
        self.username = username
        self.password = password
        self.location = location
        self.isp = isp
        self.status = status
        self.response_time = response_time
        self.anonymity = anonymity
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.last_health_check = last_health_check
        self.health_check_results = health_check_results or []
        self.fail_count = fail_count
        self.success_count = success_count
        self.score = score
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'id': self.id,
            'ip': self.ip,
            'port': self.port,
            'protocol': self.protocol,
            'username': self.username,
            'password': self.password,
            'location': self.location,
            'isp': self.isp,
            'status': self.status,
            'response_time': self.response_time,
            'anonymity': self.anonymity,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'health_check_results': self.health_check_results,
            'fail_count': self.fail_count,
            'success_count': self.success_count,
            'score': self.score
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyItem':
        """从字典创建ProxyItem实例"""
        # 转换时间字段
        for key in ['created_at', 'updated_at', 'last_health_check']:
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key].replace('Z', '+00:00'))
                except ValueError:
                    data[key] = None
        
        return cls(**data)
    
    @property
    def url(self) -> str:
        """获取代理URL"""
        if self.username and self.password:
            return f"{self.protocol}://{self.username}:{self.password}@{self.ip}:{self.port}"
        else:
            return f"{self.protocol}://{self.ip}:{self.port}"
    
    @property
    def is_authenticated(self) -> bool:
        """是否需要认证"""
        return self.username is not None and self.password is not None


class ProxyLease:
    """代理租用"""
    def __init__(self,
                 id: Optional[str] = None,
                 proxy_id: str = '',
                 proxy_pool_id: str = '',
                 task_id: str = '',
                 status: str = 'active',
                 leased_at: Optional[datetime] = None,
                 expires_at: Optional[datetime] = None,
                 released_at: Optional[datetime] = None):
        self.id = id or f"lease_{int(time.time())}_{random.randint(1000, 9999)}"
        self.proxy_id = proxy_id
        self.proxy_pool_id = proxy_pool_id
        self.task_id = task_id
        self.status = status  # active, released, expired
        self.leased_at = leased_at or datetime.now(timezone.utc)
        self.expires_at = expires_at
        self.released_at = released_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'id': self.id,
            'proxy_id': self.proxy_id,
            'proxy_pool_id': self.proxy_pool_id,
            'task_id': self.task_id,
            'status': self.status,
            'leased_at': self.leased_at.isoformat() if self.leased_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'released_at': self.released_at.isoformat() if self.released_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyLease':
        """从字典创建ProxyLease实例"""
        # 转换时间字段
        for key in ['leased_at', 'expires_at', 'released_at']:
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key].replace('Z', '+00:00'))
                except ValueError:
                    data[key] = None
        
        return cls(**data)
    
    def release(self):
        """释放租用"""
        self.status = 'released'
        self.released_at = datetime.now(timezone.utc)
    
    @property
    def is_active(self) -> bool:
        """租用是否活跃"""
        return self.status == 'active' and \
               (self.expires_at is None or datetime.now(timezone.utc) < self.expires_at)


class ProxyPool:
    """代理池"""
    def __init__(self,
                 id: Optional[str] = None,
                 name: str = '',
                 description: Optional[str] = None,
                 type: str = ProxyPoolType.PUBLIC,
                 proxies: Optional[List[ProxyItem]] = None,
                 created_at: Optional[datetime] = None,
                 updated_at: Optional[datetime] = None):
        self.id = id or f"pool_{int(time.time())}_{random.randint(1000, 9999)}"
        self.name = name
        self.description = description
        self.type = type
        self.proxies = proxies or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'type': self.type,
            'proxies': [proxy.to_dict() for proxy in self.proxies],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyPool':
        """从字典创建ProxyPool实例"""
        # 转换时间字段
        for key in ['created_at', 'updated_at']:
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = datetime.fromisoformat(data[key].replace('Z', '+00:00'))
                except ValueError:
                    data[key] = None
        
        # 转换代理列表
        proxies = []
        if 'proxies' in data and isinstance(data['proxies'], list):
            for proxy_data in data['proxies']:
                proxies.append(ProxyItem.from_dict(proxy_data))
        
        data['proxies'] = proxies
        
        return cls(**data)
    
    @property
    def valid_proxy_count(self) -> int:
        """有效代理数量"""
        return sum(1 for proxy in self.proxies if proxy.status == ProxyStatus.VALID)
    
    @property
    def warning_proxy_count(self) -> int:
        """警告代理数量"""
        return sum(1 for proxy in self.proxies if proxy.status == ProxyStatus.WARNING)
    
    @property
    def invalid_proxy_count(self) -> int:
        """无效代理数量"""
        return sum(1 for proxy in self.proxies if proxy.status == ProxyStatus.INVALID)
    
    @property
    def total_proxy_count(self) -> int:
        """代理总数"""
        return len(self.proxies)
    
    def update_timestamp(self):
        """更新时间戳"""
        self.updated_at = datetime.now(timezone.utc)


class ProxyManager:
    """代理管理器类"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(ProxyManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance
    
    def _init(self):
        """初始化代理管理器"""
        self.proxy_pools: Dict[str, ProxyPool] = {}
        self.proxy_leases: Dict[str, ProxyLease] = {}
        self.pool_lock = asyncio.Lock()
        self.logger = get_logger(__name__)
        self.storage = StorageManager.create_storage(settings.get('storage', {}))
        self.cache = get_cache('proxy_cache', {'type': 'memory', 'max_size': 1000, 'default_ttl': 600})
        self.health_check_intervals = {
            ProxyStatus.VALID: 300,  # 5分钟
            ProxyStatus.WARNING: 60,  # 1分钟
            ProxyStatus.INVALID: 3600,  # 1小时
            ProxyStatus.PENDING: 30  # 30秒
        }
        
        # 健康检查配置
        self.health_check_config = {
            'test_urls': [
                'https://www.example.com',
                'https://www.google.com',
                'https://www.baidu.com'
            ],
            'timeout': 10,  # 10秒
            'success_threshold': 0.6,  # 60%的测试URL成功
            'max_response_time': 5.0  # 5秒
        }
        
        self._initialized = False
        
        # 延迟初始化，避免在没有事件循环时创建任务
        if settings.get('delay_init', False):
            self.logger.info("代理管理器初始化成功(延迟加载模式)")
        else:
            # 从存储加载代理池
            asyncio.create_task(self._load_proxy_pools_from_storage())
            
            # 启动健康检查任务
            asyncio.create_task(self._health_check_loop())
            
            # 启动代理自动刷新任务
            asyncio.create_task(self._auto_refresh_proxies())
        
        self.logger.info("代理管理器初始化成功")
    
    async def _load_proxy_pools_from_storage(self):
        """从存储加载代理池"""
        try:
            pools_data = await self.storage.get(filename='proxy_pools.json')
            if pools_data and isinstance(pools_data, list):
                for pool_dict in pools_data:
                    try:
                        proxy_pool = ProxyPool.from_dict(pool_dict)
                        self.proxy_pools[proxy_pool.id] = proxy_pool
                        self.logger.info(f"加载代理池: {proxy_pool.id} - {proxy_pool.name}")
                    except Exception as e:
                        self.logger.error(f"加载代理池失败: {str(e)}")
        except Exception as e:
            self.logger.error(f"从存储加载代理池失败: {str(e)}")
    
    async def _save_proxy_pools_to_storage(self):
        """将代理池保存到存储"""
        try:
            pools_data = [pool.to_dict() for pool in self.proxy_pools.values()]
            await self.storage.save(pools_data, filename='proxy_pools.json', overwrite=True)
            self.logger.debug("代理池保存到存储成功")
        except Exception as e:
            self.logger.error(f"将代理池保存到存储失败: {str(e)}")
    
    async def create_proxy_pool(self, config: Union[Dict[str, Any], ProxyPool]) -> ProxyPool:
        """创建代理池
        Args:
            config: 代理池配置，可以是字典或ProxyPool对象
        Returns:
            ProxyPool: 创建的代理池对象
        """
        async with self.pool_lock:
            try:
                # 转换配置格式
                if isinstance(config, dict):
                    # 如果没有提供id，生成一个
                    if 'id' not in config:
                        config['id'] = f"pool_{int(time.time())}_{random.randint(1000, 9999)}"
                    proxy_pool = ProxyPool.from_dict(config)
                else:
                    proxy_pool = config
                
                # 验证代理池配置
                self._validate_proxy_pool(proxy_pool)
                
                # 添加到代理池集合
                self.proxy_pools[proxy_pool.id] = proxy_pool
                
                # 保存代理池到存储
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"创建代理池成功: {proxy_pool.id} - {proxy_pool.name}")
                return proxy_pool
            except Exception as e:
                self.logger.error(f"创建代理池失败: {str(e)}")
                raise
    
    def _validate_proxy_pool(self, proxy_pool: ProxyPool):
        """验证代理池配置
        Args:
            proxy_pool: 代理池对象
        Raises:
            ValueError: 配置无效时抛出
        """
        # 验证名称
        if not proxy_pool.name or len(proxy_pool.name) > 100:
            raise ValueError("代理池名称不能为空且长度不能超过100个字符")
        
        # 验证类型
        valid_types = [t.value for t in [ProxyPoolType.PUBLIC, ProxyPoolType.PRIVATE, ProxyPoolType.SHARED]]
        if proxy_pool.type not in valid_types:
            raise ValueError(f"无效的代理池类型: {proxy_pool.type}")
        
        # 验证描述
        if proxy_pool.description and len(proxy_pool.description) > 500:
            raise ValueError("代理池描述长度不能超过500个字符")
    
    async def get_proxy_pool(self, pool_id: str) -> Optional[ProxyPool]:
        """获取代理池
        Args:
            pool_id: 代理池ID
        Returns:
            ProxyPool: 代理池对象或None
        """
        async with self.pool_lock:
            return self.proxy_pools.get(pool_id)
    
    async def list_proxy_pools(self, pool_type: Optional[str] = None) -> List[ProxyPool]:
        """列出所有代理池
        Args:
            pool_type: 代理池类型过滤
        Returns:
            List[ProxyPool]: 代理池列表
        """
        async with self.pool_lock:
            if pool_type:
                return [pool for pool in self.proxy_pools.values() if pool.type == pool_type]
            else:
                return list(self.proxy_pools.values())
    
    async def update_proxy_pool(self, pool_id: str, config: Dict[str, Any]) -> Optional[ProxyPool]:
        """更新代理池配置
        Args:
            pool_id: 代理池ID
            config: 要更新的配置
        Returns:
            ProxyPool: 更新后的代理池对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return None
            
            try:
                proxy_pool = self.proxy_pools[pool_id]
                
                # 更新配置
                for key, value in config.items():
                    if hasattr(proxy_pool, key) and key != 'id' and key != 'proxies':
                        setattr(proxy_pool, key, value)
                
                # 验证更新后的配置
                self._validate_proxy_pool(proxy_pool)
                
                # 更新时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"更新代理池成功: {pool_id} - {proxy_pool.name}")
                return proxy_pool
            except Exception as e:
                self.logger.error(f"更新代理池失败: {str(e)}")
                return None
    
    async def delete_proxy_pool(self, pool_id: str) -> bool:
        """删除代理池
        Args:
            pool_id: 代理池ID
        Returns:
            bool: 是否删除成功
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return False
            
            try:
                # 检查是否有正在使用的代理
                for lease in self.proxy_leases.values():
                    if lease.proxy_pool_id == pool_id and lease.is_active:
                        self.logger.error(f"代理池还有活跃的代理租用，无法删除: {pool_id}")
                        return False
                
                # 从内存中删除代理池
                del self.proxy_pools[pool_id]
                
                # 保存更新后的代理池集合
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"删除代理池成功: {pool_id}")
                return True
            except Exception as e:
                self.logger.error(f"删除代理池失败: {str(e)}")
                return False
    
    async def add_proxy(self, pool_id: str, proxy_data: Union[Dict[str, Any], ProxyItem]) -> Optional[ProxyItem]:
        """添加代理到代理池
        Args:
            pool_id: 代理池ID
            proxy_data: 代理数据，可以是字典或ProxyItem对象
        Returns:
            ProxyItem: 添加的代理对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return None
            
            try:
                proxy_pool = self.proxy_pools[pool_id]
                
                # 转换代理数据格式
                if isinstance(proxy_data, dict):
                    # 如果没有提供id，生成一个
                    if 'id' not in proxy_data:
                        proxy_data['id'] = f"proxy_{int(time.time())}_{random.randint(1000, 9999)}"
                    # 如果没有提供状态，默认为待验证
                    if 'status' not in proxy_data:
                        proxy_data['status'] = ProxyStatus.PENDING
                    proxy_item = ProxyItem.from_dict(proxy_data)
                else:
                    proxy_item = proxy_data
                
                # 验证代理数据
                self._validate_proxy(proxy_item)
                
                # 检查是否已存在相同的代理
                for existing_proxy in proxy_pool.proxies:
                    if existing_proxy.ip == proxy_item.ip and existing_proxy.port == proxy_item.port:
                        self.logger.warning(f"代理已存在于池: {proxy_pool.id}")
                        return existing_proxy
                
                # 添加代理到池
                proxy_pool.proxies.append(proxy_item)
                
                # 更新时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"添加代理到池成功: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port}) -> {pool_id}")
                
                # 立即进行健康检查
                asyncio.create_task(self._check_proxy_health(proxy_item, proxy_pool))
                
                return proxy_item
            except Exception as e:
                self.logger.error(f"添加代理到池失败: {str(e)}")
                return None
    
    def _validate_proxy(self, proxy_item: ProxyItem):
        """验证代理数据
        Args:
            proxy_item: 代理对象
        Raises:
            ValueError: 数据无效时抛出
        """
        # 验证必要字段
        if not proxy_item.ip or not proxy_item.port:
            raise ValueError("代理IP和端口不能为空")
        
        # 验证端口范围
        if not (0 < proxy_item.port <= 65535):
            raise ValueError("代理端口必须在1-65535之间")
        
        # 验证代理类型
        valid_types = [t.value for t in [ProxyType.HTTP, ProxyType.HTTPS, ProxyType.SOCKS5, ProxyType.SOCKS4]]
        if proxy_item.protocol not in valid_types:
            raise ValueError(f"无效的代理类型: {proxy_item.protocol}")
        
        # 验证状态
        valid_statuses = [s for s in [ProxyStatus.VALID, ProxyStatus.WARNING, ProxyStatus.INVALID, ProxyStatus.PENDING, ProxyStatus.BLACKLISTED]]
        if proxy_item.status not in valid_statuses:
            raise ValueError(f"无效的代理状态: {proxy_item.status}")
    
    async def remove_proxy(self, pool_id: str, proxy_id: str) -> bool:
        """从代理池移除代理
        Args:
            pool_id: 代理池ID
            proxy_id: 代理ID
        Returns:
            bool: 是否移除成功
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return False
            
            proxy_pool = self.proxy_pools[pool_id]
            
            # 检查是否有正在使用的代理租用
            for lease in self.proxy_leases.values():
                if lease.proxy_id == proxy_id and lease.is_active:
                    self.logger.error(f"代理还有活跃的租用，无法移除: {proxy_id}")
                    return False
            
            try:
                # 移除代理
                original_count = len(proxy_pool.proxies)
                proxy_pool.proxies = [p for p in proxy_pool.proxies if p.id != proxy_id]
                
                if len(proxy_pool.proxies) == original_count:
                    self.logger.warning(f"代理不存在于池: {proxy_id} -> {pool_id}")
                    return False
                
                # 更新时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"从池移除代理成功: {proxy_id} -> {pool_id}")
                return True
            except Exception as e:
                self.logger.error(f"从池移除代理失败: {str(e)}")
                return False
    
    async def update_proxy(self, pool_id: str, proxy_id: str, updates: Dict[str, Any]) -> Optional[ProxyItem]:
        """更新代理信息
        Args:
            pool_id: 代理池ID
            proxy_id: 代理ID
            updates: 要更新的字段
        Returns:
            ProxyItem: 更新后的代理对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return None
            
            proxy_pool = self.proxy_pools[pool_id]
            
            # 查找代理
            proxy_item = next((p for p in proxy_pool.proxies if p.id == proxy_id), None)
            if not proxy_item:
                self.logger.error(f"代理不存在: {proxy_id} -> {pool_id}")
                return None
            
            try:
                # 保存旧状态，用于比较
                old_status = proxy_item.status
                
                # 更新代理信息
                for key, value in updates.items():
                    if hasattr(proxy_item, key) and key != 'id' and key != 'created_at':
                        setattr(proxy_item, key, value)
                
                # 更新最后更新时间
                proxy_item.updated_at = datetime.now(timezone.utc)
                
                # 更新时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
                
                self.logger.info(f"更新代理信息成功: {proxy_id} -> {pool_id}")
                
                # 如果状态发生变化，进行健康检查
                if proxy_item.status != old_status:
                    asyncio.create_task(self._check_proxy_health(proxy_item, proxy_pool))
                
                return proxy_item
            except Exception as e:
                self.logger.error(f"更新代理信息失败: {str(e)}")
                return None
    
    async def lease_proxy(self, pool_id: str, task_id: str, protocol: str = 'all', ttl: int = 300) -> Optional[ProxyLease]:
        """租用代理
        Args:
            pool_id: 代理池ID
            task_id: 任务ID
            protocol: 代理协议类型
            ttl: 租用时长（秒）
        Returns:
            ProxyLease: 代理租用对象或None
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return None
            
            proxy_pool = self.proxy_pools[pool_id]
            
            try:
                # 查找可用的代理（优先级：VALID > WARNING > PENDING）
                available_proxies = []
                
                # 筛选符合协议要求的代理
                for proxy in proxy_pool.proxies:
                    # 检查协议是否匹配
                    if protocol != 'all' and proxy.protocol != protocol:
                        continue
                    
                    # 检查是否未被租用
                    if not self._is_proxy_leased(proxy.id):
                        available_proxies.append(proxy)
                
                # 按状态优先级排序
                available_proxies.sort(key=lambda p: {
                    ProxyStatus.VALID: 0,
                    ProxyStatus.WARNING: 1,
                    ProxyStatus.PENDING: 2,
                    ProxyStatus.INVALID: 3,
                    ProxyStatus.BLACKLISTED: 4
                }.get(p.status, 999))
                
                # 如果有可用代理，选择响应时间最短的
                if available_proxies:
                    # 先按状态分组
                    proxies_by_status = {}
                    for proxy in available_proxies:
                        if proxy.status not in proxies_by_status:
                            proxies_by_status[proxy.status] = []
                        proxies_by_status[proxy.status].append(proxy)
                    
                    # 选择优先级最高的状态组
                    for status in [ProxyStatus.VALID, ProxyStatus.WARNING, ProxyStatus.PENDING]:
                        if status in proxies_by_status:
                            # 在该状态组中选择响应时间最短的（排除响应时间为0的）
                            valid_proxies = [p for p in proxies_by_status[status] if p.response_time > 0]
                            if valid_proxies:
                                # 按响应时间排序，选择最快的几个进行随机选择
                                valid_proxies.sort(key=lambda p: p.response_time)
                                # 选择响应时间前30%的代理进行随机选择，避免总是选择同一个代理
                                sample_size = max(1, int(len(valid_proxies) * 0.3))
                                selected_proxy = random.choice(valid_proxies[:sample_size])
                                break
                            else:
                                # 如果没有响应时间数据，随机选择
                                selected_proxy = random.choice(proxies_by_status[status])
                                break
                    else:
                        # 如果没有符合条件的代理，返回None
                        self.logger.warning(f"代理池 {pool_id} 中没有可用的代理")
                        return None
                    
                    # 创建代理租用
                    lease = ProxyLease(
                        proxy_id=selected_proxy.id,
                        proxy_pool_id=pool_id,
                        task_id=task_id,
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl)
                    )
                    
                    # 添加到租用集合
                    self.proxy_leases[lease.id] = lease
                    
                    self.logger.info(f"租用代理成功: {selected_proxy.id} ({selected_proxy.ip}:{selected_proxy.port}) -> {pool_id} (任务: {task_id})")
                    
                    # 启动租用到期检查
                    asyncio.create_task(self._check_lease_expiration(lease.id))
                    
                    return lease
                else:
                    self.logger.warning(f"代理池 {pool_id} 中没有可用的代理")
                    return None
            except Exception as e:
                self.logger.error(f"租用代理失败: {str(e)}")
                return None
    
    def _is_proxy_leased(self, proxy_id: str) -> bool:
        """检查代理是否已被租用
        Args:
            proxy_id: 代理ID
        Returns:
            bool: 是否已被租用
        """
        for lease in self.proxy_leases.values():
            if lease.proxy_id == proxy_id and lease.is_active:
                return True
        return False
    
    async def release_proxy(self, lease_id: str) -> bool:
        """释放代理租用
        Args:
            lease_id: 租用ID
        Returns:
            bool: 是否释放成功
        """
        async with self.pool_lock:
            if lease_id not in self.proxy_leases:
                self.logger.error(f"代理租用不存在: {lease_id}")
                return False
            
            lease = self.proxy_leases[lease_id]
            
            try:
                # 更新租用状态
                lease.release()
                
                self.logger.info(f"释放代理租用成功: {lease_id}")
                return True
            except Exception as e:
                self.logger.error(f"释放代理租用失败: {str(e)}")
                return False
    
    async def _check_lease_expiration(self, lease_id: str):
        """检查代理租用是否到期
        Args:
            lease_id: 租用ID
        """
        while True:
            # 检查租用是否存在
            if lease_id not in self.proxy_leases:
                break
            
            lease = self.proxy_leases[lease_id]
            
            # 检查租用是否已到期
            if lease.is_active and datetime.now(timezone.utc) > lease.expires_at:
                # 自动释放到期的租用
                await self.release_proxy(lease_id)
                
                self.logger.info(f"代理租用已自动释放（到期）: {lease_id}")
                break
            
            # 如果租用已释放，停止检查
            if lease.status == 'released':
                break
            
            # 等待一段时间后再次检查
            await asyncio.sleep(10)
    
    async def _health_check_loop(self):
        """代理健康检查循环"""
        self.logger.info("启动代理健康检查循环")
        
        while True:
            try:
                # 对每个代理池中的代理进行健康检查
                for pool_id, proxy_pool in list(self.proxy_pools.items()):
                    for proxy_item in list(proxy_pool.proxies):
                        # 根据代理状态决定检查间隔
                        check_interval = self.health_check_intervals.get(proxy_item.status, 300)
                        
                        # 检查是否需要进行健康检查
                        last_check = proxy_item.last_health_check or proxy_item.created_at
                        time_since_last_check = (datetime.now(timezone.utc) - last_check).total_seconds()
                        
                        if time_since_last_check >= check_interval:
                            # 异步进行健康检查
                            asyncio.create_task(self._check_proxy_health(proxy_item, proxy_pool))
                
                # 清理过期的租用
                self._clean_expired_leases()
                
                # 等待一段时间后再次检查
                await asyncio.sleep(60)  # 每分钟检查一次是否需要进行健康检查
            except Exception as e:
                self.logger.error(f"代理健康检查循环异常: {str(e)}")
                # 出错后等待一段时间再继续
                await asyncio.sleep(10)
    
    def _clean_expired_leases(self):
        """清理过期的租用"""
        current_time = datetime.now(timezone.utc)
        expired_lease_ids = []
        
        for lease_id, lease in list(self.proxy_leases.items()):
            # 移除已释放且已过期1小时以上的租用记录
            if lease.status == 'released' and \
               lease.released_at and \
               (current_time - lease.released_at).total_seconds() > 3600:
                expired_lease_ids.append(lease_id)
        
        for lease_id in expired_lease_ids:
            if lease_id in self.proxy_leases:
                del self.proxy_leases[lease_id]
                self.logger.debug(f"清理过期的代理租用记录: {lease_id}")
    
    async def _check_proxy_health(self, proxy_item: ProxyItem, proxy_pool: ProxyPool):
        """检查代理的健康状态
        Args:
            proxy_item: 代理对象
            proxy_pool: 代理池对象
        """
        try:
            # 更新最后健康检查时间
            proxy_item.last_health_check = datetime.now(timezone.utc)
            
            self.logger.debug(f"开始代理健康检查: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port})")
            
            # 测试代理的有效性
            test_results = await self._test_proxy(proxy_item)
            
            # 计算测试成功率
            success_rate = test_results['success_count'] / len(test_results['results']) if test_results['results'] else 0
            
            # 计算平均响应时间
            avg_response_time = sum(r['response_time'] for r in test_results['results'] if r['success']) / \
                               test_results['success_count'] if test_results['success_count'] > 0 else float('inf')
            
            # 更新代理信息
            proxy_item.response_time = avg_response_time
            
            # 更新代理状态
            if success_rate >= self.health_check_config['success_threshold'] and \
               avg_response_time <= self.health_check_config['max_response_time']:
                new_status = ProxyStatus.VALID
                self.logger.debug(f"代理健康检查成功: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port}), 成功率: {success_rate:.2f}, 响应时间: {avg_response_time:.2f}s")
            elif success_rate > 0:
                new_status = ProxyStatus.WARNING
                self.logger.warning(f"代理健康检查警告: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port}), 成功率: {success_rate:.2f}, 响应时间: {avg_response_time:.2f}s")
            else:
                new_status = ProxyStatus.INVALID
                self.logger.warning(f"代理健康检查失败: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port}), 成功率: {success_rate:.2f}")
            
            # 更新代理状态
            if new_status != proxy_item.status:
                proxy_item.status = new_status
                proxy_item.updated_at = datetime.now(timezone.utc)
                self.logger.info(f"代理状态更新: {proxy_item.id} ({proxy_item.ip}:{proxy_item.port}) -> {new_status}")
                
                # 更新代理池时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
            
            # 更新分数（简化版）
            self._update_proxy_score(proxy_item, success_rate, avg_response_time)
            
            # 记录健康检查结果
            proxy_item.health_check_results.append({
                'timestamp': datetime.now(timezone.utc),
                'status': new_status,
                'success_rate': success_rate,
                'avg_response_time': avg_response_time,
                'details': test_results
            })
            
            # 保持最近10次健康检查结果
            if len(proxy_item.health_check_results) > 10:
                proxy_item.health_check_results = proxy_item.health_check_results[-10:]
                
        except Exception as e:
            self.logger.error(f"代理健康检查失败: {str(e)}")
            
            # 更新代理状态为警告
            if proxy_item.status != ProxyStatus.INVALID:
                proxy_item.status = ProxyStatus.WARNING
                proxy_item.updated_at = datetime.now(timezone.utc)
                
                # 更新代理池时间戳
                proxy_pool.update_timestamp()
                
                # 保存更新后的代理池
                await self._save_proxy_pools_to_storage()
    
    async def _test_proxy(self, proxy_item: ProxyItem) -> Dict[str, Any]:
        """测试代理的有效性
        Args:
            proxy_item: 代理对象
        Returns:
            Dict[str, Any]: 测试结果
        """
        results = []
        success_count = 0
        
        # 准备代理配置
        proxy_url = proxy_item.url
        timeout = aiohttp.ClientTimeout(total=self.health_check_config['timeout'])
        
        # 并发测试多个URL
        async def test_url(url):
            nonlocal success_count
            start_time = time.time()
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, proxy=proxy_url) as response:
                        end_time = time.time()
                        response_time = end_time - start_time
                        success = response.status == 200
                        if success:
                            success_count += 1
                        
                        return {
                            'url': url,
                            'success': success,
                            'status_code': response.status,
                            'response_time': response_time
                        }
            except Exception as e:
                end_time = time.time()
                response_time = end_time - start_time
                return {
                    'url': url,
                    'success': False,
                    'error': str(e),
                    'response_time': response_time
                }
        
        # 创建测试任务
        tasks = []
        for url in self.health_check_config['test_urls']:
            tasks.append(test_url(url))
        
        # 执行测试
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        cleaned_results = []
        for result in results:
            if isinstance(result, Exception):
                cleaned_results.append({
                    'url': 'unknown',
                    'success': False,
                    'error': str(result),
                    'response_time': float('inf')
                })
            else:
                cleaned_results.append(result)
        
        return {
            'results': cleaned_results,
            'success_count': success_count,
            'total_count': len(cleaned_results)
        }
    
    def _update_proxy_score(self, proxy_item: ProxyItem, success_rate: float, avg_response_time: float):
        """更新代理分数
        Args:
            proxy_item: 代理对象
            success_rate: 成功率
            avg_response_time: 平均响应时间
        """
        # 计算新分数（基于成功率和响应时间）
        # 成功率权重 0.7，响应时间权重 0.3
        # 响应时间标准化为0-1（越小越好）
        max_time = self.health_check_config['max_response_time']
        time_score = max(0, 1 - (avg_response_time / max_time)) if avg_response_time < float('inf') else 0
        
        new_score = (success_rate * 0.7) + (time_score * 0.3)
        
        # 平滑更新分数（新分数权重 0.7，旧分数权重 0.3）
        if proxy_item.score > 0:
            proxy_item.score = (new_score * 0.7) + (proxy_item.score * 0.3)
        else:
            proxy_item.score = new_score
        
        # 记录成功/失败次数
        if success_rate >= self.health_check_config['success_threshold']:
            proxy_item.success_count += 1
        else:
            proxy_item.fail_count += 1
    
    async def get_leased_proxy(self, lease_id: str) -> Optional[Dict[str, Any]]:
        """获取租用的代理信息
        Args:
            lease_id: 租用ID
        Returns:
            Dict[str, Any]: 代理信息字典或None
        """
        async with self.pool_lock:
            # 检查租用是否存在且有效
            if lease_id not in self.proxy_leases:
                self.logger.error(f"代理租用不存在: {lease_id}")
                return None
            
            lease = self.proxy_leases[lease_id]
            
            if not lease.is_active:
                self.logger.error(f"代理租用已失效: {lease_id}")
                return None
            
            # 查找代理池和代理
            if lease.proxy_pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {lease.proxy_pool_id}")
                return None
            
            proxy_pool = self.proxy_pools[lease.proxy_pool_id]
            proxy_item = next((p for p in proxy_pool.proxies if p.id == lease.proxy_id), None)
            
            if not proxy_item:
                self.logger.error(f"代理不存在: {lease.proxy_id}")
                return None
            
            # 返回代理信息
            return {
                'id': proxy_item.id,
                'ip': proxy_item.ip,
                'port': proxy_item.port,
                'protocol': proxy_item.protocol,
                'username': proxy_item.username,
                'password': proxy_item.password,
                'url': proxy_item.url,
                'status': proxy_item.status,
                'response_time': proxy_item.response_time,
                'score': proxy_item.score,
                'location': proxy_item.location,
                'isp': proxy_item.isp,
                'anonymity': proxy_item.anonymity
            }
    
    async def batch_add_proxies(self, pool_id: str, proxies_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加代理到代理池
        Args:
            pool_id: 代理池ID
            proxies_data: 代理数据列表
        Returns:
            Dict[str, Any]: 添加结果统计
        """
        stats = {
            'total': len(proxies_data),
            'success': 0,
            'failed': 0,
            'errors': []
        }
        
        for proxy_data in proxies_data:
            try:
                # 添加时间戳
                if 'created_at' not in proxy_data:
                    proxy_data['created_at'] = datetime.now(timezone.utc)
                if 'updated_at' not in proxy_data:
                    proxy_data['updated_at'] = datetime.now(timezone.utc)
                
                # 添加代理
                result = await self.add_proxy(pool_id, proxy_data)
                if result:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"添加代理失败: {proxy_data.get('ip', 'unknown')}:{proxy_data.get('port', 'unknown')}")
            except Exception as e:
                stats['failed'] += 1
                stats['errors'].append(f"添加代理异常: {str(e)}")
        
        self.logger.info(f"批量添加代理完成: {stats['success']} 成功, {stats['failed']} 失败")
        return stats
    
    async def get_proxy_pool_stats(self, pool_id: str) -> Optional[Dict[str, Any]]:
        """获取代理池统计信息
        Args:
            pool_id: 代理池ID
        Returns:
            Dict[str, Any]: 统计信息字典或None
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return None
            
            proxy_pool = self.proxy_pools[pool_id]
            
            # 统计各状态的代理数量
            status_counts = {
                ProxyStatus.VALID: 0,
                ProxyStatus.WARNING: 0,
                ProxyStatus.INVALID: 0,
                ProxyStatus.PENDING: 0,
                ProxyStatus.BLACKLISTED: 0
            }
            
            # 统计各类型的代理数量
            type_counts = {
                ProxyType.HTTP: 0,
                ProxyType.HTTPS: 0,
                ProxyType.SOCKS5: 0,
                ProxyType.SOCKS4: 0
            }
            
            # 计算平均响应时间和平均分数
            total_response_time = 0
            total_score = 0
            valid_proxies_count = 0
            
            for proxy in proxy_pool.proxies:
                status_counts[proxy.status] += 1
                if proxy.protocol in type_counts:
                    type_counts[proxy.protocol] += 1
                
                # 计算平均响应时间和平均分数（只考虑VALID状态的代理）
                if proxy.status == ProxyStatus.VALID and proxy.response_time > 0:
                    total_response_time += proxy.response_time
                    total_score += proxy.score
                    valid_proxies_count += 1
            
            # 计算平均响应时间和平均分数
            avg_response_time = total_response_time / valid_proxies_count if valid_proxies_count > 0 else 0
            avg_score = total_score / valid_proxies_count if valid_proxies_count > 0 else 0
            
            # 统计活跃的租用数量
            active_leases = 0
            for lease in self.proxy_leases.values():
                if lease.proxy_pool_id == pool_id and lease.is_active:
                    active_leases += 1
            
            return {
                'pool_id': pool_id,
                'pool_name': proxy_pool.name,
                'total_proxies': proxy_pool.total_proxy_count,
                'status_counts': status_counts,
                'type_counts': type_counts,
                'active_leases': active_leases,
                'avg_response_time': round(avg_response_time, 3),
                'avg_score': round(avg_score, 3),
                'created_at': proxy_pool.created_at,
                'updated_at': proxy_pool.updated_at
            }
    
    async def refresh_all_proxies(self, pool_id: str) -> Dict[str, Any]:
        """刷新代理池中的所有代理
        Args:
            pool_id: 代理池ID
        Returns:
            Dict[str, Any]: 刷新结果统计
        """
        async with self.pool_lock:
            if pool_id not in self.proxy_pools:
                self.logger.error(f"代理池不存在: {pool_id}")
                return {'success': False, 'error': '代理池不存在'}
            
            proxy_pool = self.proxy_pools[pool_id]
            
            # 只对非活跃租用的代理进行刷新
            refreshable_proxies = []
            for proxy in proxy_pool.proxies:
                if not self._is_proxy_leased(proxy.id):
                    refreshable_proxies.append(proxy)
            
            self.logger.info(f"开始刷新代理池中的代理: {pool_id}, 共 {len(refreshable_proxies)} 个代理可刷新")
            
            # 异步刷新每个代理
            tasks = []
            for proxy in refreshable_proxies:
                tasks.append(self._check_proxy_health(proxy, proxy_pool))
            
            # 执行刷新任务（限制并发数为5，避免过多请求）
            chunk_size = 5
            for i in range(0, len(tasks), chunk_size):
                chunk = tasks[i:i+chunk_size]
                await asyncio.gather(*chunk, return_exceptions=True)
                # 每批次之间等待一段时间
                await asyncio.sleep(1)
            
            # 保存更新后的代理池
            await self._save_proxy_pools_to_storage()
            
            # 返回刷新结果
            stats = await self.get_proxy_pool_stats(pool_id)
            
            self.logger.info(f"代理池刷新完成: {pool_id}")
            return {
                'success': True,
                'stats': stats
            }
    
    async def _auto_refresh_proxies(self):
        """自动刷新代理池（从外部源获取新代理）"""
        self.logger.info("启动自动刷新代理任务")
        
        # 这是一个示例实现，实际使用时需要根据具体的代理源进行调整
        # 在实际应用中，可以从公开的代理API、爬虫等获取新的代理
        
        # 目前只是一个占位实现，实际应用中需要替换为真实的代理源获取逻辑
        while True:
            try:
                # 每小时尝试刷新一次代理
                await asyncio.sleep(3600)
                
                self.logger.info("执行自动刷新代理任务")
                
                # 这里应该是从代理源获取新代理的代码
                # 例如：
                # new_proxies = await self._fetch_proxies_from_source()
                # if new_proxies:
                #     for pool_id in self.proxy_pools:
                #         if self.proxy_pools[pool_id].type == ProxyPoolType.PUBLIC:
                #             await self.batch_add_proxies(pool_id, new_proxies)
                
            except Exception as e:
                self.logger.error(f"自动刷新代理任务异常: {str(e)}")
                # 出错后等待一段时间再继续
                await asyncio.sleep(60)
    
    async def blacklist_proxy(self, pool_id: str, proxy_id: str, reason: str = '') -> bool:
        """将代理加入黑名单
        Args:
            pool_id: 代理池ID
            proxy_id: 代理ID
            reason: 黑名单原因
        Returns:
            bool: 是否加入黑名单成功
        """
        # 更新代理状态为黑名单
        updates = {
            'status': ProxyStatus.BLACKLISTED,
            'blacklist_reason': reason
        }
        
        result = await self.update_proxy(pool_id, proxy_id, updates)
        
        if result:
            self.logger.info(f"代理已加入黑名单: {proxy_id} -> {pool_id}, 原因: {reason}")
            return True
        else:
            self.logger.error(f"将代理加入黑名单失败: {proxy_id} -> {pool_id}")
            return False
    
    async def whitelist_proxy(self, pool_id: str, proxy_id: str) -> bool:
        """将代理从黑名单中移除
        Args:
            pool_id: 代理池ID
            proxy_id: 代理ID
        Returns:
            bool: 是否移除成功
        """
        # 更新代理状态为待验证
        updates = {
            'status': ProxyStatus.PENDING,
            'blacklist_reason': None
        }
        
        result = await self.update_proxy(pool_id, proxy_id, updates)
        
        if result:
            self.logger.info(f"代理已从黑名单中移除: {proxy_id} -> {pool_id}")
            return True
        else:
            self.logger.error(f"将代理从黑名单中移除失败: {proxy_id} -> {pool_id}")
            return False
    
    async def shutdown(self):
        """关闭代理管理器"""
        # 保存代理池
        await self._save_proxy_pools_to_storage()
        
        # 释放所有活跃的代理租用
        for lease_id in list(self.proxy_leases.keys()):
            lease = self.proxy_leases[lease_id]
            if lease.is_active:
                await self.release_proxy(lease_id)
        
        self.logger.info("代理管理器已关闭")