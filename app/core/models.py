"""
ORM 模型：User + Workspace。

设计：
- 一个 User 现在只挂一个 Workspace（注册即创建）
  未来扩展"邀请同事"时，加 WorkspaceMember 多对多表
- Workspace 是数据归属单元；employees / jobs / sessions 都属于 workspace
  （这些后续在 shared/data 下用 JSON 列存或单独表）
"""
import secrets
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from app.core.db import Base


def _gen_id(prefix: str) -> str:
    return f'{prefix}_{secrets.token_urlsafe(10)}'


class User(Base):
    __tablename__ = 'users'

    id = Column(String, primary_key=True, default=lambda: _gen_id('usr'))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # bcrypt
    display_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 1 用户 1 workspace（v1）
    workspace_id = Column(String, ForeignKey('workspaces.id'), nullable=True)
    workspace = relationship('Workspace', back_populates='owner', uselist=False, foreign_keys=[workspace_id])


class Workspace(Base):
    __tablename__ = 'workspaces'

    id = Column(String, primary_key=True, default=lambda: _gen_id('ws'))
    name = Column(String, nullable=False)
    company_name = Column(String, nullable=True)  # 客户公司名
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 反向关系：哪个 user 拥有这个 workspace
    owner = relationship('User', back_populates='workspace', uselist=False, foreign_keys=[User.workspace_id])

    # workspace 级别的资产（v1 都用 JSON 列简单存；后续频繁查询的会拆出独立表）
    # employees / jobs / sessions 当前还在 in-memory + storage，下一阶段迁过来
