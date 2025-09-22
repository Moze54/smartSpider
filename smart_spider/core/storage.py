"""
存储模块 - 提供不同的存储后端支持
"""

import os
import json
import asyncio
import csv
import pickle
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Iterator, Union
import aiofiles

from smart_spider.utils.logger import get_logger


class StorageBackend(ABC):
    """存储后端抽象基类"""
    
    @abstractmethod
    async def save(self, data: Any, **kwargs) -> bool:
        """保存数据到存储后端"""
        pass
    
    @abstractmethod
    async def get(self, **kwargs) -> Any:
        """从存储后端获取数据"""
        pass
    
    @abstractmethod
    async def delete(self, **kwargs) -> bool:
        """从存储后端删除数据"""
        pass
    
    @abstractmethod
    async def list_items(self, **kwargs) -> List[Dict[str, Any]]:
        """列出存储中的所有项"""
        pass
    
    @abstractmethod
    async def count(self, **kwargs) -> int:
        """统计存储中的项数量"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """关闭存储连接"""
        pass


class FileSystemStorage(StorageBackend):
    """文件系统存储后端"""
    
    def __init__(self, config: Dict[str, Any]):
        """初始化文件系统存储
        Args:
            config: 存储配置，包含路径、格式等
        """
        self.path = config.get('path', 'data')
        self.format = config.get('format', 'jsonl')  # jsonl, json, csv, pickle
        self.logger = get_logger(__name__)
        
        # 确保存储目录存在
        os.makedirs(self.path, exist_ok=True)
        
        self.logger.info(f"初始化文件系统存储: 路径={self.path}, 格式={self.format}")
    
    async def save(self, data: Any, **kwargs) -> bool:
        """保存数据到文件
        Args:
            data: 要保存的数据，可以是字典或字典列表
            **kwargs:
                filename: 文件名，如果不提供则使用默认名称
                overwrite: 是否覆盖现有文件
                append: 是否追加到现有文件（仅对jsonl格式有效）
        Returns:
            bool: 是否保存成功
        """
        filename = kwargs.get('filename', self._get_default_filename())
        filepath = os.path.join(self.path, filename)
        overwrite = kwargs.get('overwrite', False)
        append = kwargs.get('append', True) if self.format == 'jsonl' else False
        
        try:
            # 确保数据是列表格式
            if not isinstance(data, list):
                data = [data]
            
            # 验证每个数据项是否为字典
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError(f"数据必须是字典格式，当前类型: {type(item)}")
            
            mode = 'w' if overwrite else ('a' if append else 'w')
            
            if self.format == 'jsonl':
                await self._save_jsonl(filepath, data, mode)
            elif self.format == 'json':
                await self._save_json(filepath, data, mode, overwrite)
            elif self.format == 'csv':
                await self._save_csv(filepath, data, mode, overwrite)
            elif self.format == 'pickle':
                await self._save_pickle(filepath, data, mode, overwrite)
            else:
                raise ValueError(f"不支持的存储格式: {self.format}")
            
            self.logger.debug(f"成功保存数据到文件: {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"保存数据到文件失败: {str(e)}")
            return False
    
    async def _save_jsonl(self, filepath: str, data: List[Dict[str, Any]], mode: str) -> None:
        """保存数据为JSON Lines格式"""
        async with aiofiles.open(filepath, mode, encoding='utf-8') as f:
            for item in data:
                await f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    async def _save_json(self, filepath: str, data: List[Dict[str, Any]], 
                        mode: str, overwrite: bool) -> None:
        """保存数据为JSON格式"""
        # 如果是追加模式且文件存在，读取现有数据
        existing_data = []
        if mode == 'a' and os.path.exists(filepath):
            try:
                async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    existing_data = json.loads(content) if content.strip() else []
            except Exception as e:
                self.logger.warning(f"读取现有JSON文件失败，将创建新文件: {str(e)}")
        
        # 合并数据
        if overwrite:
            merged_data = data
        else:
            merged_data = existing_data + data
        
        # 写入文件
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(merged_data, ensure_ascii=False, indent=2))
    
    async def _save_csv(self, filepath: str, data: List[Dict[str, Any]], 
                       mode: str, overwrite: bool) -> None:
        """保存数据为CSV格式"""
        if not data:
            return
        
        # 确定CSV的字段名（使用第一个数据项的键）
        fieldnames = list(data[0].keys())
        
        # 如果是追加模式且文件存在，检查字段名是否一致
        if mode == 'a' and os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    existing_fieldnames = reader.fieldnames or []
                    if existing_fieldnames and existing_fieldnames != fieldnames:
                        self.logger.warning(f"CSV字段名不匹配，将创建新文件")
                        mode = 'w'
            except Exception as e:
                self.logger.warning(f"读取现有CSV文件失败，将创建新文件: {str(e)}")
                mode = 'w'
        
        # 写入文件
        async with aiofiles.open(filepath, mode, encoding='utf-8', newline='') as f:
            # 在追加模式下，如果文件为空，需要写入表头
            if mode == 'a' and os.path.getsize(filepath) == 0:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                await writer.writeheader()
            elif mode == 'w':
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                await writer.writeheader()
                for item in data:
                    # 确保每个项目都有所有字段
                    row = {field: item.get(field, '') for field in fieldnames}
                    await writer.writerow(row)
            else:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                for item in data:
                    # 确保每个项目都有所有字段
                    row = {field: item.get(field, '') for field in fieldnames}
                    await writer.writerow(row)
    
    async def _save_pickle(self, filepath: str, data: List[Dict[str, Any]], 
                          mode: str, overwrite: bool) -> None:
        """保存数据为pickle格式"""
        # 如果是追加模式且文件存在，读取现有数据
        existing_data = []
        if mode == 'a' and os.path.exists(filepath):
            try:
                async with aiofiles.open(filepath, 'rb') as f:
                    content = await f.read()
                    existing_data = pickle.loads(content) if content else []
            except Exception as e:
                self.logger.warning(f"读取现有pickle文件失败，将创建新文件: {str(e)}")
        
        # 合并数据
        if overwrite:
            merged_data = data
        else:
            merged_data = existing_data + data
        
        # 写入文件
        async with aiofiles.open(filepath, 'wb') as f:
            await f.write(pickle.dumps(merged_data))
    
    async def get(self, **kwargs) -> Any:
        """从文件获取数据
        Args:
            **kwargs:
                filename: 文件名
                item_id: 项目ID（如果数据是字典列表且有id字段）
        Returns:
            Any: 获取的数据或None
        """
        filename = kwargs.get('filename')
        if not filename:
            self.logger.error("获取数据时必须提供文件名")
            return None
        
        filepath = os.path.join(self.path, filename)
        item_id = kwargs.get('item_id')
        
        try:
            if not os.path.exists(filepath):
                self.logger.warning(f"文件不存在: {filepath}")
                return None
            
            if self.format == 'jsonl':
                data = await self._read_jsonl(filepath)
            elif self.format == 'json':
                data = await self._read_json(filepath)
            elif self.format == 'csv':
                data = await self._read_csv(filepath)
            elif self.format == 'pickle':
                data = await self._read_pickle(filepath)
            else:
                raise ValueError(f"不支持的存储格式: {self.format}")
            
            # 如果指定了item_id，返回特定项
            if item_id and isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('id') == item_id:
                        return item
                self.logger.warning(f"未找到ID为 {item_id} 的项目")
                return None
            
            return data
        except Exception as e:
            self.logger.error(f"读取文件数据失败: {str(e)}")
            return None
    
    async def _read_jsonl(self, filepath: str) -> List[Dict[str, Any]]:
        """读取JSON Lines格式文件"""
        data = []
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            async for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
        return data
    
    async def _read_json(self, filepath: str) -> Any:
        """读取JSON格式文件"""
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content) if content.strip() else []
    
    async def _read_csv(self, filepath: str) -> List[Dict[str, Any]]:
        """读取CSV格式文件"""
        data = []
        try:
            # CSV模块不支持异步读取，所以使用线程池执行
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._read_csv_sync, filepath)
        except Exception as e:
            self.logger.error(f"读取CSV文件失败: {str(e)}")
        return data
    
    def _read_csv_sync(self, filepath: str) -> List[Dict[str, Any]]:
        """同步读取CSV文件的辅助函数"""
        data = []
        with open(filepath, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(dict(row))
        return data
    
    async def _read_pickle(self, filepath: str) -> Any:
        """读取pickle格式文件"""
        async with aiofiles.open(filepath, 'rb') as f:
            content = await f.read()
            return pickle.loads(content) if content else []
    
    async def delete(self, **kwargs) -> bool:
        """删除文件或文件中的特定项目
        Args:
            **kwargs:
                filename: 文件名
                item_id: 项目ID（如果数据是字典列表且有id字段）
        Returns:
            bool: 是否删除成功
        """
        filename = kwargs.get('filename')
        if not filename:
            self.logger.error("删除数据时必须提供文件名")
            return False
        
        filepath = os.path.join(self.path, filename)
        item_id = kwargs.get('item_id')
        
        try:
            if not os.path.exists(filepath):
                self.logger.warning(f"文件不存在: {filepath}")
                return True  # 认为删除成功
            
            # 如果指定了item_id，只删除特定项
            if item_id:
                data = await self.get(filename=filename)
                if data and isinstance(data, list):
                    new_data = [item for item in data if not (isinstance(item, dict) and item.get('id') == item_id)]
                    if len(new_data) < len(data):
                        await self.save(new_data, filename=filename, overwrite=True)
                        self.logger.debug(f"成功删除ID为 {item_id} 的项目")
                        return True
                    else:
                        self.logger.warning(f"未找到ID为 {item_id} 的项目")
                        return True
            
            # 否则删除整个文件
            os.remove(filepath)
            self.logger.debug(f"成功删除文件: {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"删除文件失败: {str(e)}")
            return False
    
    async def list_items(self, **kwargs) -> List[Dict[str, Any]]:
        """列出存储中的所有项
        Args:
            **kwargs:
                filename: 文件名（可选，如果不提供则列出所有文件）
        Returns:
            List[Dict[str, Any]]: 项目列表或文件列表
        """
        filename = kwargs.get('filename')
        
        if filename:
            # 列出特定文件中的所有项
            data = await self.get(filename=filename)
            if data is None:
                return []
            if not isinstance(data, list):
                data = [data]
            return data
        else:
            # 列出所有文件
            try:
                files = []
                for f in os.listdir(self.path):
                    filepath = os.path.join(self.path, f)
                    if os.path.isfile(filepath):
                        stat = os.stat(filepath)
                        files.append({
                            'name': f,
                            'path': filepath,
                            'size': stat.st_size,
                            'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
                return files
            except Exception as e:
                self.logger.error(f"列出文件失败: {str(e)}")
                return []
    
    async def count(self, **kwargs) -> int:
        """统计存储中的项数量
        Args:
            **kwargs:
                filename: 文件名（可选，如果不提供则统计所有文件）
        Returns:
            int: 项数量
        """
        filename = kwargs.get('filename')
        
        if filename:
            # 统计特定文件中的项数量
            data = await self.get(filename=filename)
            if data is None:
                return 0
            if isinstance(data, list):
                return len(data)
            else:
                return 1
        else:
            # 统计所有文件数量
            try:
                return len([f for f in os.listdir(self.path) if os.path.isfile(os.path.join(self.path, f))])
            except Exception as e:
                self.logger.error(f"统计文件数量失败: {str(e)}")
                return 0
    
    async def close(self) -> None:
        """关闭存储连接（文件系统存储不需要关闭连接）"""
        pass
    
    def _get_default_filename(self) -> str:
        """生成默认文件名"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f'data_{timestamp}.{self.format}'


class MemoryStorage(StorageBackend):
    """内存存储后端（用于测试和临时数据）"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """初始化内存存储"""
        self.data = {}
        self.logger = get_logger(__name__)
        self.logger.info("初始化内存存储")
    
    async def save(self, data: Any, **kwargs) -> bool:
        """保存数据到内存
        Args:
            data: 要保存的数据
            **kwargs:
                key: 数据的键
                overwrite: 是否覆盖现有数据
        Returns:
            bool: 是否保存成功
        """
        key = kwargs.get('key')
        if not key:
            self.logger.error("保存数据时必须提供键")
            return False
        
        overwrite = kwargs.get('overwrite', True)
        
        try:
            if key in self.data and not overwrite:
                self.logger.warning(f"键 '{key}' 已存在，不覆盖现有数据")
                return False
            
            self.data[key] = data
            self.logger.debug(f"成功保存数据到内存: {key}")
            return True
        except Exception as e:
            self.logger.error(f"保存数据到内存失败: {str(e)}")
            return False
    
    async def get(self, **kwargs) -> Any:
        """从内存获取数据
        Args:
            **kwargs:
                key: 数据的键
        Returns:
            Any: 获取的数据或None
        """
        key = kwargs.get('key')
        if not key:
            self.logger.error("获取数据时必须提供键")
            return None
        
        return self.data.get(key)
    
    async def delete(self, **kwargs) -> bool:
        """从内存删除数据
        Args:
            **kwargs:
                key: 数据的键
        Returns:
            bool: 是否删除成功
        """
        key = kwargs.get('key')
        if not key:
            self.logger.error("删除数据时必须提供键")
            return False
        
        try:
            if key in self.data:
                del self.data[key]
                self.logger.debug(f"成功从内存删除数据: {key}")
                return True
            else:
                self.logger.warning(f"键 '{key}' 不存在")
                return True  # 认为删除成功
        except Exception as e:
            self.logger.error(f"从内存删除数据失败: {str(e)}")
            return False
    
    async def list_items(self, **kwargs) -> List[Dict[str, Any]]:
        """列出内存中的所有项
        Returns:
            List[Dict[str, Any]]: 项目列表
        """
        return [{'key': k, 'type': type(v).__name__} for k, v in self.data.items()]
    
    async def count(self, **kwargs) -> int:
        """统计内存中的项数量
        Returns:
            int: 项数量
        """
        return len(self.data)
    
    async def close(self) -> None:
        """关闭存储连接（内存存储不需要关闭连接）"""
        pass


class StorageManager:
    """存储管理器，负责创建和管理不同的存储后端"""
    
    _storage_backends = {
        'file': FileSystemStorage,
        'memory': MemoryStorage
    }
    
    @staticmethod
    def create_storage(config: Dict[str, Any]) -> StorageBackend:
        """创建存储后端实例
        Args:
            config: 存储配置，包含类型、路径等
        Returns:
            StorageBackend: 存储后端实例
        """
        storage_type = config.get('type', 'file')
        
        if storage_type not in StorageManager._storage_backends:
            raise ValueError(f"不支持的存储类型: {storage_type}")
        
        backend_class = StorageManager._storage_backends[storage_type]
        return backend_class(config)
    
    @staticmethod
    def register_storage(storage_type: str, backend_class: type) -> None:
        """注册新的存储后端
        Args:
            storage_type: 存储类型名称
            backend_class: 存储后端类
        """
        if not issubclass(backend_class, StorageBackend):
            raise TypeError("存储后端必须是StorageBackend的子类")
        
        StorageManager._storage_backends[storage_type] = backend_class
    
    @staticmethod
    def get_supported_types() -> List[str]:
        """获取支持的存储类型列表
        Returns:
            List[str]: 支持的存储类型列表
        """
        return list(StorageManager._storage_backends.keys())


# 使用示例
if __name__ == '__main__':
    # 创建文件系统存储
    file_config = {
        'type': 'file',
        'path': 'test_data',
        'format': 'jsonl'
    }
    file_storage = StorageManager.create_storage(file_config)
    
    # 创建测试数据
    test_data = [
        {'id': '1', 'name': '测试数据1', 'value': 100},
        {'id': '2', 'name': '测试数据2', 'value': 200}
    ]
    
    # 测试文件系统存储
    async def test_file_storage():
        # 保存数据
        success = await file_storage.save(test_data, filename='test.jsonl')
        print(f"保存数据到文件: {'成功' if success else '失败'}")
        
        # 获取数据
        data = await file_storage.get(filename='test.jsonl')
        print(f"从文件获取数据: {data}")
        
        # 列出文件
        files = await file_storage.list_items()
        print(f"列出文件: {files}")
        
        # 统计数量
        count = await file_storage.count(filename='test.jsonl')
        print(f"文件中的项数量: {count}")
        
        # 删除特定项
        delete_success = await file_storage.delete(filename='test.jsonl', item_id='1')
        print(f"删除特定项: {'成功' if delete_success else '失败'}")
        
        # 再次获取数据
        data_after_delete = await file_storage.get(filename='test.jsonl')
        print(f"删除后的数据: {data_after_delete}")
        
        # 删除文件
        delete_file_success = await file_storage.delete(filename='test.jsonl')
        print(f"删除文件: {'成功' if delete_file_success else '失败'}")
    
    # 测试内存存储
    async def test_memory_storage():
        memory_config = {'type': 'memory'}
        memory_storage = StorageManager.create_storage(memory_config)
        
        # 保存数据
        success = await memory_storage.save(test_data, key='test_data')
        print(f"保存数据到内存: {'成功' if success else '失败'}")
        
        # 获取数据
        data = await memory_storage.get(key='test_data')
        print(f"从内存获取数据: {data}")
        
        # 列出项
        items = await memory_storage.list_items()
        print(f"列出内存中的项: {items}")
        
        # 统计数量
        count = await memory_storage.count()
        print(f"内存中的项数量: {count}")
        
        # 删除数据
        delete_success = await memory_storage.delete(key='test_data')
        print(f"删除内存中的数据: {'成功' if delete_success else '失败'}")
    
    # 运行测试
    async def run_tests():
        print("===== 测试文件系统存储 =====")
        await test_file_storage()
        print("\n===== 测试内存存储 =====")
        await test_memory_storage()
    
    # 运行异步测试
    import asyncio
    asyncio.run(run_tests())