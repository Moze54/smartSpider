"""
SmartSpider API 服务入口点
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from smart_spider.api.routes import router
from smart_spider.api.proxy_routes import router as proxy_router
from smart_spider.settings import settings
from smart_spider.utils.logger import get_logger

# 初始化日志记录器
logger = get_logger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="SmartSpider API",
    description="智能网络爬虫系统的REST API",
    version=settings.get("app.version", "0.1.0"),
)

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(router, prefix="/api")
app.include_router(proxy_router, prefix="/api")

# 健康检查端点
@app.get("/health", tags=["健康检查"])
def health_check():
    """检查API服务是否健康"""
    return {"status": "healthy", "version": app.version}

# 根端点
@app.get("/", tags=["根"])
def root():
    """API根端点"""
    return {"message": "Welcome to SmartSpider API", "docs": "/docs"}

def run_api():
    """运行FastAPI服务"""
    logger.info(f"Starting SmartSpider API v{app.version}")
    logger.info(f"Documentation available at http://localhost:8000/docs")
    uvicorn.run(
        "smart_spider.main_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式下启用自动重载
    )

if __name__ == "__main__":
    run_api()