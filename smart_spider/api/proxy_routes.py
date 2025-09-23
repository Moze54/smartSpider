"""
代理管理API路由 - 提供代理池和代理IP的管理接口
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, validator
import asyncio

from smart_spider.core.proxy_manager import (
    ProxyManager,
    ProxyStatus,
    ProxyType,
    ProxyPoolType,
    ProxyItem,
    ProxyPool,
    ProxyLease
)
from smart_spider.utils.logger import get_logger
from smart_spider.settings import settings

router = APIRouter(prefix="/proxies", tags=["代理管理"])
proxy_manager = ProxyManager()
logger = get_logger(__name__)


# Pydantic模型定义
class ProxyItemModel(BaseModel):
    """代理IP项模型"""
    ip: str = Field(..., min_length=1, description="代理IP地址")
    port: int = Field(..., ge=1, le=65535, description="代理端口")
    protocol: str = Field(default="http", description="代理协议")
    username: Optional[str] = Field(default=None, description="代理用户名")
    password: Optional[str] = Field(default=None, description="代理密码")
    location: Optional[str] = Field(default=None, description="代理地理位置")
    isp: Optional[str] = Field(default=None, description="代理运营商")
    status: str = Field(default="pending", description="代理状态")
    anonymity: Optional[str] = Field(default=None, description="代理匿名程度")
    
    @validator('protocol')
    def validate_protocol(cls, v):
        valid_protocols = [t for t in [ProxyType.HTTP, ProxyType.HTTPS, ProxyType.SOCKS5, ProxyType.SOCKS4]]
        if v not in valid_protocols:
            raise ValueError(f"无效的代理协议: {v}. 有效值: {valid_protocols}")
        return v
    
    @validator('status')
    def validate_status(cls, v):
        valid_statuses = [s for s in [ProxyStatus.VALID, ProxyStatus.WARNING, ProxyStatus.INVALID, ProxyStatus.PENDING, ProxyStatus.BLACKLISTED]]
        if v not in valid_statuses:
            raise ValueError(f"无效的代理状态: {v}. 有效值: {valid_statuses}")
        return v


class ProxyPoolModel(BaseModel):
    """代理池模型"""
    name: str = Field(..., min_length=1, max_length=100, description="代理池名称")
    description: Optional[str] = Field(default=None, max_length=500, description="代理池描述")
    type: str = Field(default="public", description="代理池类型")
    
    @validator('type')
    def validate_type(cls, v):
        valid_types = [t.value for t in [ProxyPoolType.PUBLIC, ProxyPoolType.PRIVATE, ProxyPoolType.SHARED]]
        if v not in valid_types:
            raise ValueError(f"无效的代理池类型: {v}. 有效值: {valid_types}")
        return v


class ProxyLeaseModel(BaseModel):
    """代理租用模型"""
    task_id: str = Field(..., min_length=1, description="任务ID")
    protocol: str = Field(default="all", description="代理协议类型")
    ttl: int = Field(default=300, ge=60, le=3600, description="租用时长（秒）")
    
    @validator('protocol')
    def validate_protocol(cls, v):
        valid_protocols = [t for t in [ProxyType.HTTP, ProxyType.HTTPS, ProxyType.SOCKS5, ProxyType.SOCKS4]] + ['all']
        if v not in valid_protocols:
            raise ValueError(f"无效的代理协议: {v}. 有效值: {valid_protocols}")
        return v


class ProxyUpdateModel(BaseModel):
    """代理更新模型"""
    ip: Optional[str] = Field(default=None, min_length=1, description="代理IP地址")
    port: Optional[int] = Field(default=None, ge=1, le=65535, description="代理端口")
    protocol: Optional[str] = Field(default=None, description="代理协议")
    username: Optional[str] = Field(default=None, description="代理用户名")
    password: Optional[str] = Field(default=None, description="代理密码")
    location: Optional[str] = Field(default=None, description="代理地理位置")
    isp: Optional[str] = Field(default=None, description="代理运营商")
    status: Optional[str] = Field(default=None, description="代理状态")
    anonymity: Optional[str] = Field(default=None, description="代理匿名程度")
    
    @validator('protocol')
    def validate_protocol(cls, v):
        if v is not None:
            valid_protocols = [t for t in [ProxyType.HTTP, ProxyType.HTTPS, ProxyType.SOCKS5, ProxyType.SOCKS4]]
            if v not in valid_protocols:
                raise ValueError(f"无效的代理协议: {v}. 有效值: {valid_protocols}")
        return v
    
    @validator('status')
    def validate_status(cls, v):
        if v is not None:
            valid_statuses = [s for s in [ProxyStatus.VALID, ProxyStatus.WARNING, ProxyStatus.INVALID, ProxyStatus.PENDING, ProxyStatus.BLACKLISTED]]
            if v not in valid_statuses:
                raise ValueError(f"无效的代理状态: {v}. 有效值: {valid_statuses}")
        return v


class ProxyPoolUpdateModel(BaseModel):
    """代理池更新模型"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="代理池名称")
    description: Optional[str] = Field(default=None, max_length=500, description="代理池描述")
    type: Optional[str] = Field(default=None, description="代理池类型")
    
    @validator('type')
    def validate_type(cls, v):
        if v is not None:
            valid_types = [t.value for t in [ProxyPoolType.PUBLIC, ProxyPoolType.PRIVATE, ProxyPoolType.SHARED]]
            if v not in valid_types:
                raise ValueError(f"无效的代理池类型: {v}. 有效值: {valid_types}")
        return v


class BlacklistProxyModel(BaseModel):
    """黑名单代理模型"""
    reason: str = Field(default="", max_length=500, description="黑名单原因")


# API路由实现
@router.post(
    "/pools", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="创建代理池",
    description="创建一个新的代理池"
)
async def create_proxy_pool(pool_data: ProxyPoolModel):
    """
    创建代理池接口
    
    参数:
        pool_data: 代理池数据
    
    返回:
        创建的代理池信息
    """
    try:
        # 创建代理池
        proxy_pool = await proxy_manager.create_proxy_pool(pool_data.dict())
        
        return {
            "status": "success",
            "message": "代理池创建成功",
            "data": {
                "id": proxy_pool.id,
                "name": proxy_pool.name,
                "description": proxy_pool.description,
                "type": proxy_pool.type,
                "total_proxies": proxy_pool.total_proxy_count,
                "created_at": proxy_pool.created_at.isoformat(),
                "updated_at": proxy_pool.updated_at.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"创建代理池失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建代理池失败: {str(e)}"
        )


@router.get(
    "/pools", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="列出代理池",
    description="获取所有代理池列表"
)
async def list_proxy_pools(pool_type: Optional[str] = Query(None, description="代理池类型过滤")):
    """
    列出代理池接口
    
    参数:
        pool_type: 代理池类型过滤
    
    返回:
        代理池列表
    """
    try:
        # 获取代理池列表
        proxy_pools = await proxy_manager.list_proxy_pools(pool_type)
        
        # 格式化返回数据
        pools_data = []
        for pool in proxy_pools:
            pools_data.append({
                "id": pool.id,
                "name": pool.name,
                "description": pool.description,
                "type": pool.type,
                "total_proxies": pool.total_proxy_count,
                "valid_proxies": pool.valid_proxy_count,
                "warning_proxies": pool.warning_proxy_count,
                "invalid_proxies": pool.invalid_proxy_count,
                "created_at": pool.created_at.isoformat(),
                "updated_at": pool.updated_at.isoformat()
            })
        
        return {
            "status": "success",
            "message": "代理池列表获取成功",
            "data": pools_data,
            "count": len(pools_data)
        }
    except Exception as e:
        logger.error(f"获取代理池列表失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理池列表失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="获取代理池详情",
    description="获取指定代理池的详细信息"
)
async def get_proxy_pool(pool_id: str):
    """
    获取代理池详情接口
    
    参数:
        pool_id: 代理池ID
    
    返回:
        代理池详细信息
    """
    try:
        # 获取代理池
        proxy_pool = await proxy_manager.get_proxy_pool(pool_id)
        
        if not proxy_pool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 格式化返回数据
        pool_data = {
            "id": proxy_pool.id,
            "name": proxy_pool.name,
            "description": proxy_pool.description,
            "type": proxy_pool.type,
            "total_proxies": proxy_pool.total_proxy_count,
            "valid_proxies": proxy_pool.valid_proxy_count,
            "warning_proxies": proxy_pool.warning_proxy_count,
            "invalid_proxies": proxy_pool.invalid_proxy_count,
            "created_at": proxy_pool.created_at.isoformat(),
            "updated_at": proxy_pool.updated_at.isoformat()
        }
        
        return {
            "status": "success",
            "message": "代理池详情获取成功",
            "data": pool_data
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取代理池详情失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理池详情失败: {str(e)}"
        )


@router.put(
    "/pools/{pool_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="更新代理池",
    description="更新指定代理池的配置信息"
)
async def update_proxy_pool(pool_id: str, pool_data: ProxyPoolUpdateModel):
    """
    更新代理池接口
    
    参数:
        pool_id: 代理池ID
        pool_data: 要更新的代理池数据
    
    返回:
        更新后的代理池信息
    """
    try:
        # 过滤None值
        update_data = {k: v for k, v in pool_data.dict().items() if v is not None}
        
        if not update_data:
            return {
                "status": "success",
                "message": "无需更新，没有提供有效的更新数据",
                "data": None
            }
        
        # 更新代理池
        updated_pool = await proxy_manager.update_proxy_pool(pool_id, update_data)
        
        if not updated_pool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 格式化返回数据
        pool_data = {
            "id": updated_pool.id,
            "name": updated_pool.name,
            "description": updated_pool.description,
            "type": updated_pool.type,
            "total_proxies": updated_pool.total_proxy_count,
            "valid_proxies": updated_pool.valid_proxy_count,
            "warning_proxies": updated_pool.warning_proxy_count,
            "invalid_proxies": updated_pool.invalid_proxy_count,
            "created_at": updated_pool.created_at.isoformat(),
            "updated_at": updated_pool.updated_at.isoformat()
        }
        
        return {
            "status": "success",
            "message": "代理池更新成功",
            "data": pool_data
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新代理池失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新代理池失败: {str(e)}"
        )


@router.delete(
    "/pools/{pool_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="删除代理池",
    description="删除指定的代理池"
)
async def delete_proxy_pool(pool_id: str):
    """
    删除代理池接口
    
    参数:
        pool_id: 代理池ID
    
    返回:
        删除结果
    """
    try:
        # 删除代理池
        success = await proxy_manager.delete_proxy_pool(pool_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"删除代理池失败，代理池不存在或有活跃的代理租用: {pool_id}"
            )
        
        return {
            "status": "success",
            "message": "代理池删除成功",
            "data": {
                "pool_id": pool_id
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"删除代理池失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除代理池失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/proxies", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="添加代理",
    description="向指定代理池添加代理"
)
async def add_proxy(pool_id: str, proxy_data: ProxyItemModel):
    """
    添加代理接口
    
    参数:
        pool_id: 代理池ID
        proxy_data: 代理数据
    
    返回:
        添加的代理信息
    """
    try:
        # 添加代理
        proxy_item = await proxy_manager.add_proxy(pool_id, proxy_data.dict())
        
        if not proxy_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"添加代理失败，代理池不存在: {pool_id}"
            )
        
        # 格式化返回数据
        proxy_info = {
            "id": proxy_item.id,
            "ip": proxy_item.ip,
            "port": proxy_item.port,
            "protocol": proxy_item.protocol,
            "username": proxy_item.username,
            "password": proxy_item.password,
            "location": proxy_item.location,
            "isp": proxy_item.isp,
            "status": proxy_item.status,
            "response_time": proxy_item.response_time,
            "anonymity": proxy_item.anonymity,
            "created_at": proxy_item.created_at.isoformat(),
            "updated_at": proxy_item.updated_at.isoformat(),
            "url": proxy_item.url
        }
        
        return {
            "status": "success",
            "message": "代理添加成功",
            "data": proxy_info
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"添加代理失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加代理失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}/proxies", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="列出代理",
    description="获取指定代理池中的所有代理列表"
)
async def list_proxies(pool_id: str, status: Optional[str] = Query(None, description="代理状态过滤")):
    """
    列出代理接口
    
    参数:
        pool_id: 代理池ID
        status: 代理状态过滤
    
    返回:
        代理列表
    """
    try:
        # 获取代理池
        proxy_pool = await proxy_manager.get_proxy_pool(pool_id)
        
        if not proxy_pool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 过滤代理
        proxies = proxy_pool.proxies
        if status:
            proxies = [p for p in proxies if p.status == status]
        
        # 格式化返回数据
        proxies_data = []
        for proxy in proxies:
            proxies_data.append({
                "id": proxy.id,
                "ip": proxy.ip,
                "port": proxy.port,
                "protocol": proxy.protocol,
                "username": proxy.username,
                "password": proxy.password,
                "location": proxy.location,
                "isp": proxy.isp,
                "status": proxy.status,
                "response_time": proxy.response_time,
                "anonymity": proxy.anonymity,
                "score": proxy.score,
                "fail_count": proxy.fail_count,
                "success_count": proxy.success_count,
                "created_at": proxy.created_at.isoformat(),
                "updated_at": proxy.updated_at.isoformat(),
                "last_health_check": proxy.last_health_check.isoformat() if proxy.last_health_check else None,
                "url": proxy.url
            })
        
        return {
            "status": "success",
            "message": "代理列表获取成功",
            "data": proxies_data,
            "count": len(proxies_data)
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取代理列表失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理列表失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}/proxies/{proxy_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="获取代理详情",
    description="获取指定代理的详细信息"
)
async def get_proxy(pool_id: str, proxy_id: str):
    """
    获取代理详情接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
    
    返回:
        代理详细信息
    """
    try:
        # 获取代理池
        proxy_pool = await proxy_manager.get_proxy_pool(pool_id)
        
        if not proxy_pool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 查找代理
        proxy_item = next((p for p in proxy_pool.proxies if p.id == proxy_id), None)
        
        if not proxy_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理不存在: {proxy_id} -> {pool_id}"
            )
        
        # 格式化返回数据
        proxy_info = {
            "id": proxy_item.id,
            "ip": proxy_item.ip,
            "port": proxy_item.port,
            "protocol": proxy_item.protocol,
            "username": proxy_item.username,
            "password": proxy_item.password,
            "location": proxy_item.location,
            "isp": proxy_item.isp,
            "status": proxy_item.status,
            "response_time": proxy_item.response_time,
            "anonymity": proxy_item.anonymity,
            "score": proxy_item.score,
            "fail_count": proxy_item.fail_count,
            "success_count": proxy_item.success_count,
            "created_at": proxy_item.created_at.isoformat(),
            "updated_at": proxy_item.updated_at.isoformat(),
            "last_health_check": proxy_item.last_health_check.isoformat() if proxy_item.last_health_check else None,
            "url": proxy_item.url
        }
        
        # 添加健康检查结果（最多最近5次）
        if proxy_item.health_check_results:
            health_checks = []
            for check in proxy_item.health_check_results[-5:]:
                health_checks.append({
                    "timestamp": check['timestamp'].isoformat() if isinstance(check['timestamp'], str) else check['timestamp'].isoformat(),
                    "status": check['status'],
                    "success_rate": check['success_rate'],
                    "avg_response_time": check['avg_response_time']
                })
            proxy_info["health_checks"] = health_checks
        
        return {
            "status": "success",
            "message": "代理详情获取成功",
            "data": proxy_info
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取代理详情失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理详情失败: {str(e)}"
        )


@router.put(
    "/pools/{pool_id}/proxies/{proxy_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="更新代理",
    description="更新指定代理的信息"
)
async def update_proxy(pool_id: str, proxy_id: str, proxy_data: ProxyUpdateModel):
    """
    更新代理接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
        proxy_data: 要更新的代理数据
    
    返回:
        更新后的代理信息
    """
    try:
        # 过滤None值
        update_data = {k: v for k, v in proxy_data.dict().items() if v is not None}
        
        if not update_data:
            return {
                "status": "success",
                "message": "无需更新，没有提供有效的更新数据",
                "data": None
            }
        
        # 更新代理
        updated_proxy = await proxy_manager.update_proxy(pool_id, proxy_id, update_data)
        
        if not updated_proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"更新代理失败，代理池或代理不存在: {proxy_id} -> {pool_id}"
            )
        
        # 格式化返回数据
        proxy_info = {
            "id": updated_proxy.id,
            "ip": updated_proxy.ip,
            "port": updated_proxy.port,
            "protocol": updated_proxy.protocol,
            "username": updated_proxy.username,
            "password": updated_proxy.password,
            "location": updated_proxy.location,
            "isp": updated_proxy.isp,
            "status": updated_proxy.status,
            "response_time": updated_proxy.response_time,
            "anonymity": updated_proxy.anonymity,
            "updated_at": updated_proxy.updated_at.isoformat()
        }
        
        return {
            "status": "success",
            "message": "代理更新成功",
            "data": proxy_info
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新代理失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新代理失败: {str(e)}"
        )


@router.delete(
    "/pools/{pool_id}/proxies/{proxy_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="删除代理",
    description="从指定代理池删除代理"
)
async def remove_proxy(pool_id: str, proxy_id: str):
    """
    删除代理接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
    
    返回:
        删除结果
    """
    try:
        # 删除代理
        success = await proxy_manager.remove_proxy(pool_id, proxy_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"删除代理失败，代理池或代理不存在，或代理有活跃的租用: {proxy_id} -> {pool_id}"
            )
        
        return {
            "status": "success",
            "message": "代理删除成功",
            "data": {
                "proxy_id": proxy_id,
                "pool_id": pool_id
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"删除代理失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除代理失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/proxies/batch", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="批量添加代理",
    description="向指定代理池批量添加代理"
)
async def batch_add_proxies(pool_id: str, proxies_data: List[ProxyItemModel]):
    """
    批量添加代理接口
    
    参数:
        pool_id: 代理池ID
        proxies_data: 代理数据列表
    
    返回:
        批量添加结果
    """
    try:
        # 转换数据格式
        proxies_list = [proxy.dict() for proxy in proxies_data]
        
        # 批量添加代理
        stats = await proxy_manager.batch_add_proxies(pool_id, proxies_list)
        
        return {
            "status": "success",
            "message": "批量添加代理完成",
            "data": {
                "total": stats["total"],
                "success": stats["success"],
                "failed": stats["failed"],
                "pool_id": pool_id
            },
            "errors": stats["errors"] if "errors" in stats else []
        }
    except Exception as e:
        logger.error(f"批量添加代理失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量添加代理失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/lease", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="租用代理",
    description="从指定代理池租用代理"
)
async def lease_proxy(pool_id: str, lease_data: ProxyLeaseModel):
    """
    租用代理接口
    
    参数:
        pool_id: 代理池ID
        lease_data: 租用数据
    
    返回:
        租用信息和代理信息
    """
    try:
        # 租用代理
        lease = await proxy_manager.lease_proxy(pool_id, lease_data.task_id, lease_data.protocol, lease_data.ttl)
        
        if not lease:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"租用代理失败，没有可用的代理或代理池不存在: {pool_id}"
            )
        
        # 获取租用的代理信息
        leased_proxy = await proxy_manager.get_leased_proxy(lease.id)
        
        if not leased_proxy:
            # 可能是代理已被删除，释放租用
            await proxy_manager.release_proxy(lease.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"租用代理失败，代理信息不可用: {lease.proxy_id}"
            )
        
        return {
            "status": "success",
            "message": "代理租用成功",
            "data": {
                "lease_id": lease.id,
                "proxy_id": lease.proxy_id,
                "pool_id": lease.proxy_pool_id,
                "task_id": lease.task_id,
                "leased_at": lease.leased_at.isoformat(),
                "expires_at": lease.expires_at.isoformat(),
                "proxy": leased_proxy
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"租用代理失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"租用代理失败: {str(e)}"
        )


@router.post(
    "/leases/{lease_id}/release", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="释放代理租用",
    description="释放指定的代理租用"
)
async def release_lease(lease_id: str):
    """
    释放代理租用接口
    
    参数:
        lease_id: 租用ID
    
    返回:
        释放结果
    """
    try:
        # 释放代理租用
        success = await proxy_manager.release_proxy(lease_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"释放代理租用失败，租用不存在: {lease_id}"
            )
        
        return {
            "status": "success",
            "message": "代理租用释放成功",
            "data": {
                "lease_id": lease_id
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"释放代理租用失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"释放代理租用失败: {str(e)}"
        )


@router.get(
    "/leases/{lease_id}", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="获取租用信息",
    description="获取指定代理租用的详细信息"
)
async def get_lease(lease_id: str):
    """
    获取租用信息接口
    
    参数:
        lease_id: 租用ID
    
    返回:
        租用详细信息
    """
    try:
        # 获取租用的代理信息
        leased_proxy = await proxy_manager.get_leased_proxy(lease_id)
        
        if not leased_proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"租用不存在或已过期: {lease_id}"
            )
        
        # 查找租用记录
        for lease in proxy_manager.proxy_leases.values():
            if lease.id == lease_id:
                return {
                    "status": "success",
                    "message": "租用信息获取成功",
                    "data": {
                        "lease_id": lease.id,
                        "proxy_id": lease.proxy_id,
                        "pool_id": lease.proxy_pool_id,
                        "task_id": lease.task_id,
                        "status": lease.status,
                        "leased_at": lease.leased_at.isoformat(),
                        "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
                        "released_at": lease.released_at.isoformat() if lease.released_at else None,
                        "proxy": leased_proxy
                    }
                }
        
        # 如果没有找到租用记录
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"租用不存在: {lease_id}"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取租用信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取租用信息失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}/stats", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="获取代理池统计信息",
    description="获取指定代理池的统计数据"
)
async def get_pool_stats(pool_id: str):
    """
    获取代理池统计信息接口
    
    参数:
        pool_id: 代理池ID
    
    返回:
        代理池统计数据
    """
    try:
        # 获取代理池统计信息
        stats = await proxy_manager.get_proxy_pool_stats(pool_id)
        
        if not stats:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 格式化时间字段
        formatted_stats = {
            k: (v.isoformat() if hasattr(v, 'isoformat') else v) 
            for k, v in stats.items()
        }
        
        return {
            "status": "success",
            "message": "代理池统计信息获取成功",
            "data": formatted_stats
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取代理池统计信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理池统计信息失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/refresh", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="刷新代理池",
    description="刷新代理池中的所有代理（执行健康检查）"
)
async def refresh_pool(pool_id: str):
    """
    刷新代理池接口
    
    参数:
        pool_id: 代理池ID
    
    返回:
        刷新结果
    """
    try:
        # 刷新代理池
        result = await proxy_manager.refresh_all_proxies(pool_id)
        
        if not result.get('success', False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get('error', f"刷新代理池失败，代理池不存在: {pool_id}")
            )
        
        # 格式化时间字段
        stats = result.get('stats', {})
        formatted_stats = {
            k: (v.isoformat() if hasattr(v, 'isoformat') else v) 
            for k, v in stats.items()
        }
        
        return {
            "status": "success",
            "message": "代理池刷新成功",
            "data": {
                "pool_id": pool_id,
                "stats": formatted_stats
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"刷新代理池失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刷新代理池失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/proxies/{proxy_id}/blacklist", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="将代理加入黑名单",
    description="将指定代理加入黑名单"
)
async def blacklist_proxy(pool_id: str, proxy_id: str, blacklist_data: BlacklistProxyModel):
    """
    将代理加入黑名单接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
        blacklist_data: 黑名单数据
    
    返回:
        操作结果
    """
    try:
        # 将代理加入黑名单
        success = await proxy_manager.blacklist_proxy(pool_id, proxy_id, blacklist_data.reason)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"将代理加入黑名单失败，代理池或代理不存在: {proxy_id} -> {pool_id}"
            )
        
        return {
            "status": "success",
            "message": "代理已加入黑名单",
            "data": {
                "proxy_id": proxy_id,
                "pool_id": pool_id,
                "reason": blacklist_data.reason
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"将代理加入黑名单失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"将代理加入黑名单失败: {str(e)}"
        )


@router.post(
    "/pools/{pool_id}/proxies/{proxy_id}/whitelist", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="将代理从黑名单中移除",
    description="将指定代理从黑名单中移除"
)
async def whitelist_proxy(pool_id: str, proxy_id: str):
    """
    将代理从黑名单中移除接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
    
    返回:
        操作结果
    """
    try:
        # 将代理从黑名单中移除
        success = await proxy_manager.whitelist_proxy(pool_id, proxy_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"将代理从黑名单中移除失败，代理池或代理不存在: {proxy_id} -> {pool_id}"
            )
        
        return {
            "status": "success",
            "message": "代理已从黑名单中移除",
            "data": {
                "proxy_id": proxy_id,
                "pool_id": pool_id
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"将代理从黑名单中移除失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"将代理从黑名单中移除失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}/health-check", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="执行代理池健康检查",
    description="立即执行代理池的健康检查"
)
async def check_pool_health(pool_id: str):
    """
    执行代理池健康检查接口
    
    参数:
        pool_id: 代理池ID
    
    返回:
        健康检查结果
    """
    try:
        # 刷新代理池（执行健康检查）
        result = await proxy_manager.refresh_all_proxies(pool_id)
        
        if not result.get('success', False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get('error', f"执行健康检查失败，代理池不存在: {pool_id}")
            )
        
        return {
            "status": "success",
            "message": "代理池健康检查执行成功",
            "data": result.get('stats', {})
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"执行代理池健康检查失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"执行代理池健康检查失败: {str(e)}"
        )


@router.get(
    "/pools/{pool_id}/proxies/{proxy_id}/health-check", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="执行单个代理健康检查",
    description="立即执行单个代理的健康检查"
)
async def check_proxy_health(pool_id: str, proxy_id: str):
    """
    执行单个代理健康检查接口
    
    参数:
        pool_id: 代理池ID
        proxy_id: 代理ID
    
    返回:
        健康检查结果
    """
    try:
        # 获取代理池
        proxy_pool = await proxy_manager.get_proxy_pool(pool_id)
        
        if not proxy_pool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理池不存在: {pool_id}"
            )
        
        # 查找代理
        proxy_item = next((p for p in proxy_pool.proxies if p.id == proxy_id), None)
        
        if not proxy_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理不存在: {proxy_id} -> {pool_id}"
            )
        
        # 执行健康检查
        await proxy_manager._check_proxy_health(proxy_item, proxy_pool)
        
        # 重新获取代理信息
        updated_proxy = next((p for p in proxy_pool.proxies if p.id == proxy_id), None)
        
        if not updated_proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"代理不存在: {proxy_id} -> {pool_id}"
            )
        
        # 格式化返回数据
        proxy_info = {
            "id": updated_proxy.id,
            "ip": updated_proxy.ip,
            "port": updated_proxy.port,
            "protocol": updated_proxy.protocol,
            "status": updated_proxy.status,
            "response_time": updated_proxy.response_time,
            "score": updated_proxy.score,
            "last_health_check": updated_proxy.last_health_check.isoformat() if updated_proxy.last_health_check else None
        }
        
        return {
            "status": "success",
            "message": "代理健康检查执行成功",
            "data": proxy_info
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"执行代理健康检查失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"执行代理健康检查失败: {str(e)}"
        )


@router.get(
    "/leases", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="列出所有租用",
    description="获取所有代理租用的列表"
)
async def list_leases(pool_id: Optional[str] = Query(None, description="代理池ID过滤"),
                     task_id: Optional[str] = Query(None, description="任务ID过滤"),
                     status: Optional[str] = Query(None, description="租用状态过滤")):
    """
    列出所有租用接口
    
    参数:
        pool_id: 代理池ID过滤
        task_id: 任务ID过滤
        status: 租用状态过滤
    
    返回:
        租用列表
    """
    try:
        # 过滤租用
        filtered_leases = []
        for lease_id, lease in proxy_manager.proxy_leases.items():
            # 应用过滤条件
            if pool_id and lease.proxy_pool_id != pool_id:
                continue
            if task_id and lease.task_id != task_id:
                continue
            if status and lease.status != status:
                continue
            
            # 获取代理信息
            try:
                proxy_info = await proxy_manager.get_leased_proxy(lease_id)
            except:
                proxy_info = None
            
            # 格式化租用信息
            lease_info = {
                "lease_id": lease.id,
                "proxy_id": lease.proxy_id,
                "pool_id": lease.proxy_pool_id,
                "task_id": lease.task_id,
                "status": lease.status,
                "leased_at": lease.leased_at.isoformat(),
                "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
                "released_at": lease.released_at.isoformat() if lease.released_at else None,
                "proxy": proxy_info
            }
            
            filtered_leases.append(lease_info)
        
        return {
            "status": "success",
            "message": "租用列表获取成功",
            "data": filtered_leases,
            "count": len(filtered_leases)
        }
    except Exception as e:
        logger.error(f"获取租用列表失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取租用列表失败: {str(e)}"
        )


@router.get(
    "/status-options", 
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="获取代理状态选项",
    description="获取所有有效的代理状态选项"
)
async def get_status_options():
    """
    获取代理状态选项接口
    
    返回:
        代理状态选项列表
    """
    try:
        return {
            "status": "success",
            "message": "代理状态选项获取成功",
            "data": {
                "statuses": [
                    {
                        "value": ProxyStatus.VALID,
                        "label": "有效"
                    },
                    {
                        "value": ProxyStatus.WARNING,
                        "label": "警告"
                    },
                    {
                        "value": ProxyStatus.INVALID,
                        "label": "无效"
                    },
                    {
                        "value": ProxyStatus.PENDING,
                        "label": "待验证"
                    },
                    {
                        "value": ProxyStatus.BLACKLISTED,
                        "label": "黑名单"
                    }
                ],
                "protocols": [
                    {
                        "value": ProxyType.HTTP,
                        "label": "HTTP"
                    },
                    {
                        "value": ProxyType.HTTPS,
                        "label": "HTTPS"
                    },
                    {
                        "value": ProxyType.SOCKS5,
                        "label": "SOCKS5"
                    },
                    {
                        "value": ProxyType.SOCKS4,
                        "label": "SOCKS4"
                    }
                ],
                "pool_types": [
                    {
                        "value": ProxyPoolType.PUBLIC,
                        "label": "公共代理"
                    },
                    {
                        "value": ProxyPoolType.PRIVATE,
                        "label": "私有代理"
                    },
                    {
                        "value": ProxyPoolType.SHARED,
                        "label": "共享代理池"
                    }
                ]
            }
        }
    except Exception as e:
        logger.error(f"获取代理状态选项失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取代理状态选项失败: {str(e)}"
        )