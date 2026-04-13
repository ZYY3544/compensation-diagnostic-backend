"""
职级匹配服务：
1. 代码统计各职级人数 + 检测调整信号
2. AI #1：公司职级 → 标准职级映射
3. AI #2：有信号的员工 → 调整建议
"""
import json
import re

# 铭曦标准职级体系（7 级）
STANDARD_GRADES = [
    '初级专业人员', '中级专业人员', '高级专业人员',
    '专家/经理', '资深专家/高级经理', '总监', '高管',
]

STANDARD_GRADE_DEFINITIONS = {
    '初级专业人员': '入门级岗位，需要指导和监督完成基础工作，通常 0-2 年经验',
    '中级专业人员': '能独立完成本职工作，具备一定专业深度，通常 2-5 年经验',
    '高级专业人员': '在专业领域有较强能力，能指导他人，可独立承担复杂任务，通常 5-8 年经验',
    '专家/经理': '专业领域专家或团队管理者，能影响部门决策，通常 8-12 年经验',
    '资深专家/高级经理': '跨领域资深专家或大团队管理者，对业务有重大影响，通常 12+ 年经验',
    '总监': '部门/事业部负责人，制定战略方向，管理多个团队',
    '高管': 'VP/SVP/C-level，公司级决策者',
}

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
    AI #1：公司职级 → 标准职级映射。
    输入很短（几个职级名），输出也短。
    返回 { 'L3': '初级专业人员', 'L4': '中级专业人员', ... }
    """
    from app.agents.base_agent import BaseAgent
    agent = BaseAgent(temperature=0.2)

    prompt = f"""请将以下公司职级映射到铭曦标准职级体系。

公司职级列表：{json.dumps(grades_list, ensure_ascii=False)}

标准职级体系（从低到高）：
{json.dumps(STANDARD_GRADES, ensure_ascii=False)}

输出严格 JSON，格式：{{"L3": "初级专业人员", "L4": "中级专业人员", ...}}
只输出 JSON，不要其他文字。"""

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
        # 确保所有值都在标准职级列表中
        for k, v in list(mapping.items()):
            if v not in STANDARD_GRADES:
                mapping[k] = _closest_standard_grade(v)
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

    prompt = f"""以下员工有调整信号，请判断是否建议调整对标级别。

员工列表：
{json.dumps(emp_summaries, ensure_ascii=False, indent=2)}

标准职级体系（从低到高）：
{json.dumps(STANDARD_GRADES, ensure_ascii=False)}

规则：
- 绩效A 的员工，建议上调一级
- 绩效C 的员工，建议下调一级
- 岗位含管理关键词但级别偏低的，建议上调一级
- 如果不建议调整，不要输出该员工

输出严格 JSON 数组：[{{"id": "EMP001", "suggested_grade": "专家/经理", "reason": "绩效A，建议上调"}}]
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


def _closest_standard_grade(name: str) -> str:
    """模糊匹配最接近的标准职级"""
    name_lower = name.lower()
    for sg in STANDARD_GRADES:
        if sg in name_lower or name_lower in sg:
            return sg
    # 关键词匹配
    if any(k in name_lower for k in ['初级', '助理', 'junior']):
        return '初级专业人员'
    if any(k in name_lower for k in ['中级']):
        return '中级专业人员'
    if any(k in name_lower for k in ['高级', 'senior']):
        return '高级专业人员'
    if any(k in name_lower for k in ['专家', '经理']):
        return '专家/经理'
    if any(k in name_lower for k in ['资深', '高级经理']):
        return '资深专家/高级经理'
    if any(k in name_lower for k in ['总监', 'director']):
        return '总监'
    if any(k in name_lower for k in ['高管', 'vp', 'ceo', 'cfo', 'cto']):
        return '高管'
    return '中级专业人员'  # 默认
