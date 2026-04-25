"""
人岗匹配服务：把主诊断的员工数据跟 JE 岗位库连接起来。

核心数据流：
  员工（来自 session.cleaned_employees / _employees）
    ↓  job_title + department 软匹配
  JE 岗位（jobs 表，每个有 Hay 标准职级）
    ↓  得到"应有职级 G(JE) vs 在岗职级 G(员工)"
  错配检测 + 矩阵渲染数据

输出供前端 PersonJobMatch 视图直接渲染：
- matched: 员工 → 岗位的具体匹配 + 是否越级 / 低配
- unmatched: 没找到对应岗位的员工
- by_cell: 按 (department, hay_grade) 分组的岗位 + 员工聚合，给矩阵图用
- summary: 总匹配率 / 越级人数 / 低配人数

匹配策略（从严到宽）：
  S1. (department, normalized_title) 精确匹配
  S2. normalized_title 精确匹配（忽略部门）
  S3. 双向 substring 匹配（员工标题 ⊂ 岗位标题，或反之）
  S4. 落空 = unmatched

normalized_title 做了：
  - lower-case
  - 去掉常见后缀（"岗"、"专员"、"职位"）以减少噪音
  - 去掉空白
"""
from __future__ import annotations

import re
from typing import Optional

from app.services.grade_matcher import HAY_GRADE_MAP


def match_employees_to_jobs(employees: list[dict], jobs: list[dict], grade_mapping: Optional[dict] = None) -> dict:
    """
    Args:
        employees: session 里取出的员工列表，每条至少需要 {job_title, department, grade}
        jobs:      JE 岗位列表（_serialize_job 序列化后的 dict）
        grade_mapping: session._grade_match_result.grade_mapping，公司职级 → 标准 Level 的映射

    Returns:
        见模块 docstring。
    """
    grade_mapping = grade_mapping or {}

    # 建岗位索引
    by_dept_title: dict[tuple, dict] = {}  # (dept, normalized_title) → job
    by_title: dict[str, list[dict]] = {}   # normalized_title → [job, ...]
    all_jobs_with_grade: list[dict] = []
    for j in jobs:
        title_n = _normalize(j.get('title', ''))
        dept = (j.get('department') or '').strip()
        grade = (j.get('result') or {}).get('job_grade')
        if grade is None:
            continue   # 还没评估的岗位不参与匹配
        all_jobs_with_grade.append({**j, 'job_grade': grade, 'title_n': title_n, 'dept_n': dept})
        if dept and title_n:
            by_dept_title[(dept, title_n)] = j
        if title_n:
            by_title.setdefault(title_n, []).append(j)

    # 人岗匹配
    matched: list[dict] = []
    unmatched: list[dict] = []
    over_leveled = 0    # 在岗职级 > 岗位标准职级（越级在岗）
    under_leveled = 0   # 在岗职级 < 岗位标准职级（屈才 / 待提拔）
    aligned = 0

    for emp in employees:
        emp_title = emp.get('job_title') or ''
        emp_dept = (emp.get('department') or '').strip()
        emp_company_grade = emp.get('grade')

        emp_hay_grade = _employee_to_hay_grade(emp_company_grade, grade_mapping)

        # 先严后宽匹配
        title_n = _normalize(emp_title)
        match: Optional[dict] = None
        match_strategy = ''

        if title_n:
            if emp_dept and (emp_dept, title_n) in by_dept_title:
                match = by_dept_title[(emp_dept, title_n)]
                match_strategy = 'dept+title'
            elif title_n in by_title:
                # 同名岗位多个部门，取第一个；这里没法做更精的判断
                match = by_title[title_n][0]
                match_strategy = 'title'
            else:
                # 子串匹配 — 只在剩余的岗位里查
                for j in all_jobs_with_grade:
                    if _substring_match(title_n, j['title_n']):
                        match = j
                        match_strategy = 'fuzzy'
                        break

        if match:
            job_grade = (match.get('result') or {}).get('job_grade') or match.get('job_grade')
            entry = {
                'employee': {
                    'job_title': emp_title,
                    'department': emp_dept or None,
                    'company_grade': emp_company_grade,
                    'hay_grade': emp_hay_grade,
                    'name': emp.get('name') or emp.get('id', ''),
                    'row_number': emp.get('row_number'),
                },
                'job': {
                    'id': match.get('id'),
                    'title': match.get('title'),
                    'department': match.get('department'),
                    'function': match.get('function'),
                    'job_grade': job_grade,
                },
                'gap': (emp_hay_grade - job_grade) if (emp_hay_grade is not None and job_grade is not None) else None,
                'match_strategy': match_strategy,
            }
            matched.append(entry)

            if entry['gap'] is not None:
                if entry['gap'] >= 2:
                    over_leveled += 1
                elif entry['gap'] <= -2:
                    under_leveled += 1
                else:
                    aligned += 1
        else:
            unmatched.append({
                'job_title': emp_title,
                'department': emp_dept or None,
                'company_grade': emp_company_grade,
                'hay_grade': emp_hay_grade,
                'name': emp.get('name') or emp.get('id', ''),
                'row_number': emp.get('row_number'),
            })

    # 矩阵聚合：按 (department, hay_grade) 分组，每个 cell 含岗位 + 员工
    by_cell: dict[str, list[dict]] = {}
    for j in all_jobs_with_grade:
        key = f"{j['department'] or '未分组'}::{j['job_grade']}"
        by_cell.setdefault(key, []).append({
            'kind': 'job',
            'id': j['id'],
            'title': j['title'],
            'department': j.get('department'),
            'job_grade': j['job_grade'],
        })
    for m in matched:
        emp = m['employee']
        if emp['hay_grade'] is None:
            continue
        key = f"{emp['department'] or '未分组'}::{emp['hay_grade']}"
        by_cell.setdefault(key, []).append({
            'kind': 'employee',
            'name': emp['name'],
            'department': emp['department'],
            'hay_grade': emp['hay_grade'],
            'matched_job_id': m['job']['id'],
            'gap': m['gap'],
        })

    return {
        'matched': matched,
        'unmatched': unmatched,
        'by_cell': by_cell,
        'summary': {
            'total_employees': len(employees),
            'matched_count': len(matched),
            'unmatched_count': len(unmatched),
            'match_rate': round(len(matched) / len(employees), 3) if employees else 0,
            'over_leveled': over_leveled,
            'under_leveled': under_leveled,
            'aligned': aligned,
            'jobs_with_grade': len(all_jobs_with_grade),
        },
    }


# ---------------------------------------------------------------------------
# 标题规范化 + 子串匹配
# ---------------------------------------------------------------------------

# 这些后缀剥掉之后还能保持语义（"销售经理岗" / "销售经理" 应该等价）
_STRIP_SUFFIX = ('岗', '岗位', '职位')


def _normalize(s: str) -> str:
    if not s:
        return ''
    s = re.sub(r'\s+', '', s.strip().lower())
    for suf in _STRIP_SUFFIX:
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def _substring_match(a: str, b: str) -> bool:
    """双向 contains，但避免 1-2 字过短词造成的假阳性。"""
    if not a or not b:
        return False
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a


def _employee_to_hay_grade(company_grade: Optional[str], grade_mapping: dict) -> Optional[int]:
    """员工的公司原始职级 → 标准 Level → Hay grade（数字）。任一环节落空就返回 None。"""
    if not company_grade or not grade_mapping:
        return None
    standard = grade_mapping.get(company_grade)
    if not standard:
        return None
    return HAY_GRADE_MAP.get(standard)
