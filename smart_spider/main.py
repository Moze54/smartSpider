"""
SmartSpider 主入口点
"""

import sys
from smart_spider.core.crawler import SmartCrawler
from smart_spider.settings import settings


def main():
    """运行 SmartSpider 的主函数"""
    try:
        # 获取版本号（从配置中或硬编码）
        version = settings.get('app', {}).get('version', '0.1.0')
        print(f"Starting SmartSpider v{version}")
        
        # 使用设置初始化爬虫
        crawler = SmartCrawler(settings)
        
        # 开始爬取（异步运行）
        import asyncio
        asyncio.run(crawler.start())
        
    except KeyboardInterrupt:
        print("\n用户停止了 SmartSpider。")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()