"""
SmartSpider 的用户模型
"""

from dataclasses import dataclass
from typing import Optional
import datetime


@dataclass
class User:
    """用户数据模型"""
    id: int
    username: str
    email: str
    is_active: bool = True
    is_admin: bool = False
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None
    
    def __post_init__(self):
        """实例创建后初始化默认值"""
        if self.created_at is None:
            self.created_at = datetime.datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.datetime.now()
    
    def to_dict(self):
        """将用户转换为字典"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建用户"""
        # 将字符串日期转换回datetime对象
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.datetime.fromisoformat(data['created_at'])
        if 'updated_at' in data and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.datetime.fromisoformat(data['updated_at'])
        
        return cls(**data)


# 使用示例
if __name__ == '__main__':
    # 创建一个新用户
    user = User(id=1, username='johndoe', email='john@example.com')
    print(f"用户: {user}")
    
    # 转换为字典
    user_dict = user.to_dict()
    print(f"用户字典: {user_dict}")
    
    # 从字典创建
    new_user = User.from_dict(user_dict)
    print(f"从字典创建的新用户: {new_user}")