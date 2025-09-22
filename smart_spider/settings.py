"""
SmartSpider 的设置管理
"""

import os
import yaml
from dotenv import load_dotenv
from smart_spider.utils.logger import get_logger

# 从.env文件加载环境变量
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

# 初始化日志记录器
logger = get_logger(__name__)


class Settings:
    """SmartSpider 的设置类"""
    
    def __init__(self):
        """通过加载配置文件和环境变量来初始化设置"""
        self._settings = {}
        
        # 从配置文件加载设置
        self._load_config_file()
        
        # 用环境变量覆盖设置
        self._override_with_env_vars()
        
        # 设置延迟初始化标志，默认为False
        # 在测试环境中，应在配置文件或环境变量中设置为True
        if 'delay_init' not in self._settings:
            self._settings['delay_init'] = False
    
    def _load_config_file(self):
        """从config.yaml文件加载设置"""
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'configs', 'config.yaml')
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self._settings = yaml.safe_load(f) or {}
                logger.info(f"从 {config_path} 加载设置")
            except Exception as e:
                logger.error(f"加载配置文件错误: {e}")
        else:
            logger.warning(f"在 {config_path} 未找到配置文件")
    
    def _override_with_env_vars(self):
        """用环境变量覆盖设置"""
        # 爬虫设置
        if 'SPIDER_USER_AGENT' in os.environ:
            self._settings.setdefault('crawler', {})['user_agent'] = os.environ['SPIDER_USER_AGENT']
        
        if 'SPIDER_DELAY' in os.environ:
            try:
                self._settings.setdefault('crawler', {})['delay'] = float(os.environ['SPIDER_DELAY'])
            except ValueError:
                logger.warning(f"无效的SPIDER_DELAY值: {os.environ['SPIDER_DELAY']}")
        
        if 'SPIDER_CONCURRENT_REQUESTS' in os.environ:
            try:
                self._settings.setdefault('crawler', {})['concurrent_requests'] = int(os.environ['SPIDER_CONCURRENT_REQUESTS'])
            except ValueError:
                logger.warning(f"无效的SPIDER_CONCURRENT_REQUESTS值: {os.environ['SPIDER_CONCURRENT_REQUESTS']}")
        
        # 日志设置
        if 'LOG_LEVEL' in os.environ:
            self._settings.setdefault('logging', {})['level'] = os.environ['LOG_LEVEL']
        
        if 'LOG_FILE' in os.environ:
            self._settings.setdefault('logging', {})['file'] = os.environ['LOG_FILE']
    
    def get(self, key, default=None):
        """获取设置值"""
        # 使用点表示法处理嵌套键
        if '.' in key:
            parts = key.split('.')
            value = self._settings
            
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return default
            
            return value
        
        return self._settings.get(key, default)
    
    def __getitem__(self, key):
        """使用类似字典的访问方式获取设置"""
        return self.get(key)
    
    def __repr__(self):
        """设置的字符串表示"""
        return f"Settings({self._settings})"


# 创建全局设置实例
settings = Settings()


# Example usage
if __name__ == '__main__':
    # Access settings
    print(f"Crawler user agent: {settings.get('crawler.user_agent')}")
    print(f"Crawler delay: {settings.get('crawler.delay')}")
    print(f"Logging level: {settings.get('logging.level')}")
    
    # Dictionary-like access
    print(f"Storage type: {settings['storage']['type']}")