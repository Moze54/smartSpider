"""
SmartSpider 日志工具
"""

import logging
import os
from typing import Optional


def get_logger(name: str, log_file: Optional[str] = None, log_level: str = "INFO") -> logging.Logger:
    """
    获取具有指定名称和配置的日志记录器
    
    参数:
        name (str): 日志记录器名称
        log_file (str, 可选): 日志文件路径
        log_level (str): 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    返回:
        logging.Logger: 配置好的日志记录器
    """
    # 创建日志记录器
    logger = logging.getLogger(name)
    
    # 设置日志级别
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    logger.setLevel(level_map.get(log_level.upper(), logging.INFO))
    
    # 如果日志记录器已有处理器，清除它们
    if logger.handlers:
        logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 如果提供了log_file，创建文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# 使用示例
if __name__ == '__main__':
    # 创建日志记录器
    logger = get_logger("test_logger", log_file="test.log", log_level="DEBUG")
    
    # 在不同级别记录消息
    logger.debug("这是一条调试消息")
    logger.info("这是一条信息消息")
    logger.warning("这是一条警告消息")
    logger.error("这是一条错误消息")
    logger.critical("这是一条严重错误消息")