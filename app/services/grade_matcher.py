"""
职级匹配服务：
1. 代码统计各职级人数 + 检测调整信号
2. AI #1：公司职级 → 标准职级映射
3. AI #2：有信号的员工 → 调整建议
"""
import json
import re

# 铭曦标准职级体系（基于 OrgChart，7 个大级 × 2 个子级）
# 区块一下拉框用大级（Level 1 - Level 7）
# 区块二调整建议用子级（Level 1-1, Level 1-2, ...）
STANDARD_LEVELS = [
    'Level 1', 'Level 2', 'Level 3', 'Level 4',
    'Level 5', 'Level 6', 'Level 7',
]

STANDARD_SUB_LEVELS = [
    'Level 1-1', 'Level 1-2',
    'Level 2-1', 'Level 2-2',
    'Level 3-1', 'Level 3-2',
    'Level 4-1', 'Level 4-2',
    'Level 5-1', 'Level 5-2',
    'Level 6-1', 'Level 6-2',
    'Level 7-1', 'Level 7-2',
]

# Hay 职级对照
HAY_GRADE_MAP = {
    'Level 1-1': 8, 'Level 1-2': 9,
    'Level 2-1': 10, 'Level 2-2': 11,
    'Level 3-1': 12, 'Level 3-2': 13,
    'Level 4-1': 14, 'Level 4-2': 15,
    'Level 5-1': 16, 'Level 5-2': 17,
    'Level 6-1': 18, 'Level 6-2': 19,
    'Level 7-1': 20, 'Level 7-2': 21,
}

STANDARD_LEVEL_DEFINITIONS = {
    'Level 1': 'Hay 8-9 | 入门岗位',
    'Level 2': 'Hay 10-11 | 助理/初级专业人员',
    'Level 3': 'Hay 12-13 | 中级专业人员 / 专员',
    'Level 4': 'Hay 14-15 | 高级专业人员 / 主管',
    'Level 5': 'Hay 16-17 | 资深专业人员 / 经理',
    'Level 6': 'Hay 18-19 | 专家 / 高级经理',
    'Level 7': 'Hay 20-21 | 总监',
}

# 向后兼容的别名（旧代码可能引用）
STANDARD_GRADES = STANDARD_LEVELS
STANDARD_GRADE_DEFINITIONS = STANDARD_LEVEL_DEFINITIONS

# 管理关键词
_MGMT_KEYWORDS = ['主管', '经理', '总监', '负责人', '部长', '院长',
                   'leader', 'manager', 'director', 'head', 'vp']


def build_grade_match_data(employees: list, grades_list: list) -> dict:
    """
    代码层：统计各职级人数 + 检测个人调整信号。
    返回 { grade_stats, employees_with_signals, all_employees_by_grade }
    """
    # 按职级分组
    by_grade: dict[str, list] = {}
    for emp in employees:
        g = emp.get('grade', '')
        if not g:
            continue
        by_grade.setdefault(g, []).append(emp)

    # 统计
    grade_stats = []
    for g in grades_list:
        grade_stats.append({
            'company_grade': g,
            'count': len(by_grade.get(g, [])),
        })

    # 检测调整信号
    employees_with_signals = []
    for emp in employees:
        signals = _detect_signals(emp)
        if signals:
            employees_with_signals.append({
                'row_number': emp.get('row_number'),
                'id': emp.get('id', ''),
                'name': emp.get('id', ''),  # 用 id 当名字（如果有姓名字段可替换）
                'job_title': emp.get('job_title', ''),
                'grade': emp.get('grade', ''),
                'performance': emp.get('performance', ''),
                'signals': signals,
            })

    return {
        'grade_stats': grade_stats,
        'employees_with_signals': employees_with_signals,
        'all_employees_by_grade': {
            g: [
                {
                    'row_number': e.get('row_number'),
                    'id': e.get('id', ''),
                    'job_title': e.get('job_title', ''),
                    'performance': e.get('performance', ''),
                    'grade': g,
                }
                for e in emps
            ]
            for g, emps in by_grade.items()
        },
    }


def _detect_signals(emp: dict) -> list:
    """检测单个员工的调整信号（纯代码，不调 AI）"""
    signals = []
    perf = str(emp.get('performance', '')).strip()
    title = str(emp.get('job_title', '')).lower()

    # 绩效信号
    if perf == 'A':
        signals.append({'type': 'high_performance', 'direction': 'up', 'reason': '绩效A'})
    elif perf == 'C':
        signals.append({'type': 'low_performance', 'direction': 'down', 'reason': '绩效C'})

    # 岗位含管理关键词
    for kw in _MGMT_KEYWORDS:
        if kw.lower() in title:
            signals.append({'type': 'management_title', 'direction': 'up', 'reason': f'岗位含管理（{kw}）'})
            break

    return signals


def ai_match_grades(grades_list: list) -> dict:
    """
    AI #1：公司职级 → 标准职级映射（Level 1 - Level 7）。
    返回 { 'L3': 'Level 2', 'L4': 'Level 3', ... }
    """
    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.2)

    level_desc = '\n'.join(f'{k}: {v}' for k, v in STANDARD_LEVEL_DEFINITIONS.items())
    prompt = f"""请将以下公司职级映射到铭曦标准职级体系。

公司职级列表：{json.dumps(grades_list, ensure_ascii=False)}

标准职级体系（从低到高）：
{level_desc}

输出严格 JSON，格式：{{"L3": "Level 2", "L4": "Level 3", ...}}
值必须是 Level 1 到 Level 7 之一。只输出 JSON，不要其他文字。"""

    messages = [
        {"role": "system", "content": "你是薪酬诊断系统的职级匹配模块。根据公司职级名称，推断其对应的标准职级。"},
        {"role": "user", "content": prompt},
    ]
    response = agent.call_llm(messages)

    if '```json' in response:
        response = response.split('```json')[1].split('```')[0]
    elif '```' in response:
        response = response.split('```')[1].split('```')[0]

    try:
        mapping = json.loads(response.strip())
        # 确保所有值都在 Level 1-7
        for k, v in list(mapping.items()):
            if v not in STANDARD_LEVELS:
                mapping[k] = _closest_standard_level(v)
        return mapping
    except json.JSONDecodeError:
        return {}


def ai_suggest_adjustments(employees_with_signals: list, grade_mapping: dict) -> list:
    """
    AI #2：对有调整信号的员工，建议调整方向。
    输入：只传有信号的人（工号、岗位、绩效、当前标准职级）
    输出：[{id, suggested_grade, reason}]
    """
    if not employees_with_signals:
        return []

    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.3)

    emp_summaries = []
    for e in employees_with_signals:
        current_std = grade_mapping.get(e['grade'], '')
        emp_summaries.append({
            'id': e['id'],
            'job_title': e['job_title'],
            'grade': e['grade'],
            'performance': e['performance'],
            'current_standard_grade': current_std,
            'signals': [s['reason'] for s in e['signals']],
        })

    level_desc = '\n'.join(f'{k}: {v}' for k, v in STANDARD_LEVEL_DEFINITIONS.items())
    prompt = f"""以下员工有调整信号，请判断是否建议调整对标子级别。

员工列表：
{json.dumps(emp_summaries, ensure_ascii=False, indent=2)}

标准职级体系：
{level_desc}

子级别列表（用于精细调整）：
{json.dumps(STANDARD_SUB_LEVELS, ensure_ascii=False)}

规则：
- 绩效A 的员工，建议上调到当前大级的 -2 子级或上一大级的 -1 子级
- 绩效C 的员工，建议下调到当前大级的 -1 子级或下一大级的 -2 子级
- 岗位含管理关键词但级别偏低的，建议上调一个子级
- suggested_grade 必须是子级别格式（如 Level 4-2, Level 5-1）
- 如果不建议调整，不要输出该员工

输出严格 JSON 数组：[{{"id": "EMP001", "suggested_grade": "Level 5-1", "reason": "绩效A，建议上调"}}]
只输出 JSON，不要其他文字。"""

    messages = [
        {"role": "system", "content": "你是薪酬诊断系统的职级调整建议模块。"},
        {"role": "user", "content": prompt},
    ]
    response = agent.call_llm(messages)

    if '```json' in response:
        response = response.split('```json')[1].split('```')[0]
    elif '```' in response:
        response = response.split('```')[1].split('```')[0]

    try:
        suggestions = json.loads(response.strip())
        return suggestions if isinstance(suggestions, list) else []
    except json.JSONDecodeError:
        return []


def _closest_standard_level(name: str) -> str:
    """模糊匹配最接近的标准 Level"""
    n = name.lower().strip()
    # 直接包含 Level N
    for lv in STANDARD_LEVELS:
        if lv.lower() in n:
            return lv
    # 关键词匹配
    if any(k in n for k in ['入门', '实习']):
        return 'Level 1'
    if any(k in n for k in ['初级', '助理', 'junior']):
        return 'Level 2'
    if any(k in n for k in ['中级', '专员']):
        return 'Level 3'
    if any(k in n for k in ['高级', 'senior', '主管']):
        return 'Level 4'
    if any(k in n for k in ['资深', '经理', 'manager']):
        return 'Level 5'
    if any(k in n for k in ['专家', '高级经理']):
        return 'Level 6'
    if any(k in n for k in ['总监', 'director', '高管', 'vp']):
        return 'Level 7'
    return 'Level 3'  # 默认中级
