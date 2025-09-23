"""
缓存模块 - 提供不同的缓存后端支持
"""

import os
import json
import asyncio
import pickle
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Union, Callable
import aiofiles

from smart_spider.utils.logger import get_logger


class CacheBackend(ABC):
    """缓存后端抽象基类"""
    
    @abstractmethod
    async def get(self, key: str, default: Any = None) -> Any:
        """获取缓存项"""
        pass
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存项"""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除缓存项"""
        pass
    
    @abstractmethod
    async def clear(self) -> bool:
        """清空缓存"""
        pass
    
    @abstractmethod
    async def has(self, key: str) -> bool:
        """检查缓存项是否存在"""
        pass
    
    @abstractmethod
    async def keys(self) -> List[str]:
        """获取所有缓存键"""
        pass
    
    @abstractmethod
    async def size(self) -> int:
        """获取缓存项数量"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """关闭缓存连接"""
        pass


class MemoryCacheBackend(CacheBackend):
    """内存缓存后端"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化内存缓存
        Args:
            config: 缓存配置，包含最大大小、默认TTL等
        """
        config = config or {}
        self.max_size = config.get('max_size', 1000)
        self.default_ttl = config.get('default_ttl', 3600)  # 默认1小时
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.logger = get_logger(__name__)
        self.logger.info(f"初始化内存缓存: 最大大小={self.max_size}, 默认TTL={self.default_ttl}秒")
    
    async def get(self, key: str, default: Any = None) -> Any:
        """获取缓存项
        Args:
            key: 缓存键
            default: 缓存项不存在时返回的默认值
        Returns:
            Any: 缓存值或默认值
        """
        if key not in self._cache:
            return default
        
        cache_item = self._cache[key]
        expire_at = cache_item['expire_at']
        
        # 检查是否过期
        if expire_at and datetime.now() > expire_at:
            await self.delete(key)
            return default
        
        self.logger.debug(f"从缓存获取: {key}")
        return cache_item['value']
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存项
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 缓存过期时间（秒），None表示永不过期
        Returns:
            bool: 是否设置成功
        """
        try:
            # 如果缓存已满，尝试清理过期项
            if len(self._cache) >= self.max_size and key not in self._cache:
                await self._cleanup_expired()
                
                # 如果清理后仍然已满，删除最早添加的项
                if len(self._cache) >= self.max_size:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]['created_at'])
                    await self.delete(oldest_key)
            
            # 计算过期时间
            expire_at = None
            if ttl is None:
                ttl = self.default_ttl
            if ttl > 0:
                expire_at = datetime.now() + timedelta(seconds=ttl)
            
            # 存储缓存项
            self._cache[key] = {
                'value': value,
                'created_at': datetime.now(),
                'expire_at': expire_at
            }
            
            self.logger.debug(f"设置缓存: {key}, TTL={ttl}秒")
            return True
        except Exception as e:
            self.logger.error(f"设置缓存失败: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """删除缓存项
        Args:
            key: 缓存键
        Returns:
            bool: 是否删除成功
        """
        if key in self._cache:
            del self._cache[key]
            self.logger.debug(f"删除缓存: {key}")
            return True
        self.logger.warning(f"缓存项不存在: {key}")
        return False
    
    async def clear(self) -> bool:
        """清空缓存
        Returns:
            bool: 是否清空成功
        """
        try:
            self._cache.clear()
            self.logger.debug("清空所有缓存")
            return True
        except Exception as e:
            self.logger.error(f"清空缓存失败: {str(e)}")
            return False
    
    async def has(self, key: str) -> bool:
        """检查缓存项是否存在
        Args:
            key: 缓存键
        Returns:
            bool: 缓存项是否存在且未过期
        """
        if key not in self._cache:
            return False
        
        cache_item = self._cache[key]
        expire_at = cache_item['expire_at']
        
        # 检查是否过期
        if expire_at and datetime.now() > expire_at:
            await self.delete(key)
            return False
        
        return True
    
    async def keys(self) -> List[str]:
        """获取所有缓存键
        Returns:
            List[str]: 缓存键列表
        """
        # 在返回前清理过期项
        await self._cleanup_expired()
        return list(self._cache.keys())
    
    async def size(self) -> int:
        """获取缓存项数量
        Returns:
            int: 缓存项数量
        """
        # 在返回前清理过期项
        await self._cleanup_expired()
        return len(self._cache)
    
    async def close(self) -> None:
        """关闭缓存连接（内存缓存不需要关闭连接）"""
        pass
    
    async def _cleanup_expired(self) -> int:
        """清理过期的缓存项
        Returns:
            int: 清理的缓存项数量
        """
        now = datetime.now()
        expired_keys = []
        
        # 预先收集所有过期键，避免在迭代过程中修改字典
        for key, item in list(self._cache.items()):
            if item['expire_at'] and now > item['expire_at']:
                expired_keys.append(key)
        
        # 一次性删除所有过期键（使用直接删除而不是调用delete方法以提高性能）
        for key in expired_keys:
            if key in self._cache:  # 再次检查，以防在收集过程中被其他操作删除
                del self._cache[key]
                self.logger.debug(f"删除过期缓存: {key}")
        
        if expired_keys:
            self.logger.debug(f"清理了 {len(expired_keys)} 个过期缓存项")
        
        return len(expired_keys)


class FileCacheBackend(CacheBackend):
    """文件缓存后端"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化文件缓存
        Args:
            config: 缓存配置，包含路径、默认TTL等
        """
        self.path = config.get('path', '.cache')
        self.default_ttl = config.get('default_ttl', 3600)  # 默认1小时
        self.serializer = config.get('serializer', 'pickle')  # pickle 或 json
        self.logger = get_logger(__name__)
        
        # 确保缓存目录存在
        os.makedirs(self.path, exist_ok=True)
        
        self.logger.info(f"初始化文件缓存: 路径={self.path}, 默认TTL={self.default_ttl}秒, 序列化方式={self.serializer}")
    
    async def get(self, key: str, default: Any = None) -> Any:
        """获取缓存项
        Args:
            key: 缓存键
            default: 缓存项不存在时返回的默认值
        Returns:
            Any: 缓存值或默认值
        """
        filepath = self._get_cache_filepath(key)
        
        if not os.path.exists(filepath):
            return default
        
        try:
            # 读取缓存文件
            if self.serializer == 'json':
                async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    cache_item = json.loads(content)
            else:  # pickle
                async with aiofiles.open(filepath, 'rb') as f:
                    content = await f.read()
                    cache_item = pickle.loads(content)
            
            # 检查是否过期
            expire_at = cache_item.get('expire_at')
            if expire_at:
                expire_datetime = datetime.fromisoformat(expire_at)
                if datetime.now() > expire_datetime:
                    await self.delete(key)
                    return default
            
            self.logger.debug(f"从文件缓存获取: {key}")
            return cache_item['value']
        except Exception as e:
            self.logger.error(f"读取文件缓存失败: {str(e)}")
            # 尝试删除损坏的缓存文件
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except:
                pass
            return default
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存项
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 缓存过期时间（秒），None表示永不过期
        Returns:
            bool: 是否设置成功
        """
        try:
            # 计算过期时间
            expire_at = None
            if ttl is None:
                ttl = self.default_ttl
            if ttl > 0:
                expire_at = (datetime.now() + timedelta(seconds=ttl)).isoformat()
            
            # 构建缓存项
            cache_item = {
                'value': value,
                'created_at': datetime.now().isoformat(),
                'expire_at': expire_at
            }
            
            # 写入缓存文件
            filepath = self._get_cache_filepath(key)
            
            if self.serializer == 'json':
                # JSON序列化不支持所有Python对象，尝试转换
                try:
                    async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(cache_item, ensure_ascii=False, default=str))
                except TypeError:
                    self.logger.warning(f"JSON序列化失败，使用pickle代替: {key}")
                    async with aiofiles.open(filepath, 'rb+') as f:
                        await f.write(pickle.dumps(cache_item))
            else:  # pickle
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(pickle.dumps(cache_item))
            
            self.logger.debug(f"设置文件缓存: {key}, TTL={ttl}秒")
            return True
        except Exception as e:
            self.logger.error(f"设置文件缓存失败: {str(e)}")
            return False
    
    async def delete(self, key: str) -> bool:
        """删除缓存项
        Args:
            key: 缓存键
        Returns:
            bool: 是否删除成功
        """
        filepath = self._get_cache_filepath(key)
        
        if not os.path.exists(filepath):
            self.logger.warning(f"文件缓存不存在: {key}")
            return True
        
        try:
            os.remove(filepath)
            self.logger.debug(f"删除文件缓存: {key}")
            return True
        except Exception as e:
            self.logger.error(f"删除文件缓存失败: {str(e)}")
            return False
    
    async def clear(self) -> bool:
        """清空缓存
        Returns:
            bool: 是否清空成功
        """
        try:
            for filename in os.listdir(self.path):
                filepath = os.path.join(self.path, filename)
                if os.path.isfile(filepath):
                    os.remove(filepath)
            
            self.logger.debug("清空所有文件缓存")
            return True
        except Exception as e:
            self.logger.error(f"清空文件缓存失败: {str(e)}")
            return False
    
    async def has(self, key: str) -> bool:
        """检查缓存项是否存在
        Args:
            key: 缓存键
        Returns:
            bool: 缓存项是否存在且未过期
        """
        filepath = self._get_cache_filepath(key)
        
        if not os.path.exists(filepath):
            return False
        
        try:
            # 快速检查文件是否过期（仅读取元数据）
            if self.serializer == 'json':
                async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    cache_item = json.loads(content)
            else:  # pickle
                async with aiofiles.open(filepath, 'rb') as f:
                    content = await f.read()
                    cache_item = pickle.loads(content)
            
            expire_at = cache_item.get('expire_at')
            if expire_at:
                expire_datetime = datetime.fromisoformat(expire_at)
                if datetime.now() > expire_datetime:
                    await self.delete(key)
                    return False
            
            return True
        except Exception as e:
            self.logger.error(f"检查文件缓存失败: {str(e)}")
            return False
    
    async def keys(self) -> List[str]:
        """获取所有缓存键
        Returns:
            List[str]: 缓存键列表
        """
        try:
            keys = []
            for filename in os.listdir(self.path):
                # 文件名格式: cache_{hash}.{ext}
                if filename.startswith('cache_'):
                    # 注意：由于我们使用哈希值作为文件名，无法直接还原原始键
                    # 这里我们返回哈希值作为键的标识
                    # 实际应用中，可能需要维护一个键到哈希值的映射表
                    key_hash = filename[6:].split('.')[0]  # 获取哈希部分（去掉扩展名）
                    # 由于我们无法获取原始键，我们使用哈希值作为标识
                    # 但我们仍然需要检查文件是否过期
                    filepath = os.path.join(self.path, filename)
                    try:
                        # 快速检查文件是否过期
                        if self.serializer == 'json':
                            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                                content = await f.readline()  # 只读取第一行检查格式
                                if content and content.startswith('{'):
                                    keys.append(f"hash_{key_hash}")
                        else:  # pickle格式无法快速检查，直接添加
                            keys.append(f"hash_{key_hash}")
                    except:
                        pass
            return keys
        except Exception as e:
            self.logger.error(f"获取文件缓存键失败: {str(e)}")
            return []
    
    async def size(self) -> int:
        """获取缓存项数量
        Returns:
            int: 缓存项数量
        """
        try:
            count = 0
            for filename in os.listdir(self.path):
                if filename.startswith('cache_') and filename.endswith(('.json', '.pkl')):
                    filepath = os.path.join(self.path, filename)
                    if os.path.isfile(filepath):
                        # 获取哈希值作为临时键
                        key_hash = filename[6:].split('.')[0]
                        # 使用临时键检查文件是否过期
                        # 注意：由于我们无法获取原始键，这里只是一个近似检查
                        try:
                            if self.serializer == 'json':
                                async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                                    content = await f.read()
                                    cache_item = json.loads(content)
                                    expire_at = cache_item.get('expire_at')
                                    if not expire_at or datetime.now() <= datetime.fromisoformat(expire_at):
                                        count += 1
                            else:  # pickle格式我们无法快速检查，直接计数
                                count += 1
                        except:
                            # 如果读取失败，可能是损坏的文件，不计入
                            pass
            return count
        except Exception as e:
            self.logger.error(f"获取文件缓存大小失败: {str(e)}")
            return 0
    
    async def close(self) -> None:
        """关闭缓存连接（文件缓存不需要关闭连接）"""
        pass
    
    def _get_cache_filepath(self, key: str) -> str:
        """获取缓存文件路径
        Args:
            key: 缓存键
        Returns:
            str: 缓存文件路径
        """
        # 为了安全和避免文件名冲突，我们对键进行哈希处理
        import hashlib
        key_hash = hashlib.md5(key.encode('utf-8')).hexdigest()
        ext = 'json' if self.serializer == 'json' else 'pkl'
        return os.path.join(self.path, f'cache_{key_hash}.{ext}')


class CacheManager:
    """缓存管理器，负责创建和管理不同的缓存后端"""
    
    _cache_backends = {
        'memory': MemoryCacheBackend,
        'file': FileCacheBackend
    }
    
    @staticmethod
    def create_cache(config: Dict[str, Any]) -> CacheBackend:
        """创建缓存后端实例
        Args:
            config: 缓存配置，包含类型、路径等
        Returns:
            CacheBackend: 缓存后端实例
        """
        cache_type = config.get('type', 'memory')
        
        if cache_type not in CacheManager._cache_backends:
            raise ValueError(f"不支持的缓存类型: {cache_type}")
        
        backend_class = CacheManager._cache_backends[cache_type]
        return backend_class(config)
    
    @staticmethod
    def register_cache(cache_type: str, backend_class: type) -> None:
        """注册新的缓存后端
        Args:
            cache_type: 缓存类型名称
            backend_class: 缓存后端类
        """
        if not issubclass(backend_class, CacheBackend):
            raise TypeError("缓存后端必须是CacheBackend的子类")
        
        CacheManager._cache_backends[cache_type] = backend_class
    
    @staticmethod
    def get_supported_types() -> List[str]:
        """获取支持的缓存类型列表
        Returns:
            List[str]: 支持的缓存类型列表
        """
        return list(CacheManager._cache_backends.keys())


# 创建全局缓存实例
_cache_instances: Dict[str, CacheBackend] = {}


def get_cache(name: str = 'default', config: Dict[str, Any] = None) -> CacheBackend:
    """获取缓存实例（单例模式）
    Args:
        name: 缓存实例名称
        config: 缓存配置
    Returns:
        CacheBackend: 缓存后端实例
    """
    global _cache_instances
    
    if name not in _cache_instances:
        config = config or {'type': 'memory'}
        _cache_instances[name] = CacheManager.create_cache(config)
        
    return _cache_instances[name]


def clear_all_caches() -> None:
    """清空所有缓存实例"""
    global _cache_instances
    
    for name, cache in list(_cache_instances.items()):
        asyncio.create_task(cache.clear())
        del _cache_instances[name]


# 缓存装饰器

def cached(ttl: Optional[int] = None, key_func: Optional[Callable] = None, 
           cache_name: str = 'default', cache_config: Optional[Dict[str, Any]] = None):
    """函数结果缓存装饰器
    Args:
        ttl: 缓存过期时间（秒）
        key_func: 自定义缓存键生成函数
        cache_name: 缓存实例名称
        cache_config: 缓存配置
    Returns:
        Callable: 装饰后的函数
    """
    def decorator(func):
        # 如果是异步函数
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                # 生成缓存键
                if key_func:
                    key = key_func(*args, **kwargs)
                else:
                    # 简单的键生成策略
                    key_parts = [func.__name__]
                    key_parts.extend(str(arg) for arg in args)
                    key_parts.extend(f"{k}={v}" for k, v in kwargs.items())
                    key = "_" .join(key_parts)
                
                # 获取缓存实例
                cache = get_cache(cache_name, cache_config)
                
                # 尝试从缓存获取
                result = await cache.get(key)
                if result is not None:
                    return result
                
                # 执行函数
                result = await func(*args, **kwargs)
                
                # 存入缓存
                await cache.set(key, result, ttl)
                
                return result
            return async_wrapper
        else:
            # 同步函数
            def sync_wrapper(*args, **kwargs):
                # 生成缓存键
                if key_func:
                    key = key_func(*args, **kwargs)
                else:
                    # 简单的键生成策略
                    key_parts = [func.__name__]
                    key_parts.extend(str(arg) for arg in args)
                    key_parts.extend(f"{k}={v}" for k, v in kwargs.items())
                    key = "_" .join(key_parts)
                
                # 获取缓存实例
                cache = get_cache(cache_name, cache_config)
                
                # 尝试从缓存获取（同步方式）
                result = None
                try:
                    # 首先尝试获取当前运行的事件循环
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # 如果事件循环正在运行，使用run_coroutine_threadsafe
                            future = asyncio.run_coroutine_threadsafe(cache.get(key), loop)
                            result = future.result()
                        else:
                            # 如果事件循环存在但未运行，直接运行
                            result = loop.run_until_complete(cache.get(key))
                    except RuntimeError:
                        # 如果没有运行中的事件循环，创建一个新的
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            result = loop.run_until_complete(cache.get(key))
                        finally:
                            loop.close()
                            asyncio.set_event_loop(None)  # 清除当前线程的事件循环引用
                except Exception as e:
                    # 如果获取缓存失败，记录错误但继续执行函数
                    pass
                
                if result is not None:
                    return result
                
                # 执行函数
                result = func(*args, **kwargs)
                
                # 存入缓存（同步方式）
                try:
                    # 首先尝试获取当前运行的事件循环
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # 如果事件循环正在运行，使用run_coroutine_threadsafe
                            future = asyncio.run_coroutine_threadsafe(cache.set(key, result, ttl), loop)
                            future.result()  # 等待完成并传播异常
                        else:
                            # 如果事件循环存在但未运行，直接运行
                            loop.run_until_complete(cache.set(key, result, ttl))
                    except RuntimeError:
                        # 如果没有运行中的事件循环，创建一个新的
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(cache.set(key, result, ttl))
                        finally:
                            loop.close()
                            asyncio.set_event_loop(None)  # 清除当前线程的事件循环引用
                except Exception as e:
                    # 如果设置缓存失败，记录错误但仍然返回函数结果
                    pass
                
                return result
            return sync_wrapper
    return decorator


# 使用示例
if __name__ == '__main__':
    # 创建内存缓存
    memory_config = {
        'type': 'memory',
        'max_size': 100,
        'default_ttl': 60
    }
    memory_cache = CacheManager.create_cache(memory_config)
    
    # 创建文件缓存
    file_config = {
        'type': 'file',
        'path': '.test_cache',
        'default_ttl': 60,
        'serializer': 'json'
    }
    file_cache = CacheManager.create_cache(file_config)
    
    # 测试内存缓存
    async def test_memory_cache():
        print("===== 测试内存缓存 =====")
        
        # 设置缓存
        await memory_cache.set('test_key', 'test_value', ttl=10)
        print("设置缓存: test_key = test_value")
        
        # 获取缓存
        value = await memory_cache.get('test_key')
        print(f"获取缓存: test_key = {value}")
        
        # 检查缓存是否存在
        exists = await memory_cache.has('test_key')
        print(f"缓存是否存在: {exists}")
        
        # 获取缓存大小
        size = await memory_cache.size()
        print(f"缓存大小: {size}")
        
        # 列出所有键
        keys = await memory_cache.keys()
        print(f"缓存键列表: {keys}")
        
        # 测试TTL
        print("等待11秒测试过期...")
        await asyncio.sleep(11)
        
        # 再次获取缓存
        expired_value = await memory_cache.get('test_key', 'default_value')
        print(f"过期后获取缓存: test_key = {expired_value}")
        
        # 检查缓存是否存在
        exists_after_ttl = await memory_cache.has('test_key')
        print(f"过期后缓存是否存在: {exists_after_ttl}")
        
        # 测试删除
        await memory_cache.set('delete_key', 'delete_value')
        print("设置缓存: delete_key = delete_value")
        
        delete_success = await memory_cache.delete('delete_key')
        print(f"删除缓存: {'成功' if delete_success else '失败'}")
        
        # 测试清空
        await memory_cache.set('clear_key1', 'clear_value1')
        await memory_cache.set('clear_key2', 'clear_value2')
        print("设置两个缓存项")
        print(f"清空前缓存大小: {await memory_cache.size()}")
        
        clear_success = await memory_cache.clear()
        print(f"清空缓存: {'成功' if clear_success else '失败'}")
        print(f"清空后缓存大小: {await memory_cache.size()}")
    
    # 测试文件缓存
    async def test_file_cache():
        print("\n===== 测试文件缓存 =====")
        
        # 设置缓存
        await file_cache.set('test_key', {'name': 'test_value', 'number': 123}, ttl=10)
        print("设置文件缓存: test_key = {name: 'test_value', number: 123}")
        
        # 获取缓存
        value = await file_cache.get('test_key')
        print(f"获取文件缓存: test_key = {value}")
        
        # 检查缓存是否存在
        exists = await file_cache.has('test_key')
        print(f"文件缓存是否存在: {exists}")
        
        # 获取缓存大小
        size = await file_cache.size()
        print(f"文件缓存大小: {size}")
        
        # 测试删除
        delete_success = await file_cache.delete('test_key')
        print(f"删除文件缓存: {'成功' if delete_success else '失败'}")
        
        # 测试清空
        await file_cache.set('clear_key1', 'clear_value1')
        await file_cache.set('clear_key2', 'clear_value2')
        print("设置两个文件缓存项")
        print(f"清空前文件缓存大小: {await file_cache.size()}")
        
        clear_success = await file_cache.clear()
        print(f"清空文件缓存: {'成功' if clear_success else '失败'}")
        print(f"清空后文件缓存大小: {await file_cache.size()}")
    
    # 测试缓存装饰器
    async def test_cache_decorator():
        print("\n===== 测试缓存装饰器 =====")
        
        # 定义一个测试函数
        @cached(ttl=5)
        async def expensive_operation(param):
            print(f"执行昂贵操作，参数: {param}")
            await asyncio.sleep(1)  # 模拟耗时操作
            return f"结果_{param}_{datetime.now().strftime('%H%M%S')}"
        
        # 第一次调用（应该执行函数）
        start_time = datetime.now()
        result1 = await expensive_operation('test')
        end_time = datetime.now()
        print(f"第一次调用结果: {result1}")
        print(f"第一次调用耗时: {(end_time - start_time).total_seconds()}秒")
        
        # 第二次调用（应该使用缓存）
        start_time = datetime.now()
        result2 = await expensive_operation('test')
        end_time = datetime.now()
        print(f"第二次调用结果: {result2}")
        print(f"第二次调用耗时: {(end_time - start_time).total_seconds()}秒")
        
        # 不同参数的调用（应该执行函数）
        start_time = datetime.now()
        result3 = await expensive_operation('different')
        end_time = datetime.now()
        print(f"不同参数调用结果: {result3}")
        print(f"不同参数调用耗时: {(end_time - start_time).total_seconds()}秒")
        
        # 等待缓存过期
        print("等待6秒测试缓存过期...")
        await asyncio.sleep(6)
        
        # 过期后调用（应该执行函数）
        start_time = datetime.now()
        result4 = await expensive_operation('test')
        end_time = datetime.now()
        print(f"过期后调用结果: {result4}")
        print(f"过期后调用耗时: {(end_time - start_time).total_seconds()}秒")
    
    # 运行测试
    async def run_tests():
        await test_memory_cache()
        await test_file_cache()
        await test_cache_decorator()
    
    # 运行异步测试
    import asyncio
    asyncio.run(run_tests())