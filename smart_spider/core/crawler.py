"""
SmartCrawler 类 - 核心爬取功能
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
from smart_spider.utils.logger import get_logger
from smart_spider.core.service import CrawlerService


class SmartCrawler:
    """用于数据提取的智能网络爬虫"""
    
    def __init__(self, settings):
        """使用设置初始化爬虫"""
        self.settings = settings
        self.logger = get_logger(__name__)
        self.visited_urls = set()
        self.service = CrawlerService(settings)
        
        # 配置爬虫参数
        self.user_agent = self.settings.get('crawler', {}).get('user_agent', 'SmartSpider/0.1')
        self.delay = self.settings.get('crawler', {}).get('delay', 1)
        self.concurrent_requests = self.settings.get('crawler', {}).get('concurrent_requests', 5)
        self.timeout = self.settings.get('crawler', {}).get('timeout', 30)
        self.retry_count = self.settings.get('crawler', {}).get('retry_count', 3)
        
        # 创建信号量控制并发
        self.semaphore = None
        
        # 任务状态
        self.running = False
        self.task_id = None
        self.metrics = {
            'success_count': 0,
            'fail_count': 0,
            'total_count': 0,
            'progress_percent': 0.0
        }
    
    async def start(self, task_config=None):
        """开始爬取过程"""
        self.logger.info("Starting SmartCrawler")
        self.running = True
        
        # 如果提供了任务配置，则使用配置进行爬取
        if task_config:
            self.logger.info(f"Using task config: {task_config['name']}")
            start_urls = task_config.get('entry_urls', [])
            self.concurrent_requests = task_config.get('concurrency', self.concurrent_requests)
        else:
            # 从设置中获取起始URL
            start_urls = self.settings.get('rules', {}).get('example_rule', {}).get('start_urls', [])
        
        # 初始化信号量
        self.semaphore = asyncio.Semaphore(self.concurrent_requests)
        
        # 创建HTTP客户端
        async with httpx.AsyncClient(
            headers={'User-Agent': self.user_agent},
            timeout=self.timeout,
            follow_redirects=True
        ) as client:
            # 创建任务列表
            tasks = []
            for url in start_urls:
                tasks.append(self._crawl(url, client, task_config))
                # 添加延迟以避免初始请求过于集中
                await asyncio.sleep(self.delay)
            
            # 等待所有任务完成
            if tasks:
                await asyncio.gather(*tasks)
        
        self.running = False
        self.logger.info(f"Crawling completed. Visited {len(self.visited_urls)} URLs.")
    
    async def stop(self):
        """停止爬取过程"""
        self.logger.info("Stopping SmartCrawler")
        self.running = False
    
    async def _crawl(self, url, client, task_config=None):
        """爬取单个URL"""
        if not self.running or url in self.visited_urls:
            return
        
        self.visited_urls.add(url)
        self.logger.info(f"Crawling: {url}")
        
        self.metrics['total_count'] += 1
        
        try:
            # 使用信号量限制并发
            async with self.semaphore:
                # 延迟发送请求
                await asyncio.sleep(self.delay)
                
                # 尝试请求URL，支持重试
                response = await self._fetch_with_retry(url, client)
                
                # 解析HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 根据规则提取数据
                data = await self._extract_data(url, soup, task_config)
                
                # 保存数据
                if data:
                    success = self.service.save_crawled_data(data)
                    if success:
                        self.metrics['success_count'] += 1
                        self.logger.info(f"Successfully crawled and saved data from {url}")
                    else:
                        self.metrics['fail_count'] += 1
                        self.logger.error(f"Failed to save data from {url}")
                
                # 查找并爬取链接
                await self._find_links(url, soup, client, task_config)
                
        except Exception as e:
            self.metrics['fail_count'] += 1
            self.logger.error(f"Error crawling {url}: {e}")
        finally:
            # 更新进度
            if self.metrics['total_count'] > 0:
                self.metrics['progress_percent'] = (
                    self.metrics['success_count'] / self.metrics['total_count'] * 100
                )
    
    async def _fetch_with_retry(self, url, client):
        """带重试的异步请求"""
        retry_wait = 1  # 初始重试等待时间（秒）
        
        for attempt in range(self.retry_count + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response
            except httpx.RequestError as e:
                if attempt == self.retry_count:
                    self.logger.error(f"Failed to fetch {url} after {self.retry_count} retries: {e}")
                    raise
                
                self.logger.warning(f"Attempt {attempt+1} failed for {url}: {e}. Retrying in {retry_wait}s...")
                await asyncio.sleep(retry_wait)
                
                # 指数退避策略
                retry_wait *= 2
    
    async def _extract_data(self, url, soup, task_config=None):
        """使用规则从HTML中提取数据"""
        try:
            # 基本数据
            data = {
                'url': url,
                'title': soup.title.string.strip() if soup.title else '无标题',
            }
            
            # 如果有任务配置，使用其中的选择器
            if task_config and 'selectors' in task_config:
                selectors = task_config['selectors']
                
                # 提取项目
                if 'items' in selectors:
                    items_selector = selectors['items']
                    items_data = self._extract_items(soup, items_selector)
                    if items_data:
                        data['items'] = items_data
                
                # 提取字段
                if 'fields' in selectors:
                    fields_data = self._extract_fields(soup, selectors['fields'])
                    data.update(fields_data)
            else:
                # 使用配置文件中的规则
                rules = self.settings.get('rules', {}).get('example_rule', {})
                if 'extract' in rules:
                    extract_rules = rules['extract']
                    for key, selector in extract_rules.items():
                        data[key] = self._extract_value(soup, selector)
            
            # 处理数据
            processed_data = self.service.process_crawled_data(data)
            
            self.logger.debug(f"Extracted data: {processed_data}")
            return processed_data
        except Exception as e:
            self.logger.error(f"Error extracting data from {url}: {e}")
            return None
    
    def _extract_items(self, soup, items_selector):
        """提取多个项目"""
        try:
            items = []
            selector_type = items_selector.get('type', 'css')
            selector_expr = items_selector.get('expr', '')
            
            if selector_type == 'css':
                elements = soup.select(selector_expr)
                for element in elements:
                    # 为每个项目提取文本内容
                    items.append(element.get_text().strip())
            
            return items
        except Exception as e:
            self.logger.error(f"Error extracting items: {e}")
            return []
    
    def _extract_fields(self, soup, fields_selectors):
        """提取多个字段"""
        fields_data = {}
        
        try:
            for field_name, field_selector in fields_selectors.items():
                selector_type = field_selector.get('type', 'css')
                selector_expr = field_selector.get('expr', '')
                
                fields_data[field_name] = self._extract_value(soup, selector_expr, selector_type)
            
            return fields_data
        except Exception as e:
            self.logger.error(f"Error extracting fields: {e}")
            return fields_data
    
    def _extract_value(self, soup, selector, selector_type='css'):
        """使用选择器提取值"""
        try:
            if selector_type == 'css':
                # 检查是否是提取属性
                if '::attr(' in selector:
                    parts = selector.split('::attr(')
                    css_selector = parts[0]
                    attr_name = parts[1].rstrip(')')
                    element = soup.select_one(css_selector)
                    if element and attr_name in element.attrs:
                        return element[attr_name]
                else:
                    element = soup.select_one(selector)
                    if element:
                        return element.get_text().strip()
            
            return None
        except Exception as e:
            self.logger.error(f"Error extracting value with selector '{selector}': {e}")
            return None
    
    async def _find_links(self, url, soup, client, task_config=None):
        """查找并跟踪页面上的链接"""
        if not self.running:
            return
        
        try:
            # 基本链接提取
            links = []
            
            # 从任务配置中获取链接选择器
            if task_config and 'pagination' in task_config:
                pagination = task_config['pagination']
                if pagination.get('type') == 'next_link':
                    selector = pagination.get('selector')
                    next_link = self._extract_value(soup, selector)
                    if next_link:
                        # 确保URL是绝对路径
                        import urllib.parse
                        absolute_url = urllib.parse.urljoin(url, next_link)
                        links.append(absolute_url)
            else:
                # 使用默认链接提取（所有a标签）
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    # 确保URL是绝对路径
                    import urllib.parse
                    absolute_url = urllib.parse.urljoin(url, href)
                    links.append(absolute_url)
            
            # 过滤链接（避免重复和外部链接）
            allowed_domains = set()
            if task_config and 'allowed_domains' in task_config:
                allowed_domains.update(task_config['allowed_domains'])
            else:
                # 从设置中获取允许的域名
                rules = self.settings.get('rules', {}).get('example_rule', {})
                if 'allowed_domains' in rules:
                    allowed_domains.update(rules['allowed_domains'])
            
            # 如果有允许的域名，则过滤链接
            if allowed_domains:
                filtered_links = []
                for link in links:
                    from urllib.parse import urlparse
                    parsed_url = urlparse(link)
                    if parsed_url.netloc in allowed_domains:
                        filtered_links.append(link)
                links = filtered_links
            
            # 跟踪链接
            for link in links:
                if link not in self.visited_urls and self.running:
                    # 使用asyncio.create_task创建新任务
                    asyncio.create_task(self._crawl(link, client, task_config))
                    # 添加延迟以避免请求过于集中
                    await asyncio.sleep(self.delay)
        except Exception as e:
            self.logger.error(f"Error finding links on {url}: {e}")


# 使用示例
if __name__ == '__main__':
    # 用于测试的简单设置
    test_settings = {
        'crawler': {
            'user_agent': 'SmartSpider/0.1',
            'delay': 1,
            'concurrent_requests': 5,
            'timeout': 30,
            'retry_count': 3
        },
        'rules': {
            'example_rule': {
                'start_urls': ['https://example.com'],
                'allowed_domains': ['example.com'],
                'extract': {
                    'title': 'h1',
                    'content': '.content',
                    'links': 'a::attr(href)'
                }
            }
        }
    }
    
    # 创建爬虫实例
    crawler = SmartCrawler(test_settings)
    
    # 运行异步爬虫
    import asyncio
    asyncio.run(crawler.start())