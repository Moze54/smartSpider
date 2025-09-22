"""
Cookie 类 - Cookie管理模型定义
"""

import uuid
from enum import Enum
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional


class CookieStatus(str, Enum):
    """Cookie状态枚举"""
    VALID = "valid"        # 有效
    EXPIRED = "expired"    # 过期
    INVALID = "invalid"    # 无效
    BLOCKED = "blocked"    # 被阻塞
    IN_USE = "in_use"      # 使用中
    AVAILABLE = "available"  # 可用
    WARNING = "warning"    # 警告状态


class CookieSource(str, Enum):
    """Cookie来源枚举"""
    USER_UPLOAD = "user_upload"  # 用户上传
    SELF_GENERATED = "self_generated"  # 自动生成
    PURCHASED = "purchased"  # 购买


class CookiePoolType(str, Enum):
    """Cookie池类型枚举"""
    COMMON = "common"      # 通用池
    SESSION = "session"    # 会话池
    DOMAIN_SPECIFIC = "domain_specific"  # 域名专用池


class LeaseStatus(str, Enum):
    """Cookie租用状态枚举"""
    ACTIVE = "active"      # 活跃状态
    RELEASED = "released"  # 已释放
    EXPIRED = "expired"    # 已过期


@dataclass
class CookieItem:
    """Cookie项数据类"""
    domain: str  # 域名
    name: str    # Cookie名称
    value: str   # Cookie值
    path: str = "/"  # 路径
    expires: Optional[datetime] = None  # 过期时间
    secure: bool = False  # 是否安全
    http_only: bool = False  # 是否HttpOnly
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 创建时间
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 更新时间
    status: CookieStatus = CookieStatus.VALID  # Cookie状态
    source: CookieSource = CookieSource.SELF_GENERATED  # Cookie来源
    user_agent: Optional[str] = None  # 关联的User-Agent
    usage_count: int = 0  # 使用次数
    last_used_at: Optional[datetime] = None  # 最后使用时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = asdict(self)
        # 转换datetime为字符串
        result['created_at'] = self.created_at.isoformat()
        result['updated_at'] = self.updated_at.isoformat()
        if self.expires:
            result['expires'] = self.expires.isoformat()
        if self.last_used_at:
            result['last_used_at'] = self.last_used_at.isoformat()
        # 转换枚举为字符串
        result['status'] = self.status.value
        result['source'] = self.source.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CookieItem':
        """从字典创建实例"""
        # 处理datetime类型
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'updated_at' in data and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        if 'expires' in data and isinstance(data['expires'], str):
            data['expires'] = datetime.fromisoformat(data['expires'])
        if 'last_used_at' in data and isinstance(data['last_used_at'], str):
            data['last_used_at'] = datetime.fromisoformat(data['last_used_at'])
        # 处理枚举类型
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = CookieStatus(data['status'])
        if 'source' in data and isinstance(data['source'], str):
            data['source'] = CookieSource(data['source'])
        return cls(**data)

    def is_expired(self) -> bool:
        """检查Cookie是否过期"""
        if self.status == CookieStatus.EXPIRED:
            return True
        if self.expires and datetime.now(timezone.utc) > self.expires:
            self.status = CookieStatus.EXPIRED
            return True
        return False

    def is_valid(self) -> bool:
        """检查Cookie是否有效"""
        return self.status == CookieStatus.VALID and not self.is_expired()

    def use(self) -> None:
        """标记Cookie为使用中并更新使用统计"""
        self.status = CookieStatus.IN_USE
        self.usage_count += 1
        self.last_used_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def release(self, is_valid: bool = True) -> None:
        """释放Cookie并更新状态"""
        self.status = CookieStatus.VALID if is_valid else CookieStatus.INVALID
        self.updated_at = datetime.now(timezone.utc)

    def block(self, reason: Optional[str] = None) -> None:
        """阻塞Cookie"""
        self.status = CookieStatus.BLOCKED
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class CookiePool:
    """Cookie池数据类"""
    name: str  # Cookie池名称
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # Cookie池ID
    type: CookiePoolType = CookiePoolType.COMMON  # Cookie池类型
    domain: Optional[str] = None  # 关联域名（如果是域名专用池）
    cookies: List[CookieItem] = field(default_factory=list)  # Cookie列表
    rotation_strategy: str = "round_robin"  # 轮换策略
    min_valid_count: int = 5  # 最小有效Cookie数量
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 创建时间
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 更新时间
    description: Optional[str] = None  # 描述

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'id': self.id,
            'name': self.name,
            'type': self.type.value,
            'domain': self.domain,
            'cookies': [cookie.to_dict() for cookie in self.cookies],
            'rotation_strategy': self.rotation_strategy,
            'min_valid_count': self.min_valid_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'description': self.description
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CookiePool':
        """从字典创建实例"""
        # 处理Cookie列表
        if 'cookies' in data and isinstance(data['cookies'], list):
            data['cookies'] = [CookieItem.from_dict(cookie) for cookie in data['cookies']]
        # 处理枚举类型
        if 'type' in data and isinstance(data['type'], str):
            data['type'] = CookiePoolType(data['type'])
        # 处理datetime类型
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'updated_at' in data and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)

    def add_cookie(self, cookie: CookieItem) -> None:
        """添加Cookie到池中"""
        # 检查是否已存在相同的Cookie
        for i, existing_cookie in enumerate(self.cookies):
            if (existing_cookie.domain == cookie.domain and 
                existing_cookie.name == cookie.name and 
                existing_cookie.path == cookie.path):
                # 替换现有Cookie
                self.cookies[i] = cookie
                self.updated_at = datetime.now(timezone.utc)
                return
        # 添加新Cookie
        self.cookies.append(cookie)
        self.updated_at = datetime.now(timezone.utc)

    def remove_cookie(self, cookie_name: str, domain: str, path: str = "/") -> bool:
        """从池中移除Cookie"""
        original_length = len(self.cookies)
        self.cookies = [
            cookie for cookie in self.cookies
            if not (cookie.name == cookie_name and cookie.domain == domain and cookie.path == path)
        ]
        if len(self.cookies) < original_length:
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False

    def get_valid_cookies(self) -> List[CookieItem]:
        """获取所有有效Cookie"""
        valid_cookies = []
        for cookie in self.cookies:
            if cookie.is_valid():
                valid_cookies.append(cookie)
        return valid_cookies

    def get_cookie_for_domain(self, domain: str) -> Optional[CookieItem]:
        """获取特定域名的一个有效Cookie"""
        domain_cookies = [
            cookie for cookie in self.cookies
            if cookie.domain == domain and cookie.is_valid()
        ]
        
        if not domain_cookies:
            return None
        
        # 根据轮换策略选择Cookie
        if self.rotation_strategy == "round_robin":
            # 简单的轮询策略：选择使用次数最少的Cookie
            return min(domain_cookies, key=lambda c: c.usage_count)
        elif self.rotation_strategy == "random":
            # 随机选择
            import random
            return random.choice(domain_cookies)
        elif self.rotation_strategy == "least_recent":
            # 选择最后使用时间最早的Cookie
            return min(domain_cookies, key=lambda c: c.last_used_at or datetime.min.replace(tzinfo=timezone.utc))
        else:
            # 默认使用轮询策略
            return min(domain_cookies, key=lambda c: c.usage_count)

    def get_cookies_dict(self, domain: str) -> Dict[str, str]:
        """获取特定域名的所有有效Cookie字典（名称:值）"""
        cookies_dict = {}
        for cookie in self.cookies:
            if cookie.domain == domain and cookie.is_valid():
                cookies_dict[cookie.name] = cookie.value
        return cookies_dict

    def mark_cookie_invalid(self, cookie_name: str, domain: str) -> bool:
        """标记Cookie为无效"""
        for cookie in self.cookies:
            if cookie.domain == domain and cookie.name == cookie_name:
                cookie.status = CookieStatus.INVALID
                cookie.updated_at = datetime.now(timezone.utc)
                self.updated_at = datetime.now(timezone.utc)
                return True
        return False

    def refresh_cookies(self) -> int:
        """刷新Cookie状态，检查过期情况"""
        expired_count = 0
        for cookie in self.cookies:
            if cookie.is_expired():
                expired_count += 1
        if expired_count > 0:
            self.updated_at = datetime.now(timezone.utc)
        return expired_count

    def get_stats(self) -> Dict[str, int]:
        """获取Cookie池统计信息"""
        stats = {
            'total': len(self.cookies),
            'valid': 0,
            'expired': 0,
            'invalid': 0,
            'blocked': 0,
            'in_use': 0
        }
        
        for cookie in self.cookies:
            if cookie.status in stats:
                stats[cookie.status.value] += 1
        
        return stats

    def is_healthy(self) -> bool:
        """检查Cookie池是否健康"""
        valid_count = len(self.get_valid_cookies())
        return valid_count >= self.min_valid_count


@dataclass
class CookieLease:
    """Cookie租用记录数据类"""
    pool_id: str  # Cookie池ID
    cookie_name: str  # Cookie名称
    domain: str  # 域名
    id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 租用ID
    leased_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 租用时间
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=1))  # 租用过期时间
    task_id: Optional[str] = None  # 关联任务ID
    released_at: Optional[datetime] = None  # 释放时间
    is_active: bool = True  # 是否活跃

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = asdict(self)
        # 转换datetime为字符串
        result['leased_at'] = self.leased_at.isoformat()
        result['expires_at'] = self.expires_at.isoformat()
        if self.released_at:
            result['released_at'] = self.released_at.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CookieLease':
        """从字典创建实例"""
        # 处理datetime类型
        if 'leased_at' in data and isinstance(data['leased_at'], str):
            data['leased_at'] = datetime.fromisoformat(data['leased_at'])
        if 'expires_at' in data and isinstance(data['expires_at'], str):
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        if 'released_at' in data and isinstance(data['released_at'], str):
            data['released_at'] = datetime.fromisoformat(data['released_at'])
        return cls(**data)

    def is_expired(self) -> bool:
        """检查租用是否过期"""
        return datetime.now(timezone.utc) > self.expires_at or not self.is_active

    def release(self) -> None:
        """释放租用"""
        self.is_active = False
        self.released_at = datetime.now(timezone.utc)


# 使用示例
if __name__ == '__main__':
    # 创建Cookie项
    cookie1 = CookieItem(
        domain="example.com",
        name="session_id",
        value="123456789",
        expires=datetime.now(timezone.utc) + timedelta(days=1)
    )
    
    cookie2 = CookieItem(
        domain="example.com",
        name="user_token",
        value="abcdef",
        expires=datetime.now(timezone.utc) + timedelta(days=1)
    )
    
    # 创建Cookie池
    cookie_pool = CookiePool(
        name="Example Cookie Pool",
        type=CookiePoolType.DOMAIN_SPECIFIC,
        domain="example.com",
        rotation_strategy="round_robin"
    )
    
    # 添加Cookie到池
    cookie_pool.add_cookie(cookie1)
    cookie_pool.add_cookie(cookie2)
    
    # 打印Cookie池信息
    print(f"Cookie池ID: {cookie_pool.id}")
    print(f"Cookie池名称: {cookie_pool.name}")
    print(f"Cookie数量: {len(cookie_pool.cookies)}")
    print(f"有效Cookie数量: {len(cookie_pool.get_valid_cookies())}")
    
    # 获取特定域名的Cookie
    domain_cookie = cookie_pool.get_cookie_for_domain("example.com")
    if domain_cookie:
        print(f"获取的Cookie: {domain_cookie.name}={domain_cookie.value}")
        
        # 使用Cookie
        domain_cookie.use()
        print(f"Cookie使用次数: {domain_cookie.usage_count}")
        print(f"Cookie状态: {domain_cookie.status}")
        
        # 释放Cookie
        domain_cookie.release()
        print(f"Cookie释放后状态: {domain_cookie.status}")
    
    # 获取Cookie池统计信息
    stats = cookie_pool.get_stats()
    print(f"\nCookie池统计: {stats}")
    print(f"Cookie池健康状态: {'健康' if cookie_pool.is_healthy() else '不健康'}")
    
    # 测试Cookie过期
    expired_cookie = CookieItem(
        domain="example.com",
        name="expired_cookie",
        value="expired_value",
        expires=datetime.now(timezone.utc) - timedelta(hours=1)  # 已过期
    )
    cookie_pool.add_cookie(expired_cookie)
    
    # 刷新Cookie状态
    expired_count = cookie_pool.refresh_cookies()
    print(f"过期Cookie数量: {expired_count}")
    
    # 更新后的统计
    stats = cookie_pool.get_stats()
    print(f"更新后Cookie池统计: {stats}")
    
    # 转换为字典
    pool_dict = cookie_pool.to_dict()
    print(f"\nCookie池字典 (部分): {pool_dict.keys()}")
    
    # 从字典重建Cookie池
    new_pool = CookiePool.from_dict(pool_dict)
    print(f"\n重建的Cookie池名称: {new_pool.name}")
    print(f"重建的Cookie数量: {len(new_pool.cookies)}")