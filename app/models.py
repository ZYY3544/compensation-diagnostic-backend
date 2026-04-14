"""
数据模型定义（TypedDict 风格，供类型提示和文档用）。
实际存储用 storage 层（当前内存，未来 Supabase）。
"""
from typing import TypedDict, Optional, Literal, Any
from datetime import datetime


# ======================================================================
# User
# ======================================================================
class User(TypedDict):
    user_id: str
    org_name: str
    role: str
    created_at: str


# ======================================================================
# DataSnapshot — 一次上传 = 一个快照
# ======================================================================
class DataSnapshot(TypedDict):
    snapshot_id: str
    user_id: str
    uploaded_at: str
    raw_excel_path: Optional[str]
    # 解析和清洗结果
    parse_result: dict
    cleaned_employees: list
    employees_original: list  # 清洗前快照
    # 映射关系
    grade_mapping: dict        # 公司职级 → 标准 Level
    func_mapping: dict         # 部门/族 → 标准职能
    # 全量分析结果
    full_analysis_json: Optional[dict]
    analyzed_at: Optional[str]  # 分析时间戳；数据变化后需清空重跑
    # 访谈纪要（重模式才有）
    interview_notes: Optional[dict]
    # 中间状态（清洗前置数据）
    _code_results: Optional[dict]
    _field_map: Optional[dict]
    _column_names: Optional[list]
    _grades_list: Optional[list]
    _mutations: Optional[list]
    _cleansed_excel_path: Optional[str]


# ======================================================================
# Conversation — 一次对话（可能调多次 skill）
# ======================================================================
ConversationType = Literal['diagnosis', 'quick', 'follow_up']


class Conversation(TypedDict):
    conv_id: str
    user_id: str
    snapshot_id: Optional[str]  # 关联的数据快照
    started_at: str
    title: str
    type: ConversationType
    messages: list  # [{role, text, timestamp, chips?, ...}]
    status: str    # active | archived


# ======================================================================
# SkillInvocation — 一次能力调用
# ======================================================================
class SkillInvocation(TypedDict):
    invocation_id: str
    conv_id: str
    snapshot_id: Optional[str]
    skill_key: str                # e.g. 'external_benchmark'
    invoked_at: str
    input_params: dict
    result_json: Optional[dict]
    narrative_text: Optional[str]  # AI 生成的解读
    render_artifacts: list         # [{card_type, props}]
    status: str                    # pending | success | failed


# ======================================================================
# Utility
# ======================================================================
def now_iso() -> str:
    return datetime.utcnow().isoformat()


def new_id(prefix: str = '') -> str:
    import uuid
    return f"{prefix}{uuid.uuid4().hex[:12]}"
