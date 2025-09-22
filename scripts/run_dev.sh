#!/bin/bash

# 在开发模式下运行SmartSpider的脚本

# 设置Python环境
if [ -d "venv" ]; then
    echo "正在激活虚拟环境..."
    source venv/bin/activate
else
    echo "未找到虚拟环境。正在创建..."
    python -m venv venv
    source venv/bin/activate
    echo "正在安装依赖..."
    pip install -r requirements-dev.txt
fi

# 运行应用程序
python -m smart_spider