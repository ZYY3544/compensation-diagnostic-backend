"""
标准字段定义。所有 engine 计算都使用这些 key。
上传的 Excel 无论列名如何，都需要映射到这里的 key 才能做下游分析。
"""

# 标准字段 key → 元数据
# required: True = 没有就没法做任何分析
# optional_for: 列出这个字段缺失会影响哪些模块
STANDARD_FIELDS = [
    # 基础标识
    {'key': 'employee_id', 'label': '员工姓名/工号', 'required': True,
     'hint': '如"EMP001"、"张三"'},
    {'key': 'job_title', 'label': '岗位名称', 'required': True,
     'hint': '如"高级软件工程师"、"HRBP经理"'},
    {'key': 'grade', 'label': '职级', 'required': True,
     'hint': '如 L5 / P7 / M3 / 总监级'},
    {'key': 'department_l1', 'label': '一级部门', 'required': True,
     'hint': '如"研发中心"、"人力资源"'},

    # 薪酬字段
    {'key': 'base_salary', 'label': '月度基本工资', 'required': True,
     'hint': '月度数字，如 15000；如果是年度工资请另外标注'},
    {'key': 'annual_fixed_bonus', 'label': '年固定奖金', 'required': False,
     'hint': '13薪、年节礼金等固定发放的奖金', 'optional_for': ['薪酬结构分析']},
    {'key': 'annual_variable_bonus', 'label': '年浮动奖金', 'required': False,
     'hint': '绩效奖金、销售佣金等浮动部分', 'optional_for': ['薪酬结构分析']},
    {'key': 'annual_allowance', 'label': '年度现金津贴', 'required': False,
     'hint': '交通、通讯、餐饮等计入总现金的津贴', 'optional_for': ['薪酬结构分析']},
    {'key': 'annual_reimbursement', 'label': '报销类津贴', 'required': False,
     'hint': '差旅、报销等不计入总现金的支出'},

    # 绩效
    {'key': 'performance_rating', 'label': '年度绩效结果', 'required': False,
     'hint': 'A/B+/B/C 或 优秀/良好/合格 等', 'optional_for': ['绩效关联分析']},

    # 入司/管理关系
    {'key': 'hire_date', 'label': '入司时间', 'required': False,
     'hint': 'YYYY-MM-DD', 'optional_for': ['年化处理', '入司不满一年识别']},
    {'key': 'direct_manager', 'label': '直属上级', 'required': False,
     'hint': '姓名或工号', 'optional_for': ['薪酬倒挂检测']},

    # 岗位属性
    {'key': 'management_or_professional', 'label': '管理岗/专业岗', 'required': False,
     'hint': '管理 / 专业 / M / P', 'optional_for': ['管理溢价分析']},
    {'key': 'is_key_position', 'label': '是否关键岗位', 'required': False,
     'hint': '是/否 或 Y/N', 'optional_for': ['关键岗位下钻']},
    {'key': 'management_complexity', 'label': '管理复杂度', 'required': False,
     'hint': '数字或分级', 'optional_for': ['管理复杂度定价']},

    # 二/三级部门
    {'key': 'department_l2', 'label': '二级部门', 'required': False, 'hint': ''},
    {'key': 'department_l3', 'label': '三级部门', 'required': False, 'hint': ''},

    # 辅助属性
    {'key': 'base_city', 'label': '工作城市', 'required': False,
     'hint': '上海/深圳/北京等', 'optional_for': ['城市分位查询']},
    {'key': 'age', 'label': '年龄', 'required': False, 'hint': ''},
    {'key': 'education', 'label': '教育背景', 'required': False, 'hint': ''},
    {'key': 'job_family', 'label': '职位族', 'required': False, 'hint': '研发/产品/销售'},
    {'key': 'job_class', 'label': '职位类', 'required': False,
     'hint': '软件开发/数据科学/前端等'},
]

# 快速查找表
FIELD_BY_KEY = {f['key']: f for f in STANDARD_FIELDS}
REQUIRED_KEYS = [f['key'] for f in STANDARD_FIELDS if f['required']]
OPTIONAL_KEYS = [f['key'] for f in STANDARD_FIELDS if not f['required']]

# 旧的 pipeline.py 用的是 employee_id / department / base_salary 等名字，
# 不是全新的 annual_* 体系。给个转换表：
#   new key (standard) → old key (pipeline/engine 里用的)
# 这样 confirm-mapping 后可以把 standard-key 还原成 pipeline 熟悉的列名，
# 最小改动就能跑通。
PIPELINE_KEY_ALIAS = {
    'employee_id': 'employee_id',
    'job_title': 'job_title',
    'grade': 'grade',
    'department_l1': 'department',
    'department_l2': 'department_2',
    'base_salary': 'base_salary',
    'annual_fixed_bonus': 'fixed_bonus',
    'annual_variable_bonus': 'variable_bonus',
    'annual_allowance': 'cash_allowance',
    'annual_reimbursement': 'reimbursement',
    'performance_rating': 'performance',
    'hire_date': 'hire_date',
    'direct_manager': 'manager',
    'management_or_professional': 'management_track',
    'is_key_position': 'key_position',
    'management_complexity': 'management_complexity',
    'base_city': 'city',
    'age': 'age',
    'education': 'education',
    'job_family': 'job_family',
    'job_class': 'job_class',
}


def summary_for_ai_prompt() -> str:
    """给 AI 识别器用的人类可读标准字段清单"""
    lines = []
    for f in STANDARD_FIELDS:
        req = '(必填)' if f['required'] else ''
        hint = f' —— {f["hint"]}' if f.get('hint') else ''
        lines.append(f'- {f["key"]}: {f["label"]} {req}{hint}')
    return '\n'.join(lines)
