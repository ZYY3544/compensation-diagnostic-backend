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
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, JSON
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
    # employees / sessions 当前还在 in-memory + storage，下一阶段迁过来


class Job(Base):
    """
    JE 岗位库：每个 workspace 维护自己的岗位列表，每个岗位独立 Hay 评估。

    factors / result 用 JSON 列存：
      factors: {practical_knowledge, managerial_knowledge, communication,
                thinking_challenge, thinking_environment,
                freedom_to_act, magnitude, nature_of_impact}
      result:  {kh_score, ps_score, acc_score, total_score, job_grade,
                profile, match_score, convergence_stats, pk_reasoning}
    """
    __tablename__ = 'jobs'

    id = Column(String, primary_key=True, default=lambda: _gen_id('job'))
    workspace_id = Column(String, ForeignKey('workspaces.id'), nullable=False, index=True)

    title = Column(String, nullable=False)               # 岗位名
    department = Column(String, nullable=True)           # 部门（可空）
    function = Column(String, nullable=False)            # 职能（必须在 function_catalog 内）
    jd_text = Column(Text, nullable=False)               # JD 原文

    factors = Column(JSON, nullable=True)                # 8 因子档位
    result = Column(JSON, nullable=True)                 # 评估结果（分数 + 职级）

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class JeProfile(Base):
    """
    JE 组织画像 + AI 岗位库（每个 workspace 一份）。

    数据流：
      Step 0 访谈 → 写入 profile_data（行业/规模/部门/管理层级/现有职级体系）
      Step 1 触发生成 → LLM 单次调用 → 写入 library_data（20-40 个推荐岗位）
      Step 1 用户从库选岗 → 落入 jobs 表（一份岗位库可被多次选用，库本身不变）

    存储取舍：
    - profile_data 和 library_data 都用 JSON 列存（写一次读多次，不需要关系查询）
    - 每个 workspace 最多 1 份 profile（在 access 层用 workspace_id 唯一约束保证），
      重新生成会覆盖 library_data 但保留已建岗位（jobs 表独立）
    """
    __tablename__ = 'je_profiles'

    id = Column(String, primary_key=True, default=lambda: _gen_id('jep'))
    workspace_id = Column(String, ForeignKey('workspaces.id'), nullable=False, unique=True, index=True)

    profile_data = Column(JSON, nullable=True)
    # 形如:
    # {
    #   'industry': '互联网',
    #   'headcount': 200,
    #   'departments': ['产品部', '技术部', '市场部', 'HR部', '财务部'],
    #   'layers': ['CEO', 'VP', '总监', '经理', '专员'],
    #   'department_layers': {'产品部': ['CEO', 'VP', '总监', '经理', '专员'], ...},
    #   'existing_grade_system': 'P1-P10' 或 null,
    # }

    library_data = Column(JSON, nullable=True)
    # 形如:
    # {
    #   'entries': [
    #     {'id': 'lib_xxx', 'name': '产品经理', 'department': '产品部', 'function': '产品管理',
    #      'hay_grade': 12, 'factors': {...8 因子...}, 'responsibilities': ['...']},
    #     ...
    #   ],
    #   'generated_at': '2026-04-25T...',
    #   'model_used': 'openai/gpt-5.4-mini',
    # }

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class JobBatch(Base):
    """
    批量岗位评估任务。一次 Excel 上传产生一个 batch，里面 N 个岗位并行评估。

    设计要点：
    - items 用 JSON 列存所有行的状态（title/function/department/jd_text/status/error/job_id/model_used），
      避免再开一张 BatchItem 表，简化查询。批量典型 50-200 行，单行 JSON 几 KB，整批 < 1 MB 没问题。
    - status: queued | running | completed | failed
      - completed = 全部跑完（含部分失败）
      - failed = 整个 batch 异常退出（如所有 LLM 调用都挂了）
    - 模型一致性：每个 item 内的所有 LLM 调用用同一个 model（写在 item.model_used），
      不同 item 之间用 round-robin 跨多个备选模型，避免单点和速率限制。
    """
    __tablename__ = 'job_batches'

    id = Column(String, primary_key=True, default=lambda: _gen_id('jb'))
    workspace_id = Column(String, ForeignKey('workspaces.id'), nullable=False, index=True)

    status = Column(String, nullable=False, default='queued')
    total = Column(Integer, nullable=False, default=0)
    completed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)

    items = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
