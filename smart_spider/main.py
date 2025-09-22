"""
SmartSpider 主入口点
"""

import sys
from smart_spider.core.crawler import SmartCrawler
from smart_spider.settings import settings


def main():
    """运行 SmartSpider 的主函数"""
    try:
        print(f"Starting SmartSpider v{__import__(__name__).__version__}")
        
        # 使用设置初始化爬虫
        crawler = SmartCrawler(settings)
        
        # 开始爬取
        crawler.start()
        
    except KeyboardInterrupt:
        print("\n用户停止了 SmartSpider。")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()