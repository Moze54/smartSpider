"""
SmartSpider 服务层 - 业务逻辑实现
"""

import os
import json
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional

from smart_spider.utils.logger import get_logger


class CrawlerService:
    """爬虫操作的服务类"""
    
    def __init__(self, settings):
        """初始化爬虫服务"""
        self.settings = settings
        self.logger = get_logger(__name__)
        
        # 初始化存储配置
        storage_config = self.settings.get('storage', {})
        self.storage_type = storage_config.get('type', 'file')
        self.storage_path = storage_config.get('path', './data')
        self.storage_format = storage_config.get('format', 'json')
        
        # 初始化数据缓存，用于临时存储
        self.data_cache = {}
        
        # 初始化锁，用于多任务访问
        self.cache_lock = asyncio.Lock()
        
        # 确保存储目录存在
        os.makedirs(self.storage_path, exist_ok=True)
    
    def validate_crawler_config(self, config):
        """验证爬虫配置"""
        """
        验证爬虫配置是否有效
        
        参数:
            config (dict): 爬虫配置
        
        返回:
            tuple: (is_valid, errors) - (是否有效，错误列表)
        """
        errors = []
        
        # 检查start_urls是否存在并且是否为列表
        if 'start_urls' not in config and 'entry_urls' not in config:
            errors.append("必须提供start_urls或entry_urls字段")
        
        # 检查start_urls或entry_urls是否为列表
        if 'start_urls' in config and not isinstance(config['start_urls'], list):
            errors.append("start_urls必须是一个列表")
        
        if 'entry_urls' in config and not isinstance(config['entry_urls'], list):
            errors.append("entry_urls必须是一个列表")
        
        # 检查并发数是否为整数
        if 'concurrency' in config and not isinstance(config['concurrency'], int):
            errors.append("concurrency必须是一个整数")
        
        # 检查选择器配置
        if 'selectors' in config:
            selectors = config['selectors']
            if 'items' in selectors and not isinstance(selectors['items'], dict):
                errors.append("items选择器必须是一个字典")
            if 'fields' in selectors and not isinstance(selectors['fields'], dict):
                errors.append("fields选择器必须是一个字典")
        
        return len(errors) == 0, errors
    
    def process_crawled_data(self, raw_data):
        """处理抓取的数据"""
        """
        将原始抓取的数据处理成标准化格式
        
        参数:
            raw_data (dict): 原始抓取的数据
        
        返回:
            dict: 处理后的数据
        """
        # 创建数据副本
        processed_data = raw_data.copy()
        
        # 确保存在url
        if 'url' not in processed_data:
            self.logger.warning("抓取的数据中没有URL")
            processed_data['url'] = ''
        
        # 添加缺失的标准字段
        if 'title' not in processed_data:
            processed_data['title'] = ''
        
        if 'content' not in processed_data:
            processed_data['content'] = ''
        
        if 'timestamp' not in processed_data:
            processed_data['timestamp'] = datetime.now().isoformat()
        
        if 'metadata' not in processed_data:
            processed_data['metadata'] = {}
        
        self.logger.debug(f"处理后的数据: {processed_data}")
        return processed_data
    
    def save_crawled_data(self, data):
        """保存抓取的数据"""
        """
        将抓取的数据保存到存储中
        
        参数:
            data (dict): 要保存的数据
        
        返回:
            bool: 成功状态
        """
        try:
            # 根据存储类型选择不同的保存方法
            if self.storage_type == 'file':
                return self._save_to_file(data)
            elif self.storage_type == 'jsonl':
                return self._save_to_jsonl(data)
            else:
                self.logger.error(f"不支持的存储类型: {self.storage_type}")
                return False
        except Exception as e:
            self.logger.error(f"保存数据错误: {e}")
            return False
    
    def _save_to_file(self, data):
        """将数据保存到文件"""
        try:
            # 为URL生成一个唯一的文件名
            url_hash = hashlib.md5(data['url'].encode()).hexdigest()
            file_path = os.path.join(self.storage_path, f"{url_hash}.{self.storage_format}")
            
            # 保存数据
            if self.storage_format == 'json':
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            elif self.storage_format == 'txt':
                content = data.get('content', '')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"URL: {data.get('url', '')}\n\n")
                    f.write(f"标题: {data.get('title', '')}\n\n")
                    f.write(f"内容:\n{content}")
            
            self.logger.info(f"数据保存到 {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"保存数据到文件错误: {e}")
            return False
    
    def _save_to_jsonl(self, data):
        """将数据保存到JSONL文件"""
        try:
            # 使用当前日期作为文件名
            today = datetime.now().strftime('%Y%m%d')
            file_path = os.path.join(self.storage_path, f"crawled_data_{today}.jsonl")
            
            # 以追加模式打开文件
            with open(file_path, 'a', encoding='utf-8') as f:
                # 写入JSON行
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
            
            self.logger.info(f"数据追加到 {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"保存数据到JSONL文件错误: {e}")
            return False
    
    async def cache_data(self, data):
        """将数据缓存到内存中"""
        async with self.cache_lock:
            url = data.get('url', '')
            if url:
                self.data_cache[url] = data
                self.logger.debug(f"数据已缓存到URL: {url}")
    
    async def get_cached_data(self, url):
        """从内存缓存中获取数据"""
        async with self.cache_lock:
            return self.data_cache.get(url)
    
    def get_all_crawled_data(self, limit=None):
        """获取所有已爬取的数据"""
        all_data = []
        try:
            if self.storage_type == 'file':
                # 从文件系统读取数据
                files = [f for f in os.listdir(self.storage_path) \
                         if os.path.isfile(os.path.join(self.storage_path, f)) \
                         and f.endswith(f'.{self.storage_format}')]
                
                # 限制返回的数据量
                if limit and len(files) > limit:
                    files = files[:limit]
                
                for file_name in files:
                    file_path = os.path.join(self.storage_path, file_name)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        all_data.append(data)
            elif self.storage_type == 'jsonl':
                # 从JSONL文件读取数据
                today = datetime.now().strftime('%Y%m%d')
                file_path = os.path.join(self.storage_path, f"crawled_data_{today}.jsonl")
                
                if os.path.exists(file_path):
                    count = 0
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            if limit and count >= limit:
                                break
                            try:
                                data = json.loads(line.strip())
                                all_data.append(data)
                                count += 1
                            except json.JSONDecodeError:
                                self.logger.warning(f"{file_path}中的无效JSON行")
            
            self.logger.info(f"获取了 {len(all_data)} 条已爬取的数据")
        except Exception as e:
            self.logger.error(f"获取已爬取数据错误: {e}")
        
        return all_data
    
    def export_data(self, format_type='json', output_path=None):
        """导出爬取的数据"""
        try:
            # 获取所有数据
            all_data = self.get_all_crawled_data()
            
            if not all_data:
                self.logger.warning("没有数据可导出")
                return False
            
            # 如果没有提供输出路径，则使用默认路径
            if not output_path:
                export_time = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_path = os.path.join(self.storage_path, f"export_{export_time}.{format_type}")
            
            # 根据格式导出数据
            if format_type == 'json':
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=2)
            elif format_type == 'csv':
                # 简单的CSV导出，只导出主要字段
                import csv
                with open(output_path, 'w', newline='', encoding='utf-8') as f:
                    # 使用第一个数据项的键作为CSV标题
                    if all_data:
                        fieldnames = list(all_data[0].keys())
                        # 移除复杂类型的字段
                        simple_fieldnames = [f for f in fieldnames \
                                             if isinstance(all_data[0][f], (str, int, float, bool, type(None)))]
                        
                        writer = csv.DictWriter(f, fieldnames=simple_fieldnames)
                        writer.writeheader()
                        for data in all_data:
                            # 只写入简单类型的字段
                            simple_data = {k: v for k, v in data.items() \
                                          if k in simple_fieldnames}
                            writer.writerow(simple_data)
            
            self.logger.info(f"数据已导出到 {output_path}")
            return True
        except Exception as e:
            self.logger.error(f"导出数据错误: {e}")
            return False
    
    def get_crawl_statistics(self):
        """获取爬取统计信息"""
        try:
            # 获取所有数据
            all_data = self.get_all_crawled_data()
            
            # 计算统计信息
            stats = {
                'total_items': len(all_data),
                'domains': set(),
                'timestamp_range': {
                    'start': None,
                    'end': None
                }
            }
            
            # 收集域名和时间戳信息
            for data in all_data:
                # 提取域名
                url = data.get('url', '')
                if url:
                    from urllib.parse import urlparse
                    parsed_url = urlparse(url)
                    domain = parsed_url.netloc
                    if domain:
                        stats['domains'].add(domain)
                
                # 更新时间戳范围
                timestamp = data.get('timestamp', '')
                if timestamp:
                    try:
                        timestamp_dt = datetime.fromisoformat(timestamp)
                        if not stats['timestamp_range']['start'] or timestamp_dt < stats['timestamp_range']['start']:
                            stats['timestamp_range']['start'] = timestamp_dt
                        if not stats['timestamp_range']['end'] or timestamp_dt > stats['timestamp_range']['end']:
                            stats['timestamp_range']['end'] = timestamp_dt
                    except ValueError:
                        self.logger.warning(f"无效的时间戳格式: {timestamp}")
            
            # 转换集合为列表
            stats['domains'] = list(stats['domains'])
            
            # 格式化时间戳
            if stats['timestamp_range']['start']:
                stats['timestamp_range']['start'] = stats['timestamp_range']['start'].isoformat()
            if stats['timestamp_range']['end']:
                stats['timestamp_range']['end'] = stats['timestamp_range']['end'].isoformat()
            
            self.logger.info(f"获取了爬取统计信息: {stats}")
            return stats
        except Exception as e:
            self.logger.error(f"获取爬取统计信息错误: {e}")
            return {
                'total_items': 0,
                'domains': [],
                'timestamp_range': {
                    'start': None,
                    'end': None
                }
            }


# 使用示例
if __name__ == '__main__':
    # 用于测试的简单设置
    test_settings = {
        'storage': {
            'type': 'file',
            'path': 'data/output',
            'format': 'json'
        }
    }
    
    service = CrawlerService(test_settings)
    
    # 测试验证
    config = {
        'entry_urls': ['https://example.com'],
        'concurrency': 5,
        'selectors': {
            'fields': {
                'title': {'type': 'css', 'expr': 'h1'},
                'content': {'type': 'css', 'expr': 'p'}
            }
        }
    }
    is_valid, errors = service.validate_crawler_config(config)
    print(f"配置有效: {is_valid}, 错误: {errors}")
    
    # 测试数据处理
    raw_data = {
        'url': 'https://example.com', 
        'title': '示例页面',
        'metadata': {
            'source': 'test',
            'priority': 1
        }
    }
    processed_data = service.process_crawled_data(raw_data)
    print(f"处理后的数据: {processed_data}")
    
    # 测试数据保存
    save_result = service.save_crawled_data(processed_data)
    print(f"保存结果: {save_result}")
    
    # 获取所有数据
    all_data = service.get_all_crawled_data()
    print(f"所有数据数量: {len(all_data)}")
    
    # 获取统计信息
    stats = service.get_crawl_statistics()
    print(f"统计信息: {stats}")
    
    # 测试保存数据
    success = service.save_crawled_data(processed_data)
    print(f"保存成功: {success}")